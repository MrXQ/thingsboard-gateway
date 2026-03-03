from tb_gateway_collect.connectors.log_collector.parsers.ab_dim_parser import ABDimParser
from tb_gateway_collect.connectors.log_collector.parsers.ivs_parser import IVSParser
from tb_gateway_collect.connectors.log_collector.parsers.ics_parser import ICSParser
from tb_gateway_collect.connectors.log_collector.parsers.hccm_parser import HCCMResultParser, HCCMSliderParser
from tb_gateway_collect.connectors.log_collector.parsers.xjsbb_parser import XJSBBParser

PARSER_REGISTRY: dict[str, type] = {
    "ab": ABDimParser,
    "ivs": IVSParser,
    "ics": ICSParser,
    "hccm_result": HCCMResultParser,
    "hccm_slider": HCCMSliderParser,
    "xjsbb": XJSBBParser,
}

_parser_instances: dict[str, object] = {}


def get_parser(system_type: str):
    """Get or create a parser instance for the given system type."""
    if system_type not in _parser_instances:
        cls = PARSER_REGISTRY[system_type]
        _parser_instances[system_type] = cls()
    return _parser_instances[system_type]
