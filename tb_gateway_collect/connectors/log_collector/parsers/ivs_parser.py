import logging
import os
import re
from datetime import datetime
from typing import Optional

from tb_gateway_collect.connectors.log_collector.parsers.base_parser import LogParser, LogRecord

log = logging.getLogger(__name__)

ROW_RE = re.compile(r"\d{4}/\d{1,2}/\d{1,2} .*,.*\r?\n")
PAD_RE = re.compile(r"^(.*?)\t(.*)$")
KV_RE = re.compile(r"(\w+)=([^\[,]+(?:\[[^\]]*\])?)")


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
                columns = raw.split(",")
                time_str = columns[0].replace("/", "-")
                timestamp = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")

                values = {"Time": columns[0], "raw_data": raw}

                if "PadResult" in raw and len(columns) >= 3:
                    # PadResult row: timestamp,PadResult,OK/NG,PadName\tKV pairs
                    values["PadResult"] = columns[2].strip()
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
