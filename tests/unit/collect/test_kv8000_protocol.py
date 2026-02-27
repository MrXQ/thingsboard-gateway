import struct
from unittest.mock import patch, MagicMock
import pytest
from tb_gateway_collect.common.plc_data_types import KVTypeFormat, PlcParam
from tb_gateway_collect.connectors.kv8000.kv8000_protocol import (
    build_read_instruction,
    build_write_instruction,
    KV8000Client,
)


class TestBuildReadInstruction:
    def test_single_read_dint(self):
        result = build_read_instruction("DM15000", KVTypeFormat.DINT)
        assert result == "RD DM15000.D\r"

    def test_single_read_uint(self):
        result = build_read_instruction("DM15000", KVTypeFormat.UINT)
        assert result == "RD DM15000.U\r"

    def test_single_read_bool(self):
        result = build_read_instruction("DM15000", KVTypeFormat.BOOL)
        assert result == "RD DM15000.U\r"

    def test_sequential_read(self):
        result = build_read_instruction("DM15000", KVTypeFormat.DINT, count=3)
        assert result == "RDS DM15000.D 3\r"

    def test_sequential_read_count_1_uses_rd(self):
        result = build_read_instruction("DM15000", KVTypeFormat.DINT, count=1)
        assert result == "RD DM15000.D\r"


class TestBuildWriteInstruction:
    def test_single_write_uint(self):
        result = build_write_instruction("DM15000", KVTypeFormat.UINT, [65535])
        assert result == "WR DM15000.U 65535\r"

    def test_sequential_write_dint(self):
        result = build_write_instruction("DM15000", KVTypeFormat.DINT, [123, 456])
        assert result == "WRS DM15000.D 2 123 456\r"

    def test_single_write_uses_wr(self):
        result = build_write_instruction("DM15000", KVTypeFormat.DINT, [42])
        assert result == "WR DM15000.D 42\r"


class TestKV8000Client:
    def _make_mock_socket(self, responses):
        """Create a mock socket that returns the given responses line by line."""
        mock_sock = MagicMock()
        mock_file = MagicMock()
        mock_file.readline.side_effect = [r.encode('utf-8') + b'\r\n' for r in responses]
        mock_sock.makefile.return_value = mock_file
        return mock_sock

    @patch('socket.socket')
    def test_read_single_dint(self, mock_socket_cls):
        mock_sock = self._make_mock_socket(["12345"])
        mock_socket_cls.return_value = mock_sock

        client = KV8000Client("192.168.1.100", 8501, timeout_ms=200)
        param = PlcParam(address="DM15000", type_format=KVTypeFormat.DINT,
                         data_length=2, name="temperature")
        result = client.read_param(param)

        assert result == 12345
        client.close()

    @patch('socket.socket')
    def test_read_real_with_ieee754(self, mock_socket_cls):
        raw_int = struct.unpack('>I', struct.pack('>f', 25.5))[0]
        mock_sock = self._make_mock_socket([str(raw_int)])
        mock_socket_cls.return_value = mock_sock

        client = KV8000Client("192.168.1.100", 8501, timeout_ms=200)
        param = PlcParam(address="DM15002", type_format=KVTypeFormat.REAL,
                         data_length=2, name="pressure")
        result = client.read_param(param)

        assert abs(result - 25.5) < 0.001
        client.close()

    @patch('socket.socket')
    def test_read_bool_with_bit_index(self, mock_socket_cls):
        # Word value where bit 3 is set: 0b1000 = 8
        mock_sock = self._make_mock_socket(["8"])
        mock_socket_cls.return_value = mock_sock

        client = KV8000Client("192.168.1.100", 8501, timeout_ms=200)
        param = PlcParam(address="DM15000", type_format=KVTypeFormat.BOOL,
                         data_length=1, name="alarm", bit_index=3)
        result = client.read_param(param)

        assert result == True
        client.close()

    @patch('socket.socket')
    def test_read_bool_bit_not_set(self, mock_socket_cls):
        # Word value 8 = bit 3 set. Bit 0 is NOT set.
        mock_sock = self._make_mock_socket(["8"])
        mock_socket_cls.return_value = mock_sock

        client = KV8000Client("192.168.1.100", 8501, timeout_ms=200)
        param = PlcParam(address="DM15000", type_format=KVTypeFormat.BOOL,
                         data_length=1, name="alarm_bit0", bit_index=0)
        result = client.read_param(param)

        assert result == False
        client.close()

    @patch('socket.socket')
    def test_read_with_scale(self, mock_socket_cls):
        mock_sock = self._make_mock_socket(["302"])
        mock_socket_cls.return_value = mock_sock

        client = KV8000Client("192.168.1.100", 8501, timeout_ms=200)
        param = PlcParam(address="DM15000", type_format=KVTypeFormat.DINT,
                         data_length=2, name="scaled_val", scale=0.001)
        result = client.read_param(param)

        assert abs(result - 0.302) < 0.0001
        client.close()

    @patch('socket.socket')
    def test_write_single_value(self, mock_socket_cls):
        mock_sock = self._make_mock_socket(["OK"])
        mock_socket_cls.return_value = mock_sock

        client = KV8000Client("192.168.1.100", 8501, timeout_ms=200)
        client.write("DM15000", KVTypeFormat.UINT, 65535)

        # Verify the correct instruction was sent
        send_calls = mock_sock.sendall.call_args_list
        sent_data = send_calls[0][0][0].decode('utf-8')
        assert sent_data == "WR DM15000.U 65535\r"
        client.close()

    @patch('socket.socket')
    def test_connection_timeout_set(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_file = MagicMock()
        mock_file.readline.return_value = b'0\r\n'
        mock_sock.makefile.return_value = mock_file
        mock_socket_cls.return_value = mock_sock

        client = KV8000Client("192.168.1.100", 8501, timeout_ms=200)

        mock_sock.settimeout.assert_called_with(0.2)
        client.close()
