from decimal import Decimal
from time import time
from typing import Dict, List, Union

from thingsboard_gateway.connectors.converter import Converter
from thingsboard_gateway.gateway.entities.converted_data import ConvertedData
from thingsboard_gateway.gateway.entities.datapoint_key import DatapointKey
from thingsboard_gateway.gateway.entities.telemetry_entry import TelemetryEntry

from tb_gateway_collect.common.plc_data_types import PlcParam, KVTypeFormat


class ScadaUplinkConverter(Converter):

    def convert(self, config: dict, data: dict, params: List[PlcParam] = None) -> ConvertedData:
        device_name = config["deviceName"]
        device_type = config.get("deviceType", "plc")
        converted = ConvertedData(device_name, device_type)

        if not data or not params:
            return converted

        param_by_address = {p.address: p for p in params}
        telemetry_values = {}

        for address, raw_value in data.items():
            param = param_by_address.get(address)
            if param is None:
                continue

            value = self._convert_value(raw_value, param)
            telemetry_values[DatapointKey(param.name)] = value

        if telemetry_values:
            ts = int(time() * 1000)
            converted.add_to_telemetry(TelemetryEntry(telemetry_values, ts))

        return converted

    @staticmethod
    def _convert_value(raw_value: str, param: PlcParam):
        if param.type_format == KVTypeFormat.DINT:
            return int(Decimal(raw_value))
        elif param.type_format == KVTypeFormat.REAL and param.scale is not None:
            return float(Decimal(raw_value) * Decimal(str(param.scale)))
        elif param.type_format == KVTypeFormat.UINT:
            return int(raw_value)
        elif param.type_format == KVTypeFormat.BOOL:
            return raw_value.strip() not in ("0", "0.00", "")
        return raw_value
