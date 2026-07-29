"""IEC 61850 MMS data type encoders for GOOSE dataset entries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.goose import asn1

# MMS context-specific tags for GOOSE allData entries (IEC 61850-8-1)
TAG_ARRAY = 0xA1
TAG_STRUCTURE = 0xA2
TAG_BOOLEAN = 0x83
TAG_BIT_STRING = 0x84
TAG_INTEGER = 0x85
TAG_UNSIGNED = 0x87
TAG_FLOAT = 0x89
TAG_VISIBLE_STRING = 0x8A
TAG_UTC_TIME = 0x91


class Dbpos(int, Enum):
    INTERMEDIATE = 1
    OFF = 2
    ON = 3
    BAD = 0


class Quality:
    """13-bit quality flags per IEC 61850-7-3."""

    def __init__(self, validity: int = 0, detail: int = 0) -> None:
        self.validity = validity  # 0=good, 1=invalid, 2=reserved, 3=questionable
        self.detail = detail

    @classmethod
    def good(cls) -> Quality:
        return cls(0, 0)

    @classmethod
    def questionable(cls) -> Quality:
        return cls(3, 0)

    def encode(self) -> bytes:
        # 13 bits packed in 2 bytes with 3 unused bits
        value = (self.validity & 0x3) | ((self.detail & 0x1FFF) << 2)
        return asn1.encode_bit_string(TAG_BIT_STRING, 3, value.to_bytes(2, "big"))


@dataclass
class GooseDataValue:
    name: str
    mms_type: str
    value: Any

    def encode(self) -> bytes:
        if self.mms_type == "boolean":
            return asn1.encode_boolean(TAG_BOOLEAN, bool(self.value))
        if self.mms_type == "int32":
            return asn1.encode_integer(TAG_INTEGER, int(self.value))
        if self.mms_type == "int32u":
            return asn1.encode_unsigned(TAG_UNSIGNED, int(self.value))
        if self.mms_type == "float32":
            return asn1.encode_float32(TAG_FLOAT, float(self.value))
        if self.mms_type == "dbpos":
            return asn1.encode_integer(TAG_INTEGER, int(self.value))
        if self.mms_type == "quality":
            if isinstance(self.value, Quality):
                return self.value.encode()
            return Quality.good().encode()
        if self.mms_type == "visible_string":
            return asn1.encode_visible_string(TAG_VISIBLE_STRING, str(self.value))
        raise ValueError(f"Unsupported MMS type: {self.mms_type}")
