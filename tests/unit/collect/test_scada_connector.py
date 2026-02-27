from unittest.mock import MagicMock, patch
import pytest
from tb_gateway_collect.connectors.scada.scada_connector import ScadaConnector


def make_gateway_mock():
    gw = MagicMock()
    gw.get_config_path.return_value = "."
    return gw


def make_config(devices=None):
    return {
        "id": "scada-test-1",
        "name": "SCADA Test",
        "logLevel": "DEBUG",
        "pollIntervalMs": 3000,
        "jarPath": "/path/to/FC7_DBcomm_Java.jar",
        "devices": devices or [
            {
                "deviceName": "SCADA-1",
                "deviceType": "plc",
                "address": "192.168.1.11",
                "port": 2006,
                "parameters": [
                    {"address": "GLUE_TIME1", "dataType": "REAL", "dataLength": 2,
                     "name": "glue_time", "scale": 0.001},
                    {"address": "TEMP", "dataType": "DINT", "dataLength": 2,
                     "name": "temperature"},
                ]
            }
        ]
    }


class TestScadaConnectorInit:
    @patch('tb_gateway_collect.connectors.scada.scada_connector.FC7Bridge')
    def test_constructor(self, mock_bridge_cls):
        gw = make_gateway_mock()
        config = make_config()
        connector = ScadaConnector(gw, config, "scada")

        assert connector.get_name() == "SCADA Test"
        assert connector.get_id() == "scada-test-1"
        assert connector.get_type() == "scada"
        assert connector.is_stopped() == False

    @patch('tb_gateway_collect.connectors.scada.scada_connector.FC7Bridge')
    def test_get_config(self, mock_bridge_cls):
        gw = make_gateway_mock()
        config = make_config()
        connector = ScadaConnector(gw, config, "scada")
        assert connector.get_config() == config


class TestScadaConnectorPolling:
    @patch('tb_gateway_collect.connectors.scada.scada_connector.FC7Bridge')
    def test_poll_reads_and_sends_data(self, mock_bridge_cls):
        mock_bridge = MagicMock()
        mock_bridge.connect.return_value = 1
        mock_bridge.is_connected.return_value = True
        mock_bridge.get_data.return_value = {"GLUE_TIME1": "302", "TEMP": "250.00"}
        mock_bridge_cls.return_value = mock_bridge

        gw = make_gateway_mock()
        config = make_config()
        connector = ScadaConnector(gw, config, "scada")

        connector._poll_device(config["devices"][0])

        assert gw.send_to_storage.call_count == 1
        converted = gw.send_to_storage.call_args[0][2]
        assert converted.device_name == "SCADA-1"
        values = converted.telemetry[0].to_dict()["values"]
        assert abs(values["glue_time"] - 0.302) < 0.001
        assert values["temperature"] == 250

    @patch('tb_gateway_collect.connectors.scada.scada_connector.FC7Bridge')
    def test_poll_handles_connection_error(self, mock_bridge_cls):
        mock_bridge = MagicMock()
        mock_bridge.connect.side_effect = Exception("Connection refused")
        mock_bridge_cls.return_value = mock_bridge

        gw = make_gateway_mock()
        config = make_config()
        connector = ScadaConnector(gw, config, "scada")

        connector._poll_device(config["devices"][0])

        assert gw.send_to_storage.call_count == 0


class TestScadaConnectorRPC:
    @patch('tb_gateway_collect.connectors.scada.scada_connector.FC7Bridge')
    def test_rpc_plc_write(self, mock_bridge_cls):
        mock_bridge = MagicMock()
        mock_bridge.connect.return_value = 1
        mock_bridge.is_connected.return_value = True
        mock_bridge_cls.return_value = mock_bridge

        gw = make_gateway_mock()
        config = make_config()
        mock_bridge.get_data.return_value = {"GLUE_TIME1": "302"}
        connector = ScadaConnector(gw, config, "scada")

        # Establish session by polling first
        connector._poll_device(config["devices"][0])

        rpc_content = {
            "device": "SCADA-1",
            "data": {
                "method": "plc_write",
                "params": {
                    "address": "GLUE_TIME1",
                    "value": 303
                }
            }
        }
        connector.server_side_rpc_handler(rpc_content)

        mock_bridge.set_data.assert_called_once()


class TestScadaConnectorLifecycle:
    @patch('tb_gateway_collect.connectors.scada.scada_connector.FC7Bridge')
    def test_close_sets_stopped(self, mock_bridge_cls):
        gw = make_gateway_mock()
        config = make_config()
        connector = ScadaConnector(gw, config, "scada")
        connector.close()
        assert connector.is_stopped() == True
