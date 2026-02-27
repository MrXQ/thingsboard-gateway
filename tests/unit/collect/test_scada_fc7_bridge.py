from unittest.mock import MagicMock, patch
import pytest
from tb_gateway_collect.connectors.scada.scada_fc7_bridge import FC7Bridge


class TestFC7Bridge:
    @patch('tb_gateway_collect.connectors.scada.scada_fc7_bridge.jpype')
    def test_connect(self, mock_jpype):
        mock_dbcomm_cls = MagicMock()
        mock_dbcomm = MagicMock()
        mock_dbcomm.Initial.return_value = 12345
        mock_dbcomm.ConnectRemoteServer.return_value = True
        mock_dbcomm.IsConnected.return_value = True
        mock_dbcomm_cls.return_value = mock_dbcomm
        mock_jpype.JClass.return_value = mock_dbcomm_cls
        mock_jpype.isJVMStarted.return_value = True

        bridge = FC7Bridge(jar_path="/path/to/FC7_DBcomm_Java.jar")
        session = bridge.connect("192.168.1.11", 2006)

        assert session == 12345
        mock_dbcomm.ConnectRemoteServer.assert_called_once_with(
            12345, "192.168.1.11", 2006, "", False)

    @patch('tb_gateway_collect.connectors.scada.scada_fc7_bridge.jpype')
    def test_is_connected(self, mock_jpype):
        mock_dbcomm_cls = MagicMock()
        mock_dbcomm = MagicMock()
        mock_dbcomm.Initial.return_value = 12345
        mock_dbcomm.ConnectRemoteServer.return_value = True
        mock_dbcomm.IsConnected.return_value = True
        mock_dbcomm_cls.return_value = mock_dbcomm
        mock_jpype.JClass.return_value = mock_dbcomm_cls
        mock_jpype.isJVMStarted.return_value = True

        bridge = FC7Bridge(jar_path="/path/to/jar")
        bridge.connect("192.168.1.11", 2006)

        assert bridge.is_connected(12345) == True

    @patch('tb_gateway_collect.connectors.scada.scada_fc7_bridge.jpype')
    def test_get_data(self, mock_jpype):
        mock_dbcomm_cls = MagicMock()
        mock_dbcomm = MagicMock()
        mock_dbcomm.Initial.return_value = 1
        mock_dbcomm.ConnectRemoteServer.return_value = True
        mock_dbcomm.IsConnected.return_value = True
        mock_dbcomm.GetData.return_value = ["GLUE_TIME1,302", "TEMP,500"]
        mock_dbcomm_cls.return_value = mock_dbcomm
        mock_jpype.JClass.return_value = mock_dbcomm_cls
        mock_jpype.isJVMStarted.return_value = True

        bridge = FC7Bridge(jar_path="/path/to/jar")
        bridge.connect("192.168.1.11", 2006)
        result = bridge.get_data(1, ["GLUE_TIME1", "TEMP"])

        assert result == {"GLUE_TIME1": "302", "TEMP": "500"}

    @patch('tb_gateway_collect.connectors.scada.scada_fc7_bridge.jpype')
    def test_get_all_tags(self, mock_jpype):
        mock_dbcomm_cls = MagicMock()
        mock_dbcomm = MagicMock()
        mock_dbcomm.Initial.return_value = 1
        mock_dbcomm.ConnectRemoteServer.return_value = True
        mock_dbcomm.IsConnected.return_value = True
        mock_dbcomm.GetAllTagName.return_value = ["TAG1", "TAG2", "TAG3"]
        mock_dbcomm_cls.return_value = mock_dbcomm
        mock_jpype.JClass.return_value = mock_dbcomm_cls
        mock_jpype.isJVMStarted.return_value = True

        bridge = FC7Bridge(jar_path="/path/to/jar")
        bridge.connect("192.168.1.11", 2006)
        tags = bridge.get_all_tags(1)

        assert tags == ["TAG1", "TAG2", "TAG3"]

    @patch('tb_gateway_collect.connectors.scada.scada_fc7_bridge.jpype')
    def test_set_data(self, mock_jpype):
        mock_dbcomm_cls = MagicMock()
        mock_dbcomm = MagicMock()
        mock_dbcomm.Initial.return_value = 1
        mock_dbcomm.ConnectRemoteServer.return_value = True
        mock_dbcomm.IsConnected.return_value = True
        mock_dbcomm_cls.return_value = mock_dbcomm
        mock_jpype.JClass.return_value = mock_dbcomm_cls
        mock_jpype.isJVMStarted.return_value = True

        bridge = FC7Bridge(jar_path="/path/to/jar")
        bridge.connect("192.168.1.11", 2006)
        bridge.set_data(1, "GLUE_TIME1", 303)

        mock_dbcomm.SetData.assert_called_once_with(1, "GLUE_TIME1", 303)

    @patch('tb_gateway_collect.connectors.scada.scada_fc7_bridge.jpype')
    def test_disconnect(self, mock_jpype):
        mock_dbcomm_cls = MagicMock()
        mock_dbcomm = MagicMock()
        mock_dbcomm.Initial.return_value = 1
        mock_dbcomm.ConnectRemoteServer.return_value = True
        mock_dbcomm.IsConnected.return_value = True
        mock_dbcomm_cls.return_value = mock_dbcomm
        mock_jpype.JClass.return_value = mock_dbcomm_cls
        mock_jpype.isJVMStarted.return_value = True

        bridge = FC7Bridge(jar_path="/path/to/jar")
        bridge.connect("192.168.1.11", 2006)
        bridge.disconnect(1)

        mock_dbcomm.DisConnect.assert_called_once_with(1)
