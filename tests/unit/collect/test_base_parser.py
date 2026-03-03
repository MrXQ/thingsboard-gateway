# tests/unit/collect/test_base_parser.py
from datetime import datetime
from tb_gateway_collect.connectors.log_collector.parsers.base_parser import LogRecord, LogParser


class TestLogRecord:

    def test_create_log_record(self):
        record = LogRecord(
            device_name="ICS-YB101",
            timestamp=datetime(2026, 3, 3, 10, 30, 45, 123000),
            values={"pos": "1", "master": "A", "result": "OK"},
            system_type="ics",
        )
        assert record.device_name == "ICS-YB101"
        assert record.system_type == "ics"
        assert record.values["pos"] == "1"
        assert record.timestamp == datetime(2026, 3, 3, 10, 30, 45, 123000)

    def test_log_record_with_raw_data(self):
        record = LogRecord(
            device_name="AB-YB101",
            timestamp=datetime(2026, 1, 15, 14, 0, 0),
            values={"raw_data": "1,OK,A,1,2,14:00:00"},
            system_type="ab",
        )
        assert "raw_data" in record.values


class TestLogParserABC:

    def test_cannot_instantiate_abstract(self):
        import pytest
        with pytest.raises(TypeError):
            LogParser()  # type: ignore

    def test_subclass_must_implement_parse(self):
        class IncompleteParser(LogParser):
            def matches_file(self, file_path: str) -> bool:
                return True
        import pytest
        with pytest.raises(TypeError):
            IncompleteParser()

    def test_subclass_must_implement_matches_file(self):
        class IncompleteParser(LogParser):
            def parse(self, file_path, device_name, cursor):
                return [], {}
        import pytest
        with pytest.raises(TypeError):
            IncompleteParser()

    def test_concrete_subclass_works(self):
        class DummyParser(LogParser):
            def parse(self, file_path, device_name, cursor):
                return [], {}
            def matches_file(self, file_path):
                return file_path.endswith(".txt")

        parser = DummyParser()
        records, new_cursor = parser.parse("test.txt", "DEV-1", None)
        assert records == []
        assert new_cursor == {}
        assert parser.matches_file("data.txt") is True
        assert parser.matches_file("data.csv") is False
