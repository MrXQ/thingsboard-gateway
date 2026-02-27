from tb_gateway_collect.connectors.kv8000.kv8000_uplink_converter import KV8000UplinkConverter


class TestKV8000UplinkConverter:
    def test_convert_single_param(self):
        converter = KV8000UplinkConverter()
        config = {"deviceName": "PLC-1", "deviceType": "plc"}
        data = {"temperature": 25}

        result = converter.convert(config, data)

        assert result.device_name == "PLC-1"
        assert result.device_type == "plc"
        assert len(result.telemetry) == 1
        values = result.telemetry[0].to_dict()["values"]
        assert values["temperature"] == 25

    def test_convert_multiple_params(self):
        converter = KV8000UplinkConverter()
        config = {"deviceName": "PLC-1", "deviceType": "plc"}
        data = {"temperature": 25, "pressure": 0.302, "alarm": True}

        result = converter.convert(config, data)

        assert len(result.telemetry) == 1
        values = result.telemetry[0].to_dict()["values"]
        assert values["temperature"] == 25
        assert abs(values["pressure"] - 0.302) < 0.001
        assert values["alarm"] == True

    def test_convert_empty_data(self):
        converter = KV8000UplinkConverter()
        config = {"deviceName": "PLC-1", "deviceType": "plc"}
        data = {}

        result = converter.convert(config, data)

        assert result.device_name == "PLC-1"
        assert len(result.telemetry) == 0

    def test_convert_with_timestamp(self):
        converter = KV8000UplinkConverter()
        config = {"deviceName": "PLC-1", "deviceType": "plc"}
        data = {"temperature": 25, "ts": 1677123456789}

        result = converter.convert(config, data)

        assert result.telemetry[0].ts == 1677123456789
        values = result.telemetry[0].to_dict()["values"]
        assert "ts" not in values
        assert values["temperature"] == 25
