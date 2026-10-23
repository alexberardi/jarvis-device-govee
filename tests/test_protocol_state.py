"""State reads against Govee's router API (/device/state), and toggle.

The 200 response below is the documented example from Govee's developer API
("Get Device State"), trimmed to the light-bar capabilities. Run as
test_protocol_color.py says.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import uuid
from pathlib import Path
from typing import Any

import pytest

from jarvis_command_sdk import DiscoveredDevice

_PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "device_families" / "govee" / "protocol.py"


def _load_protocol() -> Any:
    spec = importlib.util.spec_from_file_location("govee_protocol_state_under_test", _PROTOCOL_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


govee_mod = _load_protocol()
GoveeProtocol = govee_mod.GoveeProtocol

SKU = "H6199"
CLOUD_ID = "AB:CD:EF:12:34:56:78:90"


def _state_response(power: Any = 1) -> dict[str, Any]:
    return {
        "requestId": "ignored",
        "msg": "success",
        "code": 200,
        "payload": {
            "sku": SKU,
            "device": CLOUD_ID,
            "capabilities": [
                {"type": "devices.capabilities.online", "instance": "online", "state": {"value": True}},
                {"type": "devices.capabilities.on_off", "instance": "powerSwitch", "state": {"value": power}},
                {"type": "devices.capabilities.range", "instance": "brightness", "state": {"value": 80}},
                {"type": "devices.capabilities.color_setting", "instance": "colorRgb", "state": {"value": 16711680}},
                {"type": "devices.capabilities.color_setting", "instance": "colorTemperatureK", "state": {"value": ""}},
            ],
        },
    }


_USER_DEVICES = {
    "code": 200,
    "message": "success",
    "data": [
        {"sku": "H6008", "device": "11:22:33:44:55:66:77:88", "deviceName": "Lamp"},
        {"sku": SKU, "device": CLOUD_ID, "deviceName": "RGBIC TV Light Bars"},
    ],
}

# Govee rejects a state request without a sku; this body shape is what the
# router API returns for parameter errors.
_BAD_REQUEST_BODY = '{"code":400,"message":"Parameter error: sku must not be empty"}'


class _FakeResp:
    def __init__(self, status: int = 200, payload: Any = None, text: str = "") -> None:
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self) -> Any:
        return self._payload


class _FakeGovee:
    """Stands in for httpx.AsyncClient: records requests, answers like Govee."""

    posts: list[dict[str, Any]] = []
    gets: list[str] = []
    power: Any = 1
    state_status: int = 200

    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeGovee":
        return self

    async def __aexit__(self, *a: Any) -> bool:
        return False

    async def get(self, url: str, headers: Any = None) -> _FakeResp:
        _FakeGovee.gets.append(url)
        return _FakeResp(200, _USER_DEVICES)

    async def post(self, url: str, headers: Any = None, json: Any = None) -> _FakeResp:
        _FakeGovee.posts.append({"url": url, "json": json})
        if url.endswith("/device/state"):
            if _FakeGovee.state_status != 200 or not json["payload"]["sku"]:
                return _FakeResp(400, None, _BAD_REQUEST_BODY)
            return _FakeResp(200, _state_response(_FakeGovee.power))
        return _FakeResp(200, {"code": 200, "msg": "success"})


@pytest.fixture(autouse=True)
def _patch(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeGovee)
    monkeypatch.setattr(GoveeProtocol, "_get_api_key", lambda self: "test-key")
    monkeypatch.setattr(govee_mod, "_sku_cache", {})
    _FakeGovee.posts = []
    _FakeGovee.gets = []
    _FakeGovee.power = 1
    _FakeGovee.state_status = 200


def _device() -> DiscoveredDevice:
    return DiscoveredDevice(
        name="RGBIC TV Light Bars", domain="light", manufacturer="govee",
        model=SKU, protocol="govee", entity_id="rgbic_tv_light_bars",
        cloud_id=CLOUD_ID,
    )


def _state_posts() -> list[dict[str, Any]]:
    return [p for p in _FakeGovee.posts if p["url"].endswith("/device/state")]


def _control_posts() -> list[dict[str, Any]]:
    return [p for p in _FakeGovee.posts if p["url"].endswith("/device/control")]


def test_state_request_body_and_parsed_response() -> None:
    state = asyncio.run(GoveeProtocol().get_state("", cloud_id=CLOUD_ID, model=SKU))

    [post] = _state_posts()
    body = post["json"]
    assert post["url"] == "https://openapi.api.govee.com/router/api/v1/device/state"
    assert set(body) == {"requestId", "payload"}
    uuid.UUID(body["requestId"])  # a fresh id per request
    assert body["payload"] == {"sku": SKU, "device": CLOUD_ID}
    assert state == {"state": "on", "brightness": 80, "rgb": [255, 0, 0]}


def test_state_reads_off() -> None:
    _FakeGovee.power = 0
    state = asyncio.run(GoveeProtocol().get_state("", cloud_id=CLOUD_ID, model=SKU))
    assert state["state"] == "off"


def test_state_without_model_looks_up_sku_once() -> None:
    # The node's state path passes only ip/entity_id/cloud_id/mac_address.
    proto = GoveeProtocol()
    for _ in range(2):
        state = asyncio.run(proto.get_state("", entity_id="rgbic_tv_light_bars", cloud_id=CLOUD_ID, mac_address=""))
        assert state["state"] == "on"

    assert [p["json"]["payload"]["sku"] for p in _state_posts()] == [SKU, SKU]
    assert _FakeGovee.gets == ["https://openapi.api.govee.com/router/api/v1/user/devices"]


def test_state_400_logs_body_and_is_not_off(caplog: pytest.LogCaptureFixture) -> None:
    _FakeGovee.state_status = 400
    with caplog.at_level(logging.WARNING):
        state = asyncio.run(GoveeProtocol().get_state("", cloud_id=CLOUD_ID, model=SKU))

    assert "400" in state["error"]
    assert "sku must not be empty" in state["error"]
    assert state.get("state") != "off"
    assert "sku must not be empty" in caplog.text


def test_unreadable_power_is_unknown_not_off() -> None:
    _FakeGovee.power = ""
    state = asyncio.run(GoveeProtocol().get_state("", cloud_id=CLOUD_ID, model=SKU))
    assert state["state"] == "unknown"


def test_toggle_on_light_turns_it_off() -> None:
    result = asyncio.run(GoveeProtocol().control(_device(), "toggle"))

    assert result.success
    assert _state_posts()[0]["json"]["payload"] == {"sku": SKU, "device": CLOUD_ID}
    [control] = _control_posts()
    assert control["json"]["payload"]["capability"]["value"] == 0


def test_toggle_with_unknown_state_sends_nothing() -> None:
    _FakeGovee.state_status = 400
    result = asyncio.run(GoveeProtocol().control(_device(), "toggle"))

    assert not result.success
    assert "unknown" in (result.error or "")
    assert _control_posts() == []


def test_control_uses_fresh_request_id() -> None:
    asyncio.run(GoveeProtocol().control(_device(), "turn_off"))
    [control] = _control_posts()
    uuid.UUID(control["json"]["requestId"])
