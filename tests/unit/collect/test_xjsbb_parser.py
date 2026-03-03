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
            parser = XJSBBParser(change_detection=False)
            records, cursor = parser.parse(path, "XJSBB-YB101", None)
            assert len(records) == 4
            r = records[0]
            assert r.device_name == "XJSBB-YB101"
            assert r.system_type == "xjsbb"
            assert r.values["Time"] == "2026-03-03 10:30:45:123"
            assert r.values["Temperature"] == "25.5"
            assert "raw_data" in r.values
            assert "var_name" not in r.values
            assert "var_value" not in r.values
            assert r.timestamp == datetime(2026, 3, 3, 10, 30, 45, 123000)
        finally:
            os.unlink(path)

    def test_change_detection_filters_duplicates(self):
        path = self._write_temp_file(SAMPLE_XJSBB)
        try:
            parser = XJSBBParser(change_detection=True)
            records, _ = parser.parse(path, "XJSBB-YB101", None)
            # Temperature: 25.5 (new), Pressure: 101.3 (new),
            # Temperature: 25.5 (same -> skip), Temperature: 26.0 (changed)
            assert len(records) == 3
            temp_records = [r for r in records if "Temperature" in r.values]
            assert len(temp_records) == 2
            assert temp_records[0].values["Temperature"] == "25.5"
            assert temp_records[1].values["Temperature"] == "26.0"
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
            assert records[0].values["Var Name"] == "Value With Spaces"
            assert records[0].values["Time"] == "2026-03-03 10:00:00:000"
        finally:
            os.unlink(path)

    def test_matches_file(self):
        parser = XJSBBParser()
        assert parser.matches_file("data.txt") is True
        assert parser.matches_file("data.jpg") is False
