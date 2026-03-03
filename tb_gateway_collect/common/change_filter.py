from typing import Any, Optional

from thingsboard_gateway.gateway.entities.converted_data import ConvertedData
from thingsboard_gateway.gateway.entities.datapoint_key import DatapointKey
from thingsboard_gateway.gateway.entities.telemetry_entry import TelemetryEntry


class ChangeFilter:
    """Filters ConvertedData to only include telemetry values that changed since last call."""

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        # {device_name: {datapoint_key_str: last_value}}
        self._last_values: dict[str, dict[str, Any]] = {}

    def filter(self, converted: ConvertedData) -> Optional[ConvertedData]:
        if not self._enabled:
            return converted

        device_cache = self._last_values.setdefault(converted.device_name, {})
        changed_entries: list[TelemetryEntry] = []

        for entry in converted.telemetry:
            changed_values = {}
            for dp_key, value in entry.values.items():
                key_str = dp_key.key
                if key_str not in device_cache or device_cache[key_str] != value:
                    changed_values[dp_key] = value
                    device_cache[key_str] = value

            if changed_values:
                changed_entries.append(TelemetryEntry(changed_values, entry.ts))

        if not changed_entries:
            return None

        result = ConvertedData(converted.device_name, converted.device_type)
        for entry in changed_entries:
            result.add_to_telemetry(entry)
        return result
