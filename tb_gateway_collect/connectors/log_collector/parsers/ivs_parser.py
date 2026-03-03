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
                if "\u68c0\u6d4b\u7ed3\u679c" in raw or len(columns) == 12:
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
