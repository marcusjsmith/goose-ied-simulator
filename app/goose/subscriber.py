"""Subscribe to IEC 61850 GOOSE multicast streams (raw Ethernet and/or UDP overlay)."""

from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from app.goose.decoder import MAX_FRAME_LEN, decode_goose_frame
from app.goose.publisher import appid_to_multicast_mac, mac_to_bytes

logger = logging.getLogger(__name__)


def parse_app_id(value: str | int) -> int:
    if isinstance(value, int):
        return value
    return int(str(value).strip(), 0)


@dataclass
class GooseSubscriber:
    interface: str = "eth0"
    app_id: int = 0x0002
    own_src_mac: str = "00:30:A7:00:01:01"
    own_gocb_ref: str = ""
    transport: str = "udp"
    udp_group: str = "239.118.50.1"
    udp_port: int = 61850
    _running: bool = False
    _raw_socket = None
    _udp_socket = None
    _threads: list[threading.Thread] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _on_message: Callable[[dict], None] | None = None
    _message_seq: int = 0
    last_error: str | None = None
    last_rx_at: float | None = None
    rx_count: int = 0
    last_detail: dict | None = None

    @property
    def dst_mac(self) -> str:
        return appid_to_multicast_mac(self.app_id)

    @property
    def running(self) -> bool:
        return self._running

    def set_on_message(self, callback: Callable[[dict], None] | None) -> None:
        self._on_message = callback

    def configure(self, app_id: int | None = None, transport: str | None = None) -> None:
        with self._lock:
            if app_id is not None:
                self.app_id = app_id
            if transport is not None:
                self.transport = transport

    def _ignore_own(self, detail: dict) -> bool:
        src = (detail.get("ethernet") or {}).get("src_mac", "").upper()
        if src == self.own_src_mac.replace("-", ":").upper():
            return True
        gocb = (detail.get("goose_pdu") or {}).get("gocb_ref", "")
        return bool(self.own_gocb_ref and gocb == self.own_gocb_ref)

    def _handle_frame(self, frame: bytes) -> None:
        if not frame or len(frame) > MAX_FRAME_LEN:
            return
        try:
            with self._lock:
                self._message_seq += 1
                message_id = self._message_seq
            detail = decode_goose_frame(frame, message_id)
        except ValueError:
            return

        received_appid = int(detail["ethernet"]["app_id"], 16)
        if received_appid != self.app_id:
            return
        if self._ignore_own(detail):
            return

        with self._lock:
            self.rx_count += 1
            self.last_rx_at = time.time()
            self.last_detail = detail
            self.last_error = None
        if self._on_message:
            self._on_message(detail)

    def _open_udp(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        sock.bind(("", self.udp_port))
        mreq = struct.pack("4s4s", socket.inet_aton(self.udp_group), socket.inet_aton("0.0.0.0"))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.settimeout(0.4)
        return sock

    def _open_raw(self):
        nic = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
        nic.bind((self.interface, 0))
        nic.settimeout(0.4)
        return nic

    def _udp_loop(self) -> None:
        while self._running and self._udp_socket:
            try:
                payload, _addr = self._udp_socket.recvfrom(MAX_FRAME_LEN)
            except TimeoutError:
                continue
            except OSError:
                if self._running:
                    logger.exception("GOOSE UDP subscribe receive failed")
                break
            self._handle_frame(payload)

    def _raw_loop(self) -> None:
        expected_dst = mac_to_bytes(self.dst_mac)
        while self._running and self._raw_socket:
            try:
                frame = self._raw_socket.recv(MAX_FRAME_LEN)
            except TimeoutError:
                continue
            except OSError:
                if self._running:
                    logger.exception("GOOSE raw subscribe receive failed")
                break
            if len(frame) < 14:
                continue
            if frame[0:6] != expected_dst and frame[0:6] != b"\xff" * 6:
                # Still try VLAN-tagged frames via decoder
                if frame[12:14] != b"\x81\x00":
                    continue
            self._handle_frame(frame)

    def start(self) -> None:
        if self._running:
            return
        self.last_error = None
        modes = {part.strip() for part in self.transport.lower().split("+")}
        if "both" in modes:
            modes = {"raw", "udp"}

        opened = []
        errors = []
        if "udp" in modes:
            try:
                self._udp_socket = self._open_udp()
                opened.append("udp")
            except OSError as exc:
                errors.append(f"udp: {exc}")
                logger.warning("GOOSE UDP subscribe failed: %s", exc)

        if "raw" in modes:
            try:
                self._raw_socket = self._open_raw()
                opened.append("raw")
            except OSError as exc:
                errors.append(f"raw: {exc}")
                logger.warning("GOOSE raw subscribe failed: %s", exc)

        if not opened:
            self.last_error = "; ".join(errors) or "no transport available"
            raise RuntimeError(self.last_error)

        self._running = True
        if self._udp_socket:
            thread = threading.Thread(target=self._udp_loop, daemon=True, name="goose-sub-udp")
            thread.start()
            self._threads.append(thread)
        if self._raw_socket:
            thread = threading.Thread(target=self._raw_loop, daemon=True, name="goose-sub-raw")
            thread.start()
            self._threads.append(thread)

        logger.info(
            "GOOSE subscriber listening for APPID 0x%04X (%s) via %s",
            self.app_id,
            self.dst_mac,
            "+".join(opened),
        )
        if errors:
            self.last_error = "; ".join(errors)

    def stop(self) -> None:
        self._running = False
        for sock in (self._udp_socket, self._raw_socket):
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
        self._udp_socket = None
        self._raw_socket = None
        for thread in self._threads:
            thread.join(timeout=1.5)
        self._threads.clear()

    def snapshot(self) -> dict:
        with self._lock:
            last = self.last_detail
            ttl_ms = None
            stale = False
            if last:
                ttl_ms = last.get("goose_pdu", {}).get("time_allowed_to_live_ms")
                if self.last_rx_at and ttl_ms:
                    stale = (time.time() - self.last_rx_at) * 1000 > ttl_ms
            return {
                "running": self._running,
                "app_id": f"0x{self.app_id:04X}",
                "dst_mac": self.dst_mac,
                "transport": self.transport,
                "udp_group": self.udp_group,
                "udp_port": self.udp_port,
                "interface": self.interface,
                "rx_count": self.rx_count,
                "last_error": self.last_error,
                "last_rx_at": self.last_rx_at,
                "stale": stale,
                "last_message": last,
            }
