import time
from unittest.mock import MagicMock, patch, PropertyMock
import pytest
from tb_gateway_collect.connectors.kv8000.kv8000_connector import KV8000Connector


def make_gateway_mock():
    gw = MagicMock()
    gw.get_config_path.return_value = "."
    return gw


def make_config(devices=None):
    return {
        "id": "kv8000-test-1",
        "name": "KV8000 Test",
        "logLevel": "DEBUG",
        "pollIntervalMs": 3000,
        "devices": devices or [
            {
                "deviceName": "PLC-1",
                "deviceType": "plc",
                "address": "192.168.1.100",
                "port": 8501,
                "parameters": [
                    {"address": "DM15000", "dataType": "DINT", "dataLength": 2, "name": "temperature"},
                    {"address": "DM15002", "dataType": "UINT", "dataLength": 1, "name": "count"},
                ]
            }
        ]
    }


class TestKV8000ConnectorInit:
    def test_constructor(self):
        gw = make_gateway_mock()
        config = make_config()
        connector = KV8000Connector(gw, config, "kv8000")

        assert connector.get_name() == "KV8000 Test"
        assert connector.get_id() == "kv8000-test-1"
        assert connector.get_type() == "kv8000"
        assert connector.is_stopped() == False
        assert connector.is_connected() == False

    def test_get_config(self):
        gw = make_gateway_mock()
        config = make_config()
        connector = KV8000Connector(gw, config, "kv8000")
        assert connector.get_config() == config


class TestKV8000ConnectorPolling:
    @patch('tb_gateway_collect.connectors.kv8000.kv8000_connector.KV8000Client')
    def test_poll_reads_params_and_sends_data(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.read_param.side_effect = [12345, 42]
        mock_client_cls.return_value = mock_client

        gw = make_gateway_mock()
        config = make_config()
        connector = KV8000Connector(gw, config, "kv8000")

        connector._poll_device(config["devices"][0])

        assert mock_client.read_param.call_count == 2
        assert gw.send_to_storage.call_count == 1

        call_args = gw.send_to_storage.call_args
        converted_data = call_args[0][2]
        assert converted_data.device_name == "PLC-1"

    @patch('tb_gateway_collect.connectors.kv8000.kv8000_connector.KV8000Client')
    def test_poll_handles_connection_error(self, mock_client_cls):
        mock_client_cls.side_effect = ConnectionError("Connection refused")

        gw = make_gateway_mock()
        config = make_config()
        connector = KV8000Connector(gw, config, "kv8000")

        # Should not raise
        connector._poll_device(config["devices"][0])

        assert gw.send_to_storage.call_count == 0

    @patch('tb_gateway_collect.connectors.kv8000.kv8000_connector.KV8000Client')
    def test_poll_skips_failed_param_continues_others(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.read_param.side_effect = [Exception("timeout"), 42]
        mock_client_cls.return_value = mock_client

        gw = make_gateway_mock()
        config = make_config()
        connector = KV8000Connector(gw, config, "kv8000")

        connector._poll_device(config["devices"][0])

        assert mock_client.read_param.call_count == 2
        assert gw.send_to_storage.call_count == 1
        converted_data = gw.send_to_storage.call_args[0][2]
        values = converted_data.telemetry[0].to_dict()["values"]
        assert "count" in values
        assert "temperature" not in values


class TestKV8000ConnectorRPC:
    @patch('tb_gateway_collect.connectors.kv8000.kv8000_connector.KV8000Client')
    def test_rpc_plc_write(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.write.return_value = "OK"
        mock_client_cls.return_value = mock_client

        gw = make_gateway_mock()
        config = make_config()
        connector = KV8000Connector(gw, config, "kv8000")

        rpc_content = {
            "device": "PLC-1",
            "data": {
                "method": "plc_write",
                "params": {
                    "address": "DM15000",
                    "dataType": "UINT",
                    "value": 100
                }
            }
        }
        connector.server_side_rpc_handler(rpc_content)

        mock_client.write.assert_called_once()


class TestKV8000ConnectorLifecycle:
    def test_close_sets_stopped(self):
        gw = make_gateway_mock()
        config = make_config()
        connector = KV8000Connector(gw, config, "kv8000")

        connector.close()

        assert connector.is_stopped() == True
