# ThingsBoard IoT Gateway — Windows Native Exe Design

**Date:** 2026-02-26
**Status:** Approved
**Branch:** release/3.8.2-sae-main

## Goal

Package the ThingsBoard IoT Gateway as a standalone Windows `.exe` with a system tray UI for monitoring gateway status. Zero modifications to the original gateway codebase to allow pulling upstream updates.

## Architecture

### Approach: Wrapper Package

A new `tb_gateway_windows/` package that imports `TBGatewayService` from the original code and wraps it with a system tray interface. All new code lives outside the original `thingsboard_gateway/` package.

```
┌─────────────────────────────────────────────────────┐
│                    PyInstaller Exe                   │
│                                                     │
│  tb_gateway_windows/                                │
│    __main__.py  → starts gateway thread + tray      │
│    tray.py      → pystray system tray icon          │
│    gateway_monitor.py → reads gateway status         │
│    gateway_runner.py  → manages gateway lifecycle    │
│                                                     │
│  thingsboard_gateway/  (original, unmodified)       │
│    TBGatewayService, connectors, storage, etc.      │
│                                                     │
│  config/  logs/  extensions/  (alongside exe)       │
└─────────────────────────────────────────────────────┘
```

### Threading Model

- **Main thread:** `pystray` tray app (required by OS for system tray)
- **Background thread:** `TBGatewayService` (the actual gateway)
- **Monitor timer:** Polls gateway status every 5 seconds from tray thread

### In-Process Monitoring

The monitor reads directly from the `TBGatewayService` instance:
- `gateway.tb_client.is_connected()` — ThingsBoard connection
- `gateway.connected_devices` — device count
- `gateway.active_connectors` / `gateway.inactive_connectors` — connector health
- `gateway.get_storage_events_count()` — storage queue depth
- `gateway.version` — version info

No IPC, sockets, or network calls needed.

## System Tray UI

### Tray States

| State | Icon Color | Tooltip |
|-------|-----------|---------|
| Starting | Yellow | "TB Gateway - Starting..." |
| Connected | Green | "TB Gateway - Connected (N devices, M connectors)" |
| Disconnected | Red | "TB Gateway - Disconnected from ThingsBoard" |
| Connector Down | Orange | "TB Gateway - N connector(s) offline" |
| Stopped | Grey | "TB Gateway - Stopped" |

### Right-Click Menu

```
 ThingsBoard IoT Gateway v3.8.2
 ─────────────────────────────────
 Status:      Connected
 Devices:     N connected
 Connectors:  M/T active
 Storage:     K events queued
 ─────────────────────────────────
 Open Config Folder
 Open Logs Folder
 Restart Gateway
 ─────────────────────────────────
 Exit
```

### Windows Toast Notifications

Triggered on state transitions (detected by diffing previous vs current state):
- "ThingsBoard connection lost"
- "ThingsBoard reconnected"
- "Connector 'X' disconnected"
- "Connector 'X' reconnected"

## Build & Packaging

### PyInstaller Configuration

- **Mode:** `--onefile` (single standalone executable)
- **Window mode:** `--noconsole` (no terminal window)
- **Target:** Windows x86_64
- **Estimated size:** ~60-80MB

### Output Structure

```
deploy/
  ├── tb-gateway.exe          (standalone executable)
  ├── config/                 (user-editable, copied from thingsboard_gateway/config/)
  │   ├── tb_gateway.json
  │   ├── logs.json
  │   ├── mqtt.json
  │   ├── modbus.json
  │   ├── opcua.json
  │   ├── rest.json
  │   └── socket.json
  ├── extensions/             (empty, for user custom extensions)
  └── logs/                   (created at runtime)
```

### Bundled Connectors (Core Set)

- MQTT
- Modbus
- OPC-UA
- REST
- Socket

Others excluded to reduce size. Expandable later by adding hidden imports to the spec.

### New Dependencies (Wrapper Only)

- `pystray` — system tray integration
- `Pillow` — icon generation (pystray dependency)

No changes to original project's requirements.

## File Structure (New Code)

```
tb_gateway_windows/
  ├── __init__.py
  ├── __main__.py              # Entry point
  ├── gateway_runner.py        # TBGatewayService lifecycle management
  ├── gateway_monitor.py       # Status polling and transition detection
  ├── tray.py                  # pystray: icon, menu, notifications
  ├── icons.py                 # Pillow-generated status icons
  ├── resources/
  │   └── tb_gateway.ico       # App icon for exe
  └── build/
      ├── windows.spec          # PyInstaller spec
      └── build.py              # Build helper
```

**Estimated total new code:** ~400-500 lines.

## Configuration

The exe resolves config path as: directory containing the exe + `/config/`.
Sets `TB_GW_CONFIG_DIR` environment variable before starting `TBGatewayService`.

Logs directory similarly resolved relative to exe location, with `logs.json` handlers patched to use absolute paths.

## Constraints

- Python >= 3.10 (matches upstream requirement)
- Zero modifications to files under `thingsboard_gateway/`
- All new code under `tb_gateway_windows/` and `docs/`
- Must survive `git pull` from upstream ThingsBoard repository
