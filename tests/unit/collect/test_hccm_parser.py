# tests/unit/collect/test_hccm_parser.py
import os
import tempfile
from datetime import datetime, date

from tb_gateway_collect.connectors.log_collector.parsers.hccm_parser import (
    HCCMResultParser, HCCMSliderParser,
)


SAMPLE_HCCM_RESULT = (
    "PosID,BaseholeX,BaseholeY,SUSP_X,SUSP_Y,Time\r\n"
    "1,10.5,20.3,0.5,0.3,10:30:5\r\n"
    "2,11.0,21.0,0.6,0.4,10:30:10\r\n"
)

SAMPLE_HCCM_SLIDER = (
    "PosID,OutLineAngle,AFSDX,AFSDY,BFSDX,BFSDY,Time\r\n"
    "1,45.0,0.1,0.2,0.3,0.4,10:30:05\r\n"
    "1,45.1,0.11,0.21,0.31,0.41,10:30:08\r\n"
    "2,46.0,0.5,0.6,0.7,0.8,10:30:15\r\n"
)


class TestHCCMResultParser:

    def _write_temp_file(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                         encoding="utf-8", newline="")
        f.write(content)
        f.close()
        return f.name

    def test_parse_basic(self):
        path = self._write_temp_file(SAMPLE_HCCM_RESULT)
        try:
            parser = HCCMResultParser()
            records, cursor = parser.parse(path, "HCCM-Result-YB101", None)
            assert len(records) == 2
            r = records[0]
            assert r.device_name == "HCCM-Result-YB101"
            assert r.system_type == "hccm_result"
            assert r.values["Time"] == "10:30:5"
            assert r.values["PosID"] == "1"
            assert r.values["BaseholeX"] == "10.5"
            assert r.values["BaseholeY"] == "20.3"
            assert r.values["SUSP_X"] == "0.5"
            assert r.values["SUSP_Y"] == "0.3"
            assert "raw_data" in r.values
            today = date.today()
            assert r.timestamp.date() == today
            assert r.timestamp.hour == 10
            assert r.timestamp.minute == 30
            assert r.timestamp.second == 5
        finally:
            os.unlink(path)

    def test_time_zero_padding(self):
        """Time '10:30:5' should be parsed as 10:30:05."""
        path = self._write_temp_file(SAMPLE_HCCM_RESULT)
        try:
            parser = HCCMResultParser()
            records, _ = parser.parse(path, "HCCM-Result-YB101", None)
            assert records[0].timestamp.second == 5
        finally:
            os.unlink(path)

    def test_cursor_incremental(self):
        path = self._write_temp_file(SAMPLE_HCCM_RESULT)
        try:
            parser = HCCMResultParser()
            _, cursor = parser.parse(path, "HCCM-Result-YB101", None)
            records2, _ = parser.parse(path, "HCCM-Result-YB101", cursor)
            assert len(records2) == 0
        finally:
            os.unlink(path)


class TestHCCMSliderParser:

    def _write_temp_file(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                         encoding="utf-8", newline="")
        f.write(content)
        f.close()
        return f.name

    def test_parse_basic(self):
        path = self._write_temp_file(SAMPLE_HCCM_SLIDER)
        try:
            parser = HCCMSliderParser()
            records, _ = parser.parse(path, "HCCM-Slider-YB101", None)
            assert len(records) >= 2
            assert records[-1].values["PosID"] == "2"
        finally:
            os.unlink(path)

    def test_dedup_same_pos_within_5s(self):
        """PosID 1 appears twice within 3 seconds - second replaces first."""
        path = self._write_temp_file(SAMPLE_HCCM_SLIDER)
        try:
            parser = HCCMSliderParser()
            records, _ = parser.parse(path, "HCCM-Slider-YB101", None)
            pos1_records = [r for r in records if r.values["PosID"] == "1"]
            assert len(pos1_records) == 1
            # The second entry (10:30:08) should replace the first (10:30:05)
            assert pos1_records[0].timestamp.second == 8
        finally:
            os.unlink(path)

    def test_no_dedup_different_pos(self):
        path = self._write_temp_file(SAMPLE_HCCM_SLIDER)
        try:
            parser = HCCMSliderParser()
            records, _ = parser.parse(path, "HCCM-Slider-YB101", None)
            assert len(records) == 2  # pos 1 (deduped) + pos 2
        finally:
            os.unlink(path)

    def test_matches_file(self):
        parser = HCCMSliderParser()
        assert parser.matches_file("data.txt") is True
