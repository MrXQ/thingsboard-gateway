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

    @staticmethod
    def _parse_timestamp(time_str: str) -> datetime:
        """Parse AB timestamp: 'yyyy-MM-dd HH:mm:ss:SSS' with zero-padding."""
        padded = time_str.ljust(23, "0")
        # Java uses ':' before millis, Python strptime needs '.'
        last_colon = padded.rfind(":")
        normalized = padded[:last_colon] + "." + padded[last_colon + 1:]
        return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S.%f")
