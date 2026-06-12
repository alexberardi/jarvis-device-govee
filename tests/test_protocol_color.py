"""End-to-end: a spoken color name reaches the Govee control API as colorRgb.

Run with an environment that has ``jarvis_command_sdk`` (>= 0.3.5),
``jarvis_log_client`` and ``httpx`` available, e.g. the node venv:

    /path/to/jarvis-node-setup/.venv/bin/python -m pytest tests/ -q
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Any

import pytest

from jarvis_command_sdk import DiscoveredDevice

_PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "device_families" / "govee" / "protocol.py"


def _load_protocol() -> Any:
    spec = importlib.util.spec_from_file_location("govee_protocol_under_test", _PROTOCOL_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


govee_mod = _load_protocol()
GoveeProtocol = govee_mod.GoveeProtocol


class _FakeResp:
    def __init__(self, status: int = 200, payload: Any = None) -> None:
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = ""

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    """Captures the POST body the protocol sends to Govee."""

    last_post: dict[str, Any] = {}

    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *a: Any) -> bool:
        return False

    async def post(self, url: str, headers: Any = None, json: Any = None) -> _FakeResp:
        _FakeClient.last_post = {"url": url, "json": json}
        return _FakeResp(200, {})


@pytest.fixture(autouse=True)
def _patch(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(GoveeProtocol, "_get_api_key", lambda self: "test-key")
    _FakeClient.last_post = {}


def _device() -> DiscoveredDevice:
    return DiscoveredDevice(
        name="Living Room Strip", domain="light", manufacturer="govee",
        model="H6159", protocol="govee", entity_id="light.living_room_strip",
        cloud_id="AB:CD:EF:12:34:56",
    )


def _capability() -> dict[str, Any]:
    return _FakeClient.last_post["json"]["payload"]["capability"]


def test_set_color_by_name() -> None:
    result = asyncio.run(GoveeProtocol().control(_device(), "set_color", {"color": "green"}))
    assert result.success
    cap = _capability()
    assert cap["instance"] == "colorRgb"
    assert cap["value"] == (0 << 16) + (255 << 8) + 0  # green -> 65280


def test_set_color_warm_white_name() -> None:
    result = asyncio.run(GoveeProtocol().control(_device(), "set_color", {"color": "warm white"}))
    assert result.success
    r, g, b = 255, 214, 170
    assert _capability()["value"] == (r << 16) + (g << 8) + b


def test_set_color_csv() -> None:
    result = asyncio.run(GoveeProtocol().control(_device(), "set_color", {"color": "255,0,128"}))
    assert result.success
    assert _capability()["value"] == (255 << 16) + (0 << 8) + 128


def test_explicit_rgb_still_works() -> None:
    result = asyncio.run(GoveeProtocol().control(_device(), "set_color", {"rgb": [10, 20, 30]}))
    assert result.success
    assert _capability()["value"] == (10 << 16) + (20 << 8) + 30


def test_unknown_color_errors() -> None:
    result = asyncio.run(GoveeProtocol().control(_device(), "set_color", {"color": "chartreuse"}))
    assert not result.success
    assert "color" in (result.error or "").lower()
