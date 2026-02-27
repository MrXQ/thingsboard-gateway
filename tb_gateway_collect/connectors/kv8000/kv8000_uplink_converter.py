from time import time
from typing import Union

from thingsboard_gateway.connectors.converter import Converter
from thingsboard_gateway.gateway.entities.converted_data import ConvertedData
from thingsboard_gateway.gateway.entities.datapoint_key import DatapointKey
from thingsboard_gateway.gateway.entities.telemetry_entry import TelemetryEntry


class KV8000UplinkConverter(Converter):

    def convert(self, config: dict, data: dict) -> ConvertedData:
        device_name = config["deviceName"]
        device_type = config.get("deviceType", "plc")
        converted = ConvertedData(device_name, device_type)

        if not data:
            return converted

        ts = data.pop("ts", None) if "ts" in data else None
        if ts is None:
            ts = int(time() * 1000)

        telemetry_values = {DatapointKey(k): v for k, v in data.items()}
        converted.add_to_telemetry(TelemetryEntry(telemetry_values, ts))

        return converted
