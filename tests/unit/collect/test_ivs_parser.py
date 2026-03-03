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
            # Row 2 has 12 columns -> resultType=1, row 3 is PadResult,OK -> skipped, row 4 has 6 cols -> resultType=2
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
        content = "2026/3/3 10:30:45,\u68c0\u6d4b\u7ed3\u679c,col2,col3\r\n"
        path = self._write_temp_file(content)
        try:
            parser = IVSParser()
            records, _ = parser.parse(path, "IVS-YB101", None)
            assert len(records) == 1
            assert records[0].values["result_type"] == 1
        finally:
            os.unlink(path)
