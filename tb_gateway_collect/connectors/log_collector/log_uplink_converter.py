# tb_gateway_collect/connectors/log_collector/log_uplink_converter.py
from thingsboard_gateway.connectors.converter import Converter
from thingsboard_gateway.gateway.entities.converted_data import ConvertedData
from thingsboard_gateway.gateway.entities.datapoint_key import DatapointKey
from thingsboard_gateway.gateway.entities.telemetry_entry import TelemetryEntry

from tb_gateway_collect.connectors.log_collector.parsers.base_parser import LogRecord


class LogUplinkConverter(Converter):
    """Converts LogRecord instances to ThingsBoard ConvertedData."""

    def __init__(self, device_type: str = "log_source"):
        self._device_type = device_type

    def convert(self, config_or_record, data=None) -> ConvertedData:
        if isinstance(config_or_record, LogRecord):
            record = config_or_record
        else:
            raise TypeError(f"Expected LogRecord, got {type(config_or_record)}")

        converted = ConvertedData(record.device_name, self._device_type)
        ts = int(record.timestamp.timestamp() * 1000)
        telemetry_values = {DatapointKey(k): v for k, v in record.values.items()}
        converted.add_to_telemetry(TelemetryEntry(telemetry_values, ts))
        return converted
