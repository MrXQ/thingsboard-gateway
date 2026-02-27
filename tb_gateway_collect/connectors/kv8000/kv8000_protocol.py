import socket
from typing import Any, List, Optional

from tb_gateway_collect.common.plc_data_types import KVTypeFormat, PlcParam


def build_read_instruction(address: str, type_format: KVTypeFormat, count: int = 1) -> str:
    """Build a Keyence ASCII read instruction.
    RD for single read, RDS for sequential read."""
    suffix = type_format.kv_data_type.suffix
    if count <= 1:
        return f"RD {address}{suffix}\r"
    return f"RDS {address}{suffix} {count}\r"


def build_write_instruction(address: str, type_format: KVTypeFormat, values: List[int]) -> str:
    """Build a Keyence ASCII write instruction.
    WR for single write, WRS for sequential write."""
    suffix = type_format.kv_data_type.suffix
    if len(values) == 1:
        return f"WR {address}{suffix} {values[0]}\r"
    count = len(values)
    vals_str = ' '.join(str(v) for v in values)
    return f"WRS {address}{suffix} {count} {vals_str}\r"


class KV8000Client:
    """TCP client for Keyence KV8000 PLC using the ASCII command protocol."""

    def __init__(self, host: str, port: int, timeout_ms: int = 200):
        self._host = host
        self._port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(timeout_ms / 1000.0)
        self._sock.connect((host, port))
        self._rfile = self._sock.makefile('rb')

    def _send_and_receive(self, instruction: str) -> str:
        self._sock.sendall(instruction.encode('utf-8'))
        line = self._rfile.readline().decode('utf-8').strip()
        return line

    def read_param(self, param: PlcParam) -> Any:
        """Read a single PLC parameter and return its parsed value."""
        instruction = build_read_instruction(param.address, param.type_format)
        raw_response = self._send_and_receive(instruction)

        # Bit-level extraction for BOOL params with bit_index
        if param.bit_index is not None:
            word_val = int(raw_response)
            value = bool((word_val >> param.bit_index) & 1)
        else:
            value = param.type_format.parse_value(raw_response)

        # Apply scale factor if present
        if param.scale is not None and isinstance(value, (int, float)):
            value = value * param.scale

        return value

    def write(self, address: str, type_format: KVTypeFormat, *values: int) -> str:
        """Write value(s) to PLC. Returns raw response."""
        instruction = build_write_instruction(address, type_format, list(values))
        return self._send_and_receive(instruction)

    def close(self):
        try:
            self._rfile.close()
        except Exception:
            pass
        try:
            self._sock.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
