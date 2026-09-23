"""GOOSE IED Simulator – FastAPI application."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.goose.publisher import GooseConfig, GoosePublisher
from app.goose.subscriber import GooseSubscriber, parse_app_id
from app.model.substation import FaultType, SubstationState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

state = SubstationState()
publisher: GoosePublisher | None = None
subscriber: GooseSubscriber | None = None
ws_clients: set[WebSocket] = set()
_state_lock = threading.Lock()
_goose_message_log: list[dict] = []
_subscribe_message_log: list[dict] = []
_MAX_MESSAGE_LOG = 100


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes")


def _build_publisher() -> GoosePublisher:
    ied_name = os.environ.get("GOOSE_IED_NAME", "DEMO_IED")
    simulation = _env_bool("GOOSE_SIMULATION_MODE", False)
    transport = os.environ.get("GOOSE_TRANSPORT") or ("udp" if simulation else "both")
    config = GooseConfig(
        interface=os.environ.get("GOOSE_INTERFACE", "eth0"),
        app_id=int(os.environ.get("GOOSE_APP_ID", "0x0001"), 0),
        src_mac=os.environ.get("GOOSE_SRC_MAC", "00:30:A7:00:01:01"),
        gocb_ref=os.environ.get("GOOSE_GOCB_REF", f"{ied_name}/LLN0$GO$GcbDemo"),
        dat_set=os.environ.get("GOOSE_DATASET", f"{ied_name}/LLN0$dsGooseDemo"),
        go_id=os.environ.get("GOOSE_GO_ID", f"{ied_name}_GOOSE"),
        conf_rev=int(os.environ.get("GOOSE_CONF_REV", "1")),
        time_allowed_to_live_ms=int(os.environ.get("GOOSE_TTL_MS", "5000")),
        min_interval_ms=int(os.environ.get("GOOSE_MIN_INTERVAL_MS", "100")),
        simulation_mode=simulation,
        transport=transport,
        udp_group=os.environ.get("GOOSE_UDP_GROUP", "239.118.50.1"),
        udp_port=int(os.environ.get("GOOSE_UDP_PORT", "61850")),
        ied_name=ied_name,
    )
    pub = GoosePublisher(config=config)

    def on_publish(payload: dict) -> None:
        detail = payload.get("detail")
        with _state_lock:
            state.goose_stats = {k: v for k, v in payload.items() if k != "detail"}
            if detail:
                _goose_message_log.insert(0, detail)
                del _goose_message_log[_MAX_MESSAGE_LOG:]
        if main_loop:
            asyncio.run_coroutine_threadsafe(broadcast_state(), main_loop)

    pub.set_on_publish(on_publish)
    return pub


def _build_subscriber(pub: GoosePublisher) -> GooseSubscriber:
    own_app = pub.config.app_id
    default_peer = 0x0002 if own_app == 0x0001 else 0x0001
    peer_app = parse_app_id(os.environ.get("GOOSE_SUBSCRIBE_APP_ID", hex(default_peer)))
    sub = GooseSubscriber(
        interface=pub.config.interface,
        app_id=peer_app,
        own_src_mac=pub.config.src_mac,
        own_gocb_ref=pub.config.gocb_ref,
        transport=pub.config.transport,
        udp_group=pub.config.udp_group,
        udp_port=pub.config.udp_port,
    )

    def on_message(detail: dict) -> None:
        with _state_lock:
            _subscribe_message_log.insert(0, detail)
            del _subscribe_message_log[_MAX_MESSAGE_LOG:]
        if main_loop:
            asyncio.run_coroutine_threadsafe(broadcast_state(), main_loop)

    sub.set_on_message(on_message)
    return sub


main_loop: asyncio.AbstractEventLoop | None = None


async def broadcast_state() -> None:
    payload = get_state_dict()
    dead: list[WebSocket] = []
    for ws in ws_clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)


def sync_publisher_dataset(trigger: bool = False) -> dict | None:
    global publisher
    if publisher is None:
        return None
    with _state_lock:
        dataset = state.build_goose_dataset()
        running = state.publisher_running
        simulation = publisher.config.simulation_mode
    # Publish outside state lock – on_publish callback also acquires _state_lock
    publisher.set_dataset(dataset)
    if trigger and (running or simulation):
        return publisher.trigger_state_change()
    return None


def _slim_log(entries: list[dict]) -> list[dict]:
    log = []
    for i, entry in enumerate(entries):
        item = dict(entry)
        if i > 0 and "frame_hex" in item:
            item["frame_hex"] = None
        log.append(item)
    return log


def get_state_dict() -> dict:
    with _state_lock:
        data = state.to_dict()
        data["goose_message_log"] = _slim_log(_goose_message_log)
        data["latest_goose_message"] = _goose_message_log[0] if _goose_message_log else None
        data["subscribe_message_log"] = _slim_log(_subscribe_message_log)
        if publisher:
            data["ied_name"] = publisher.config.ied_name
            data["goose_config"] = {
                "interface": publisher.config.interface,
                "app_id": f"0x{publisher.config.app_id:04X}",
                "dst_mac": publisher.dst_mac,
                "src_mac": publisher.config.src_mac,
                "gocb_ref": publisher.config.gocb_ref,
                "dat_set": publisher.config.dat_set,
                "go_id": publisher.config.go_id,
                "simulation_mode": publisher.config.simulation_mode,
                "transport": publisher.config.transport,
                "udp_group": publisher.config.udp_group,
                "udp_port": publisher.config.udp_port,
            }
        if subscriber:
            data["subscriber"] = subscriber.snapshot()
        return data


_measurements_task: asyncio.Task | None = None
_MEASUREMENTS_INTERVAL_S = 0.5


async def _measurements_loop() -> None:
    """Periodically update V/I/P and push live readings to clients and GOOSE dataset."""
    while True:
        try:
            with _state_lock:
                state.update_live_measurements()
                dataset = state.build_goose_dataset()
                running = state.publisher_running

            if publisher and running:
                publisher.set_dataset(dataset)

            if ws_clients:
                await broadcast_state()
        except Exception:
            logger.exception("Measurements loop error")
        await asyncio.sleep(_MEASUREMENTS_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop, publisher, subscriber, _measurements_task
    main_loop = asyncio.get_running_loop()
    publisher = _build_publisher()
    subscriber = _build_subscriber(publisher)
    with _state_lock:
        state.update_live_measurements()
        publisher.set_dataset(state.build_goose_dataset())
    if _env_bool("GOOSE_SUBSCRIBE_AUTO_START", True):
        try:
            subscriber.start()
        except Exception:
            logger.exception("GOOSE subscriber failed to auto-start")
    _measurements_task = asyncio.create_task(_measurements_loop())
    logger.info("GOOSE IED Simulator ready (%s)", publisher.config.ied_name)
    yield
    if _measurements_task:
        _measurements_task.cancel()
        try:
            await _measurements_task
        except asyncio.CancelledError:
            pass
    if publisher:
        publisher.stop()
    if subscriber:
        subscriber.stop()


app = FastAPI(
    title="IEC 61850 GOOSE IED Simulator",
    description="Simulates an IED publishing GOOSE messages with configurable logical nodes",
    version="1.0.0",
    lifespan=lifespan,
)


class AddLNRequest(BaseModel):
    ln_key: str


class AttributeToggleRequest(BaseModel):
    ln_key: str
    da_name: str
    enabled: bool


class FaultRequest(BaseModel):
    fault_type: str = "none"


class GooseConfigUpdate(BaseModel):
    interface: str | None = None
    app_id: str | None = None
    min_interval_ms: int | None = Field(None, ge=20, le=10000)


@app.get("/api/state")
async def api_state():
    return get_state_dict()


@app.post("/api/publisher/start")
async def start_publisher():
    global publisher
    if publisher is None:
        raise HTTPException(500, "Publisher not initialized")
    with _state_lock:
        publisher.set_dataset(state.build_goose_dataset())
        publisher.start()
        state.publisher_running = True
    await broadcast_state()
    return {"status": "started"}


@app.post("/api/publisher/stop")
async def stop_publisher():
    global publisher
    if publisher is None:
        raise HTTPException(500, "Publisher not initialized")
    publisher.stop()
    with _state_lock:
        state.publisher_running = False
    await broadcast_state()
    return {"status": "stopped"}


class SubscribeRequest(BaseModel):
    app_id: str | None = None


@app.post("/api/subscriber/start")
async def start_subscriber(req: SubscribeRequest = SubscribeRequest()):
    global subscriber
    if subscriber is None:
        raise HTTPException(500, "Subscriber not initialized")
    if req.app_id:
        subscriber.configure(app_id=parse_app_id(req.app_id))
    if subscriber.running:
        subscriber.stop()
    try:
        subscriber.start()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    await broadcast_state()
    return {"status": "started", "subscriber": subscriber.snapshot()}


@app.post("/api/subscriber/stop")
async def stop_subscriber():
    global subscriber
    if subscriber is None:
        raise HTTPException(500, "Subscriber not initialized")
    subscriber.stop()
    await broadcast_state()
    return {"status": "stopped"}


@app.post("/api/goose/messages/clear")
async def clear_goose_messages():
    global _goose_message_log
    with _state_lock:
        _goose_message_log.clear()
    await broadcast_state()
    return {"status": "cleared"}


@app.post("/api/goose/subscribe/messages/clear")
async def clear_subscribe_messages():
    global _subscribe_message_log
    with _state_lock:
        _subscribe_message_log.clear()
    await broadcast_state()
    return {"status": "cleared"}


@app.post("/api/publisher/publish")
async def publish_once():
    if publisher is None:
        raise HTTPException(500, "Publisher not initialized")
    sync_publisher_dataset(trigger=True)
    await broadcast_state()
    return {"status": "published"}


@app.post("/api/logical-nodes/add")
async def add_logical_node(req: AddLNRequest):
    with _state_lock:
        if not state.add_logical_node(req.ln_key):
            raise HTTPException(400, f"Cannot add logical node: {req.ln_key}")
    sync_publisher_dataset(trigger=True)
    await broadcast_state()
    return {"status": "added", "ln_key": req.ln_key}


@app.post("/api/logical-nodes/remove")
async def remove_logical_node(req: AddLNRequest):
    with _state_lock:
        if not state.remove_logical_node(req.ln_key):
            raise HTTPException(400, f"Cannot remove logical node: {req.ln_key}")
    sync_publisher_dataset(trigger=True)
    await broadcast_state()
    return {"status": "removed", "ln_key": req.ln_key}


@app.post("/api/logical-nodes/attribute")
async def toggle_attribute(req: AttributeToggleRequest):
    with _state_lock:
        if not state.set_attribute_enabled(req.ln_key, req.da_name, req.enabled):
            raise HTTPException(400, "Attribute toggle failed")
    sync_publisher_dataset(trigger=True)
    await broadcast_state()
    return {"status": "updated"}


@app.post("/api/breaker/toggle")
async def toggle_breaker():
    with _state_lock:
        state.toggle_breaker()
    sync_publisher_dataset(trigger=True)
    await broadcast_state()
    return {"breaker_state": state.breaker_state.value}


@app.post("/api/fault/apply")
async def apply_fault(req: FaultRequest):
    try:
        fault = FaultType(req.fault_type)
    except ValueError as exc:
        raise HTTPException(400, f"Unknown fault type: {req.fault_type}") from exc
    with _state_lock:
        state.apply_fault(fault)
    sync_publisher_dataset(trigger=True)
    await broadcast_state()
    return {"active_fault": state.active_fault.value}


@app.post("/api/fault/clear")
async def clear_fault():
    with _state_lock:
        state.apply_normal_state()
    sync_publisher_dataset(trigger=True)
    await broadcast_state()
    return {"active_fault": "none"}


@app.patch("/api/goose/config")
async def update_goose_config(req: GooseConfigUpdate):
    global publisher
    if publisher is None:
        raise HTTPException(500, "Publisher not initialized")
    was_running = state.publisher_running
    if was_running:
        publisher.stop()
    if req.interface:
        publisher.config.interface = req.interface
    if req.app_id:
        publisher.config.app_id = int(req.app_id, 0)
    if req.min_interval_ms:
        publisher.config.min_interval_ms = req.min_interval_ms
    if was_running:
        publisher.start()
    await broadcast_state()
    return get_state_dict()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        await ws.send_json(get_state_dict())
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")
