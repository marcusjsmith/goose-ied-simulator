"""Decode IEC 61850 GOOSE Ethernet frames into the UI message-detail shape."""

from __future__ import annotations

import struct
from datetime import datetime, timezone

from app.goose import asn1
from app.goose.datatypes import TAG_BIT_STRING, TAG_BOOLEAN, TAG_FLOAT, TAG_INTEGER, TAG_UNSIGNED, TAG_UTC_TIME, TAG_VISIBLE_STRING
from app.goose.message_detail import format_utc_timestamp
from app.goose.publisher import (
    TAG_ALL_DATA,
    TAG_CONF_REV,
    TAG_DAT_SET,
    TAG_GO_ID,
    TAG_GOCB_REF,
    TAG_GOOSE_PDU,
    TAG_NDS_COM,
    TAG_NUM_DAT_SET_ENTRIES,
    TAG_SQNUM,
    TAG_STNUM,
    TAG_TEST,
    TAG_TIME_ALLOWED_TO_LIVE,
    TAG_TIMESTAMP,
    appid_to_multicast_mac,
)

MAX_FRAME_LEN = 2048
ETHERTYPE_GOOSE = 0x88B8
ETHERTYPE_VLAN = 0x8100


def bytes_to_mac(raw: bytes) -> str:
    return ":".join(f"{b:02X}" for b in raw)


def decode_unsigned(value: bytes) -> int:
    return int.from_bytes(value or b"\x00", "big")


def decode_boolean(value: bytes) -> bool:
    return bool(value and value[0])


def decode_integer(value: bytes) -> int:
    if not value:
        return 0
    return int.from_bytes(value, "big", signed=True)


def decode_float(value: bytes) -> float:
    if len(value) == 5:
        value = value[1:]
    if len(value) != 4:
        raise ValueError("invalid float encoding")
    return struct.unpack("!f", value)[0]


def decode_utc_time(value: bytes) -> str:
    if len(value) < 7:
        return "—"
    seconds = int.from_bytes(value[0:4], "big")
    fraction = int.from_bytes(value[4:7], "big")
    return format_utc_timestamp(seconds, fraction)


def decode_quality(value: bytes) -> str:
    if len(value) < 3:
        return value.hex()
    bits = int.from_bytes(value[1:3], "big")
    validity = bits & 0x3
    names = {0: "good", 1: "invalid", 2: "reserved", 3: "questionable"}
    return names.get(validity, str(validity))


def decode_dbpos(value: int) -> str:
    return {0: "bad-state", 1: "intermediate", 2: "off", 3: "on"}.get(value, str(value))


def decode_all_data_entry(index: int, tag: int, value: bytes) -> dict:
    encoded_hex = bytes([tag]) + asn1.encode_length(len(value)) + value
    mms_type = "unknown"
    display = value.hex()
    try:
        if tag == TAG_BOOLEAN:
            mms_type = "boolean"
            display = "TRUE" if decode_boolean(value) else "FALSE"
        elif tag == TAG_INTEGER:
            mms_type = "int32"
            number = decode_integer(value)
            if 0 <= number <= 3:
                mms_type = "dbpos"
                display = decode_dbpos(number)
            else:
                display = str(number)
        elif tag == TAG_UNSIGNED:
            mms_type = "int32u"
            display = str(decode_unsigned(value))
        elif tag == TAG_FLOAT:
            mms_type = "float32"
            display = f"{decode_float(value):.4g}"
        elif tag == TAG_BIT_STRING:
            mms_type = "quality"
            display = decode_quality(value)
        elif tag == TAG_VISIBLE_STRING:
            mms_type = "visible_string"
            display = value.decode("ascii", errors="replace")
        elif tag == TAG_UTC_TIME:
            mms_type = "utc_time"
            display = decode_utc_time(value)
    except (ValueError, struct.error):
        display = value.hex()

    return {
        "index": index,
        "ref": f"allData[{index}]",
        "mms_type": mms_type,
        "value": display,
        "encoded_hex": encoded_hex.hex(),
        "encoded_len": len(encoded_hex),
    }


def parse_ethernet(frame: bytes) -> tuple[dict, bytes]:
    if len(frame) < 22 or len(frame) > MAX_FRAME_LEN:
        raise ValueError("GOOSE frame length out of range")

    dst_mac = bytes_to_mac(frame[0:6])
    src_mac = bytes_to_mac(frame[6:12])
    ethertype = struct.unpack("!H", frame[12:14])[0]
    offset = 14
    if ethertype == ETHERTYPE_VLAN:
        if len(frame) < 26:
            raise ValueError("truncated VLAN GOOSE frame")
        ethertype = struct.unpack("!H", frame[16:18])[0]
        offset = 18
    if ethertype != ETHERTYPE_GOOSE:
        raise ValueError(f"not a GOOSE frame (EtherType 0x{ethertype:04X})")

    app_id, length = struct.unpack("!HH", frame[offset : offset + 4])
    pdu = frame[offset + 8 :]
    ethernet = {
        "dst_mac": dst_mac,
        "src_mac": src_mac,
        "ethertype": "0x88B8",
        "app_id": f"0x{app_id:04X}",
        "length": length,
    }
    return ethernet, pdu


def parse_goose_pdu(pdu: bytes) -> tuple[dict, list[dict]]:
    tag, body, _ = asn1.decode_tlv(pdu, 0)
    if tag != TAG_GOOSE_PDU:
        raise ValueError("missing GOOSE PDU tag")

    fields: dict[int, bytes] = {t: v for t, v in asn1.iter_tlvs(body)}
    all_data_raw = fields.get(TAG_ALL_DATA, b"")
    dataset = [
        decode_all_data_entry(i, t, v)
        for i, (t, v) in enumerate(asn1.iter_tlvs(all_data_raw))
    ]
    goose_pdu = {
        "gocb_ref": fields.get(TAG_GOCB_REF, b"").decode("ascii", errors="replace") or "—",
        "time_allowed_to_live_ms": decode_unsigned(fields.get(TAG_TIME_ALLOWED_TO_LIVE, b"")),
        "dat_set": fields.get(TAG_DAT_SET, b"").decode("ascii", errors="replace") or "—",
        "go_id": fields.get(TAG_GO_ID, b"").decode("ascii", errors="replace") or "—",
        "timestamp": decode_utc_time(fields.get(TAG_TIMESTAMP, b"")),
        "st_num": decode_unsigned(fields.get(TAG_STNUM, b"")),
        "sq_num": decode_unsigned(fields.get(TAG_SQNUM, b"")),
        "test": decode_boolean(fields.get(TAG_TEST, b"")),
        "conf_rev": decode_unsigned(fields.get(TAG_CONF_REV, b"")),
        "nds_com": decode_boolean(fields.get(TAG_NDS_COM, b"")),
        "num_dat_set_entries": decode_unsigned(fields.get(TAG_NUM_DAT_SET_ENTRIES, b"")) or len(dataset),
    }
    return goose_pdu, dataset


def decode_goose_frame(frame: bytes, message_id: int) -> dict:
    ethernet, pdu = parse_ethernet(frame)
    goose_pdu, dataset = parse_goose_pdu(pdu)
    expected_mac = appid_to_multicast_mac(int(ethernet["app_id"], 16)).upper()
    return {
        "id": message_id,
        "time": datetime.now(timezone.utc).isoformat(),
        "state_change": goose_pdu["sq_num"] == 0,
        "ethernet": ethernet,
        "goose_pdu": goose_pdu,
        "dataset": dataset,
        "frame_len": len(frame),
        "frame_hex": frame.hex(),
        "expected_dst_mac": expected_mac,
    }
