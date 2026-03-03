# Log Collector Connector Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Port the Java Spring Boot log collection system (AB Dim, IVS, ICS, HCCM, XJSBB) to a Python ThingsBoard Gateway connector that watches log files on disk/network shares and sends parsed data as telemetry.

**Architecture:** Single `LogCollectorConnector(Connector, Thread)` with a parser registry mapping `systemType` to parser classes. Uses `watchdog` for filesystem events with periodic fallback polling for SMB resilience. Persistent JSON-based cursor tracking per file.

**Tech Stack:** Python 3, watchdog (file monitoring), chardet (charset detection), ThingsBoard Gateway Connector API

**Design doc:** `docs/plans/2026-03-03-log-collector-design.md`

**Reference Java source:** `collect/src/main/java/com/tdk/sae/collect/`

**Reference Python connector:** `tb_gateway_collect/connectors/kv8000/`

---

## Task 1: Core Data Models — LogRecord and LogParser ABC

**Files:**
- Create: `tb_gateway_collect/connectors/log_collector/__init__.py`
- Create: `tb_gateway_collect/connectors/log_collector/parsers/__init__.py`
- Create: `tb_gateway_collect/connectors/log_collector/parsers/base_parser.py`
- Test: `tests/unit/collect/test_base_parser.py`

**Step 1: Write the failing test**

```python
# tests/unit/collect/test_base_parser.py
from datetime import datetime
from tb_gateway_collect.connectors.log_collector.parsers.base_parser import LogRecord, LogParser


class TestLogRecord:

    def test_create_log_record(self):
        record = LogRecord(
            device_name="ICS-YB101",
            timestamp=datetime(2026, 3, 3, 10, 30, 45, 123000),
            values={"pos": "1", "master": "A", "result": "OK"},
            system_type="ics",
        )
        assert record.device_name == "ICS-YB101"
        assert record.system_type == "ics"
        assert record.values["pos"] == "1"
        assert record.timestamp == datetime(2026, 3, 3, 10, 30, 45, 123000)

    def test_log_record_with_raw_data(self):
        record = LogRecord(
            device_name="AB-YB101",
            timestamp=datetime(2026, 1, 15, 14, 0, 0),
            values={"raw_data": "1,OK,A,1,2,14:00:00"},
            system_type="ab",
        )
        assert "raw_data" in record.values


class TestLogParserABC:

    def test_cannot_instantiate_abstract(self):
        import pytest
        with pytest.raises(TypeError):
            LogParser()  # type: ignore

    def test_subclass_must_implement_parse(self):
        class IncompleteParser(LogParser):
            def matches_file(self, file_path: str) -> bool:
                return True
        import pytest
        with pytest.raises(TypeError):
            IncompleteParser()

    def test_subclass_must_implement_matches_file(self):
        class IncompleteParser(LogParser):
            def parse(self, file_path, device_name, cursor):
                return [], {}
        import pytest
        with pytest.raises(TypeError):
            IncompleteParser()

    def test_concrete_subclass_works(self):
        class DummyParser(LogParser):
            def parse(self, file_path, device_name, cursor):
                return [], {}
            def matches_file(self, file_path):
                return file_path.endswith(".txt")

        parser = DummyParser()
        records, new_cursor = parser.parse("test.txt", "DEV-1", None)
        assert records == []
        assert new_cursor == {}
        assert parser.matches_file("data.txt") is True
        assert parser.matches_file("data.csv") is False
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/collect/test_base_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Create package structure and implement**

```python
# tb_gateway_collect/connectors/log_collector/__init__.py
```

```python
# tb_gateway_collect/connectors/log_collector/parsers/__init__.py
```

```python
# tb_gateway_collect/connectors/log_collector/parsers/base_parser.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class LogRecord:
    """A single parsed log entry to send as ThingsBoard telemetry."""
    device_name: str
    timestamp: datetime
    values: dict[str, Any]
    system_type: str


class LogParser(ABC):
    """Abstract base for log file parsers.

    Each parser handles a specific log format (AB Dim, IVS, ICS, etc.).
    The cursor is opaque — each parser defines its own format.
    """

    @abstractmethod
    def parse(
        self,
        file_path: str,
        device_name: str,
        cursor: Optional[dict],
    ) -> tuple[list[LogRecord], dict]:
        """Parse file from cursor position.

        Args:
            file_path: Absolute path to the log file.
            device_name: ThingsBoard device name for the records.
            cursor: Previous cursor state, or None for first read.

        Returns:
            Tuple of (new_records, updated_cursor).
        """
        ...

    @abstractmethod
    def matches_file(self, file_path: str) -> bool:
        """Check if this parser handles the given file."""
        ...
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/collect/test_base_parser.py -v`
Expected: PASS (all 5 tests)

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/__init__.py \
        tb_gateway_collect/connectors/log_collector/parsers/__init__.py \
        tb_gateway_collect/connectors/log_collector/parsers/base_parser.py \
        tests/unit/collect/test_base_parser.py
git commit -m "feat(log-collector): add LogRecord dataclass and LogParser ABC"
```

---

## Task 2: State Tracker — Persistent JSON Cursor Storage

**Files:**
- Create: `tb_gateway_collect/connectors/log_collector/state_tracker.py`
- Test: `tests/unit/collect/test_state_tracker.py`

**Step 1: Write the failing test**

```python
# tests/unit/collect/test_state_tracker.py
import json
import os
import tempfile
from tb_gateway_collect.connectors.log_collector.state_tracker import StateTracker


class TestStateTracker:

    def test_get_cursor_returns_none_for_unknown_file(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker = StateTracker(path)
            assert tracker.get_cursor("unknown.txt") is None
        finally:
            os.unlink(path)

    def test_save_and_get_cursor(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker = StateTracker(path)
            tracker.save_cursor("logs/data.txt", {"byte_offset": 1234})
            assert tracker.get_cursor("logs/data.txt") == {"byte_offset": 1234}
        finally:
            os.unlink(path)

    def test_persistence_across_instances(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker1 = StateTracker(path)
            tracker1.save_cursor("file_a.txt", {"byte_offset": 500})

            tracker2 = StateTracker(path)
            assert tracker2.get_cursor("file_a.txt") == {"byte_offset": 500}
        finally:
            os.unlink(path)

    def test_update_existing_cursor(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker = StateTracker(path)
            tracker.save_cursor("file.txt", {"byte_offset": 100})
            tracker.save_cursor("file.txt", {"byte_offset": 200})
            assert tracker.get_cursor("file.txt") == {"byte_offset": 200}
        finally:
            os.unlink(path)

    def test_multiple_files(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker = StateTracker(path)
            tracker.save_cursor("a.txt", {"byte_offset": 10})
            tracker.save_cursor("b.txt", {"byte_offset": 20})
            assert tracker.get_cursor("a.txt") == {"byte_offset": 10}
            assert tracker.get_cursor("b.txt") == {"byte_offset": 20}
        finally:
            os.unlink(path)

    def test_missing_state_file_creates_new(self):
        path = os.path.join(tempfile.gettempdir(), "nonexistent_state.json")
        if os.path.exists(path):
            os.unlink(path)
        try:
            tracker = StateTracker(path)
            assert tracker.get_cursor("any.txt") is None
            tracker.save_cursor("any.txt", {"byte_offset": 0})
            assert os.path.exists(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_corrupted_state_file_resets(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("not valid json {{{")
            path = f.name
        try:
            tracker = StateTracker(path)
            assert tracker.get_cursor("any.txt") is None
        finally:
            os.unlink(path)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/collect/test_state_tracker.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement**

```python
# tb_gateway_collect/connectors/log_collector/state_tracker.py
import json
import logging
import os
from typing import Optional

log = logging.getLogger(__name__)


class StateTracker:
    """Persists per-file cursor state to a JSON file."""

    def __init__(self, state_file_path: str):
        self._path = state_file_path
        self._state: dict[str, dict] = {}
        self._load()

    def _load(self):
        if not os.path.exists(self._path):
            self._state = {}
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                self._state = json.load(f)
        except (json.JSONDecodeError, ValueError):
            log.warning("Corrupted state file %s, resetting", self._path)
            self._state = {}

    def _flush(self):
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2)

    def get_cursor(self, file_path: str) -> Optional[dict]:
        return self._state.get(file_path)

    def save_cursor(self, file_path: str, cursor: dict):
        self._state[file_path] = cursor
        self._flush()
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/collect/test_state_tracker.py -v`
Expected: PASS (all 7 tests)

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/state_tracker.py \
        tests/unit/collect/test_state_tracker.py
git commit -m "feat(log-collector): add StateTracker for persistent cursor storage"
```

---

## Task 3: AB Dim Parser

**Files:**
- Create: `tb_gateway_collect/connectors/log_collector/parsers/ab_dim_parser.py`
- Test: `tests/unit/collect/test_ab_dim_parser.py`

**Java reference:** `collect/.../module/abDim/service/ABLogService.java`

**Key logic to port:**
- Header regex: `Order,Result,.*,Head,HGA,Time`
- Row regex: `.*,\d{4}-\d{1,2}-\d{1,2} .*\n|.*\r\n`
- Timestamp at END of row, format `yyyy-MM-dd HH:mm:ss:SSS` (colon before ms)
- Pad timestamp to 23 chars with `"0"`
- Header-driven column extraction: Time, POS, Master, A_Dim(um), B_Dim(um), Result
- File date filter: path must contain `yyyyMM\dd` for last 30 days (configurable via `dateFilterDays`)

**Step 1: Write the failing test**

```python
# tests/unit/collect/test_ab_dim_parser.py
import os
import tempfile
from datetime import datetime

from tb_gateway_collect.connectors.log_collector.parsers.ab_dim_parser import ABDimParser


SAMPLE_AB_LOG = (
    "Order,Result,some,extra,cols,POS,Master,A_Dim(um),B_Dim(um),Head,HGA,Time\r\n"
    "1,OK,x,y,z,3,A,12.34,56.78,H1,HGA1,2026-03-03 10:30:45:123\r\n"
    "2,NG,x,y,z,5,B,11.11,22.22,H2,HGA2,2026-03-03 10:30:46:45\r\n"
)


class TestABDimParser:

    def _write_temp_file(self, content, suffix=".txt"):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False,
                                         encoding="utf-8", newline="")
        f.write(content)
        f.close()
        return f.name

    def test_parse_basic(self):
        path = self._write_temp_file(SAMPLE_AB_LOG)
        try:
            parser = ABDimParser()
            records, cursor = parser.parse(path, "AB-YB101", None)
            assert len(records) == 2
            r = records[0]
            assert r.device_name == "AB-YB101"
            assert r.system_type == "ab"
            assert r.values["pos"] == "3"
            assert r.values["master"] == "A"
            assert r.values["a_dim"] == "12.34"
            assert r.values["b_dim"] == "56.78"
            assert r.values["result"] == "OK"
            assert r.timestamp == datetime(2026, 3, 3, 10, 30, 45, 123000)
        finally:
            os.unlink(path)

    def test_parse_pads_short_timestamp(self):
        """Timestamp '10:30:46:45' should be padded to '10:30:46:450'."""
        path = self._write_temp_file(SAMPLE_AB_LOG)
        try:
            parser = ABDimParser()
            records, _ = parser.parse(path, "AB-YB101", None)
            assert records[1].timestamp == datetime(2026, 3, 3, 10, 30, 46, 450000)
        finally:
            os.unlink(path)

    def test_parse_with_cursor_skips_already_read(self):
        path = self._write_temp_file(SAMPLE_AB_LOG)
        try:
            parser = ABDimParser()
            records1, cursor1 = parser.parse(path, "AB-YB101", None)
            assert len(records1) == 2

            records2, cursor2 = parser.parse(path, "AB-YB101", cursor1)
            assert len(records2) == 0
            assert cursor2["byte_offset"] == cursor1["byte_offset"]
        finally:
            os.unlink(path)

    def test_parse_incremental_new_lines(self):
        path = self._write_temp_file(SAMPLE_AB_LOG)
        try:
            parser = ABDimParser()
            _, cursor = parser.parse(path, "AB-YB101", None)

            with open(path, "a", encoding="utf-8", newline="") as f:
                f.write("3,OK,x,y,z,7,C,33.33,44.44,H3,HGA3,2026-03-03 10:31:00:000\r\n")

            records, cursor2 = parser.parse(path, "AB-YB101", cursor)
            assert len(records) == 1
            assert records[0].values["pos"] == "7"
        finally:
            os.unlink(path)

    def test_skips_header_row_in_data(self):
        content = (
            "Order,Result,POS,Master,A_Dim(um),B_Dim(um),Head,HGA,Time\r\n"
            "Order,Result,POS,Master,A_Dim(um),B_Dim(um),Head,HGA,Time\r\n"
            "1,OK,3,A,12.34,56.78,H1,HGA1,2026-03-03 10:30:45:123\r\n"
        )
        path = self._write_temp_file(content)
        try:
            parser = ABDimParser()
            records, _ = parser.parse(path, "AB-YB101", None)
            assert len(records) == 1
        finally:
            os.unlink(path)

    def test_malformed_row_skipped(self):
        content = (
            "Order,Result,POS,Master,A_Dim(um),B_Dim(um),Head,HGA,Time\r\n"
            "GARBAGE LINE WITHOUT DATE\r\n"
            "1,OK,3,A,12.34,56.78,H1,HGA1,2026-03-03 10:30:45:123\r\n"
        )
        path = self._write_temp_file(content)
        try:
            parser = ABDimParser()
            records, _ = parser.parse(path, "AB-YB101", None)
            assert len(records) == 1
        finally:
            os.unlink(path)

    def test_matches_file(self):
        parser = ABDimParser()
        assert parser.matches_file("data.txt") is True
        assert parser.matches_file("data.csv") is True
        assert parser.matches_file("data.log") is True
        assert parser.matches_file("data.jpg") is False

    def test_empty_file(self):
        path = self._write_temp_file("")
        try:
            parser = ABDimParser()
            records, cursor = parser.parse(path, "AB-YB101", None)
            assert records == []
        finally:
            os.unlink(path)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/collect/test_ab_dim_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement**

```python
# tb_gateway_collect/connectors/log_collector/parsers/ab_dim_parser.py
import logging
import os
import re
from datetime import datetime
from typing import Optional

from tb_gateway_collect.connectors.log_collector.parsers.base_parser import LogParser, LogRecord

log = logging.getLogger(__name__)

HEADER_RE = re.compile(r"Order,Result,.*,Head,HGA,Time")
ROW_RE = re.compile(r".*,\d{4}-\d{1,2}-\d{1,2} .*\r?\n")

TEXT_EXTENSIONS = {".txt", ".csv", ".log"}


class ABDimParser(LogParser):
    """Parser for AB Dim log files.

    Java reference: ABLogService.java
    Format: CSV with dynamic headers. Timestamp at end of row.
    """

    def matches_file(self, file_path: str) -> bool:
        _, ext = os.path.splitext(file_path)
        return ext.lower() in TEXT_EXTENSIONS

    def parse(
        self,
        file_path: str,
        device_name: str,
        cursor: Optional[dict],
    ) -> tuple[list[LogRecord], dict]:
        byte_offset = (cursor or {}).get("byte_offset", 0)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            log.warning("Failed to read %s: %s", file_path, e)
            return [], cursor or {"byte_offset": 0}

        if not content:
            return [], {"byte_offset": 0}

        # Parse header to know column positions
        headers = self._find_headers(content)
        if headers is None:
            return [], {"byte_offset": len(content.encode("utf-8"))}

        # Only parse new content from byte_offset
        raw_bytes = content.encode("utf-8")
        new_content = raw_bytes[byte_offset:].decode("utf-8", errors="replace")

        records = self._extract_records(new_content, headers, device_name)
        new_offset = len(raw_bytes)
        return records, {"byte_offset": new_offset}

    def _find_headers(self, content: str) -> Optional[list[str]]:
        m = HEADER_RE.search(content)
        if m:
            return m.group().split(",")
        return None

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

                values = {}
                timestamp = None
                is_header_row = False

                for i, header in enumerate(headers):
                    col = columns[i].strip()
                    if header == col:
                        is_header_row = True
                        break
                    if header == "Time":
                        timestamp = self._parse_timestamp(col)
                    elif header == "POS":
                        values["pos"] = col
                    elif header == "Master":
                        values["master"] = col
                    elif header == "A_Dim(um)":
                        values["a_dim"] = col
                    elif header == "B_Dim(um)":
                        values["b_dim"] = col
                    elif header == "Result":
                        values["result"] = col

                if is_header_row or timestamp is None:
                    continue

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

    @staticmethod
    def _parse_timestamp(time_str: str) -> datetime:
        """Parse AB timestamp: 'yyyy-MM-dd HH:mm:ss:SSS' with zero-padding."""
        padded = time_str.ljust(23, "0")
        return datetime.strptime(padded, "%Y-%m-%d %H:%M:%S:%f")
```

Note: Python `%f` interprets the fractional part as microseconds (6 digits). Since AB uses 3-digit millis padded to 3 digits with `"0"`, we pad to 23 chars total (`yyyy-MM-dd HH:mm:ss:SSS` = 23 chars). But `strptime` with `%f` reads up to 6 digits after the separator. Since the Java format uses `:` before millis, and the string is exactly `HH:mm:ss:SSS`, we use `%S:%f` which will parse `:SSS` as seconds colon then fractional. Actually we need to handle this: `%H:%M:%S:%f` — but `%f` expects up to 6 digits. A 3-digit value like `123` will be parsed as `123000` microseconds = 123ms. This is correct.

Wait — `strptime` with format `%Y-%m-%d %H:%M:%S:%f` won't work because `%S` will consume the seconds and then `:%f` expects a colon followed by microseconds. Let me verify: the input is `2026-03-03 10:30:45:123` and format is `%Y-%m-%d %H:%M:%S:%f`. Actually `strptime` does NOT support `:` as a fractional separator — it only supports `.`. We need to replace the last `:` with `.` before parsing.

The actual implementation should replace the last colon:

```python
    @staticmethod
    def _parse_timestamp(time_str: str) -> datetime:
        padded = time_str.ljust(23, "0")
        # Java uses ':' before millis, Python strptime needs '.'
        last_colon = padded.rfind(":")
        normalized = padded[:last_colon] + "." + padded[last_colon + 1:]
        return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S.%f")
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/collect/test_ab_dim_parser.py -v`
Expected: PASS (all 8 tests)

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/parsers/ab_dim_parser.py \
        tests/unit/collect/test_ab_dim_parser.py
git commit -m "feat(log-collector): add AB Dim log parser"
```

---

## Task 4: IVS Parser

**Files:**
- Create: `tb_gateway_collect/connectors/log_collector/parsers/ivs_parser.py`
- Test: `tests/unit/collect/test_ivs_parser.py`

**Java reference:** `collect/.../module/ivs/service/IVSLogService.java`

**Key logic to port:**
- Row regex: `\d{4}/\d{1,2}/\d{1,2} .*,.*\n|.*\r\n`
- Timestamp at START, format `yyyy/M/d HH:mm:ss` → replace `/` with `-` → parse as `yyyy-MM-dd HH:mm:ss`
- Charset auto-detection via chardet
- Skip rows containing `PadResult,OK`
- resultType: 1 if contains `检测结果` or 12 columns, else 2
- File path must contain `IVSLog`

**Step 1: Write the failing test**

```python
# tests/unit/collect/test_ivs_parser.py
import os
import tempfile
from datetime import datetime

from tb_gateway_collect.connectors.log_collector.parsers.ivs_parser import IVSParser


SAMPLE_IVS_LOG = (
    "Order,Result,extra,Head,HGA,Time\r\n"
    "2026/3/3 10:30:45,col1,col2,col3,col4,col5,col6,col7,col8,col9,col10,col11\r\n"
    "2026/3/3 10:31:00,PadResult,OK,x,x,x,x,x,x,x,x,x\r\n"
    "2026/3/3 10:31:15,a,b,c,d,e\r\n"
)


class TestIVSParser:

    def _write_temp_file(self, content, suffix=".txt", subdir="IVSLog"):
        d = os.path.join(tempfile.gettempdir(), subdir)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"test{suffix}")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        return path

    def test_parse_basic(self):
        path = self._write_temp_file(SAMPLE_IVS_LOG)
        try:
            parser = IVSParser()
            records, cursor = parser.parse(path, "IVS-YB101", None)
            # Row 2 has 12 columns → resultType=1, row 3 is PadResult,OK → skipped, row 4 has 6 cols → resultType=2
            assert len(records) == 2
            assert records[0].values["result_type"] == 1
            assert records[0].timestamp == datetime(2026, 3, 3, 10, 30, 45)
            assert records[1].values["result_type"] == 2
        finally:
            os.unlink(path)

    def test_skip_pad_result_ok(self):
        path = self._write_temp_file(SAMPLE_IVS_LOG)
        try:
            parser = IVSParser()
            records, _ = parser.parse(path, "IVS-YB101", None)
            for r in records:
                assert "PadResult,OK" not in r.values.get("raw_data", "")
        finally:
            os.unlink(path)

    def test_cursor_incremental(self):
        path = self._write_temp_file(SAMPLE_IVS_LOG)
        try:
            parser = IVSParser()
            records1, cursor1 = parser.parse(path, "IVS-YB101", None)
            records2, cursor2 = parser.parse(path, "IVS-YB101", cursor1)
            assert len(records2) == 0
        finally:
            os.unlink(path)

    def test_matches_file_requires_ivslog_in_path(self):
        parser = IVSParser()
        assert parser.matches_file("/path/IVSLog/data.txt") is True
        assert parser.matches_file("/path/AllLog/data.txt") is False
        assert parser.matches_file("/path/other/data.txt") is False

    def test_result_type_chinese_marker(self):
        content = "2026/3/3 10:30:45,检测结果,col2,col3\r\n"
        path = self._write_temp_file(content)
        try:
            parser = IVSParser()
            records, _ = parser.parse(path, "IVS-YB101", None)
            assert len(records) == 1
            assert records[0].values["result_type"] == 1
        finally:
            os.unlink(path)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/collect/test_ivs_parser.py -v`
Expected: FAIL

**Step 3: Implement**

```python
# tb_gateway_collect/connectors/log_collector/parsers/ivs_parser.py
import logging
import os
import re
from datetime import datetime
from typing import Optional

from tb_gateway_collect.connectors.log_collector.parsers.base_parser import LogParser, LogRecord

log = logging.getLogger(__name__)

ROW_RE = re.compile(r"\d{4}/\d{1,2}/\d{1,2} .*,.*\r?\n")


class IVSParser(LogParser):
    """Parser for IVS log files.

    Java reference: IVSLogService.java
    Format: CSV with timestamp at start, charset auto-detect.
    """

    def matches_file(self, file_path: str) -> bool:
        return "IVSLog" in file_path

    def parse(
        self,
        file_path: str,
        device_name: str,
        cursor: Optional[dict],
    ) -> tuple[list[LogRecord], dict]:
        byte_offset = (cursor or {}).get("byte_offset", 0)

        try:
            content = self._read_with_charset_detect(file_path)
        except Exception as e:
            log.warning("Failed to read %s: %s", file_path, e)
            return [], cursor or {"byte_offset": 0}

        if not content:
            return [], {"byte_offset": 0}

        raw_bytes = content.encode("utf-8")
        new_content = raw_bytes[byte_offset:].decode("utf-8", errors="replace")

        records = self._extract_records(new_content, device_name)
        return records, {"byte_offset": len(raw_bytes)}

    @staticmethod
    def _read_with_charset_detect(file_path: str) -> str:
        with open(file_path, "rb") as f:
            raw = f.read()
        if not raw:
            return ""
        try:
            import chardet
            detected = chardet.detect(raw)
            encoding = detected.get("encoding") or "utf-8"
        except ImportError:
            encoding = "utf-8"
        return raw.decode(encoding, errors="replace")

    def _extract_records(self, content: str, device_name: str) -> list[LogRecord]:
        records = []
        for m in ROW_RE.finditer(content):
            try:
                raw = m.group().rstrip("\r\n")
                if "PadResult,OK" in raw:
                    continue
                columns = raw.split(",")
                time_str = columns[0].replace("/", "-")
                timestamp = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")

                result_type = 2
                if "检测结果" in raw or len(columns) == 12:
                    result_type = 1

                records.append(LogRecord(
                    device_name=device_name,
                    timestamp=timestamp,
                    values={
                        "raw_data": raw,
                        "result_type": result_type,
                    },
                    system_type="ivs",
                ))
            except Exception as e:
                log.warning("Skipping malformed IVS row: %s", e)
        return records
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/collect/test_ivs_parser.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/parsers/ivs_parser.py \
        tests/unit/collect/test_ivs_parser.py
git commit -m "feat(log-collector): add IVS log parser with charset detection"
```

---

## Task 5: ICS Parser

**Files:**
- Create: `tb_gateway_collect/connectors/log_collector/parsers/ics_parser.py`
- Test: `tests/unit/collect/test_ics_parser.py`

**Java reference:** `collect/.../module/ics/service/ICSLogService.java`

**Key logic to port:**
- Header regex: `Time,POS,Master,.*,Result` (case-insensitive)
- Row regex: `\d{4}-\d{1,2}-\d{1,2} .*,.*\r?\n`
- Timestamp format: `yyyy-MM-dd HH:mm:ss:SSS` (padded to 23, colon before ms)
- Adaptive column detection by column count: 7, 9, 10, 13, 14, 19
- Extract: Time, POS/Pos, Master, Result, rest → logValue (comma-separated)

**Step 1: Write the failing test**

```python
# tests/unit/collect/test_ics_parser.py
import os
import tempfile
from datetime import datetime

from tb_gateway_collect.connectors.log_collector.parsers.ics_parser import ICSParser


SAMPLE_ICS_9COL = (
    "Time,POS,Master,EX1,EY1,ED1,EDX1,EDY1,Result\r\n"
    "2026-03-03 10:30:45:123,3,A,1.1,2.2,3.3,4.4,5.5,OK\r\n"
    "2026-03-03 10:30:46:45,5,B,6.6,7.7,8.8,9.9,10.1,NG\r\n"
)

SAMPLE_ICS_14COL = (
    "Time,POS,Master,EX1,EX2,EY1,EY2,ED1,ED2,EDX1,EDY1,EDX2,EDY2,Result\r\n"
    "2026-03-03 10:30:45:100,1,A,1,2,3,4,5,6,7,8,9,10,OK\r\n"
)


class TestICSParser:

    def _write_temp_file(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                         encoding="utf-8", newline="")
        f.write(content)
        f.close()
        return f.name

    def test_parse_9col(self):
        path = self._write_temp_file(SAMPLE_ICS_9COL)
        try:
            parser = ICSParser()
            records, cursor = parser.parse(path, "ICS-YB101", None)
            assert len(records) == 2
            r = records[0]
            assert r.device_name == "ICS-YB101"
            assert r.system_type == "ics"
            assert r.values["pos"] == "3"
            assert r.values["master"] == "A"
            assert r.values["result"] == "OK"
            assert "log_value" in r.values
            assert r.timestamp == datetime(2026, 3, 3, 10, 30, 45, 123000)
        finally:
            os.unlink(path)

    def test_parse_14col(self):
        path = self._write_temp_file(SAMPLE_ICS_14COL)
        try:
            parser = ICSParser()
            records, _ = parser.parse(path, "ICS-YB101", None)
            assert len(records) == 1
            assert records[0].values["result"] == "OK"
        finally:
            os.unlink(path)

    def test_timestamp_padding(self):
        path = self._write_temp_file(SAMPLE_ICS_9COL)
        try:
            parser = ICSParser()
            records, _ = parser.parse(path, "ICS-YB101", None)
            # '10:30:46:45' padded to '10:30:46:450' = 450ms
            assert records[1].timestamp == datetime(2026, 3, 3, 10, 30, 46, 450000)
        finally:
            os.unlink(path)

    def test_cursor_incremental(self):
        path = self._write_temp_file(SAMPLE_ICS_9COL)
        try:
            parser = ICSParser()
            _, cursor = parser.parse(path, "ICS-YB101", None)
            records2, _ = parser.parse(path, "ICS-YB101", cursor)
            assert len(records2) == 0
        finally:
            os.unlink(path)

    def test_adaptive_headers_by_column_count(self):
        """If file header doesn't match but data has known column count, use fallback."""
        content = (
            "CustomHeader\r\n"
            "2026-03-03 10:30:45:123,3,A,1.1,2.2,3.3,4.4,5.5,OK\r\n"
        )
        path = self._write_temp_file(content)
        try:
            parser = ICSParser()
            records, _ = parser.parse(path, "ICS-YB101", None)
            # 9 columns → should use fallback 9-col headers
            assert len(records) == 1
            assert records[0].values["pos"] == "3"
        finally:
            os.unlink(path)

    def test_matches_file(self):
        parser = ICSParser()
        assert parser.matches_file("data.txt") is True
        assert parser.matches_file("data.jpg") is False
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/collect/test_ics_parser.py -v`
Expected: FAIL

**Step 3: Implement**

```python
# tb_gateway_collect/connectors/log_collector/parsers/ics_parser.py
import logging
import os
import re
from datetime import datetime
from typing import Optional

from tb_gateway_collect.connectors.log_collector.parsers.base_parser import LogParser, LogRecord

log = logging.getLogger(__name__)

HEADER_RE = re.compile(r"Time,POS,Master,.*,Result", re.IGNORECASE)
ROW_RE = re.compile(r"\d{4}-\d{1,2}-\d{1,2} .*,.*\r?\n")

TEXT_EXTENSIONS = {".txt", ".csv", ".log"}

# Adaptive header templates by column count (from Java ICSLogService)
ADAPTIVE_HEADERS = {
    7:  "Time,POS,Master,EX1,EY1,EW1,Result".split(","),
    9:  "Time,POS,Master,EX1,EY1,ED1,EDX1,EDY1,Result".split(","),
    10: "Time,POS,Master,EX1,EX2,EY1,EY2,EW1,EW2,Result".split(","),
    13: "Time,POS,Master,EX1,EX2,EX3,EY1,EY2,EY3,EW1,EW2,EW3,Result".split(","),
    14: "Time,POS,Master,EX1,EX2,EY1,EY2,ED1,ED2,EDX1,EDY1,EDX2,EDY2,Result".split(","),
    19: "Time,POS,Master,EX1,EX2,EX3,EY1,EY2,EY3,ED1,ED2,ED3,EDX1,EDY1,EDX2,EDY2,EDX3,EDY3,Result".split(","),
}


class ICSParser(LogParser):
    """Parser for ICS log files.

    Java reference: ICSLogService.java
    Format: CSV with adaptive column counts for different glue modes.
    """

    def matches_file(self, file_path: str) -> bool:
        _, ext = os.path.splitext(file_path)
        return ext.lower() in TEXT_EXTENSIONS

    def parse(
        self,
        file_path: str,
        device_name: str,
        cursor: Optional[dict],
    ) -> tuple[list[LogRecord], dict]:
        byte_offset = (cursor or {}).get("byte_offset", 0)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            log.warning("Failed to read %s: %s", file_path, e)
            return [], cursor or {"byte_offset": 0}

        if not content:
            return [], {"byte_offset": 0}

        headers = self._find_headers(content)

        raw_bytes = content.encode("utf-8")
        new_content = raw_bytes[byte_offset:].decode("utf-8", errors="replace")

        records = self._extract_records(new_content, headers, device_name)
        return records, {"byte_offset": len(raw_bytes)}

    def _find_headers(self, content: str) -> Optional[list[str]]:
        m = HEADER_RE.search(content)
        if m:
            return m.group().split(",")
        return None

    def _get_headers_for_row(self, columns: list[str], file_headers: Optional[list[str]]) -> list[str]:
        n = len(columns)
        if file_headers and len(file_headers) == n:
            return file_headers
        if n in ADAPTIVE_HEADERS:
            return ADAPTIVE_HEADERS[n]
        if file_headers:
            return file_headers
        return ADAPTIVE_HEADERS.get(9, [])

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

                values = {}
                timestamp = None
                is_header_row = False
                log_val_parts = []

                for i, header in enumerate(headers):
                    col = columns[i].strip()
                    if header.lower() == col.lower():
                        is_header_row = True
                        break
                    h = header.lower()
                    if h == "time":
                        timestamp = _parse_timestamp_with_millis(col)
                    elif h in ("pos",):
                        values["pos"] = col
                    elif h == "master":
                        values["master"] = col
                    elif h == "result":
                        values["log_value"] = ",".join(log_val_parts)
                        values["result"] = col
                    else:
                        log_val_parts.append(col)

                if is_header_row or timestamp is None:
                    continue

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


def _parse_timestamp_with_millis(time_str: str) -> datetime:
    """Parse timestamp 'yyyy-MM-dd HH:mm:ss:SSS' with colon-separated millis."""
    padded = time_str.ljust(23, "0")
    last_colon = padded.rfind(":")
    normalized = padded[:last_colon] + "." + padded[last_colon + 1:]
    return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S.%f")
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/collect/test_ics_parser.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/parsers/ics_parser.py \
        tests/unit/collect/test_ics_parser.py
git commit -m "feat(log-collector): add ICS log parser with adaptive column detection"
```

---

## Task 6: HCCM Parsers (Result + Slider)

**Files:**
- Create: `tb_gateway_collect/connectors/log_collector/parsers/hccm_parser.py`
- Test: `tests/unit/collect/test_hccm_parser.py`

**Java reference:** `HCCMResultLogService.java`, `HCCMSliderLogService.java`

**Key logic to port:**
- Result header: `PosID,BaseholeX,.*,Time`
- Slider header: `PosID,OutLineAngle,.*,Time`
- Row regex: `\d{1,2},.*\r?\n` (starts with 1-2 digit PosID)
- Time-only column (`HH:mm:ss`) — prepend today's date
- Adaptive columns (same templates as ICS but rarely needed)
- Slider: 5-second dedup on same POS

**Step 1: Write the failing test**

```python
# tests/unit/collect/test_hccm_parser.py
import os
import tempfile
from datetime import datetime, date

from tb_gateway_collect.connectors.log_collector.parsers.hccm_parser import (
    HCCMResultParser, HCCMSliderParser,
)


SAMPLE_HCCM_RESULT = (
    "PosID,BaseholeX,BaseholeY,SUSP_X,SUSP_Y,Time\r\n"
    "1,10.5,20.3,0.5,0.3,10:30:5\r\n"
    "2,11.0,21.0,0.6,0.4,10:30:10\r\n"
)

SAMPLE_HCCM_SLIDER = (
    "PosID,OutLineAngle,AFSDX,AFSDY,BFSDX,BFSDY,Time\r\n"
    "1,45.0,0.1,0.2,0.3,0.4,10:30:05\r\n"
    "1,45.1,0.11,0.21,0.31,0.41,10:30:08\r\n"
    "2,46.0,0.5,0.6,0.7,0.8,10:30:15\r\n"
)


class TestHCCMResultParser:

    def _write_temp_file(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                         encoding="utf-8", newline="")
        f.write(content)
        f.close()
        return f.name

    def test_parse_basic(self):
        path = self._write_temp_file(SAMPLE_HCCM_RESULT)
        try:
            parser = HCCMResultParser()
            records, cursor = parser.parse(path, "HCCM-Result-YB101", None)
            assert len(records) == 2
            r = records[0]
            assert r.device_name == "HCCM-Result-YB101"
            assert r.system_type == "hccm_result"
            assert r.values["pos"] == "1"
            today = date.today()
            assert r.timestamp.date() == today
            assert r.timestamp.hour == 10
            assert r.timestamp.minute == 30
            assert r.timestamp.second == 5
        finally:
            os.unlink(path)

    def test_time_zero_padding(self):
        """Time '10:30:5' should be parsed as 10:30:05."""
        path = self._write_temp_file(SAMPLE_HCCM_RESULT)
        try:
            parser = HCCMResultParser()
            records, _ = parser.parse(path, "HCCM-Result-YB101", None)
            assert records[0].timestamp.second == 5
        finally:
            os.unlink(path)

    def test_cursor_incremental(self):
        path = self._write_temp_file(SAMPLE_HCCM_RESULT)
        try:
            parser = HCCMResultParser()
            _, cursor = parser.parse(path, "HCCM-Result-YB101", None)
            records2, _ = parser.parse(path, "HCCM-Result-YB101", cursor)
            assert len(records2) == 0
        finally:
            os.unlink(path)


class TestHCCMSliderParser:

    def _write_temp_file(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                         encoding="utf-8", newline="")
        f.write(content)
        f.close()
        return f.name

    def test_parse_basic(self):
        path = self._write_temp_file(SAMPLE_HCCM_SLIDER)
        try:
            parser = HCCMSliderParser()
            records, _ = parser.parse(path, "HCCM-Slider-YB101", None)
            assert len(records) >= 2
            assert records[-1].values["pos"] == "2"
        finally:
            os.unlink(path)

    def test_dedup_same_pos_within_5s(self):
        """PosID 1 appears twice within 3 seconds — second replaces first."""
        path = self._write_temp_file(SAMPLE_HCCM_SLIDER)
        try:
            parser = HCCMSliderParser()
            records, _ = parser.parse(path, "HCCM-Slider-YB101", None)
            pos1_records = [r for r in records if r.values["pos"] == "1"]
            assert len(pos1_records) == 1
            # The second entry (10:30:08) should replace the first (10:30:05)
            assert pos1_records[0].timestamp.second == 8
        finally:
            os.unlink(path)

    def test_no_dedup_different_pos(self):
        path = self._write_temp_file(SAMPLE_HCCM_SLIDER)
        try:
            parser = HCCMSliderParser()
            records, _ = parser.parse(path, "HCCM-Slider-YB101", None)
            assert len(records) == 2  # pos 1 (deduped) + pos 2
        finally:
            os.unlink(path)

    def test_matches_file(self):
        parser = HCCMSliderParser()
        assert parser.matches_file("data.txt") is True
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/collect/test_hccm_parser.py -v`
Expected: FAIL

**Step 3: Implement**

```python
# tb_gateway_collect/connectors/log_collector/parsers/hccm_parser.py
import logging
import os
import re
from datetime import datetime, date
from typing import Optional

from tb_gateway_collect.connectors.log_collector.parsers.base_parser import LogParser, LogRecord

log = logging.getLogger(__name__)

RESULT_HEADER_RE = re.compile(r"PosID,BaseholeX,.*,Time")
SLIDER_HEADER_RE = re.compile(r"PosID,OutLineAngle,.*,Time")
ROW_RE = re.compile(r"\d{1,2},.*\r?\n")

TEXT_EXTENSIONS = {".txt", ".csv", ".log"}


def _parse_time_only(time_str: str) -> datetime:
    """Parse HH:mm:ss with zero-padding, prepend today's date."""
    parts = time_str.split(":")
    h = parts[0].zfill(2)
    m = parts[1].zfill(2) if len(parts) > 1 else "00"
    s = parts[2].zfill(2) if len(parts) > 2 else "00"
    today = date.today()
    return datetime.strptime(f"{today} {h}:{m}:{s}", "%Y-%m-%d %H:%M:%S")


class _BaseHCCMParser(LogParser):
    """Shared logic for HCCM Result and Slider parsers."""

    _header_re: re.Pattern
    _system_type: str

    def matches_file(self, file_path: str) -> bool:
        _, ext = os.path.splitext(file_path)
        return ext.lower() in TEXT_EXTENSIONS

    def parse(
        self,
        file_path: str,
        device_name: str,
        cursor: Optional[dict],
    ) -> tuple[list[LogRecord], dict]:
        byte_offset = (cursor or {}).get("byte_offset", 0)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            log.warning("Failed to read %s: %s", file_path, e)
            return [], cursor or {"byte_offset": 0}

        if not content:
            return [], {"byte_offset": 0}

        headers = self._find_headers(content)

        raw_bytes = content.encode("utf-8")
        new_content = raw_bytes[byte_offset:].decode("utf-8", errors="replace")

        records = self._extract_records(new_content, headers, device_name)
        records = self._post_process(records)
        return records, {"byte_offset": len(raw_bytes)}

    def _find_headers(self, content: str) -> Optional[list[str]]:
        m = self._header_re.search(content)
        if m:
            return m.group().split(",")
        return None

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

                pos = columns[0].strip()
                values = {"pos": pos, "raw_data": raw}
                timestamp = None

                if used_headers:
                    log_val_parts = []
                    is_header_row = False
                    for i, header in enumerate(used_headers):
                        col = columns[i].strip()
                        if header == col:
                            is_header_row = True
                            break
                        if header == "Time":
                            timestamp = _parse_time_only(col)
                        elif header == "PosID":
                            values["pos"] = col
                            log_val_parts.append(col)
                        else:
                            log_val_parts.append(col)
                    if is_header_row:
                        continue
                    values["log_value"] = ",".join(log_val_parts)
                else:
                    # No header found: assume last column is time
                    timestamp = _parse_time_only(columns[-1].strip())
                    values["log_value"] = ",".join(c.strip() for c in columns[:-1])

                if timestamp is None:
                    continue

                records.append(LogRecord(
                    device_name=device_name,
                    timestamp=timestamp,
                    values=values,
                    system_type=self._system_type,
                ))
            except Exception as e:
                log.warning("Skipping malformed HCCM row: %s", e)
        return records

    def _post_process(self, records: list[LogRecord]) -> list[LogRecord]:
        return records


class HCCMResultParser(_BaseHCCMParser):
    _header_re = RESULT_HEADER_RE
    _system_type = "hccm_result"


class HCCMSliderParser(_BaseHCCMParser):
    _header_re = SLIDER_HEADER_RE
    _system_type = "hccm_slider"

    def _post_process(self, records: list[LogRecord]) -> list[LogRecord]:
        """5-second dedup: if same POS within 5s, keep the later record."""
        if not records:
            return records
        deduped = [records[0]]
        for r in records[1:]:
            prev = deduped[-1]
            same_pos = r.values.get("pos") == prev.values.get("pos")
            if same_pos:
                delta = abs((r.timestamp - prev.timestamp).total_seconds())
                if delta < 5:
                    deduped[-1] = r  # replace with newer
                    continue
            deduped.append(r)
        return deduped
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/collect/test_hccm_parser.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/parsers/hccm_parser.py \
        tests/unit/collect/test_hccm_parser.py
git commit -m "feat(log-collector): add HCCM Result and Slider parsers with dedup"
```

---

## Task 7: XJSBB Parser

**Files:**
- Create: `tb_gateway_collect/connectors/log_collector/parsers/xjsbb_parser.py`
- Test: `tests/unit/collect/test_xjsbb_parser.py`

**Java reference:** `XJSBBLogService.java`, `XJSBBDataService.java`

**Key logic to port:**
- Row regex: `(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}:\d{3})   (.*):(.*)\r\n`
- Three spaces between timestamp and variable name
- Colon between varName and varValue
- In-memory change detection: only emit when value differs from last known

**Step 1: Write the failing test**

```python
# tests/unit/collect/test_xjsbb_parser.py
import os
import tempfile
from datetime import datetime

from tb_gateway_collect.connectors.log_collector.parsers.xjsbb_parser import XJSBBParser


SAMPLE_XJSBB = (
    "2026-03-03 10:30:45:123   Temperature:25.5\r\n"
    "2026-03-03 10:30:46:000   Pressure:101.3\r\n"
    "2026-03-03 10:30:47:500   Temperature:25.5\r\n"
    "2026-03-03 10:30:48:000   Temperature:26.0\r\n"
)


class TestXJSBBParser:

    def _write_temp_file(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                         encoding="utf-8", newline="")
        f.write(content)
        f.close()
        return f.name

    def test_parse_basic(self):
        path = self._write_temp_file(SAMPLE_XJSBB)
        try:
            parser = XJSBBParser()
            records, cursor = parser.parse(path, "XJSBB-YB101", None)
            assert len(records) == 4
            r = records[0]
            assert r.device_name == "XJSBB-YB101"
            assert r.system_type == "xjsbb"
            assert r.values["var_name"] == "Temperature"
            assert r.values["var_value"] == "25.5"
            assert r.timestamp == datetime(2026, 3, 3, 10, 30, 45, 123000)
        finally:
            os.unlink(path)

    def test_change_detection_filters_duplicates(self):
        path = self._write_temp_file(SAMPLE_XJSBB)
        try:
            parser = XJSBBParser(change_detection=True)
            records, _ = parser.parse(path, "XJSBB-YB101", None)
            # Temperature: 25.5 (new), Pressure: 101.3 (new),
            # Temperature: 25.5 (same → skip), Temperature: 26.0 (changed)
            assert len(records) == 3
            temp_records = [r for r in records if r.values["var_name"] == "Temperature"]
            assert len(temp_records) == 2
            assert temp_records[0].values["var_value"] == "25.5"
            assert temp_records[1].values["var_value"] == "26.0"
        finally:
            os.unlink(path)

    def test_no_change_detection(self):
        path = self._write_temp_file(SAMPLE_XJSBB)
        try:
            parser = XJSBBParser(change_detection=False)
            records, _ = parser.parse(path, "XJSBB-YB101", None)
            assert len(records) == 4  # All records emitted
        finally:
            os.unlink(path)

    def test_cursor_incremental(self):
        path = self._write_temp_file(SAMPLE_XJSBB)
        try:
            parser = XJSBBParser()
            _, cursor = parser.parse(path, "XJSBB-YB101", None)
            records2, _ = parser.parse(path, "XJSBB-YB101", cursor)
            assert len(records2) == 0
        finally:
            os.unlink(path)

    def test_whitespace_trimming(self):
        content = "2026-03-03 10:00:00:000   Var Name :  Value With Spaces  \r\n"
        path = self._write_temp_file(content)
        try:
            parser = XJSBBParser()
            records, _ = parser.parse(path, "XJSBB-YB101", None)
            assert len(records) == 1
            assert records[0].values["var_name"] == "Var Name"
            assert records[0].values["var_value"] == "Value With Spaces"
        finally:
            os.unlink(path)

    def test_matches_file(self):
        parser = XJSBBParser()
        assert parser.matches_file("data.txt") is True
        assert parser.matches_file("data.jpg") is False
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/collect/test_xjsbb_parser.py -v`
Expected: FAIL

**Step 3: Implement**

```python
# tb_gateway_collect/connectors/log_collector/parsers/xjsbb_parser.py
import logging
import os
import re
from datetime import datetime
from typing import Optional

from tb_gateway_collect.connectors.log_collector.parsers.base_parser import LogParser, LogRecord

log = logging.getLogger(__name__)

ROW_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}:\d{3})   (.*):(.*)\r?\n"
)

TEXT_EXTENSIONS = {".txt", ".csv", ".log"}


class XJSBBParser(LogParser):
    """Parser for XJSBB key-value log files.

    Java reference: XJSBBLogService.java + XJSBBDataService.java
    Format: (timestamp)   (varName):(varValue) per line.
    Optional change detection: only emit records when value differs.
    """

    def __init__(self, change_detection: bool = True):
        self._change_detection = change_detection
        self._last_values: dict[str, str] = {}

    def matches_file(self, file_path: str) -> bool:
        _, ext = os.path.splitext(file_path)
        return ext.lower() in TEXT_EXTENSIONS

    def parse(
        self,
        file_path: str,
        device_name: str,
        cursor: Optional[dict],
    ) -> tuple[list[LogRecord], dict]:
        byte_offset = (cursor or {}).get("byte_offset", 0)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            log.warning("Failed to read %s: %s", file_path, e)
            return [], cursor or {"byte_offset": 0}

        if not content:
            return [], {"byte_offset": 0}

        raw_bytes = content.encode("utf-8")
        new_content = raw_bytes[byte_offset:].decode("utf-8", errors="replace")

        records = self._extract_records(new_content, device_name)
        return records, {"byte_offset": len(raw_bytes)}

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
                        "var_name": var_name,
                        "var_value": var_value,
                        "raw_data": m.group().rstrip("\r\n"),
                    },
                    system_type="xjsbb",
                ))
            except Exception as e:
                log.warning("Skipping malformed XJSBB row: %s", e)
        return records
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/collect/test_xjsbb_parser.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/parsers/xjsbb_parser.py \
        tests/unit/collect/test_xjsbb_parser.py
git commit -m "feat(log-collector): add XJSBB key-value parser with change detection"
```

---

## Task 8: Parser Registry

**Files:**
- Modify: `tb_gateway_collect/connectors/log_collector/parsers/__init__.py`
- Test: `tests/unit/collect/test_parser_registry.py`

**Step 1: Write the failing test**

```python
# tests/unit/collect/test_parser_registry.py
from tb_gateway_collect.connectors.log_collector.parsers import PARSER_REGISTRY, get_parser
from tb_gateway_collect.connectors.log_collector.parsers.base_parser import LogParser


class TestParserRegistry:

    def test_all_system_types_registered(self):
        expected = {"ab", "ivs", "ics", "hccm_result", "hccm_slider", "xjsbb"}
        assert set(PARSER_REGISTRY.keys()) == expected

    def test_get_parser_returns_instance(self):
        parser = get_parser("ab")
        assert isinstance(parser, LogParser)

    def test_get_parser_unknown_type_raises(self):
        import pytest
        with pytest.raises(KeyError):
            get_parser("unknown_type")

    def test_get_parser_caches_instances(self):
        p1 = get_parser("ics")
        p2 = get_parser("ics")
        assert p1 is p2
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/collect/test_parser_registry.py -v`
Expected: FAIL

**Step 3: Implement**

```python
# tb_gateway_collect/connectors/log_collector/parsers/__init__.py
from tb_gateway_collect.connectors.log_collector.parsers.ab_dim_parser import ABDimParser
from tb_gateway_collect.connectors.log_collector.parsers.ivs_parser import IVSParser
from tb_gateway_collect.connectors.log_collector.parsers.ics_parser import ICSParser
from tb_gateway_collect.connectors.log_collector.parsers.hccm_parser import HCCMResultParser, HCCMSliderParser
from tb_gateway_collect.connectors.log_collector.parsers.xjsbb_parser import XJSBBParser

PARSER_REGISTRY: dict[str, type] = {
    "ab": ABDimParser,
    "ivs": IVSParser,
    "ics": ICSParser,
    "hccm_result": HCCMResultParser,
    "hccm_slider": HCCMSliderParser,
    "xjsbb": XJSBBParser,
}

_parser_instances: dict[str, object] = {}


def get_parser(system_type: str):
    """Get or create a parser instance for the given system type."""
    if system_type not in _parser_instances:
        cls = PARSER_REGISTRY[system_type]
        _parser_instances[system_type] = cls()
    return _parser_instances[system_type]
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/collect/test_parser_registry.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/parsers/__init__.py \
        tests/unit/collect/test_parser_registry.py
git commit -m "feat(log-collector): add parser registry with all 6 parsers"
```

---

## Task 9: Uplink Converter

**Files:**
- Create: `tb_gateway_collect/connectors/log_collector/log_uplink_converter.py`
- Test: `tests/unit/collect/test_log_uplink_converter.py`

**Step 1: Write the failing test**

```python
# tests/unit/collect/test_log_uplink_converter.py
from datetime import datetime
from tb_gateway_collect.connectors.log_collector.parsers.base_parser import LogRecord
from tb_gateway_collect.connectors.log_collector.log_uplink_converter import LogUplinkConverter


class TestLogUplinkConverter:

    def test_convert_single_record(self):
        converter = LogUplinkConverter()
        record = LogRecord(
            device_name="ICS-YB101",
            timestamp=datetime(2026, 3, 3, 10, 30, 45, 123000),
            values={"pos": "3", "result": "OK", "raw_data": "line"},
            system_type="ics",
        )
        converted = converter.convert(record)
        assert converted.device_name == "ICS-YB101"
        assert converted.device_type == "log_source"
        assert len(converted.telemetry_datapoints) > 0

    def test_convert_preserves_timestamp(self):
        converter = LogUplinkConverter()
        record = LogRecord(
            device_name="AB-YB101",
            timestamp=datetime(2026, 3, 3, 10, 30, 45, 123000),
            values={"a_dim": "12.34"},
            system_type="ab",
        )
        converted = converter.convert(record)
        # The telemetry entry should have the record's timestamp as ts
        entries = converted.telemetry_datapoints
        assert len(entries) == 1
        ts_ms = int(datetime(2026, 3, 3, 10, 30, 45, 123000).timestamp() * 1000)
        assert entries[0].ts == ts_ms

    def test_convert_with_custom_device_type(self):
        converter = LogUplinkConverter(device_type="custom_type")
        record = LogRecord(
            device_name="DEV-1",
            timestamp=datetime(2026, 1, 1),
            values={"key": "val"},
            system_type="ab",
        )
        converted = converter.convert(record)
        assert converted.device_type == "custom_type"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/collect/test_log_uplink_converter.py -v`
Expected: FAIL

**Step 3: Implement**

```python
# tb_gateway_collect/connectors/log_collector/log_uplink_converter.py
from thingsboard_gateway.connectors.converter import Converter
from thingsboard_gateway.gateway.entities.converted_data import ConvertedData
from thingsboard_gateway.gateway.entities.datapoint_key import DatapointKey
from thingsboard_gateway.gateway.entities.telemetry_entry import TelemetryEntry

from tb_gateway_collect.connectors.log_collector.parsers.base_parser import LogRecord


class LogUplinkConverter(Converter):
    """Converts LogRecord instances to ThingsBoard ConvertedData."""

    def __init__(self, device_type: str = "log_source"):
        self._device_type = device_type

    def convert(self, config_or_record, data=None) -> ConvertedData:
        if isinstance(config_or_record, LogRecord):
            record = config_or_record
        else:
            raise TypeError(f"Expected LogRecord, got {type(config_or_record)}")

        converted = ConvertedData(record.device_name, self._device_type)
        ts = int(record.timestamp.timestamp() * 1000)
        telemetry_values = {DatapointKey(k): v for k, v in record.values.items()}
        converted.add_to_telemetry(TelemetryEntry(telemetry_values, ts))
        return converted
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/collect/test_log_uplink_converter.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/log_uplink_converter.py \
        tests/unit/collect/test_log_uplink_converter.py
git commit -m "feat(log-collector): add uplink converter for LogRecord to ConvertedData"
```

---

## Task 10: File Watcher

**Files:**
- Create: `tb_gateway_collect/connectors/log_collector/log_file_watcher.py`
- Test: `tests/unit/collect/test_log_file_watcher.py`

**Step 1: Write the failing test**

```python
# tests/unit/collect/test_log_file_watcher.py
import os
import tempfile
import time
from unittest.mock import MagicMock

from tb_gateway_collect.connectors.log_collector.log_file_watcher import LogFileWatcher


class TestLogFileWatcher:

    def test_create_watcher(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback)
        assert watcher is not None

    def test_add_watch_dir(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback)
        d = tempfile.mkdtemp()
        try:
            watcher.add_watch(d, "*.txt")
            assert len(watcher.watched_dirs) == 1
        finally:
            watcher.stop()
            os.rmdir(d)

    def test_start_stop(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback)
        d = tempfile.mkdtemp()
        try:
            watcher.add_watch(d, "*.txt")
            watcher.start()
            assert watcher.is_running()
            watcher.stop()
            assert not watcher.is_running()
        finally:
            if os.path.exists(d):
                os.rmdir(d)

    def test_detects_new_file(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback)
        d = tempfile.mkdtemp()
        try:
            watcher.add_watch(d, "*.txt")
            watcher.start()
            time.sleep(0.5)

            path = os.path.join(d, "test.txt")
            with open(path, "w") as f:
                f.write("data\n")

            # Give watchdog time to detect
            time.sleep(2)
            watcher.stop()

            assert callback.call_count >= 1
            args = callback.call_args[0]
            assert args[0].endswith("test.txt")
        finally:
            if os.path.exists(os.path.join(d, "test.txt")):
                os.unlink(os.path.join(d, "test.txt"))
            if os.path.exists(d):
                os.rmdir(d)

    def test_ignores_non_matching_files(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback)
        d = tempfile.mkdtemp()
        try:
            watcher.add_watch(d, "*.txt")
            watcher.start()
            time.sleep(0.5)

            path = os.path.join(d, "test.jpg")
            with open(path, "w") as f:
                f.write("data\n")

            time.sleep(2)
            watcher.stop()

            assert callback.call_count == 0
        finally:
            if os.path.exists(os.path.join(d, "test.jpg")):
                os.unlink(os.path.join(d, "test.jpg"))
            if os.path.exists(d):
                os.rmdir(d)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/collect/test_log_file_watcher.py -v`
Expected: FAIL

**Step 3: Implement**

```python
# tb_gateway_collect/connectors/log_collector/log_file_watcher.py
import fnmatch
import logging
import os
from typing import Callable

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

log = logging.getLogger(__name__)


class _FileHandler(FileSystemEventHandler):
    """Routes file create/modify events to the callback if they match the pattern."""

    def __init__(self, callback: Callable[[str], None], pattern: str):
        self._callback = callback
        self._pattern = pattern

    def on_created(self, event):
        if not event.is_directory and self._matches(event.src_path):
            self._callback(event.src_path)

    def on_modified(self, event):
        if not event.is_directory and self._matches(event.src_path):
            self._callback(event.src_path)

    def _matches(self, path: str) -> bool:
        return fnmatch.fnmatch(os.path.basename(path), self._pattern)


class LogFileWatcher:
    """Wraps watchdog Observer to watch multiple directories with file patterns."""

    def __init__(self, callback: Callable[[str], None]):
        self._callback = callback
        self._observer = Observer()
        self._watches: list[dict] = []

    @property
    def watched_dirs(self) -> list[str]:
        return [w["dir"] for w in self._watches]

    def add_watch(self, directory: str, pattern: str = "*.*", recursive: bool = True):
        handler = _FileHandler(self._callback, pattern)
        watch = self._observer.schedule(handler, directory, recursive=recursive)
        self._watches.append({"dir": directory, "pattern": pattern, "watch": watch})

    def remove_watch(self, directory: str):
        for w in self._watches:
            if w["dir"] == directory:
                self._observer.unschedule(w["watch"])
                self._watches.remove(w)
                break

    def start(self):
        self._observer.start()

    def stop(self):
        self._observer.stop()
        self._observer.join(timeout=5)

    def is_running(self) -> bool:
        return self._observer.is_alive()
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/collect/test_log_file_watcher.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/log_file_watcher.py \
        tests/unit/collect/test_log_file_watcher.py
git commit -m "feat(log-collector): add watchdog-based file watcher"
```

---

## Task 11: Log Collector Connector

**Files:**
- Create: `tb_gateway_collect/connectors/log_collector/log_collector_connector.py`
- Test: `tests/unit/collect/test_log_collector_connector.py`

**Step 1: Write the failing test**

```python
# tests/unit/collect/test_log_collector_connector.py
import os
import tempfile
import time
from unittest.mock import MagicMock, patch

from tb_gateway_collect.connectors.log_collector.log_collector_connector import LogCollectorConnector


def _make_config(sources=None, state_dir=None):
    if state_dir is None:
        state_dir = tempfile.mkdtemp()
    return {
        "name": "Log Collector",
        "id": "test-log-collector-001",
        "pollIntervalMs": 500,
        "stateFile": os.path.join(state_dir, "state.json"),
        "logLevel": "DEBUG",
        "sources": sources or [],
    }


class TestLogCollectorConnectorLifecycle:

    def test_constructor(self):
        gateway = MagicMock()
        config = _make_config()
        connector = LogCollectorConnector(gateway, config, "log_collector")
        assert connector.get_name() == "Log Collector"
        assert connector.get_id() == "test-log-collector-001"
        assert connector.is_stopped() is False
        assert connector.is_connected() is False

    def test_open_and_close(self):
        gateway = MagicMock()
        config = _make_config()
        connector = LogCollectorConnector(gateway, config, "log_collector")
        connector.open()
        time.sleep(0.5)
        assert connector.is_stopped() is False
        connector.close()
        time.sleep(0.5)
        assert connector.is_stopped() is True

    def test_get_type_and_config(self):
        gateway = MagicMock()
        config = _make_config()
        connector = LogCollectorConnector(gateway, config, "log_collector")
        assert connector.get_type() == "log_collector"
        assert connector.get_config() is config


class TestLogCollectorConnectorSources:

    def test_source_health_connected(self):
        d = tempfile.mkdtemp()
        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "ab",
            "deviceName": "AB-YB101",
            "deviceType": "log_source",
            "watchDirs": [d],
            "filePattern": "*.txt",
        }])
        connector = LogCollectorConnector(gateway, config, "log_collector")
        connector.open()
        time.sleep(1)
        assert connector.is_connected() is True
        connector.close()
        os.rmdir(d)

    def test_source_health_disconnected(self):
        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "ab",
            "deviceName": "AB-YB101",
            "deviceType": "log_source",
            "watchDirs": ["/nonexistent/path/that/does/not/exist"],
            "filePattern": "*.txt",
        }])
        connector = LogCollectorConnector(gateway, config, "log_collector")
        connector.open()
        time.sleep(1)
        assert connector.is_connected() is False
        connector.close()

    def test_file_event_triggers_parse_and_send(self):
        d = tempfile.mkdtemp()
        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "xjsbb",
            "deviceName": "XJSBB-YB101",
            "deviceType": "log_source",
            "watchDirs": [d],
            "filePattern": "*.txt",
        }])
        connector = LogCollectorConnector(gateway, config, "log_collector")
        connector.open()
        time.sleep(1)

        # Write a valid XJSBB log file
        path = os.path.join(d, "test.txt")
        with open(path, "w", newline="") as f:
            f.write("2026-03-03 10:30:45:123   Temp:25.5\r\n")

        time.sleep(3)
        connector.close()

        assert gateway.send_to_storage.call_count >= 1
        os.unlink(path)
        os.rmdir(d)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/collect/test_log_collector_connector.py -v`
Expected: FAIL

**Step 3: Implement**

```python
# tb_gateway_collect/connectors/log_collector/log_collector_connector.py
import fnmatch
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from threading import Thread
from time import sleep, monotonic
from typing import Optional

from thingsboard_gateway.connectors.connector import Connector
from thingsboard_gateway.gateway.constants import CONNECTOR_PARAMETER
from thingsboard_gateway.tb_utility.tb_logger import init_logger

from tb_gateway_collect.connectors.log_collector.log_file_watcher import LogFileWatcher
from tb_gateway_collect.connectors.log_collector.log_uplink_converter import LogUplinkConverter
from tb_gateway_collect.connectors.log_collector.parsers import get_parser
from tb_gateway_collect.connectors.log_collector.state_tracker import StateTracker

log = logging.getLogger(__name__)


@dataclass
class SourceStatus:
    system_type: str
    device_name: str
    connected: bool = False
    last_check: Optional[datetime] = None
    last_data: Optional[datetime] = None
    error: Optional[str] = None


class LogCollectorConnector(Connector, Thread):

    def __init__(self, gateway, config, connector_type):
        super().__init__()
        self.__gateway = gateway
        self.__config = config
        self.__connector_type = connector_type
        self.__name = config.get("name", "Log Collector")
        self.__id = config.get("id")
        self.__poll_interval = config.get("pollIntervalMs", 60000) / 1000.0
        self.__connected = False
        self.__stopped = False
        self.daemon = True

        self.__converter = LogUplinkConverter(
            device_type=config.get("defaultDeviceType", "log_source")
        )
        self.__state_tracker = StateTracker(config.get("stateFile", "log_collector_state.json"))
        self.__sources = config.get("sources", [])
        self.__source_statuses: dict[str, SourceStatus] = {}

        for src in self.__sources:
            key = src["deviceName"]
            self.__source_statuses[key] = SourceStatus(
                system_type=src["systemType"],
                device_name=src["deviceName"],
            )

        self.__watcher = LogFileWatcher(self._on_file_event)
        self.__log = self._create_logger(config)

    def _create_logger(self, config):
        try:
            logger = init_logger(self.__gateway, self.__name,
                                 config.get('logLevel', 'INFO'),
                                 enable_remote_logging=config.get('enableRemoteLogging', False),
                                 is_connector_logger=True)
            return logger
        except Exception:
            return log

    # --- Connector interface ---

    def open(self):
        self.__stopped = False
        self._setup_watches()
        self.__watcher.start()
        self.start()
        self.__log.info("Log Collector started with %d sources", len(self.__sources))

    def close(self):
        self.__stopped = True
        self.__connected = False
        try:
            self.__watcher.stop()
        except Exception:
            pass
        self.__log.info("Log Collector stopped")

    def get_id(self):
        return self.__id

    def get_name(self):
        return self.__name

    def get_type(self):
        return self.__connector_type

    def get_config(self):
        return self.__config

    def is_connected(self):
        return self.__connected

    def is_stopped(self):
        return self.__stopped

    def on_attributes_update(self, content):
        pass

    def server_side_rpc_handler(self, content):
        pass

    # --- Setup ---

    def _setup_watches(self):
        for src in self.__sources:
            pattern = src.get("filePattern", "*.txt")
            for watch_dir in src.get("watchDirs", []):
                if os.path.isdir(watch_dir):
                    try:
                        self.__watcher.add_watch(watch_dir, pattern)
                    except Exception as e:
                        self.__log.warning("Failed to watch %s: %s", watch_dir, e)

    # --- File event handler ---

    def _on_file_event(self, file_path: str):
        """Called by watchdog when a file is created or modified."""
        for src in self.__sources:
            if self._file_belongs_to_source(file_path, src):
                self._process_file(file_path, src)
                return

    def _file_belongs_to_source(self, file_path: str, source: dict) -> bool:
        pattern = source.get("filePattern", "*.txt")
        if not fnmatch.fnmatch(os.path.basename(file_path), pattern):
            return False
        for watch_dir in source.get("watchDirs", []):
            try:
                if os.path.commonpath([watch_dir, file_path]) == os.path.normpath(watch_dir):
                    return True
            except ValueError:
                continue
        return False

    def _process_file(self, file_path: str, source: dict):
        system_type = source["systemType"]
        device_name = source["deviceName"]
        device_type = source.get("deviceType", "log_source")
        date_filter_days = source.get("dateFilterDays")

        if date_filter_days and not self._file_in_date_range(file_path, date_filter_days):
            return

        try:
            parser = get_parser(system_type)
            cursor = self.__state_tracker.get_cursor(file_path)
            records, new_cursor = parser.parse(file_path, device_name, cursor)
            self.__state_tracker.save_cursor(file_path, new_cursor)

            for record in records:
                converted = self.__converter.convert(record)
                self.__gateway.add_device(device_name, {CONNECTOR_PARAMETER: self},
                                          device_type=device_type)
                self.__gateway.send_to_storage(self.get_name(), self.get_id(), converted)

            if records:
                status = self.__source_statuses.get(device_name)
                if status:
                    status.last_data = datetime.now()
                self.__log.debug("Processed %d records from %s for %s",
                                 len(records), file_path, device_name)
        except Exception as e:
            self.__log.error("Error processing %s: %s", file_path, e)

    @staticmethod
    def _file_in_date_range(file_path: str, days: int) -> bool:
        """Check if file path contains a date pattern (yyyyMM/dd) within range."""
        from datetime import timedelta
        now = datetime.now()
        start = now - timedelta(days=days)
        current = start
        while current <= now:
            # Match Java pattern: yyyyMM\dd (e.g., "202603\03" or "202603/03")
            pattern = current.strftime("%Y%m") + os.sep + current.strftime("%d")
            pattern_alt = current.strftime("%Y%m") + "/" + current.strftime("%d")
            pattern_back = current.strftime("%Y%m") + "\\" + current.strftime("%d")
            if pattern in file_path or pattern_alt in file_path or pattern_back in file_path:
                return True
            current += timedelta(days=1)
        return False

    # --- Thread run loop (fallback polling) ---

    def run(self):
        while not self.__stopped:
            start = monotonic()
            self._poll_all_sources()

            any_connected = any(s.connected for s in self.__source_statuses.values())
            self.__connected = any_connected

            elapsed = monotonic() - start
            remaining = self.__poll_interval - elapsed
            if remaining > 0 and not self.__stopped:
                sleep(remaining)

    def _poll_all_sources(self):
        """Fallback polling: scan directories for new/changed files."""
        for src in self.__sources:
            device_name = src["deviceName"]
            status = self.__source_statuses.get(device_name)

            for watch_dir in src.get("watchDirs", []):
                is_accessible = os.path.isdir(watch_dir)

                if status:
                    was_connected = status.connected
                    status.connected = is_accessible
                    status.last_check = datetime.now()

                    if is_accessible and not was_connected:
                        self.__log.info("Source %s reconnected: %s", device_name, watch_dir)
                        status.error = None
                    elif not is_accessible and was_connected:
                        status.error = f"Directory not accessible: {watch_dir}"
                        self.__log.warning("Source %s disconnected: %s", device_name, watch_dir)

                if is_accessible:
                    self._scan_directory(watch_dir, src)

    def _scan_directory(self, directory: str, source: dict):
        """Walk directory and process any matching files."""
        pattern = source.get("filePattern", "*.txt")
        for root, dirs, files in os.walk(directory):
            for fname in files:
                if fnmatch.fnmatch(fname, pattern):
                    file_path = os.path.join(root, fname)
                    self._process_file(file_path, source)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/collect/test_log_collector_connector.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/log_collector_connector.py \
        tests/unit/collect/test_log_collector_connector.py
git commit -m "feat(log-collector): add LogCollectorConnector with watchdog + fallback polling"
```

---

## Task 12: Extension Shim, Config, and Build Integration

**Files:**
- Create: `thingsboard_gateway/extensions/log_collector/__init__.py`
- Create: `tb_gateway_collect/config/log_collector.json`
- Modify: `tb_gateway_collect/config/tb_gateway_connectors.json`
- Modify: `requirements-sae.txt`
- Modify: `tb_gateway_windows/build/build.py` (add log_collector hidden imports and config copy)

**Step 1: Create the extension shim**

```python
# thingsboard_gateway/extensions/log_collector/__init__.py
from tb_gateway_collect.connectors.log_collector.log_collector_connector import LogCollectorConnector
```

**Step 2: Create default config**

```json
// tb_gateway_collect/config/log_collector.json
{
  "pollIntervalMs": 60000,
  "stateFile": "log_collector_state.json",
  "logLevel": "INFO",
  "sources": [
    {
      "systemType": "ab",
      "deviceName": "AB-YB101",
      "deviceType": "log_source",
      "watchDirs": [],
      "filePattern": "*.txt",
      "dateFilterDays": 30
    },
    {
      "systemType": "ivs",
      "deviceName": "IVS-YB101",
      "deviceType": "log_source",
      "watchDirs": [],
      "filePattern": "*.txt",
      "dateFilterDays": null
    },
    {
      "systemType": "ics",
      "deviceName": "ICS-YB101",
      "deviceType": "log_source",
      "watchDirs": [],
      "filePattern": "*.txt",
      "dateFilterDays": 30
    },
    {
      "systemType": "hccm_result",
      "deviceName": "HCCM-Result-YB101",
      "deviceType": "log_source",
      "watchDirs": [],
      "filePattern": "*.txt",
      "dateFilterDays": null
    },
    {
      "systemType": "hccm_slider",
      "deviceName": "HCCM-Slider-YB101",
      "deviceType": "log_source",
      "watchDirs": [],
      "filePattern": "*.txt",
      "dateFilterDays": null
    },
    {
      "systemType": "xjsbb",
      "deviceName": "XJSBB-YB101",
      "deviceType": "log_source",
      "watchDirs": [],
      "filePattern": "*.txt",
      "dateFilterDays": null
    }
  ]
}
```

**Step 3: Update tb_gateway_connectors.json** — add a log_collector entry:

```json
{
  "connectors": [
    // ... existing entries ...
    {
      "name": "Log Collector",
      "type": "log_collector",
      "class": "LogCollectorConnector",
      "configuration": "log_collector.json"
    }
  ]
}
```

**Step 4: Update requirements-sae.txt** — add:

```
watchdog
chardet
```

**Step 5: Update build.py** — add hidden imports for the log_collector connector and copy its config:

In the `hidden_imports` list, add:
```python
'tb_gateway_collect.connectors.log_collector',
'tb_gateway_collect.connectors.log_collector.log_collector_connector',
'tb_gateway_collect.connectors.log_collector.log_file_watcher',
'tb_gateway_collect.connectors.log_collector.log_uplink_converter',
'tb_gateway_collect.connectors.log_collector.state_tracker',
'tb_gateway_collect.connectors.log_collector.parsers',
'tb_gateway_collect.connectors.log_collector.parsers.ab_dim_parser',
'tb_gateway_collect.connectors.log_collector.parsers.ivs_parser',
'tb_gateway_collect.connectors.log_collector.parsers.ics_parser',
'tb_gateway_collect.connectors.log_collector.parsers.hccm_parser',
'tb_gateway_collect.connectors.log_collector.parsers.xjsbb_parser',
'watchdog',
'chardet',
```

In the config copy section, add `log_collector.json` alongside existing configs.

**Step 6: Run all tests**

Run: `python -m pytest tests/unit/collect/ -v`
Expected: All tests pass

**Step 7: Commit**

```bash
git add thingsboard_gateway/extensions/log_collector/__init__.py \
        tb_gateway_collect/config/log_collector.json \
        tb_gateway_collect/config/tb_gateway_connectors.json \
        requirements-sae.txt \
        tb_gateway_windows/build/build.py
git commit -m "feat(log-collector): add extension shim, config, deps, and build integration"
```

---

## Task 13: Run Full Test Suite and Verify

**Step 1: Run all collect tests**

```bash
python -m pytest tests/unit/collect/ -v
```

Expected: All tests pass (base_parser, state_tracker, ab_dim, ivs, ics, hccm, xjsbb, parser_registry, uplink_converter, file_watcher, connector).

**Step 2: Run existing Windows tests to verify no regressions**

```bash
python -m pytest tests/unit/windows/ -v
```

Expected: All 17 existing tests still pass.

**Step 3: Test build (optional if build environment available)**

```bash
pip install -r requirements-sae.txt
python tb_gateway_windows/build/build.py
```

Expected: Build succeeds, `dist/config/log_collector.json` exists.

**Step 4: Final commit**

If any fixes were needed, commit them. Otherwise, task complete.

---

## Summary

| Task | Component | Files | Tests |
|------|-----------|-------|-------|
| 1 | LogRecord + LogParser ABC | `parsers/base_parser.py` | 5 tests |
| 2 | StateTracker | `state_tracker.py` | 7 tests |
| 3 | AB Dim Parser | `parsers/ab_dim_parser.py` | 8 tests |
| 4 | IVS Parser | `parsers/ivs_parser.py` | 5 tests |
| 5 | ICS Parser | `parsers/ics_parser.py` | 6 tests |
| 6 | HCCM Parsers | `parsers/hccm_parser.py` | 7 tests |
| 7 | XJSBB Parser | `parsers/xjsbb_parser.py` | 6 tests |
| 8 | Parser Registry | `parsers/__init__.py` | 4 tests |
| 9 | Uplink Converter | `log_uplink_converter.py` | 3 tests |
| 10 | File Watcher | `log_file_watcher.py` | 5 tests |
| 11 | Connector | `log_collector_connector.py` | 6 tests |
| 12 | Extension + Config + Build | shim, config, deps, build | — |
| 13 | Full Verification | — | All |
