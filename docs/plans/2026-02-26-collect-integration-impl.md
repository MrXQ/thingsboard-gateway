# Collect Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build KV8000 and SCADA/FC7 custom connectors in `tb_gateway_collect/` that replace the Java collect app's PLC data collection, sending telemetry to ThingsBoard via the Gateway's storage pipeline.

**Architecture:** Two independent connectors (`KV8000Connector`, `ScadaConnector`) each extending `Connector` + `Thread`. KV8000 uses pure Python TCP sockets with Keyence ASCII protocol. SCADA uses JPype to bridge to `FC7_DBcomm_Java.jar`. Both read PLC parameters from ThingsBoard device attributes and poll at configurable intervals (default 3s), producing `ConvertedData` for `gateway.send_to_storage()`.

**Tech Stack:** Python 3.8+, `socket` (stdlib), `JPype1`, ThingsBoard Gateway Connector API (`Connector`, `ConvertedData`, `TelemetryEntry`, `DatapointKey`).

**Key Reference Files:**
- Connector interface: `thingsboard_gateway/connectors/connector.py`
- Converter interface: `thingsboard_gateway/connectors/converter.py`
- ConvertedData: `thingsboard_gateway/gateway/entities/converted_data.py`
- TelemetryEntry: `thingsboard_gateway/gateway/entities/telemetry_entry.py`
- DatapointKey: `thingsboard_gateway/gateway/entities/datapoint_key.py`
- Constants: `thingsboard_gateway/gateway/constants.py` (`CONNECTOR_PARAMETER`, etc.)
- Modbus connector (reference): `thingsboard_gateway/connectors/modbus/modbus_connector.py`
- Java KV8000 protocol: `collect/src/main/java/com/tdk/sae/collect/module/plc/kv8000/util/KVInstructBuilder.java`
- Java KV8000 reader: `collect/src/main/java/com/tdk/sae/collect/module/plc/kv8000/rw/KVDataReader.java`
- Java SCADA bridge: `collect/src/main/java/com/tdk/sae/collect/module/plc/scada/ScadaConnection.java`
- Java SCADA reader: `collect/src/main/java/com/tdk/sae/collect/module/plc/scada/ScadaDataReader.java`

---

## Task 1: Package Scaffolding

**Files:**
- Create: `tb_gateway_collect/__init__.py`
- Create: `tb_gateway_collect/connectors/__init__.py`
- Create: `tb_gateway_collect/connectors/kv8000/__init__.py`
- Create: `tb_gateway_collect/connectors/scada/__init__.py`
- Create: `tb_gateway_collect/common/__init__.py`
- Create: `tests/unit/collect/__init__.py`

**Step 1: Create package directories and init files**

```python
# tb_gateway_collect/__init__.py
# (empty)
```

```python
# tb_gateway_collect/connectors/__init__.py
# (empty)
```

```python
# tb_gateway_collect/connectors/kv8000/__init__.py
# (empty)
```

```python
# tb_gateway_collect/connectors/scada/__init__.py
# (empty)
```

```python
# tb_gateway_collect/common/__init__.py
# (empty)
```

```python
# tests/unit/collect/__init__.py
# (empty)
```

**Step 2: Verify structure**

Run: `python -c "import tb_gateway_collect; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add tb_gateway_collect/ tests/unit/collect/__init__.py
git commit -m "feat(collect): scaffold tb_gateway_collect package structure"
```

---

## Task 2: Shared Data Types

**Files:**
- Create: `tb_gateway_collect/common/plc_data_types.py`
- Create: `tests/unit/collect/test_plc_data_types.py`

These map directly from Java's `KVDataType` and `KVTypeFormat` enums in `collect/src/main/java/com/tdk/sae/collect/module/plc/kv8000/`.

**Step 1: Write the failing tests**

```python
# tests/unit/collect/test_plc_data_types.py

import struct
import pytest
from tb_gateway_collect.common.plc_data_types import KVDataType, KVTypeFormat, PlcParam


class TestKVDataType:
    def test_u16_suffix(self):
        assert KVDataType.U_16DEC.suffix == ".U"

    def test_s16_suffix(self):
        assert KVDataType.S_16DEC.suffix == ".S"

    def test_u32_suffix(self):
        assert KVDataType.U_32DEC.suffix == ".D"

    def test_s32_suffix(self):
        assert KVDataType.S_32DEC.suffix == ".L"

    def test_hex16_suffix(self):
        assert KVDataType.HEX_16.suffix == ".H"


class TestKVTypeFormat:
    def test_bool_maps_to_u16(self):
        fmt = KVTypeFormat.BOOL
        assert fmt.kv_data_type == KVDataType.U_16DEC
        assert fmt.default_length == 1

    def test_uint_maps_to_u16(self):
        fmt = KVTypeFormat.UINT
        assert fmt.kv_data_type == KVDataType.U_16DEC
        assert fmt.default_length == 1

    def test_dint_maps_to_u32(self):
        fmt = KVTypeFormat.DINT
        assert fmt.kv_data_type == KVDataType.U_32DEC
        assert fmt.default_length == 2

    def test_real_maps_to_u32(self):
        fmt = KVTypeFormat.REAL
        assert fmt.kv_data_type == KVDataType.U_32DEC
        assert fmt.default_length == 2

    def test_string_maps_to_u16(self):
        fmt = KVTypeFormat.STRING
        assert fmt.kv_data_type == KVDataType.U_16DEC
        assert fmt.default_length == 1

    def test_from_string_case_insensitive(self):
        assert KVTypeFormat.from_string("dint") == KVTypeFormat.DINT
        assert KVTypeFormat.from_string("REAL") == KVTypeFormat.REAL

    def test_from_string_invalid_raises(self):
        with pytest.raises(ValueError):
            KVTypeFormat.from_string("INVALID")

    def test_parse_value_bool_true(self):
        assert KVTypeFormat.BOOL.parse_value("1") == True

    def test_parse_value_bool_false(self):
        assert KVTypeFormat.BOOL.parse_value("0") == False

    def test_parse_value_uint(self):
        assert KVTypeFormat.UINT.parse_value("65535") == 65535

    def test_parse_value_dint(self):
        assert KVTypeFormat.DINT.parse_value("12345") == 12345

    def test_parse_value_real(self):
        raw_int = struct.unpack('>I', struct.pack('>f', 3.14))[0]
        result = KVTypeFormat.REAL.parse_value(str(raw_int))
        assert abs(result - 3.14) < 0.001

    def test_parse_value_string(self):
        assert KVTypeFormat.STRING.parse_value("65 66 67") == "ABC"


class TestPlcParam:
    def test_from_dict(self):
        d = {"address": "DM15000", "dataType": "DINT", "dataLength": 2, "name": "temperature"}
        p = PlcParam.from_dict(d)
        assert p.address == "DM15000"
        assert p.type_format == KVTypeFormat.DINT
        assert p.data_length == 2
        assert p.name == "temperature"
        assert p.scale is None
        assert p.bit_index is None

    def test_from_dict_with_bit_address(self):
        d = {"address": "DM15000.3", "dataType": "BOOL", "dataLength": 1, "name": "alarm"}
        p = PlcParam.from_dict(d)
        assert p.address == "DM15000"
        assert p.bit_index == 3

    def test_from_dict_with_scale(self):
        d = {"address": "DM15002", "dataType": "REAL", "dataLength": 2, "name": "pressure", "scale": 0.001}
        p = PlcParam.from_dict(d)
        assert p.scale == 0.001
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_plc_data_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tb_gateway_collect.common.plc_data_types'`

**Step 3: Implement data types**

```python
# tb_gateway_collect/common/plc_data_types.py

import struct
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class KVDataType(Enum):
    """Keyence KV8000 data type suffixes for the ASCII protocol.
    Maps to Java's KVDataType enum."""
    U_16DEC = ".U"    # Unsigned 16-bit decimal
    S_16DEC = ".S"    # Signed 16-bit decimal
    U_32DEC = ".D"    # Unsigned 32-bit decimal
    S_32DEC = ".L"    # Signed 32-bit decimal
    HEX_16 = ".H"     # 16-bit hexadecimal

    @property
    def suffix(self):
        return self.value


class KVTypeFormat(Enum):
    """PLC parameter type formats. Maps to Java's KVTypeFormat enum.
    Each format maps to a KVDataType and has a default data length (in 16-bit words)."""
    BOOL = (KVDataType.U_16DEC, 1)
    UINT = (KVDataType.U_16DEC, 1)
    DINT = (KVDataType.U_32DEC, 2)
    REAL = (KVDataType.U_32DEC, 2)
    STRING = (KVDataType.U_16DEC, 1)

    def __init__(self, kv_data_type: KVDataType, default_length: int):
        self.kv_data_type = kv_data_type
        self.default_length = default_length

    @classmethod
    def from_string(cls, value: str) -> 'KVTypeFormat':
        upper = value.upper()
        for fmt in cls:
            if fmt.name == upper:
                return fmt
        raise ValueError(f"Unknown type format: {value}")

    def parse_value(self, raw: str):
        """Parse a raw string value from PLC into the appropriate Python type."""
        if self == KVTypeFormat.BOOL:
            return raw.strip() != "0"
        elif self == KVTypeFormat.UINT:
            return int(raw)
        elif self == KVTypeFormat.DINT:
            return int(raw)
        elif self == KVTypeFormat.REAL:
            int_val = int(raw)
            return struct.unpack('>f', struct.pack('>I', int_val))[0]
        elif self == KVTypeFormat.STRING:
            chars = []
            for word_str in raw.split():
                code = int(word_str)
                if code == 0:
                    break
                chars.append(chr(code))
            return ''.join(chars)
        return raw


@dataclass
class PlcParam:
    """A single PLC parameter definition, parsed from ThingsBoard device attributes."""
    address: str
    type_format: KVTypeFormat
    data_length: int
    name: str
    scale: Optional[float] = None
    bit_index: Optional[int] = None

    @classmethod
    def from_dict(cls, d: dict) -> 'PlcParam':
        raw_address = d["address"]
        bit_index = None
        address = raw_address

        # Parse bit-level address: "DM15000.3" -> address="DM15000", bit_index=3
        if "." in raw_address:
            parts = raw_address.split(".")
            # Check if the part after dot is a digit (bit index) vs. a type suffix
            if parts[1].isdigit():
                address = parts[0]
                bit_index = int(parts[1])

        return cls(
            address=address,
            type_format=KVTypeFormat.from_string(d["dataType"]),
            data_length=d.get("dataLength", KVTypeFormat.from_string(d["dataType"]).default_length),
            name=d["name"],
            scale=d.get("scale"),
            bit_index=bit_index,
        )
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_plc_data_types.py -v`
Expected: All 19 tests PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/common/plc_data_types.py tests/unit/collect/test_plc_data_types.py
git commit -m "feat(collect): add PLC data types (KVDataType, KVTypeFormat, PlcParam)"
```

---

## Task 3: KV8000 Protocol Client

**Files:**
- Create: `tb_gateway_collect/connectors/kv8000/kv8000_protocol.py`
- Create: `tests/unit/collect/test_kv8000_protocol.py`

This reimplements Java's `KVInstructBuilder`, `KV8000Utils`, `KVDataStream`, and `KVDataReader` as a single Python module.

**Step 1: Write the failing tests**

```python
# tests/unit/collect/test_kv8000_protocol.py

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
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_kv8000_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement KV8000 protocol client**

```python
# tb_gateway_collect/connectors/kv8000/kv8000_protocol.py

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
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_kv8000_protocol.py -v`
Expected: All 10 tests PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/kv8000/kv8000_protocol.py tests/unit/collect/test_kv8000_protocol.py
git commit -m "feat(collect): add KV8000 Keyence ASCII protocol client"
```

---

## Task 4: KV8000 Uplink Converter

**Files:**
- Create: `tb_gateway_collect/connectors/kv8000/kv8000_uplink_converter.py`
- Create: `tests/unit/collect/test_kv8000_uplink_converter.py`

**Step 1: Write the failing tests**

```python
# tests/unit/collect/test_kv8000_uplink_converter.py

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
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_kv8000_uplink_converter.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement converter**

```python
# tb_gateway_collect/connectors/kv8000/kv8000_uplink_converter.py

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
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_kv8000_uplink_converter.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/kv8000/kv8000_uplink_converter.py tests/unit/collect/test_kv8000_uplink_converter.py
git commit -m "feat(collect): add KV8000 uplink converter"
```

---

## Task 5: KV8000 Connector

**Files:**
- Create: `tb_gateway_collect/connectors/kv8000/kv8000_connector.py`
- Create: `tests/unit/collect/test_kv8000_connector.py`

This is the main connector class. It extends `Connector` + `Thread`, polls PLC devices, and sends data through the gateway.

**Step 1: Write the failing tests**

```python
# tests/unit/collect/test_kv8000_connector.py

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
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_kv8000_connector.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement connector**

```python
# tb_gateway_collect/connectors/kv8000/kv8000_connector.py

import logging
from threading import Thread
from time import sleep, monotonic

from thingsboard_gateway.connectors.connector import Connector
from thingsboard_gateway.gateway.constants import CONNECTOR_PARAMETER
from thingsboard_gateway.tb_utility.tb_logger import init_logger

from tb_gateway_collect.common.plc_data_types import PlcParam, KVTypeFormat
from tb_gateway_collect.connectors.kv8000.kv8000_protocol import KV8000Client
from tb_gateway_collect.connectors.kv8000.kv8000_uplink_converter import KV8000UplinkConverter

log = logging.getLogger(__name__)


class KV8000Connector(Connector, Thread):

    def __init__(self, gateway, config, connector_type):
        super().__init__()
        self.__gateway = gateway
        self.__config = config
        self.__connector_type = connector_type
        self.__name = config.get("name", "KV8000 Connector")
        self.__id = config.get("id")
        self.__poll_interval = config.get("pollIntervalMs", 3000) / 1000.0
        self.__connected = False
        self.__stopped = False
        self.daemon = True
        self.__converter = KV8000UplinkConverter()
        self.__devices = []
        self._parse_devices(config.get("devices", []))

        try:
            self.__log = init_logger(self.__gateway, self.__name,
                                     config.get('logLevel', 'INFO'),
                                     enable_remote_logging=config.get('enableRemoteLogging', False),
                                     is_connector_logger=True)
        except Exception:
            self.__log = log

    def _parse_devices(self, devices_config):
        self.__devices = []
        for dev_cfg in devices_config:
            params = [PlcParam.from_dict(p) for p in dev_cfg.get("parameters", [])]
            self.__devices.append({
                "config": dev_cfg,
                "params": params,
            })

    # --- Connector interface ---

    def open(self):
        self.__stopped = False
        self.start()
        self.__log.info("KV8000 Connector started")

    def close(self):
        self.__stopped = True
        self.__connected = False
        self.__log.info("KV8000 Connector stopped")

    def get_id(self):
        return self.__id

    def get_name(self):
        return self.__name

    def get_type(self):
        return self.__connector_type

    def get_config(self):
        return self.__config

    def is_connected(self):
        return self.__connected

    def is_stopped(self):
        return self.__stopped

    def on_attributes_update(self, content):
        device_name = content.get("device")
        data = content.get("data", {})

        if "plcParams" in data:
            for dev in self.__devices:
                if dev["config"]["deviceName"] == device_name:
                    dev["params"] = [PlcParam.from_dict(p) for p in data["plcParams"]]
                    self.__log.info("Updated PLC params for %s: %d params",
                                    device_name, len(dev["params"]))
                    break

    def server_side_rpc_handler(self, content):
        device_name = content.get("device")
        rpc_data = content.get("data", {})
        method = rpc_data.get("method")
        params = rpc_data.get("params", {})

        if method == "plc_write":
            self._handle_plc_write(device_name, params)

    # --- Thread run loop ---

    def run(self):
        while not self.__stopped:
            start = monotonic()

            for dev in self.__devices:
                if self.__stopped:
                    break
                self._poll_device(dev["config"], dev.get("params"))

            if not self.__stopped:
                self.__connected = True

            elapsed = monotonic() - start
            remaining = self.__poll_interval - elapsed
            if remaining > 0 and not self.__stopped:
                sleep(remaining)

    def _poll_device(self, dev_config, params=None):
        if isinstance(dev_config, dict) and params is None:
            # Called from tests with just the device config dict
            for dev in self.__devices:
                if dev["config"] is dev_config:
                    params = dev["params"]
                    break
            if params is None:
                params = [PlcParam.from_dict(p) for p in dev_config.get("parameters", [])]

        host = dev_config["address"]
        port = dev_config["port"]
        device_name = dev_config["deviceName"]
        device_type = dev_config.get("deviceType", "plc")

        try:
            client = KV8000Client(host, port)
        except Exception as e:
            self.__log.warning("Failed to connect to %s:%d - %s", host, port, e)
            return

        telemetry_data = {}
        try:
            for param in params:
                try:
                    value = client.read_param(param)
                    telemetry_data[param.name] = value
                except Exception as e:
                    self.__log.warning("Failed to read param %s from %s - %s",
                                       param.name, device_name, e)
        finally:
            client.close()

        if telemetry_data:
            config = {"deviceName": device_name, "deviceType": device_type}
            converted = self.__converter.convert(config, telemetry_data)

            self.__gateway.add_device(device_name, {CONNECTOR_PARAMETER: self},
                                      device_type=device_type)
            self.__gateway.send_to_storage(self.get_name(), self.get_id(), converted)

    def _handle_plc_write(self, device_name, params):
        address = params.get("address")
        data_type_str = params.get("dataType")
        value = params.get("value")

        for dev in self.__devices:
            if dev["config"]["deviceName"] == device_name:
                host = dev["config"]["address"]
                port = dev["config"]["port"]
                try:
                    type_format = KVTypeFormat.from_string(data_type_str)
                    client = KV8000Client(host, port)
                    try:
                        result = client.write(address, type_format, int(value))
                        self.__log.info("PLC write to %s/%s = %s -> %s",
                                         device_name, address, value, result)
                    finally:
                        client.close()
                except Exception as e:
                    self.__log.error("PLC write failed for %s/%s: %s",
                                     device_name, address, e)
                break
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_kv8000_connector.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/kv8000/kv8000_connector.py tests/unit/collect/test_kv8000_connector.py
git commit -m "feat(collect): add KV8000 connector with polling and RPC write"
```

---

## Task 6: SCADA FC7 Bridge

**Files:**
- Create: `tb_gateway_collect/connectors/scada/scada_fc7_bridge.py`
- Create: `tests/unit/collect/test_scada_fc7_bridge.py`

This wraps the Java `DBComm` class from `FC7_DBcomm_Java.jar` via JPype.

**Step 1: Write the failing tests**

```python
# tests/unit/collect/test_scada_fc7_bridge.py

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
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_scada_fc7_bridge.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement FC7 bridge**

```python
# tb_gateway_collect/connectors/scada/scada_fc7_bridge.py

import logging
from typing import Dict, List, Optional

try:
    import jpype
    import jpype.imports
except ImportError:
    jpype = None

log = logging.getLogger(__name__)


class FC7Bridge:
    """JPype bridge to FC7_DBcomm_Java.jar for SCADA PLC communication."""

    def __init__(self, jar_path: str):
        self._jar_path = jar_path
        self._dbcomm = None
        self._ensure_jvm()

    def _ensure_jvm(self):
        if jpype is None:
            raise ImportError("JPype1 is required for SCADA/FC7 support. Install with: pip install JPype1")
        if not jpype.isJVMStarted():
            jpype.startJVM(classpath=[self._jar_path])
        DBComm = jpype.JClass("com.scada.dbcomm.DBComm")
        self._dbcomm = DBComm()

    def connect(self, ip: str, port: int) -> int:
        session_id = self._dbcomm.Initial()
        self._dbcomm.ConnectRemoteServer(session_id, ip, port, "", False)
        return int(session_id)

    def is_connected(self, session_id: int) -> bool:
        return bool(self._dbcomm.IsConnected(session_id))

    def get_all_tags(self, session_id: int) -> List[str]:
        tags = self._dbcomm.GetAllTagName(session_id)
        return list(tags)

    def get_data(self, session_id: int, addresses: List[str]) -> Dict[str, str]:
        raw_arr = self._dbcomm.GetData(session_id, addresses)
        result = {}
        for item in raw_arr:
            item_str = str(item)
            if "," in item_str:
                addr, value = item_str.split(",", 1)
                result[addr] = value
        return result

    def set_data(self, session_id: int, address: str, value: int) -> None:
        self._dbcomm.SetData(session_id, address, value)

    def disconnect(self, session_id: int) -> None:
        self._dbcomm.DisConnect(session_id)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_scada_fc7_bridge.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/scada/scada_fc7_bridge.py tests/unit/collect/test_scada_fc7_bridge.py
git commit -m "feat(collect): add SCADA FC7 bridge via JPype"
```

---

## Task 7: SCADA Uplink Converter

**Files:**
- Create: `tb_gateway_collect/connectors/scada/scada_uplink_converter.py`
- Create: `tests/unit/collect/test_scada_uplink_converter.py`

The SCADA converter is similar to KV8000 but handles FC7's raw integer scaling.

**Step 1: Write the failing tests**

```python
# tests/unit/collect/test_scada_uplink_converter.py

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
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_scada_uplink_converter.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement converter**

```python
# tb_gateway_collect/connectors/scada/scada_uplink_converter.py

from decimal import Decimal
from time import time
from typing import Dict, List, Union

from thingsboard_gateway.connectors.converter import Converter
from thingsboard_gateway.gateway.entities.converted_data import ConvertedData
from thingsboard_gateway.gateway.entities.datapoint_key import DatapointKey
from thingsboard_gateway.gateway.entities.telemetry_entry import TelemetryEntry

from tb_gateway_collect.common.plc_data_types import PlcParam, KVTypeFormat


class ScadaUplinkConverter(Converter):

    def convert(self, config: dict, data: dict, params: List[PlcParam] = None) -> ConvertedData:
        device_name = config["deviceName"]
        device_type = config.get("deviceType", "plc")
        converted = ConvertedData(device_name, device_type)

        if not data or not params:
            return converted

        param_by_address = {p.address: p for p in params}
        telemetry_values = {}

        for address, raw_value in data.items():
            param = param_by_address.get(address)
            if param is None:
                continue

            value = self._convert_value(raw_value, param)
            telemetry_values[DatapointKey(param.name)] = value

        if telemetry_values:
            ts = int(time() * 1000)
            converted.add_to_telemetry(TelemetryEntry(telemetry_values, ts))

        return converted

    @staticmethod
    def _convert_value(raw_value: str, param: PlcParam):
        if param.type_format == KVTypeFormat.DINT:
            return int(Decimal(raw_value))
        elif param.type_format == KVTypeFormat.REAL and param.scale is not None:
            return float(Decimal(raw_value) * Decimal(str(param.scale)))
        elif param.type_format == KVTypeFormat.UINT:
            return int(raw_value)
        elif param.type_format == KVTypeFormat.BOOL:
            return raw_value.strip() not in ("0", "0.00", "")
        return raw_value
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_scada_uplink_converter.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/scada/scada_uplink_converter.py tests/unit/collect/test_scada_uplink_converter.py
git commit -m "feat(collect): add SCADA uplink converter with FC7 scaling"
```

---

## Task 8: SCADA Connector

**Files:**
- Create: `tb_gateway_collect/connectors/scada/scada_connector.py`
- Create: `tests/unit/collect/test_scada_connector.py`

**Step 1: Write the failing tests**

```python
# tests/unit/collect/test_scada_connector.py

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
        connector = ScadaConnector(gw, config, "scada")

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
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_scada_connector.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement connector**

```python
# tb_gateway_collect/connectors/scada/scada_connector.py

import logging
from threading import Thread
from time import sleep, monotonic

from thingsboard_gateway.connectors.connector import Connector
from thingsboard_gateway.gateway.constants import CONNECTOR_PARAMETER
from thingsboard_gateway.tb_utility.tb_logger import init_logger

from tb_gateway_collect.common.plc_data_types import PlcParam
from tb_gateway_collect.connectors.scada.scada_fc7_bridge import FC7Bridge
from tb_gateway_collect.connectors.scada.scada_uplink_converter import ScadaUplinkConverter

log = logging.getLogger(__name__)


class ScadaConnector(Connector, Thread):

    def __init__(self, gateway, config, connector_type):
        super().__init__()
        self.__gateway = gateway
        self.__config = config
        self.__connector_type = connector_type
        self.__name = config.get("name", "SCADA Connector")
        self.__id = config.get("id")
        self.__poll_interval = config.get("pollIntervalMs", 3000) / 1000.0
        self.__connected = False
        self.__stopped = False
        self.daemon = True
        self.__converter = ScadaUplinkConverter()
        self.__bridge = FC7Bridge(jar_path=config.get("jarPath", "FC7_DBcomm_Java.jar"))
        self.__devices = []
        self._parse_devices(config.get("devices", []))

        try:
            self.__log = init_logger(self.__gateway, self.__name,
                                     config.get('logLevel', 'INFO'),
                                     enable_remote_logging=config.get('enableRemoteLogging', False),
                                     is_connector_logger=True)
        except Exception:
            self.__log = log

    def _parse_devices(self, devices_config):
        self.__devices = []
        for dev_cfg in devices_config:
            params = [PlcParam.from_dict(p) for p in dev_cfg.get("parameters", [])]
            self.__devices.append({
                "config": dev_cfg,
                "params": params,
                "session_id": None,
            })

    # --- Connector interface ---

    def open(self):
        self.__stopped = False
        self.start()
        self.__log.info("SCADA Connector started")

    def close(self):
        self.__stopped = True
        self.__connected = False
        for dev in self.__devices:
            if dev.get("session_id") is not None:
                try:
                    self.__bridge.disconnect(dev["session_id"])
                except Exception:
                    pass
                dev["session_id"] = None
        self.__log.info("SCADA Connector stopped")

    def get_id(self):
        return self.__id

    def get_name(self):
        return self.__name

    def get_type(self):
        return self.__connector_type

    def get_config(self):
        return self.__config

    def is_connected(self):
        return self.__connected

    def is_stopped(self):
        return self.__stopped

    def on_attributes_update(self, content):
        device_name = content.get("device")
        data = content.get("data", {})

        if "plcParams" in data:
            for dev in self.__devices:
                if dev["config"]["deviceName"] == device_name:
                    dev["params"] = [PlcParam.from_dict(p) for p in data["plcParams"]]
                    self.__log.info("Updated PLC params for %s: %d params",
                                    device_name, len(dev["params"]))
                    break

    def server_side_rpc_handler(self, content):
        device_name = content.get("device")
        rpc_data = content.get("data", {})
        method = rpc_data.get("method")
        params = rpc_data.get("params", {})

        if method == "plc_write":
            self._handle_plc_write(device_name, params)

    # --- Thread run loop ---

    def run(self):
        while not self.__stopped:
            start = monotonic()

            for dev in self.__devices:
                if self.__stopped:
                    break
                self._poll_device(dev["config"], dev)

            if not self.__stopped:
                self.__connected = True

            elapsed = monotonic() - start
            remaining = self.__poll_interval - elapsed
            if remaining > 0 and not self.__stopped:
                sleep(remaining)

    def _poll_device(self, dev_config, dev_state=None):
        if dev_state is None:
            for dev in self.__devices:
                if dev["config"] is dev_config:
                    dev_state = dev
                    break
            if dev_state is None:
                dev_state = {
                    "config": dev_config,
                    "params": [PlcParam.from_dict(p) for p in dev_config.get("parameters", [])],
                    "session_id": None,
                }

        host = dev_config["address"]
        port = dev_config["port"]
        device_name = dev_config["deviceName"]
        device_type = dev_config.get("deviceType", "plc")
        params = dev_state["params"]

        try:
            session_id = dev_state.get("session_id")
            if session_id is None or not self.__bridge.is_connected(session_id):
                session_id = self.__bridge.connect(host, port)
                dev_state["session_id"] = session_id
        except Exception as e:
            self.__log.warning("Failed to connect to SCADA %s:%d - %s", host, port, e)
            return

        try:
            addresses = [p.address for p in params]
            raw_data = self.__bridge.get_data(session_id, addresses)
        except Exception as e:
            self.__log.warning("Failed to read from SCADA %s - %s", device_name, e)
            dev_state["session_id"] = None
            return

        if raw_data:
            config = {"deviceName": device_name, "deviceType": device_type}
            converted = self.__converter.convert(config, raw_data, params)

            if converted.telemetry:
                self.__gateway.add_device(device_name, {CONNECTOR_PARAMETER: self},
                                          device_type=device_type)
                self.__gateway.send_to_storage(self.get_name(), self.get_id(), converted)

    def _handle_plc_write(self, device_name, params):
        address = params.get("address")
        value = params.get("value")

        for dev in self.__devices:
            if dev["config"]["deviceName"] == device_name:
                session_id = dev.get("session_id")
                if session_id is None:
                    self.__log.error("No SCADA session for %s, cannot write", device_name)
                    return
                try:
                    self.__bridge.set_data(session_id, address, int(value))
                    self.__log.info("SCADA write to %s/%s = %s", device_name, address, value)
                except Exception as e:
                    self.__log.error("SCADA write failed for %s/%s: %s", device_name, address, e)
                break
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_scada_connector.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/scada/scada_connector.py tests/unit/collect/test_scada_connector.py
git commit -m "feat(collect): add SCADA connector with FC7 bridge polling and RPC"
```

---

## Task 9: Example Configuration Files

**Files:**
- Create: `tb_gateway_collect/config/kv8000.json`
- Create: `tb_gateway_collect/config/scada.json`

**Step 1: Create KV8000 config example**

```json
{
  "pollIntervalMs": 3000,
  "devices": [
    {
      "deviceName": "KV8000-Line1",
      "deviceType": "plc",
      "address": "192.168.1.100",
      "port": 8501,
      "attributeSource": "thingsboard",
      "parameters": [
        {"address": "DM15000", "dataType": "DINT", "dataLength": 2, "name": "temperature"},
        {"address": "DM15002", "dataType": "REAL", "dataLength": 2, "name": "pressure", "scale": 0.001},
        {"address": "DM15004.3", "dataType": "BOOL", "dataLength": 1, "name": "alarm_motor_overheat"}
      ]
    }
  ]
}
```

**Step 2: Create SCADA config example**

```json
{
  "pollIntervalMs": 3000,
  "jarPath": "exlib/FC7_DBcomm_Java.jar",
  "devices": [
    {
      "deviceName": "SCADA-Line1",
      "deviceType": "plc",
      "address": "192.168.1.11",
      "port": 2006,
      "attributeSource": "thingsboard",
      "parameters": [
        {"address": "GLUE_TIME1", "dataType": "REAL", "dataLength": 2, "name": "glue_time", "scale": 0.001},
        {"address": "TEMP", "dataType": "DINT", "dataLength": 2, "name": "temperature"}
      ]
    }
  ]
}
```

**Step 3: Commit**

```bash
git add tb_gateway_collect/config/
git commit -m "feat(collect): add example KV8000 and SCADA connector configs"
```

---

## Task 10: Add JPype1 Dependency and Run Full Test Suite

**Files:**
- Modify: `requirements-sae.txt`

**Step 1: Add JPype1 to requirements**

Add `JPype1>=1.4.0` to `requirements-sae.txt`.

**Step 2: Run full test suite**

Run: `python -m pytest tests/unit/collect/ -v`
Expected: All tests PASS (approx. 43 tests across 7 test files)

**Step 3: Commit**

```bash
git add requirements-sae.txt
git commit -m "feat(collect): add JPype1 dependency for SCADA FC7 bridge"
```

---

## Summary

| Task | Component | Tests | Status |
|------|-----------|-------|--------|
| 1 | Package scaffolding | - | - |
| 2 | Shared data types (KVDataType, KVTypeFormat, PlcParam) | 19 | - |
| 3 | KV8000 protocol client (TCP + ASCII) | 10 | - |
| 4 | KV8000 uplink converter | 4 | - |
| 5 | KV8000 connector (polling, RPC, lifecycle) | 7 | - |
| 6 | SCADA FC7 bridge (JPype wrapper) | 6 | - |
| 7 | SCADA uplink converter | 4 | - |
| 8 | SCADA connector (polling, RPC, lifecycle) | 6 | - |
| 9 | Example config files | - | - |
| 10 | Dependencies + full test run | - | - |
| **Total** | | **~56** | |
