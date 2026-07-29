"""Format GOOSE values for display and message breakdown."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.goose.datatypes import Dbpos, GooseDataValue, Quality


def format_goose_value(mms_type: str, value: Any) -> str:
    if mms_type == "boolean":
        return "TRUE" if value else "FALSE"
    if mms_type == "dbpos":
        if isinstance(value, Dbpos):
            return value.name
        mapping = {1: "intermediate", 2: "off", 3: "on", 0: "bad-state"}
        return mapping.get(int(value), str(value))
    if mms_type == "quality":
        if isinstance(value, Quality):
            names = {0: "good", 1: "invalid", 2: "reserved", 3: "questionable"}
            return names.get(value.validity, f"validity={value.validity}")
        return str(value)
    if mms_type == "float32":
        return f"{float(value):.4g}"
    return str(value)


def serialize_value_raw(mms_type: str, value: Any) -> Any:
    if isinstance(value, Dbpos):
        return value.value
    if isinstance(value, Quality):
        return {"validity": value.validity, "detail": value.detail}
    if isinstance(value, float):
        return round(value, 6)
    return value


def build_dataset_breakout(dataset: list[GooseDataValue]) -> list[dict]:
    entries: list[dict] = []
    for index, item in enumerate(dataset):
        encoded = item.encode()
        entries.append(
            {
                "index": index,
                "ref": item.name,
                "mms_type": item.mms_type,
                "value": format_goose_value(item.mms_type, item.value),
                "value_raw": serialize_value_raw(item.mms_type, item.value),
                "encoded_hex": encoded.hex(),
                "encoded_len": len(encoded),
            }
        )
    return entries


def format_utc_timestamp(seconds: int, fraction: int) -> str:
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    ms = int(fraction / 0xFFFFFF * 1000) if fraction else 0
    return dt.strftime("%Y-%m-%d %H:%M:%S") + f".{ms:03d} UTC"
