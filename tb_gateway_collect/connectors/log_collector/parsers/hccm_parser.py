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

    def _post_process(self, records: list[LogRecord]) -> list[LogRecord]:
        return records


class HCCMResultParser(_BaseHCCMParser):
    _header_re = RESULT_HEADER_RE
    _system_type = "hccm_result"


class HCCMSliderParser(_BaseHCCMParser):
    _header_re = SLIDER_HEADER_RE
    _system_type = "hccm_slider"

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
                    deduped[-1] = r  # replace with newer
                    continue
            deduped.append(r)
        return deduped
