# Key-Value Telemetry Format Redesign

**Date:** 2026-03-03
**Branch:** `release/3.8.2-sae-main-collect-integrate`
**Status:** Approved

## Problem

All 6 log parsers currently emit telemetry in a format tailored for the original "collect" project's database model. CSV column values are either cherry-picked into hardcoded field names (`pos`, `master`) or combined into a single `log_value` string. The downstream Edge system cannot parse this — it expects individual key-value pairs matching the original CSV column headers so it can perform calculations on specific fields.

**Example (ICS, current):**
```python
{"pos": "4", "master": "N", "log_value": "6.8,2.0,132.6,...", "result": "1", "raw_data": "..."}
```

**Example (ICS, desired):**
```python
{"Time": "2026-03-03 00:00:02:269", "POS": "4", "Master": "N", "EX1": "6.8", "EX2": "2.0", "EY1": "132.6", "EY2": "406.7", "ED1": "275.1", "ED2": "151.2", "EDX1": "276.1", "EDY1": "274.1", "EDX2": "146.4", "EDY2": "156.1", "Result": "1", "raw_data": "..."}
```

## Decisions

1. **Scope:** All 6 parsers (AB Dim, IVS, ICS, HCCM Result, HCCM Slider, XJSBB)
2. **Approach:** Modify each parser individually (Approach A) — minimal structural change
3. **Timestamp:** Both `TelemetryEntry.ts` (epoch ms from parsed record time) AND `Time` as a telemetry key-value pair (original string)
4. **Value types:** All strings — no numeric conversion; Edge handles types
5. **Extra fields:** Keep `raw_data` alongside per-column values
6. **Key names:** Dynamic from file header row (except IVS/XJSBB which have no headers)

## Design

### Unchanged Components

- `LogUplinkConverter` — already maps `record.values` dict to `TelemetryEntry` with `DatapointKey` keys
- `ConvertedData` / `TelemetryEntry` — already correct structure
- `StateTracker` / cold start — unaffected
- `LogCollectorConnector._process_file()` — unaffected
- File watching / polling — unaffected

### CSV Parsers: Common Pattern

For ICS, AB Dim, HCCM Result, HCCM Slider — all read headers dynamically from file:

```python
# Old: cherry-pick + combine
for i, header in enumerate(headers):
    if h == "time": timestamp = parse(col)
    elif h == "pos": values["pos"] = col
    elif h == "result": values["log_value"] = ",".join(parts)
    else: log_val_parts.append(col)

# New: zip all
for i, header in enumerate(headers):
    values[header] = columns[i].strip()
timestamp = parse_ts(values["Time"])
values["raw_data"] = raw
```

### ICS Parser

- Header source: dynamic from file + `ADAPTIVE_HEADERS` fallback (7/9/10/13/14/19 columns)
- Change: Replace cherry-pick loop with zip-all
- Drop: `log_value` field
- Keep: header-row detection, `_parse_timestamp_with_millis`

**Output:**
```python
{"Time": "2026-03-03 00:00:02:269", "POS": "4", "Master": "N", "EX1": "6.8", ..., "Result": "1", "raw_data": "..."}
```

### AB Dim Parser

- Header source: dynamic from file (`HEADER_RE`)
- Change: Replace cherry-pick loop with zip-all
- Drop: hardcoded `pos`/`master`/`a_dim`/`b_dim` field names
- Keep: header-row detection, `_parse_timestamp`

**Output:**
```python
{"Order": "1", "Result": "OK", ..., "Time": "2026-03-03 10:30:45:123", "raw_data": "..."}
```

### HCCM Result/Slider Parsers

- Header source: dynamic from file (`RESULT_HEADER_RE` / `SLIDER_HEADER_RE`)
- Change: Replace cherry-pick loop with zip-all in `_BaseHCCMParser._extract_records`
- Drop: `log_value` field
- Dedup key: `values.get("PosID")` instead of `values.get("pos")`
- Time parsing: `_parse_time_only` (HH:mm:ss, prepends today's date)

**Output:**
```python
{"PosID": "1", "BaseholeX": "0.5", ..., "Time": "14:30:05", "raw_data": "..."}
```

### IVS Parser

IVS has **no header row** and **two distinct row types**. Fixed key names required.

**Type 1 — Detection Result (检测结果):**
Row: `2026/03/02 07:14:09,L检测结果,T2,T4,T6,T2,T6,T4,T6,T2,T2,T2`

```python
{
    "Time": "2026/03/02 07:14:09",
    "Direction": "L",
    "Result0": "T2", "Result1": "T4", "Result2": "T6",
    "Result3": "T2", "Result4": "T6", "Result5": "T4",
    "Result6": "T6", "Result7": "T2", "Result8": "T2", "Result9": "T2",
    "result_type": "1",
    "raw_data": "..."
}
```

**Type 2 — PadResult (no longer skipped):**
Row: `2026/03/02 07:14:31,PadResult,OK,HGA4Pad0\tHR=0.733[0.500],WP=58.0[74.0]`

```python
{
    "Time": "2026/03/02 07:14:31",
    "PadResult": "OK",
    "PadName": "HGA4Pad0",
    "HR": "0.733[0.500]",
    "WP": "58.0[74.0]",
    "result_type": "2",
    "raw_data": "..."
}
```

### XJSBB Parser

Format is key-value per line: `timestamp   var_name:var_value`

**Change:** Use `var_name` as the telemetry key directly instead of two separate fields.

**Old:** `{"var_name": "Temp", "var_value": "25.5", "raw_data": "..."}`
**New:** `{"Time": "2026-03-03 10:30:45:123", "Temp": "25.5", "raw_data": "..."}`

Change detection stays (compare var_name + var_value).

## Testing

All existing parser tests must be updated to verify the new output format:
- Key names match column headers (case-preserved)
- All values are strings
- `Time` is present as a telemetry key
- `raw_data` is present
- `LogRecord.timestamp` is correctly parsed from the Time value
- IVS: both row types emit correct keys
- XJSBB: var_name used as key
