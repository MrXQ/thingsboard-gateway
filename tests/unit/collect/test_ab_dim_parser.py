# tests/unit/collect/test_ab_dim_parser.py
import os
import tempfile
from datetime import datetime

from tb_gateway_collect.connectors.log_collector.parsers.ab_dim_parser import ABDimParser


SAMPLE_AB_LOG = (
    "Order,Result,some,extra,cols,POS,Master,A_Dim(um),B_Dim(um),Head,HGA,Time\r\n"
    "1,OK,x,y,z,3,A,12.34,56.78,H1,HGA1,2026-03-03 10:30:45:123\r\n"
    "2,NG,x,y,z,5,B,11.11,22.22,H2,HGA2,2026-03-03 10:30:46:45\r\n"
)


class TestABDimParser:

    def _write_temp_file(self, content, suffix=".txt"):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False,
                                         encoding="utf-8", newline="")
        f.write(content)
        f.close()
        return f.name

    def test_parse_basic(self):
        path = self._write_temp_file(SAMPLE_AB_LOG)
        try:
            parser = ABDimParser()
            records, cursor = parser.parse(path, "AB-YB101", None)
            assert len(records) == 2
            r = records[0]
            assert r.device_name == "AB-YB101"
            assert r.system_type == "ab"
            assert r.values["Time"] == "2026-03-03 10:30:45:123"
            assert r.values["Order"] == "1"
            assert r.values["Result"] == "OK"
            assert r.values["POS"] == "3"
            assert r.values["Master"] == "A"
            assert r.values["A_Dim(um)"] == "12.34"
            assert r.values["B_Dim(um)"] == "56.78"
            assert r.values["Head"] == "H1"
            assert r.values["HGA"] == "HGA1"
            assert "raw_data" in r.values
            assert r.timestamp == datetime(2026, 3, 3, 10, 30, 45, 123000)
        finally:
            os.unlink(path)

    def test_parse_pads_short_timestamp(self):
        """Timestamp '10:30:46:45' should be padded to '10:30:46:450'."""
        path = self._write_temp_file(SAMPLE_AB_LOG)
        try:
            parser = ABDimParser()
            records, _ = parser.parse(path, "AB-YB101", None)
            assert records[1].timestamp == datetime(2026, 3, 3, 10, 30, 46, 450000)
        finally:
            os.unlink(path)

    def test_parse_with_cursor_skips_already_read(self):
        path = self._write_temp_file(SAMPLE_AB_LOG)
        try:
            parser = ABDimParser()
            records1, cursor1 = parser.parse(path, "AB-YB101", None)
            assert len(records1) == 2

            records2, cursor2 = parser.parse(path, "AB-YB101", cursor1)
            assert len(records2) == 0
            assert cursor2["byte_offset"] == cursor1["byte_offset"]
        finally:
            os.unlink(path)

    def test_parse_incremental_new_lines(self):
        path = self._write_temp_file(SAMPLE_AB_LOG)
        try:
            parser = ABDimParser()
            _, cursor = parser.parse(path, "AB-YB101", None)

            with open(path, "a", encoding="utf-8", newline="") as f:
                f.write("3,OK,x,y,z,7,C,33.33,44.44,H3,HGA3,2026-03-03 10:31:00:000\r\n")

            records, cursor2 = parser.parse(path, "AB-YB101", cursor)
            assert len(records) == 1
            assert records[0].values["POS"] == "7"
        finally:
            os.unlink(path)

    def test_skips_header_row_in_data(self):
        content = (
            "Order,Result,POS,Master,A_Dim(um),B_Dim(um),Head,HGA,Time\r\n"
            "Order,Result,POS,Master,A_Dim(um),B_Dim(um),Head,HGA,Time\r\n"
            "1,OK,3,A,12.34,56.78,H1,HGA1,2026-03-03 10:30:45:123\r\n"
        )
        path = self._write_temp_file(content)
        try:
            parser = ABDimParser()
            records, _ = parser.parse(path, "AB-YB101", None)
            assert len(records) == 1
        finally:
            os.unlink(path)

    def test_malformed_row_skipped(self):
        content = (
            "Order,Result,POS,Master,A_Dim(um),B_Dim(um),Head,HGA,Time\r\n"
            "GARBAGE LINE WITHOUT DATE\r\n"
            "1,OK,3,A,12.34,56.78,H1,HGA1,2026-03-03 10:30:45:123\r\n"
        )
        path = self._write_temp_file(content)
        try:
            parser = ABDimParser()
            records, _ = parser.parse(path, "AB-YB101", None)
            assert len(records) == 1
        finally:
            os.unlink(path)

    def test_matches_file(self):
        parser = ABDimParser()
        assert parser.matches_file("data.txt") is True
        assert parser.matches_file("data.csv") is True
        assert parser.matches_file("data.log") is True
        assert parser.matches_file("data.jpg") is False

    def test_empty_file(self):
        path = self._write_temp_file("")
        try:
            parser = ABDimParser()
            records, cursor = parser.parse(path, "AB-YB101", None)
            assert records == []
        finally:
            os.unlink(path)
