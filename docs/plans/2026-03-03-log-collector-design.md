# Log Collector Connector — Design Document

**Date:** 2026-03-03
**Branch:** `release/3.8.2-sae-main-collect-integrate`
**Status:** Approved

## Goal

Port the Java Spring Boot log collection system (`collect/`) to a Python ThingsBoard Gateway connector. Replace the MySQL + RocketMQ pipeline with direct ThingsBoard telemetry via `gateway.send_to_storage()`.

## Target Log Systems

| System | Equipment Type | File Format | Key Parsing Logic |
|--------|---------------|-------------|-------------------|
| AB Dim | `AB_LOG` | CSV `.txt`, header `Order,Result,...,Time` | Timestamp at END of row (`yyyy-MM-dd HH:mm:ss:SSS`). Extract A_Dim, B_Dim, Result, POS. |
| IVS | `IVS_LOG` | CSV `.txt`, charset auto-detect | Timestamp at START (`yyyy/M/d`). Two result types (12-col vs other). Skip `PadResult,OK` rows. |
| ICS | `ICS_LOG` | CSV `.txt`, adaptive columns | 1/2/3-dot glue modes (7-19 columns). Detect column count from header. Time at START. |
| HCCM Result | `HCCM_RESULT` | CSV `.txt`, header `PosID,BaseholeX,...,Time` | Time-only field (`HH:mm:ss`) — prepend today's date. Adaptive columns like ICS. |
| HCCM Slider | `HCCM_SLIDER` | CSV `.txt`, header `PosID,OutLineAngle,...,Time` | Same as Result + 5-second dedup on same POS. |
| XJSBB | `XJSBB_LOG` | Key-value `.txt`: `(time)   (var):(value)` | Regex parse. In-memory change detection — only emit when value differs. |

Extensible for future systems (e.g., `.csv`, `.mdb`, Excel) via new parser classes.

## Architecture

**Approach:** Single `LogCollectorConnector` with parser registry (Approach A).

### Data Flow

```
File change detected (watchdog / fallback poll)
    |
    v
log_file_watcher --> route to correct parser via config systemType
    |
    v
parser.parse(file, cursor) --> list[LogRecord] + new cursor
    |
    v
state_tracker.save(file, new_cursor)
    |
    v
uplink_converter.convert(LogRecord) --> ConvertedData
    |
    v
gateway.send_to_storage(connector_name, connector_id, data)
```

### File Watching Strategy

Dual strategy for reliability:

1. **watchdog** — OS-level filesystem events for real-time detection
2. **Periodic fallback scan** (configurable, default 60s) — catches events missed by watchdog on SMB/network shares

On each poll cycle, the connector probes each source's directories and handles reconnection.

## Package Structure

```
tb_gateway_collect/
  connectors/
    log_collector/
      __init__.py
      log_collector_connector.py    # Main connector (Connector + Thread)
      log_file_watcher.py           # watchdog Observer wrapper
      log_uplink_converter.py       # LogRecord -> ConvertedData
      state_tracker.py              # Persistent JSON file-position tracking
      parsers/
        __init__.py                 # Parser registry
        base_parser.py              # LogParser ABC + LogRecord dataclass
        ab_dim_parser.py
        ivs_parser.py
        ics_parser.py
        hccm_parser.py              # Both Result and Slider parsers
        xjsbb_parser.py

thingsboard_gateway/
  extensions/
    log_collector/
      __init__.py                   # Re-export LogCollectorConnector
```

## Core Interfaces

### LogRecord

```python
@dataclass
class LogRecord:
    device_name: str          # TB device name (e.g., "ICS-YB101")
    timestamp: datetime       # Log entry time
    values: dict[str, Any]    # Parsed fields as telemetry keys
    system_type: str          # "ab", "ivs", "ics", "hccm_result", "hccm_slider", "xjsbb"
```

### LogParser (abstract)

```python
class LogParser(ABC):
    @abstractmethod
    def parse(self, file_path: str, cursor: dict | None) -> tuple[list[LogRecord], dict]:
        """Parse file from cursor position. Returns (new records, updated cursor).
        Cursor is opaque — each parser defines its own format."""

    @abstractmethod
    def matches_file(self, file_path: str) -> bool:
        """Check if this parser handles the given file."""
```

**Cursor formats by parser type:**
- Text/CSV parsers: `{"byte_offset": 12345}`
- Future DB parsers: `{"last_timestamp": "2026-03-03T10:00:00"}`
- Future Excel parsers: `{"last_row": 100}`

### Parser Registry

```python
PARSER_REGISTRY = {
    "ab":           ABDimParser,
    "ivs":          IVSParser,
    "ics":          ICSParser,
    "hccm_result":  HCCMResultParser,
    "hccm_slider":  HCCMSliderParser,
    "xjsbb":        XJSBBParser,
}
```

## Configuration

### log_collector.json

```json
{
  "pollIntervalMs": 60000,
  "stateFile": "log_collector_state.json",
  "logLevel": "INFO",
  "sources": [
    {
      "systemType": "ab",
      "deviceName": "AB-YB101",
      "deviceType": "log_source",
      "watchDirs": ["\\\\192.168.1.100\\share\\AB_logs"],
      "filePattern": "*.txt",
      "dateFilterDays": 30
    },
    {
      "systemType": "ivs",
      "deviceName": "IVS-YB101",
      "deviceType": "log_source",
      "watchDirs": ["\\\\192.168.1.101\\share\\IVS_logs"],
      "filePattern": "*.txt",
      "dateFilterDays": null
    }
  ]
}
```

**Config fields:**
- `pollIntervalMs` — fallback scan interval (supplements watchdog for SMB)
- `stateFile` — path to persistent cursor file (relative to config dir)
- `sources[].systemType` — maps to parser in registry
- `sources[].watchDirs` — directories to monitor (supports UNC paths)
- `sources[].filePattern` — glob for matching log files
- `sources[].dateFilterDays` — only process files within N days (null = no filter)

### Gateway config entry (tb_gateway.json)

```json
{
  "name": "Log Collector",
  "type": "log_collector",
  "class": "LogCollectorConnector",
  "configuration": "log_collector.json"
}
```

## Per-Source Health Monitoring

Each source gets independent health tracking:

```python
@dataclass
class SourceStatus:
    system_type: str
    device_name: str
    connected: bool
    last_check: datetime
    last_data: datetime | None
    error: str | None
```

**Health check behavior (each poll cycle):**
- Probe each source's `watchDirs` for accessibility
- On disconnect: log warning, report device offline to TB, stop watcher
- On reconnect: log info, report device online, restart watcher, catch up on missed files
- `connector.is_connected()` returns `True` if at least one source is connected

## Parser Details (Ported from Java)

### AB Dim (`ABLogService.java` -> `ab_dim_parser.py`)
- Header regex: `Order,Result,.*,Head,HGA,Time`
- Row regex: `.*,\d{4}-\d{1,2}-\d{1,2} .*`
- Timestamp at END of row, format `yyyy-MM-dd HH:mm:ss:SSS`
- Extract: Time, POS, Master, A_Dim(um), B_Dim(um), Result

### IVS (`IVSLogService.java` -> `ivs_parser.py`)
- Header regex: `Order,Result,.*,Head,HGA,Time`
- Row regex: `\d{4}/\d{1,2}/\d{1,2} .*,.*`
- Timestamp at START, format `yyyy/M/d HH:mm:ss`
- Charset auto-detection via `chardet`
- resultType = 1 if contains special markers or 12 columns; 2 otherwise
- Skip rows containing `PadResult,OK`

### ICS (`ICSLogService.java` -> `ics_parser.py`)
- Header regex: `Time,POS,Master,.*,Result`
- Row regex: `\d{4}-\d{1,2}-\d{1,2} .*,.*`
- Timestamp format: `yyyy-MM-dd HH:mm:ss:SSS`
- Adaptive headers: 1/2/3-dot glue modes (7, 9, 10, 13, 14, 19 columns)
- One-dot: `Time,POS,Master,EX1,EY1,ED1,EDX1,EDY1,Result` (9 cols)
- Two-dot: adds EX2,EY2,ED2,EDX2,EDY2 (14 cols)
- Three-dot: adds EX3,EY3,ED3,EDX3,EDY3 (19 cols)
- Width variants use EW instead of ED (7, 10, 13 cols)

### HCCM Result (`HCCMResultLogService.java` -> `hccm_parser.py`)
- Header regex: `PosID,BaseholeX,.*,Time`
- Row regex: `\d{1,2},.*`
- Time-only field `HH:mm:ss` — prepend today's date
- Adaptive column counts like ICS

### HCCM Slider (`HCCMSliderLogService.java` -> `hccm_parser.py`)
- Header regex: `PosID,OutLineAngle,.*,Time`
- Same row/time patterns as Result
- 5-second dedup: if same POS arrives within 5s of previous, replace previous record

### XJSBB (`XJSBBLogService.java` -> `xjsbb_parser.py`)
- Row regex: `(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}:\d{3})   (.*):(.*)\r\n`
- Extracts: logTime, varName (trimmed), varValue (trimmed)
- In-memory change detection: only emits a record when varValue differs from last known

## Dependencies

Add to `requirements-sae.txt`:
```
watchdog
chardet
```

## Testing Strategy

```
tests/unit/collect/
  test_log_collector_connector.py    # Lifecycle, event routing, health monitoring
  test_log_file_watcher.py           # Watcher setup, event handling
  test_state_tracker.py              # Cursor persistence
  test_log_uplink_converter.py       # LogRecord -> ConvertedData
  test_ab_dim_parser.py
  test_ivs_parser.py
  test_ics_parser.py
  test_hccm_parser.py
  test_xjsbb_parser.py
```

- **Parsers**: Fixture files with known content. Assert LogRecord output, cursor advancement, malformed row handling.
- **StateTracker**: JSON save/load, missing file, corrupted file.
- **Watcher**: Mock watchdog events, verify parser routing.
- **Connector**: Mock gateway, verify `send_to_storage()` calls.
- **Health**: Test source status transitions.

## Java Source Reference

All Java implementations are at `collect/src/main/java/com/tdk/sae/collect/`:
- Shared: `init/utils/FileMonitor.java`, `module/common/service/ILogFileService.java`
- AB: `module/abDim/service/ABLogService.java`
- IVS: `module/ivs/service/IVSLogService.java`
- ICS: `module/ics/service/ICSLogService.java`
- HCCM: `module/hccm/service/HCCMResultLogService.java`, `HCCMSliderLogService.java`
- XJSBB: `module/xjsbb/service/XJSBBLogService.java`, `XJSBBDataService.java`
