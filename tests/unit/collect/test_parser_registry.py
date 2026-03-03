# tests/unit/collect/test_parser_registry.py
from tb_gateway_collect.connectors.log_collector.parsers import PARSER_REGISTRY, get_parser
from tb_gateway_collect.connectors.log_collector.parsers.base_parser import LogParser


class TestParserRegistry:

    def test_all_system_types_registered(self):
        expected = {"ab", "ivs", "ics", "hccm_result", "hccm_slider", "xjsbb"}
        assert set(PARSER_REGISTRY.keys()) == expected

    def test_get_parser_returns_instance(self):
        parser = get_parser("ab")
        assert isinstance(parser, LogParser)

    def test_get_parser_unknown_type_raises(self):
        import pytest
        with pytest.raises(KeyError):
            get_parser("unknown_type")

    def test_get_parser_caches_instances(self):
        p1 = get_parser("ics")
        p2 = get_parser("ics")
        assert p1 is p2
