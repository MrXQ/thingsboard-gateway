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
            assert r.timestamp == datetime(2026, 3, 3, 10, 30, 45, 123000)
        finally:
            os.unlink(path)

    def test_parse_14col(self):
        path = self._write_temp_file(SAMPLE_ICS_14COL)
        try:
            parser = ICSParser()
            records, _ = parser.parse(path, "ICS-YB101", None)
            assert len(records) == 1
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
            # 9 columns -> should use fallback 9-col headers
            assert len(records) == 1
            assert records[0].values["POS"] == "3"
            assert records[0].values["EX1"] == "1.1"
            assert records[0].values["Result"] == "OK"
        finally:
            os.unlink(path)

    def test_matches_file(self):
        parser = ICSParser()
        assert parser.matches_file("data.txt") is True
        assert parser.matches_file("data.jpg") is False
