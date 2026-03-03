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
