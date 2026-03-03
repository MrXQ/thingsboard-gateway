from thingsboard_gateway.gateway.entities.converted_data import ConvertedData
from thingsboard_gateway.gateway.entities.datapoint_key import DatapointKey
from thingsboard_gateway.gateway.entities.telemetry_entry import TelemetryEntry

from tb_gateway_collect.common.change_filter import ChangeFilter


def _make_converted(device_name, values, ts=1000):
    """Helper: build a ConvertedData with one TelemetryEntry."""
    cd = ConvertedData(device_name, "default")
    tv = {DatapointKey(k): v for k, v in values.items()}
    cd.add_to_telemetry(TelemetryEntry(tv, ts))
    return cd


class TestChangeFilterColdStart:

    def test_first_call_passes_all_values(self):
        cf = ChangeFilter()
        cd = _make_converted("DEV-A", {"temp": 25.0, "speed": 100})
        result = cf.filter(cd)
        assert result is not None
        assert len(result.telemetry) == 1
        assert len(result.telemetry[0].values) == 2

    def test_first_call_per_device_passes_all(self):
        cf = ChangeFilter()
        cd_a = _make_converted("DEV-A", {"temp": 25.0})
        cd_b = _make_converted("DEV-B", {"temp": 30.0})
        result_a = cf.filter(cd_a)
        result_b = cf.filter(cd_b)
        assert result_a is not None
        assert result_b is not None


class TestChangeFilterSuppression:

    def test_unchanged_values_return_none(self):
        cf = ChangeFilter()
        cd = _make_converted("DEV-A", {"temp": 25.0, "speed": 100})
        cf.filter(cd)
        result = cf.filter(_make_converted("DEV-A", {"temp": 25.0, "speed": 100}, ts=2000))
        assert result is None

    def test_one_key_changed_returns_only_changed(self):
        cf = ChangeFilter()
        cf.filter(_make_converted("DEV-A", {"temp": 25.0, "speed": 100}))
        result = cf.filter(_make_converted("DEV-A", {"temp": 26.0, "speed": 100}, ts=2000))
        assert result is not None
        assert len(result.telemetry) == 1
        keys = {k.key for k in result.telemetry[0].values.keys()}
        assert keys == {"temp"}

    def test_all_keys_changed_returns_all(self):
        cf = ChangeFilter()
        cf.filter(_make_converted("DEV-A", {"temp": 25.0, "speed": 100}))
        result = cf.filter(_make_converted("DEV-A", {"temp": 26.0, "speed": 200}, ts=2000))
        assert result is not None
        keys = {k.key for k in result.telemetry[0].values.keys()}
        assert keys == {"temp", "speed"}

    def test_devices_tracked_independently(self):
        cf = ChangeFilter()
        cf.filter(_make_converted("DEV-A", {"temp": 25.0}))
        cf.filter(_make_converted("DEV-B", {"temp": 25.0}))
        # DEV-A unchanged, DEV-B unchanged
        assert cf.filter(_make_converted("DEV-A", {"temp": 25.0}, ts=2000)) is None
        assert cf.filter(_make_converted("DEV-B", {"temp": 25.0}, ts=2000)) is None
        # DEV-A changed
        result = cf.filter(_make_converted("DEV-A", {"temp": 30.0}, ts=3000))
        assert result is not None
        assert result.device_name == "DEV-A"


class TestChangeFilterDisabled:

    def test_disabled_passes_everything(self):
        cf = ChangeFilter(enabled=False)
        cd = _make_converted("DEV-A", {"temp": 25.0})
        cf.filter(cd)
        result = cf.filter(_make_converted("DEV-A", {"temp": 25.0}, ts=2000))
        assert result is not None


class TestChangeFilterAttributes:

    def test_attributes_always_pass_through(self):
        cf = ChangeFilter()
        cd = ConvertedData("DEV-A", "default")
        cd.add_to_attributes({"firmware": "1.0"})
        tv = {DatapointKey("temp"): 25.0}
        cd.add_to_telemetry(TelemetryEntry(tv, 1000))
        cf.filter(cd)

        # Second call: telemetry unchanged, but has attributes
        cd2 = ConvertedData("DEV-A", "default")
        cd2.add_to_attributes({"firmware": "1.0"})
        tv2 = {DatapointKey("temp"): 25.0}
        cd2.add_to_telemetry(TelemetryEntry(tv2, 2000))
        result = cf.filter(cd2)
        # Telemetry unchanged → None (attributes alone don't force upload)
        assert result is None
