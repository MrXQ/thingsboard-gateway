# tests/unit/collect/test_log_uplink_converter.py
from datetime import datetime
from tb_gateway_collect.connectors.log_collector.parsers.base_parser import LogRecord
from tb_gateway_collect.connectors.log_collector.log_uplink_converter import LogUplinkConverter


class TestLogUplinkConverter:

    def test_convert_single_record(self):
        converter = LogUplinkConverter()
        record = LogRecord(
            device_name="ICS-YB101",
            timestamp=datetime(2026, 3, 3, 10, 30, 45, 123000),
            values={"Time": "2026-03-03 10:30:45:123", "POS": "3", "Result": "OK", "raw_data": "line"},
            system_type="ics",
        )
        converted = converter.convert(record)
        assert converted.device_name == "ICS-YB101"
        assert converted.device_type == "log_source"
        assert len(converted.telemetry) > 0

    def test_convert_preserves_timestamp(self):
        converter = LogUplinkConverter()
        record = LogRecord(
            device_name="AB-YB101",
            timestamp=datetime(2026, 3, 3, 10, 30, 45, 123000),
            values={"Time": "2026-03-03 10:30:45:123", "A_Dim(um)": "12.34"},
            system_type="ab",
        )
        converted = converter.convert(record)
        # The telemetry entry should have the record's timestamp as ts
        entries = converted.telemetry
        assert len(entries) == 1
        ts_ms = int(datetime(2026, 3, 3, 10, 30, 45, 123000).timestamp() * 1000)
        assert entries[0].ts == ts_ms

    def test_convert_with_custom_device_type(self):
        converter = LogUplinkConverter(device_type="custom_type")
        record = LogRecord(
            device_name="DEV-1",
            timestamp=datetime(2026, 1, 1),
            values={"key": "val"},
            system_type="ab",
        )
        converted = converter.convert(record)
        assert converted.device_type == "custom_type"
