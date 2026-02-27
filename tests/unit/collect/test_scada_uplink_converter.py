from tb_gateway_collect.connectors.scada.scada_uplink_converter import ScadaUplinkConverter
from tb_gateway_collect.common.plc_data_types import PlcParam, KVTypeFormat


class TestScadaUplinkConverter:
    def test_convert_dint_strips_decimals(self):
        converter = ScadaUplinkConverter()
        config = {"deviceName": "SCADA-1", "deviceType": "plc"}
        params = [PlcParam("TEMP", KVTypeFormat.DINT, 2, "temperature")]
        data = {"TEMP": "302.00"}

        result = converter.convert(config, data, params)

        values = result.telemetry[0].to_dict()["values"]
        assert values["temperature"] == 302

    def test_convert_real_with_scale(self):
        converter = ScadaUplinkConverter()
        config = {"deviceName": "SCADA-1", "deviceType": "plc"}
        params = [PlcParam("GLUE_TIME1", KVTypeFormat.REAL, 2, "glue_time", scale=0.001)]
        data = {"GLUE_TIME1": "302"}

        result = converter.convert(config, data, params)

        values = result.telemetry[0].to_dict()["values"]
        assert abs(values["glue_time"] - 0.302) < 0.0001

    def test_convert_multiple_params(self):
        converter = ScadaUplinkConverter()
        config = {"deviceName": "SCADA-1", "deviceType": "plc"}
        params = [
            PlcParam("TEMP", KVTypeFormat.DINT, 2, "temperature"),
            PlcParam("PRESS", KVTypeFormat.REAL, 2, "pressure", scale=0.01),
        ]
        data = {"TEMP": "250.00", "PRESS": "1013"}

        result = converter.convert(config, data, params)

        values = result.telemetry[0].to_dict()["values"]
        assert values["temperature"] == 250
        assert abs(values["pressure"] - 10.13) < 0.01

    def test_convert_skips_unknown_addresses(self):
        converter = ScadaUplinkConverter()
        config = {"deviceName": "SCADA-1", "deviceType": "plc"}
        params = [PlcParam("TEMP", KVTypeFormat.DINT, 2, "temperature")]
        data = {"TEMP": "302.00", "UNKNOWN": "999"}

        result = converter.convert(config, data, params)

        values = result.telemetry[0].to_dict()["values"]
        assert "temperature" in values
        assert len(values) == 1
