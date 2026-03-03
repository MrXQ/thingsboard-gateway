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
