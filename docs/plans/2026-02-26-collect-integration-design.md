# Collect Integration Design — Migrate PLC Data Collection to ThingsBoard Gateway

**Date:** 2026-02-26
**Branch:** `release/3.8.2-sae-main-collect-integrate`
**Status:** Approved

## Goal

Replace the Java-based `collect` application (Spring Boot, 316 classes) with Python-based custom connectors in the ThingsBoard IoT Gateway. The `collect` app aggregates data from 14 types of factory equipment. This phase focuses on **PLC communication**: KV8000 (Keyence TCP) and SCADA (FC7_DBcomm).

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Migration scope | KV8000 + SCADA/FC7 first | Core real-time data sources |
| FC7 JAR strategy | JPype bridge | JVM already present for TB Edge |
| Config source | ThingsBoard device attributes | Centralized, no HDS server dependency |
| Data storage | Gateway built-in event storage | No local MySQL needed |
| Auto-adjustment | ThingsBoard Rule Engine (out of scope) | Clean separation of concerns |
| Architecture | One connector per protocol | Independent lifecycle, testing, deployment |
| Package location | `tb_gateway_collect/` | Follows project convention — no modifications to `thingsboard_gateway/` |

## Package Structure

```
tb_gateway_collect/
├── __init__.py
├── connectors/
│   ├── __init__.py
│   ├── kv8000/
│   │   ├── __init__.py
│   │   ├── kv8000_connector.py        # Connector + Thread, polling loop
│   │   ├── kv8000_protocol.py         # TCP client, Keyence ASCII protocol
│   │   ├── kv8000_data_types.py       # BOOL, UINT, DINT, REAL, STRING enums
│   │   └── kv8000_uplink_converter.py # Raw PLC data → ConvertedData
│   └── scada/
│       ├── __init__.py
│       ├── scada_connector.py          # Connector + Thread, polling loop
│       ├── scada_fc7_bridge.py         # JPype wrapper for FC7_DBcomm_Java.jar
│       └── scada_uplink_converter.py   # Raw SCADA data → ConvertedData
├── common/
│   ├── __init__.py
│   ├── plc_config.py                   # Shared config model
│   └── plc_data_types.py              # Shared data types (KVData equivalent)
└── tests/
    ├── __init__.py
    ├── test_kv8000_protocol.py
    ├── test_kv8000_connector.py
    ├── test_scada_bridge.py
    └── test_scada_connector.py
```

## KV8000 Connector

### Protocol Layer (`kv8000_protocol.py`)

Pure Python TCP client reimplementing the Keyence ASCII protocol from Java's `KVInstructBuilder`:

| Operation | Command Format | Example |
|-----------|---------------|---------|
| Single read | `RD <ADDR><TYPE>\r` | `RD DM15000.D\r` |
| Sequential read | `RDS <ADDR><TYPE> <N>\r` | `RDS DM15000.D 2\r` |
| Single write | `WR <ADDR><TYPE> <VALUE>\r` | `WR DM15000.U 65535\r` |
| Sequential write | `WRS <ADDR><TYPE> <N> <V1> <V2>...\r` | `WRS DM15000.D 2 123 456\r` |

Data types:
- `.U` — unsigned 16-bit
- `.S` — signed 16-bit
- `.D` — unsigned 32-bit
- `.L` — signed 32-bit
- `.H` — 16-bit hex

Bit-level addressing: `DM15000.3` → read full word at DM15000, extract bit 3.

Connection: TCP socket, 200ms timeout (matching Java implementation).

### Connector Layer (`kv8000_connector.py`)

- Extends `Connector` + `Thread` (same as Modbus connector pattern)
- **Startup**: fetches `plcParams` from ThingsBoard device shared attributes
- **Polling**: every 3 seconds (configurable `pollIntervalMs`), opens TCP connection, reads all parameters, closes connection
- **Change detection**: via Gateway's `ON_CHANGE_ONLY` report strategy
- **Telemetry output**: each PLC parameter → telemetry key on the ThingsBoard device
- **RPC**: `server_side_rpc_handler` supports `plc_write(address, type, value)` for writing back to PLC
- **Attributes**: `on_attributes_update` handles parameter config changes

## SCADA/FC7 Connector

### FC7 Bridge (`scada_fc7_bridge.py`)

JPype wrapper around `FC7_DBcomm_Java.jar`:

```python
class FC7Bridge:
    def connect(ip, port) -> session_id
    def is_connected(session_id) -> bool
    def get_all_tags(session_id) -> List[str]
    def get_data(session_id, addresses) -> Dict[str, str]
    def set_data(session_id, address, value) -> bool
    def disconnect(session_id)
```

- JVM started once on first `connect()`, reused
- JAR path configurable (default: bundled)
- REAL type: multiply raw int by scale factor (e.g., `302 * 0.001 = 0.302`)
- DINT type: strip decimal places

### Connector Layer (`scada_connector.py`)

Structurally identical to KV8000Connector:
- Same `Connector` + `Thread` base, same polling loop pattern
- Uses `FC7Bridge` instead of TCP socket
- Same 3-second polling, same config-from-attributes pattern
- Batch reads via `get_all_tags()` + `get_data()` (unlike KV8000's per-parameter reads)

## Configuration

### Gateway config (`tb_gateway.json`)

Only ONE of these per deployment (KV8000 and FC7 are mutually exclusive):

```json
{
  "name": "KV8000 Connector",
  "type": "kv8000",
  "configuration": "kv8000.json"
}
```

### Connector config (`kv8000.json`)

```json
{
  "pollIntervalMs": 3000,
  "devices": [
    {
      "deviceName": "KV8000-Line1",
      "deviceType": "plc",
      "address": "192.168.1.100",
      "port": 8501,
      "attributeSource": "thingsboard",
      "parameters": []
    }
  ]
}
```

When `attributeSource` is `"thingsboard"`, parameters are fetched from device shared attributes. The `parameters` array is a fallback for offline deployments.

### ThingsBoard device attribute format

Shared attribute `plcParams` on the PLC device:

```json
[
  {"address": "DM15000", "dataType": "DINT", "dataLength": 2, "name": "temperature"},
  {"address": "DM15002", "dataType": "REAL", "dataLength": 2, "name": "pressure", "scale": 0.001},
  {"address": "DM15004.3", "dataType": "BOOL", "dataLength": 1, "name": "alarm_motor_overheat"}
]
```

## Data Flow

### Read path (telemetry)

```
KV8000 PLC ──TCP──▶ KV8000Connector ──ConvertedData──▶ Gateway Event Storage
                       (3s poll)                              ▼
                                                         TB Client (MQTT)
                                                              ▼
                                                        ThingsBoard Edge
                                                              ▼
                                                        Rule Engine
```

### Write path (RPC)

```
ThingsBoard ──RPC──▶ Gateway ──server_side_rpc_handler──▶ Connector ──TCP/FC7──▶ PLC
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| TCP connection failure | Log warning, skip poll cycle, retry next cycle. After N consecutive failures, mark device disconnected. |
| JVM/JPype startup failure | Log error, connector stays `is_connected() = False`, reports to Gateway. |
| PLC read timeout (200ms) | Skip that parameter, continue with next. |
| Invalid data from PLC | Log warning with raw response, skip data point. |
| TB attribute fetch failure | Fall back to local `parameters` config. Log warning. |
| PLC unreachable | Keep polling at interval. Resume on reconnection. |

## Testing

Located in `tests/unit/collect/` (pytest, same pattern as `tests/unit/windows/`):

- `test_kv8000_protocol.py` — protocol message building/parsing (mock socket)
- `test_kv8000_connector.py` — polling loop, change detection, ConvertedData output
- `test_scada_bridge.py` — FC7Bridge (mock JPype/JVM)
- `test_scada_connector.py` — SCADA polling and data conversion

## Dependencies

Added to `requirements-sae.txt`:
- `JPype1` — for SCADA/FC7 bridge

KV8000 connector uses only Python stdlib (`socket`).

## Future Phases (Out of Scope)

- Log-based modules: AB Dim, IVS, ICS, HCCM, XJSBB (file-watching connectors)
- Auto-adjustment logic in ThingsBoard Rule Engine
- Alarm management connector
- Auth/WebSocket/RocketMQ features (replaced by ThingsBoard equivalents)
