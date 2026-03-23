# jarvis-device-govee

Govee smart device protocol adapter with hybrid LAN+cloud control for [Jarvis](https://github.com/alexberardi/jarvis-node-setup).

## Install

```bash
python scripts/command_store.py install --url https://github.com/alexberardi/jarvis-device-govee
```

## Supported Devices

- Smart lights and LED strips
- Smart plugs
- Smart kettles and appliances

## Secrets

| Key | Required | Description |
|-----|----------|-------------|
| `GOVEE_API_KEY` | Yes | Govee Developer API key from https://developer.govee.com |

## Structure

```
device_families/govee/protocol.py   # Device protocol adapter
```
