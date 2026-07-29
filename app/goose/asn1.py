"""Minimal ASN.1 BER encoder for IEC 61850 GOOSE PDUs."""

from __future__ import annotations

from struct import pack


def encode_length(length: int) -> bytes:
    if length < 0x80:
        return pack("!B", length)
    if length <= 0xFF:
        return pack("!BB", 0x81, length)
    if length <= 0xFFFF:
        return pack("!BH", 0x82, length)
    raise ValueError(f"ASN.1 length too large: {length}")


def encode_tlv(tag: int, value: bytes) -> bytes:
    return pack("!B", tag) + encode_length(len(value)) + value


def encode_visible_string(tag: int, text: str) -> bytes:
    return encode_tlv(tag, text.encode("ascii"))


def encode_unsigned(tag: int, value: int, size: int = 4) -> bytes:
    return encode_tlv(tag, value.to_bytes(size, "big"))


def encode_integer(tag: int, value: int) -> bytes:
    if value >= 0:
        byte_len = max(1, (value.bit_length() + 7) // 8)
        payload = value.to_bytes(byte_len, "big")
    else:
        bit_len = max(8, (-value).bit_length() + 1)
        byte_len = (bit_len + 7) // 8
        payload = value.to_bytes(byte_len, "big", signed=True)
    return encode_tlv(tag, payload)


def encode_boolean(tag: int, value: bool) -> bytes:
    return encode_tlv(tag, b"\xff" if value else b"\x00")


def encode_bit_string(tag: int, unused_bits: int, data: bytes) -> bytes:
    return encode_tlv(tag, pack("!B", unused_bits) + data)


def encode_float32(tag: int, value: float) -> bytes:
    import struct

    return encode_tlv(tag, struct.pack("!f", value))


def encode_utc_time(tag: int, seconds: int, fraction: int = 0, quality: int = 0x0A) -> bytes:
    """Encode MMS UTC time (8 bytes seconds + 3 bytes fraction + 1 byte quality)."""
    payload = (
        pack("!I", seconds)
        + pack("!I", fraction)[1:]
        + pack("!B", quality)
    )
    return encode_tlv(tag, payload)


def encode_structure(tag: int, members: list[bytes]) -> bytes:
    payload = b"".join(members)
    return encode_tlv(tag, payload)


def encode_array(tag: int, items: list[bytes]) -> bytes:
    payload = b"".join(items)
    return encode_tlv(tag, payload)
