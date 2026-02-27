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
