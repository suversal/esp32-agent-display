from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import logging
import time
import uuid
from contextlib import suppress
from decimal import Decimal, InvalidOperation
from pathlib import Path

from aiohttp import WSMsgType, web

from .config import Config, atomic_write
from .events import Event, normalize, simulated_event
from .paging import Pager
from .state import Engine
from .vibe import VibeCache


LOG = logging.getLogger("agent-display")


def local_request(request: web.Request) -> bool:
    try:
        return ipaddress.ip_address(request.remote or "").is_loopback
    except ValueError:
        return False


class Service:
    def __init__(self, config: Config):
        self.config = config
        self.engine = Engine(config)
        self.vibe = VibeCache(config.vibe_island_path) if config.vibe_island_path else None
        self.content_revision = 0
        self.last_content_refresh = 0.0
        self.connections: set[web.WebSocketResponse] = set()
        self.device_versions: dict[web.WebSocketResponse, str] = {}
        self.pagers: dict[web.WebSocketResponse, Pager] = {}
        self.pending: list[Event] = []
        self.pending_since = 0.0
        self.sequence = 0
        self.task: asyncio.Task | None = None
        self.persisted_revision = -1
        self.sent_revision = -1
        self.last_persist = 0.0
        self.last_snapshot = 0.0
        self.state_path = Path(config.state_path).expanduser()

    async def start(self, app: web.Application) -> None:
        if self.state_path.exists():
            try:
                data = await asyncio.to_thread(self.state_path.read_text, encoding="utf-8")
                self.engine.restore(json.loads(data))
                LOG.info("Restored %d sessions; restored alerts stay silent", len(self.engine.sessions))
            except (OSError, ValueError, TypeError, KeyError):
                self.engine.stats["restore_failed"] += 1
                LOG.warning("Could not restore state; starting with an empty state")
        self.task = asyncio.create_task(self.run())

    async def stop(self, app: web.Application) -> None:
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        self.flush()
        await self.persist()
        # Close active WebSockets before aiohttp waits for request handlers.
        # A stalled peer must not delay every other device's disconnect.
        await asyncio.gather(*(
            asyncio.wait_for(socket.close(code=1001, message=b"bridge stopping"), timeout=3)
            for socket in list(self.connections)
        ), return_exceptions=True)

    def enqueue(self, event: Event) -> bool:
        if len(self.pending) >= 4096:
            self.engine.stats["queue_dropped"] += 1
            return False
        if not self.pending:
            self.pending_since = time.monotonic()
        self.pending.append(event)
        return True

    def flush(self) -> None:
        pending, self.pending = self.pending, []
        for event in sorted(pending, key=lambda item: (item.hook_ts, item.seq)):
            self.engine.apply(event)
            if LOG.isEnabledFor(logging.DEBUG):
                LOG.debug("event agent=%s kind=%s session=%s tool=%s", event.agent, event.kind, event.session_id, event.tool_name)

    async def persist(self) -> None:
        revision = self.engine.revision
        if revision == self.persisted_revision:
            return
        # Serialize before yielding: the write contains a coherent event-loop snapshot.
        text = json.dumps(self.engine.export(), ensure_ascii=False, separators=(",", ":"))
        try:
            await asyncio.to_thread(atomic_write, self.state_path, text)
            self.persisted_revision = revision
        except OSError:
            self.engine.stats["persist_failed"] += 1
            LOG.warning("Could not persist state")

    async def broadcast(self) -> None:
        for socket in list(self.connections):
            try:
                await asyncio.wait_for(socket.send_json(self.device_snapshot(socket)), timeout=0.5)
            except (ConnectionError, RuntimeError, TimeoutError):
                self.connections.discard(socket)
                await socket.close()

    def device_snapshot(self, socket: web.WebSocketResponse | None = None) -> dict:
        snapshot = self.display_snapshot()
        if socket in self.pagers:
            return self.pagers[socket].view(snapshot, time.monotonic())
        snapshot["total_sessions"] = len(snapshot["sessions"])
        snapshot["sessions"] = snapshot["sessions"][:4]
        return snapshot

    def display_snapshot(self) -> dict:
        snapshot = self.engine.snapshot()
        if self.vibe:
            self.vibe.decorate(snapshot, time.time(), self.config.restore_max_age_minutes * 60,
                               self.config.hung_minutes * 60,
                               {key: item.last_event_at for key, item in self.engine.sessions.items()})
        return snapshot

    async def run(self) -> None:
        while True:
            await asyncio.sleep(0.05)
            now = time.monotonic()
            if self.pending and now - self.pending_since >= self.config.reorder_window_ms / 1000:
                self.flush()
            self.engine.tick()
            if self.vibe and now - self.last_content_refresh >= 1:
                if await asyncio.to_thread(self.vibe.refresh):
                    self.content_revision += 1
                self.last_content_refresh = now
            revision = self.engine.revision + self.content_revision
            if revision != self.sent_revision or now - self.last_snapshot >= 30 or any(pager.due(now) for pager in self.pagers.values()):
                await self.broadcast()
                self.sent_revision, self.last_snapshot = revision, now
            if now - self.last_persist >= 1:
                await self.persist()
                self.last_persist = now


SERVICE = web.AppKey("service", Service)


async def hook(request: web.Request) -> web.Response:
    if not local_request(request):
        return web.Response(status=403)
    service = request.app[SERVICE]
    service.sequence += 1
    try:
        payload = await request.json()
        header = request.headers.get("X-Hook-Ts")
        stamp = int(Decimal(header) * 1_000_000) if header else time.time_ns() // 1000
        if stamp <= 0 or stamp > time.time_ns() // 1000 + 60_000_000:
            raise ValueError("invalid timestamp")
        event = normalize(request.match_info["agent"], payload, stamp, service.sequence, service.config)
        if event:
            service.enqueue(event)
        else:
            service.engine.stats["ignored_hook"] += 1
    except (ValueError, TypeError, OverflowError, InvalidOperation, web.HTTPRequestEntityTooLarge):
        service.engine.stats["invalid_hook"] += 1
    return web.Response(status=204)


async def state(request: web.Request) -> web.Response:
    if not local_request(request):
        return web.Response(status=403)
    service = request.app[SERVICE]
    result = service.engine.debug_state()
    result["display_snapshot"] = service.display_snapshot()
    result["device_connections"] = {
        "active": sum(not socket.closed for socket in service.device_versions),
        "firmware": sorted({version for socket, version in service.device_versions.items() if not socket.closed}),
    }
    result["device_pages"] = [dict(pager.status(time.monotonic()), firmware=service.device_versions.get(socket, ""),
                                   auto_rotations=pager.auto_rotations)
                              for socket, pager in service.pagers.items() if not socket.closed]
    return web.json_response(result)


async def simulate(request: web.Request) -> web.Response:
    if not local_request(request):
        return web.Response(status=403)
    service = request.app[SERVICE]
    service.sequence += 1
    try:
        event = simulated_event(await request.json(), service.sequence)
        service.enqueue(event)
    except (ValueError, TypeError, web.HTTPRequestEntityTooLarge):
        return web.json_response({"error": "invalid normalized event"}, status=400)
    return web.Response(status=204)


async def sound_test(request: web.Request) -> web.Response:
    if not local_request(request):
        return web.Response(status=403)
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) != {"sound"} or payload["sound"] not in {"urgent", "soft"}:
            raise ValueError
    except (ValueError, TypeError, web.HTTPRequestEntityTooLarge):
        return web.json_response({"error": "sound must be urgent or soft"}, status=400)
    service = request.app[SERVICE]
    delivered = 0
    # This explicit manual audition does not change quiet hours, sessions, or sound_seq.
    for socket, version in list(service.device_versions.items()):
        if version not in {"0.2.0", "0.3.0", "0.4.0", "0.5.0"} or socket.closed:
            continue
        try:
            await asyncio.wait_for(socket.send_json({
                "type": "sound_test", "sound": payload["sound"], "test_id": uuid.uuid4().hex,
            }), 0.5)
            delivered += 1
        except (ConnectionError, RuntimeError, TimeoutError):
            pass
    return web.json_response({"delivered": delivered, "manual": True})


async def websocket(request: web.Request) -> web.StreamResponse:
    service = request.app[SERVICE]
    token = request.query.get("token", "")
    if not hmac.compare_digest(token.encode(), service.config.token.encode()):
        return web.Response(status=403)
    if len(service.connections) >= 8:
        return web.Response(status=503)
    socket = web.WebSocketResponse(heartbeat=15, max_msg_size=4096)
    await socket.prepare(request)
    service.connections.add(socket)
    try:
        await socket.send_json(service.device_snapshot())
        async for message in socket:
            if message.type != WSMsgType.TEXT:
                continue
            try:
                payload = json.loads(message.data)
                if not isinstance(payload, dict):
                    continue
                if payload.get("type") == "ack":
                    alert_id = payload.get("alert_id")
                    if isinstance(alert_id, str) and len(alert_id) <= 64:
                        service.engine.ack(alert_id)
                elif payload.get("type") == "hello":
                    version = payload.get("fw")
                    if isinstance(version, str) and len(version) <= 16:
                        service.device_versions[socket] = version
                    service.engine.stats["device_messages"] += 1
                    if payload.get("paging") is True:
                        if socket not in service.pagers:
                            service.pagers[socket] = Pager(time.monotonic(), auto=payload.get("auto_page") is not False)
                        await socket.send_json(service.device_snapshot(socket))
                elif payload.get("type") == "page" and socket in service.pagers:
                    pager = service.pagers[socket]
                    pager.sync(service.display_snapshot(), time.monotonic())
                    action = payload.get("action")
                    if pager.request(action, time.monotonic()):
                        service.engine.stats["device_page_requests"] += 1
                        if action == "toggle_auto":
                            service.engine.stats["device_page_pause_toggles"] += 1
                        await socket.send_json(service.device_snapshot(socket))
                elif payload.get("type") == "status":
                    service.engine.stats["device_messages"] += 1
            except (ValueError, TypeError):
                service.engine.stats["invalid_device_message"] += 1
    finally:
        service.connections.discard(socket)
        service.device_versions.pop(socket, None)
        service.pagers.pop(socket, None)
    return socket


def create_app(config: Config) -> web.Application:
    config.validate()
    app = web.Application(client_max_size=1_048_576)
    app[SERVICE] = Service(config)
    app.router.add_post("/hook/{agent}", hook)
    app.router.add_get("/state", state)
    app.router.add_post("/debug/simulate", simulate)
    app.router.add_post("/debug/sound", sound_test)
    app.router.add_get("/ws", websocket)
    app.on_startup.append(app[SERVICE].start)
    app.on_shutdown.append(app[SERVICE].stop)
    return app
