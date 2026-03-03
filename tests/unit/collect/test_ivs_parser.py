# tests/unit/collect/test_ivs_parser.py
import os
import tempfile
from datetime import datetime

from tb_gateway_collect.connectors.log_collector.parsers.ivs_parser import IVSParser


SAMPLE_IVS_LOG = (
    "Order,Result,extra,Head,HGA,Time\r\n"
    "2026/3/3 10:30:45,L\u68c0\u6d4b\u7ed3\u679c,T2,T4,T6,T2,T6,T4,T6,T2,T2,T2\r\n"
    "2026/3/3 10:31:00,PadResult,OK,HGA4Pad0\tHR=0.733[0.500],WP=58.0[74.0]\r\n"
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
