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
    Each format maps to a KVDataType and has a default data length (in 16-bit words).
    Third tuple element is a discriminator to ensure unique enum values."""
    BOOL = (KVDataType.U_16DEC, 1, "bool")
    UINT = (KVDataType.U_16DEC, 1, "uint")
    DINT = (KVDataType.U_32DEC, 2, "dint")
    REAL = (KVDataType.U_32DEC, 2, "real")
    STRING = (KVDataType.U_16DEC, 1, "string")

    def __init__(self, kv_data_type: KVDataType, default_length: int, _tag: str):
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
