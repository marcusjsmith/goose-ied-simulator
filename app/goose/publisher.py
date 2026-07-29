"""Build and publish IEC 61850 GOOSE Ethernet frames."""

from __future__ import annotations

import logging
import struct
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from app.goose import asn1
from app.goose.datatypes import GooseDataValue
from app.goose.message_detail import build_dataset_breakout, format_utc_timestamp

logger = logging.getLogger(__name__)

TAG_GOOSE_PDU = 0x61
TAG_GOCB_REF = 0x80
TAG_TIME_ALLOWED_TO_LIVE = 0x81
TAG_DAT_SET = 0x82
TAG_GO_ID = 0x83
TAG_TIMESTAMP = 0x84
TAG_STNUM = 0x85
TAG_SQNUM = 0x86
TAG_TEST = 0x87
TAG_CONF_REV = 0x88
TAG_NDS_COM = 0x89
TAG_NUM_DAT_SET_ENTRIES = 0x8A
TAG_ALL_DATA = 0xAB


def appid_to_multicast_mac(app_id: int) -> str:
    hi = (app_id >> 8) & 0xFF
    lo = app_id & 0xFF
    return f"01:0c:cd:01:{hi:02x}:{lo:02x}"


def mac_to_bytes(mac: str) -> bytes:
    return bytes(int(part, 16) for part in mac.replace("-", ":").split(":"))


@dataclass
class GooseConfig:
    interface: str = "eth0"
    app_id: int = 0x0001
    src_mac: str = "00:30:A7:00:01:01"
    gocb_ref: str = "DEMO_IED/LLN0$GO$GcbDemo"
    dat_set: str = "DEMO_IED/LLN0$dsGooseDemo"
    go_id: str = "DEMO_IED_GOOSE"
    conf_rev: int = 1
    time_allowed_to_live_ms: int = 5000
    min_interval_ms: int = 20
    max_interval_ms: int = 1000
    simulation_mode: bool = False


@dataclass
class GoosePublisher:
    config: GooseConfig
    dataset: list[GooseDataValue] = field(default_factory=list)
    _st_num: int = 1
    _sq_num: int = 0
    _running: bool = False
    _thread: threading.Thread | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _socket = None
    _on_publish: Callable[[dict], None] | None = None
    _message_seq: int = 0

    @property
    def dst_mac(self) -> str:
        return appid_to_multicast_mac(self.config.app_id)

    def _current_timestamp_parts(self) -> tuple[int, int]:
        now = time.time()
        seconds = int(now)
        fraction = int((now - seconds) * 0xFFFFFF)
        return seconds, fraction

    def build_message_detail(self, frame: bytes, state_change: bool) -> dict:
        self._message_seq += 1
        seconds, fraction = self._current_timestamp_parts()
        with self._lock:
            dataset = list(self.dataset)
            st_num = self._st_num
            sq_num = self._sq_num

        return {
            "id": self._message_seq,
            "time": datetime.now(timezone.utc).isoformat(),
            "state_change": state_change,
            "ethernet": {
                "dst_mac": self.dst_mac,
                "src_mac": self.config.src_mac,
                "ethertype": "0x88B8",
                "app_id": f"0x{self.config.app_id:04X}",
                "length": len(frame) - 14,
            },
            "goose_pdu": {
                "gocb_ref": self.config.gocb_ref,
                "time_allowed_to_live_ms": self.config.time_allowed_to_live_ms,
                "dat_set": self.config.dat_set,
                "go_id": self.config.go_id,
                "timestamp": format_utc_timestamp(seconds, fraction),
                "st_num": st_num,
                "sq_num": sq_num,
                "test": False,
                "conf_rev": self.config.conf_rev,
                "nds_com": False,
                "num_dat_set_entries": len(dataset),
            },
            "dataset": build_dataset_breakout(dataset),
            "frame_len": len(frame),
            "frame_hex": frame.hex(),
        }

    def set_dataset(self, values: list[GooseDataValue]) -> None:
        with self._lock:
            self.dataset = list(values)

    def set_on_publish(self, callback: Callable[[dict], None] | None) -> None:
        self._on_publish = callback

    def _encode_timestamp(self) -> bytes:
        now = time.time()
        seconds = int(now)
        fraction = int((now - seconds) * 0xFFFFFF)
        return asn1.encode_utc_time(TAG_TIMESTAMP, seconds, fraction)

    def build_goose_pdu(self, retransmit: bool = True) -> bytes:
        with self._lock:
            if not retransmit:
                self._st_num += 1
                self._sq_num = 0
            else:
                self._sq_num = (self._sq_num + 1) & 0xFFFFFFFF

            dataset = list(self.dataset)

        data_entries = b"".join(item.encode() for item in dataset)
        all_data = asn1.encode_tlv(TAG_ALL_DATA, data_entries)

        pdu_body = (
            asn1.encode_visible_string(TAG_GOCB_REF, self.config.gocb_ref)
            + asn1.encode_unsigned(TAG_TIME_ALLOWED_TO_LIVE, self.config.time_allowed_to_live_ms)
            + asn1.encode_visible_string(TAG_DAT_SET, self.config.dat_set)
            + asn1.encode_visible_string(TAG_GO_ID, self.config.go_id)
            + self._encode_timestamp()
            + asn1.encode_unsigned(TAG_STNUM, self._st_num, 4)
            + asn1.encode_unsigned(TAG_SQNUM, self._sq_num, 4)
            + asn1.encode_boolean(TAG_TEST, False)
            + asn1.encode_unsigned(TAG_CONF_REV, self.config.conf_rev, 4)
            + asn1.encode_boolean(TAG_NDS_COM, False)
            + asn1.encode_unsigned(TAG_NUM_DAT_SET_ENTRIES, len(dataset), 1)
            + all_data
        )
        return asn1.encode_tlv(TAG_GOOSE_PDU, pdu_body)

    def build_frame(self, retransmit: bool = True) -> bytes:
        goose_pdu = self.build_goose_pdu(retransmit=retransmit)
        app_id = self.config.app_id
        length = len(goose_pdu) + 8
        eth_header = (
            mac_to_bytes(self.dst_mac)
            + mac_to_bytes(self.config.src_mac)
            + struct.pack("!H", 0x88B8)
            + struct.pack("!HH", app_id, length)
            + struct.pack("!HH", 0, 0)
        )
        return eth_header + goose_pdu

    def publish_once(self, state_change: bool = False) -> dict:
        frame = self.build_frame(retransmit=not state_change)
        detail = self.build_message_detail(frame, state_change=state_change)
        stats = {
            "st_num": detail["goose_pdu"]["st_num"],
            "sq_num": detail["goose_pdu"]["sq_num"],
            "dst_mac": self.dst_mac,
            "frame_len": len(frame),
            "entries": detail["goose_pdu"]["num_dat_set_entries"],
            "timestamp": time.time(),
            "message_id": detail["id"],
        }

        if self.config.simulation_mode:
            logger.debug("Simulation mode: GOOSE frame built (%d bytes)", len(frame))
        else:
            if self._socket is None:
                raise RuntimeError("GOOSE publisher not started")
            self._socket.send(frame)

        if self._on_publish:
            self._on_publish({**stats, "detail": detail})
        return stats

    def trigger_state_change(self) -> dict:
        return self.publish_once(state_change=True)

    def start(self) -> None:
        if self._running:
            return

        if not self.config.simulation_mode:
            import socket

            nic = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
            nic.bind((self.config.interface, 0))
            self._socket = nic
            logger.info(
                "GOOSE publisher started on %s -> %s (APPID 0x%04X)",
                self.config.interface,
                self.dst_mac,
                self.config.app_id,
            )
        else:
            logger.info("GOOSE publisher in simulation mode (no raw socket)")

        self._running = True
        self._thread = threading.Thread(target=self._publish_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        if self._socket:
            self._socket.close()
            self._socket = None

    def _publish_loop(self) -> None:
        interval = self.config.min_interval_ms / 1000.0
        while self._running:
            try:
                self.publish_once(state_change=False)
            except Exception:
                logger.exception("GOOSE publish failed")
            time.sleep(interval)
