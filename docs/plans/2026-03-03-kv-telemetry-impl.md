# Key-Value Telemetry Format Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign all 6 log parsers to emit per-column key-value telemetry instead of combined `log_value` fields, so the Edge system can perform calculations on individual data fields.

**Architecture:** Each parser's `_extract_records` method is modified to zip file headers with column values (CSV parsers) or use var_name as the telemetry key (XJSBB). IVS gets two-type parsing (detection result + PadResult). No changes to LogUplinkConverter, ConvertedData, or StateTracker.

**Tech Stack:** Python 3, pytest, ThingsBoard Gateway ConvertedData/TelemetryEntry

**Design doc:** `docs/plans/2026-03-03-kv-telemetry-design.md`

---

### Task 1: ICS Parser — Key-Value Output

**Files:**
- Modify: `tb_gateway_collect/connectors/log_collector/parsers/ics_parser.py`
- Modify: `tests/unit/collect/test_ics_parser.py`

**Step 1: Update tests to assert new key-value format**

Replace the test assertions in `test_ics_parser.py`. The test data (`SAMPLE_ICS_9COL`, `SAMPLE_ICS_14COL`) stays the same — only assertions change.

In `test_parse_9col`, replace:
```python
assert r.values["pos"] == "3"
assert r.values["master"] == "A"
assert r.values["result"] == "OK"
assert "log_value" in r.values
```
with:
```python
assert r.values["Time"] == "2026-03-03 10:30:45:123"
assert r.values["POS"] == "3"
assert r.values["Master"] == "A"
assert r.values["EX1"] == "1.1"
assert r.values["EY1"] == "2.2"
assert r.values["ED1"] == "3.3"
assert r.values["EDX1"] == "4.4"
assert r.values["EDY1"] == "5.5"
assert r.values["Result"] == "OK"
assert "raw_data" in r.values
assert "log_value" not in r.values
```

In `test_parse_14col`, replace:
```python
assert records[0].values["result"] == "OK"
```
with:
```python
r = records[0]
assert r.values["Time"] == "2026-03-03 10:30:45:100"
assert r.values["POS"] == "1"
assert r.values["EX1"] == "1"
assert r.values["EX2"] == "2"
assert r.values["EY1"] == "3"
assert r.values["EY2"] == "4"
assert r.values["ED1"] == "5"
assert r.values["ED2"] == "6"
assert r.values["EDX1"] == "7"
assert r.values["EDY1"] == "8"
assert r.values["EDX2"] == "9"
assert r.values["EDY2"] == "10"
assert r.values["Result"] == "OK"
```

In `test_adaptive_headers_by_column_count`, replace:
```python
assert records[0].values["pos"] == "3"
```
with:
```python
assert records[0].values["POS"] == "3"
assert records[0].values["EX1"] == "1.1"
assert records[0].values["Result"] == "OK"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_ics_parser.py -v`
Expected: FAIL — old format still uses `pos`, `master`, `log_value`

**Step 3: Implement ICS parser zip-all**

In `ics_parser.py`, replace the `_extract_records` method body. The new loop inside the `for m in ROW_RE.finditer(content):` block:

```python
def _extract_records(
    self, content: str, file_headers: Optional[list[str]], device_name: str
) -> list[LogRecord]:
    records = []
    for m in ROW_RE.finditer(content):
        try:
            raw = m.group().rstrip("\r\n")
            columns = raw.split(",")
            headers = self._get_headers_for_row(columns, file_headers)

            if len(columns) < len(headers):
                continue

            # Check if this is a header row (column value == header name)
            is_header_row = False
            for i, header in enumerate(headers):
                if columns[i].strip().lower() == header.lower():
                    is_header_row = True
                    break

            if is_header_row:
                continue

            # Zip all headers with column values
            values = {}
            for i, header in enumerate(headers):
                values[header] = columns[i].strip()

            # Parse timestamp from Time column
            time_str = values.get("Time")
            if not time_str:
                continue
            timestamp = _parse_timestamp_with_millis(time_str)

            values["raw_data"] = raw
            records.append(LogRecord(
                device_name=device_name,
                timestamp=timestamp,
                values=values,
                system_type="ics",
            ))
        except Exception as e:
            log.warning("Skipping malformed ICS row: %s", e)
    return records
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_ics_parser.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/parsers/ics_parser.py tests/unit/collect/test_ics_parser.py
git commit -m "refactor(ics-parser): emit per-column key-value telemetry"
```

---

### Task 2: AB Dim Parser — Key-Value Output

**Files:**
- Modify: `tb_gateway_collect/connectors/log_collector/parsers/ab_dim_parser.py`
- Modify: `tests/unit/collect/test_ab_dim_parser.py`

**Step 1: Update tests to assert new key-value format**

In `test_parse_basic`, replace:
```python
assert r.values["pos"] == "3"
assert r.values["master"] == "A"
assert r.values["a_dim"] == "12.34"
assert r.values["b_dim"] == "56.78"
assert r.values["result"] == "OK"
```
with:
```python
assert r.values["Time"] == "2026-03-03 10:30:45:123"
assert r.values["Order"] == "1"
assert r.values["Result"] == "OK"
assert r.values["POS"] == "3"
assert r.values["Master"] == "A"
assert r.values["A_Dim(um)"] == "12.34"
assert r.values["B_Dim(um)"] == "56.78"
assert r.values["Head"] == "H1"
assert r.values["HGA"] == "HGA1"
assert "raw_data" in r.values
```

In `test_parse_incremental_new_lines`, replace:
```python
assert records[0].values["pos"] == "7"
```
with:
```python
assert records[0].values["POS"] == "7"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_ab_dim_parser.py -v`
Expected: FAIL

**Step 3: Implement AB Dim parser zip-all**

In `ab_dim_parser.py`, replace the `_extract_records` method:

```python
def _extract_records(
    self, content: str, headers: list[str], device_name: str
) -> list[LogRecord]:
    records = []
    for m in ROW_RE.finditer(content):
        try:
            raw = m.group().rstrip("\r\n")
            columns = raw.split(",")
            if len(columns) < len(headers):
                continue

            # Check if this is a header row
            is_header_row = False
            for i, header in enumerate(headers):
                if columns[i].strip() == header:
                    is_header_row = True
                    break

            if is_header_row:
                continue

            # Zip all headers with column values
            values = {}
            for i, header in enumerate(headers):
                values[header] = columns[i].strip()

            # Parse timestamp from Time column
            time_str = values.get("Time")
            if not time_str:
                continue
            timestamp = self._parse_timestamp(time_str)

            values["raw_data"] = raw
            records.append(LogRecord(
                device_name=device_name,
                timestamp=timestamp,
                values=values,
                system_type="ab",
            ))
        except Exception as e:
            log.warning("Skipping malformed AB row: %s", e)
    return records
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_ab_dim_parser.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/parsers/ab_dim_parser.py tests/unit/collect/test_ab_dim_parser.py
git commit -m "refactor(ab-parser): emit per-column key-value telemetry"
```

---

### Task 3: HCCM Result/Slider Parsers — Key-Value Output

**Files:**
- Modify: `tb_gateway_collect/connectors/log_collector/parsers/hccm_parser.py`
- Modify: `tests/unit/collect/test_hccm_parser.py`

**Step 1: Update tests to assert new key-value format**

In `TestHCCMResultParser.test_parse_basic`, replace:
```python
assert r.values["pos"] == "1"
```
with:
```python
assert r.values["Time"] == "10:30:5"
assert r.values["PosID"] == "1"
assert r.values["BaseholeX"] == "10.5"
assert r.values["BaseholeY"] == "20.3"
assert r.values["SUSP_X"] == "0.5"
assert r.values["SUSP_Y"] == "0.3"
assert "raw_data" in r.values
```

In `TestHCCMSliderParser.test_parse_basic`, replace:
```python
assert records[-1].values["pos"] == "2"
```
with:
```python
assert records[-1].values["PosID"] == "2"
```

In `TestHCCMSliderParser.test_dedup_same_pos_within_5s`, replace:
```python
pos1_records = [r for r in records if r.values["pos"] == "1"]
```
with:
```python
pos1_records = [r for r in records if r.values["PosID"] == "1"]
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_hccm_parser.py -v`
Expected: FAIL

**Step 3: Implement HCCM parser zip-all**

In `hccm_parser.py`, replace the `_extract_records` method in `_BaseHCCMParser`:

```python
def _extract_records(
    self, content: str, headers: Optional[list[str]], device_name: str
) -> list[LogRecord]:
    records = []
    for m in ROW_RE.finditer(content):
        try:
            raw = m.group().rstrip("\r\n")
            columns = raw.split(",")

            if headers and len(columns) >= len(headers):
                used_headers = headers
            else:
                used_headers = None

            if used_headers:
                # Check if header row
                is_header_row = False
                for i, header in enumerate(used_headers):
                    if columns[i].strip() == header:
                        is_header_row = True
                        break
                if is_header_row:
                    continue

                # Zip all headers with column values
                values = {}
                for i, header in enumerate(used_headers):
                    values[header] = columns[i].strip()

                time_str = values.get("Time")
                if not time_str:
                    continue
                timestamp = _parse_time_only(time_str)
            else:
                # No header found: assume last column is time, rest are positional
                timestamp = _parse_time_only(columns[-1].strip())
                values = {}
                for i, col in enumerate(columns[:-1]):
                    values[f"col_{i}"] = col.strip()
                values["Time"] = columns[-1].strip()

            values["raw_data"] = raw
            records.append(LogRecord(
                device_name=device_name,
                timestamp=timestamp,
                values=values,
                system_type=self._system_type,
            ))
        except Exception as e:
            log.warning("Skipping malformed HCCM row: %s", e)
    return records
```

Also update `HCCMSliderParser._post_process` to use `"PosID"` instead of `"pos"`:

```python
def _post_process(self, records: list[LogRecord]) -> list[LogRecord]:
    """5-second dedup: if same PosID within 5s, keep the later record."""
    if not records:
        return records
    deduped = [records[0]]
    for r in records[1:]:
        prev = deduped[-1]
        same_pos = r.values.get("PosID") == prev.values.get("PosID")
        if same_pos:
            delta = abs((r.timestamp - prev.timestamp).total_seconds())
            if delta < 5:
                deduped[-1] = r
                continue
        deduped.append(r)
    return deduped
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_hccm_parser.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/parsers/hccm_parser.py tests/unit/collect/test_hccm_parser.py
git commit -m "refactor(hccm-parser): emit per-column key-value telemetry"
```

---

### Task 4: XJSBB Parser — var_name as Telemetry Key

**Files:**
- Modify: `tb_gateway_collect/connectors/log_collector/parsers/xjsbb_parser.py`
- Modify: `tests/unit/collect/test_xjsbb_parser.py`

**Step 1: Update tests to assert new format**

In `test_parse_basic`, replace:
```python
assert r.values["var_name"] == "Temperature"
assert r.values["var_value"] == "25.5"
```
with:
```python
assert r.values["Time"] == "2026-03-03 10:30:45:123"
assert r.values["Temperature"] == "25.5"
assert "raw_data" in r.values
assert "var_name" not in r.values
assert "var_value" not in r.values
```

In `test_change_detection_filters_duplicates`, replace:
```python
temp_records = [r for r in records if r.values["var_name"] == "Temperature"]
assert len(temp_records) == 2
assert temp_records[0].values["var_value"] == "25.5"
assert temp_records[1].values["var_value"] == "26.0"
```
with:
```python
temp_records = [r for r in records if "Temperature" in r.values]
assert len(temp_records) == 2
assert temp_records[0].values["Temperature"] == "25.5"
assert temp_records[1].values["Temperature"] == "26.0"
```

In `test_whitespace_trimming`, replace:
```python
assert records[0].values["var_name"] == "Var Name"
assert records[0].values["var_value"] == "Value With Spaces"
```
with:
```python
assert records[0].values["Var Name"] == "Value With Spaces"
assert records[0].values["Time"] == "2026-03-03 10:00:00:000"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_xjsbb_parser.py -v`
Expected: FAIL

**Step 3: Implement XJSBB parser key-as-name**

In `xjsbb_parser.py`, modify the record creation in `_extract_records`:

```python
def _extract_records(self, content: str, device_name: str) -> list[LogRecord]:
    records = []
    for m in ROW_RE.finditer(content):
        try:
            time_str = m.group(1)
            var_name = m.group(2).strip()
            var_value = m.group(3).strip()

            # Change detection
            if self._change_detection:
                if self._last_values.get(var_name) == var_value:
                    continue
                self._last_values[var_name] = var_value

            last_colon = time_str.rfind(":")
            normalized = time_str[:last_colon] + "." + time_str[last_colon + 1:]
            timestamp = datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S.%f")

            records.append(LogRecord(
                device_name=device_name,
                timestamp=timestamp,
                values={
                    "Time": time_str,
                    var_name: var_value,
                    "raw_data": m.group().rstrip("\r\n"),
                },
                system_type="xjsbb",
            ))
        except Exception as e:
            log.warning("Skipping malformed XJSBB row: %s", e)
    return records
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_xjsbb_parser.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/parsers/xjsbb_parser.py tests/unit/collect/test_xjsbb_parser.py
git commit -m "refactor(xjsbb-parser): use var_name as telemetry key"
```

---

### Task 5: IVS Parser — Two-Type Key-Value Output

**Files:**
- Modify: `tb_gateway_collect/connectors/log_collector/parsers/ivs_parser.py`
- Modify: `tests/unit/collect/test_ivs_parser.py`

This is the most complex change. IVS has no header row and two distinct row types.

**Step 1: Update tests for new format**

Replace `SAMPLE_IVS_LOG` and all test methods:

```python
SAMPLE_IVS_LOG = (
    "Order,Result,extra,Head,HGA,Time\r\n"
    "2026/3/3 10:30:45,L\u68c0\u6d4b\u7ed3\u679c,T2,T4,T6,T2,T6,T4,T6,T2,T2,T2\r\n"
    "2026/3/3 10:31:00,PadResult,OK,HGA4Pad0\tHR=0.733[0.500],WP=58.0[74.0]\r\n"
    "2026/3/3 10:31:15,a,b,c,d,e\r\n"
)
```

In `test_parse_basic`:
```python
def test_parse_basic(self):
    path = self._write_temp_file(SAMPLE_IVS_LOG)
    try:
        parser = IVSParser()
        records, cursor = parser.parse(path, "IVS-YB101", None)
        # Row 1: 检测结果 (12 cols) -> detection result
        # Row 2: PadResult -> now parsed (no longer skipped)
        # Row 3: other row (6 cols) -> result_type=2 with positional keys
        assert len(records) == 3

        # Detection result
        r0 = records[0]
        assert r0.values["result_type"] == "1"
        assert r0.values["Direction"] == "L"
        assert r0.values["Result0"] == "T2"
        assert r0.values["Result1"] == "T4"
        assert r0.values["Result9"] == "T2"
        assert r0.values["Time"] == "2026/3/3 10:30:45"
        assert r0.timestamp == datetime(2026, 3, 3, 10, 30, 45)

        # PadResult (no longer skipped)
        r1 = records[1]
        assert r1.values["result_type"] == "2"
        assert r1.values["PadResult"] == "OK"
        assert r1.values["PadName"] == "HGA4Pad0"
        assert r1.values["HR"] == "0.733[0.500]"
        assert r1.values["WP"] == "58.0[74.0]"
        assert r1.values["Time"] == "2026/3/3 10:31:00"
    finally:
        os.unlink(path)
```

Replace `test_skip_pad_result_ok` with `test_pad_result_parsed`:
```python
def test_pad_result_parsed(self):
    """PadResult rows are now parsed, not skipped."""
    content = "2026/3/3 10:31:00,PadResult,OK,HGA4Pad0\tHR=0.733[0.500],WP=58.0[74.0]\r\n"
    path = self._write_temp_file(content)
    try:
        parser = IVSParser()
        records, _ = parser.parse(path, "IVS-YB101", None)
        assert len(records) == 1
        assert records[0].values["PadResult"] == "OK"
        assert records[0].values["PadName"] == "HGA4Pad0"
    finally:
        os.unlink(path)
```

Update `test_result_type_chinese_marker`:
```python
def test_result_type_chinese_marker(self):
    content = "2026/3/3 10:30:45,L\u68c0\u6d4b\u7ed3\u679c,T2,T4,T6,T2,T6,T4,T6,T2,T2,T2\r\n"
    path = self._write_temp_file(content)
    try:
        parser = IVSParser()
        records, _ = parser.parse(path, "IVS-YB101", None)
        assert len(records) == 1
        assert records[0].values["result_type"] == "1"
        assert records[0].values["Direction"] == "L"
        assert records[0].values["Result0"] == "T2"
    finally:
        os.unlink(path)
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_ivs_parser.py -v`
Expected: FAIL

**Step 3: Implement IVS parser two-type parsing**

Replace the `_extract_records` method in `ivs_parser.py`:

```python
import re

PAD_RE = re.compile(r"^(.*?)\t(.*)$")
KV_RE = re.compile(r"(\w+)=([^\[,]+(?:\[[^\]]*\])?)")

def _extract_records(self, content: str, device_name: str) -> list[LogRecord]:
    records = []
    for m in ROW_RE.finditer(content):
        try:
            raw = m.group().rstrip("\r\n")
            columns = raw.split(",")
            time_str = columns[0].replace("/", "-")
            timestamp = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")

            values = {"Time": columns[0], "raw_data": raw}

            if "PadResult" in raw and len(columns) >= 3:
                # PadResult row: timestamp,PadResult,OK/NG,PadName\tKV pairs
                values["PadResult"] = columns[1].strip() if len(columns) > 1 else ""
                # The OK/NG status is column 2 (after "PadResult")
                values["PadResult"] = columns[2].strip() if len(columns) > 2 else ""
                # Column 3+ may contain PadName\tKV pairs
                rest = ",".join(columns[3:]) if len(columns) > 3 else ""
                pad_match = PAD_RE.match(rest)
                if pad_match:
                    values["PadName"] = pad_match.group(1).strip()
                    kv_part = pad_match.group(2).strip()
                    for kv_m in KV_RE.finditer(kv_part):
                        values[kv_m.group(1)] = kv_m.group(2)
                else:
                    values["PadName"] = rest.strip()
                values["result_type"] = "2"

            elif "\u68c0\u6d4b\u7ed3\u679c" in raw or len(columns) == 12:
                # Detection result row
                label = columns[1].strip() if len(columns) > 1 else ""
                direction = label[0] if label else ""
                values["Direction"] = direction
                for i in range(2, min(12, len(columns))):
                    values[f"Result{i - 2}"] = columns[i].strip()
                values["result_type"] = "1"

            else:
                # Other row type — store columns positionally
                for i in range(1, len(columns)):
                    values[f"col_{i}"] = columns[i].strip()
                values["result_type"] = "2"

            records.append(LogRecord(
                device_name=device_name,
                timestamp=timestamp,
                values=values,
                system_type="ivs",
            ))
        except Exception as e:
            log.warning("Skipping malformed IVS row: %s", e)
    return records
```

Also add the imports at the top of the file:
```python
PAD_RE = re.compile(r"^(.*?)\t(.*)$")
KV_RE = re.compile(r"(\w+)=([^\[,]+(?:\[[^\]]*\])?)")
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_ivs_parser.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/parsers/ivs_parser.py tests/unit/collect/test_ivs_parser.py
git commit -m "refactor(ivs-parser): two-type key-value telemetry, parse PadResult"
```

---

### Task 6: Update LogUplinkConverter Tests

**Files:**
- Modify: `tests/unit/collect/test_log_uplink_converter.py`

The converter itself doesn't change, but its tests use old key names. Update them to use new-style keys to verify integration.

**Step 1: Update test data to use new key names**

In `test_convert_single_record`, replace:
```python
values={"pos": "3", "result": "OK", "raw_data": "line"},
```
with:
```python
values={"Time": "2026-03-03 10:30:45:123", "POS": "3", "Result": "OK", "raw_data": "line"},
```

In `test_convert_preserves_timestamp`, replace:
```python
values={"a_dim": "12.34"},
```
with:
```python
values={"Time": "2026-03-03 10:30:45:123", "A_Dim(um)": "12.34"},
```

**Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_log_uplink_converter.py -v`
Expected: ALL PASS (converter handles arbitrary dicts — the keys don't matter to it)

**Step 3: Commit**

```bash
git add tests/unit/collect/test_log_uplink_converter.py
git commit -m "test: update uplink converter tests for new key-value format"
```

---

### Task 7: Run Full Test Suite

**Step 1: Run all collect tests**

Run: `python -m pytest tests/unit/collect/ -v`
Expected: ALL PASS

**Step 2: Run all project tests**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

**Step 3: Final commit if any fixups needed**

If all tests pass, no commit needed. If fixes were required, commit them:
```bash
git commit -m "fix: address test failures from key-value telemetry migration"
```
