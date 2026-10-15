import asyncio
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web

from bridge.config import Config
from bridge.server import SERVICE, create_app, local_request
from bridge.vibe import APPLE_EPOCH, VibeCache


RELAY = Path(__file__).resolve().parents[1] / "hook/agent-display-hook"


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config = Config(
            token="test-token-which-is-not-a-real-secret", port=0, quiet_hours="",
            reorder_window_ms=30, state_path=str(Path(self.directory.name) / "state.json"),
            vibe_island_path="",
        )
        self.client = TestClient(TestServer(create_app(self.config)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.directory.cleanup()

    async def wait_for(self, predicate):
        deadline = asyncio.get_running_loop().time() + 3
        while not predicate():
            if asyncio.get_running_loop().time() > deadline:
                self.fail("bridge event did not arrive within three seconds")
            await asyncio.sleep(0.02)

    @property
    def engine(self):
        return self.client.app[SERVICE].engine

    async def post(self, name, **values):
        payload = dict(session_id="live", cwd="/tmp/blog", prompt_id="turn", hook_event_name=name)
        payload.update(values)
        async with self.client.post("/hook/claude-code", json=payload) as response:
            self.assertEqual(response.status, 204)

    async def wait_session(self, state):
        await self.wait_for(lambda: "claude-code:live" in self.engine.sessions and self.engine.sessions["claude-code:live"].state == state)

    async def read_snapshot(self, socket, predicate):
        async with asyncio.timeout(3):
            while True:
                snapshot = await socket.receive_json()
                if predicate(snapshot):
                    return snapshot

    async def test_hook_and_websocket_ack_complete_round_trip(self):
        socket = await self.client.ws_connect("/ws?token=" + self.config.token)
        first = await socket.receive_json()
        self.assertEqual(first["current_sound_seq"], 0)
        await self.post("UserPromptSubmit")
        await self.post("PreToolUse", tool_use_id="tool", tool_name="Bash", tool_input={"command": "sleep 150"})
        await self.post("PermissionRequest", tool_name="Bash", tool_input={"command": "sleep 150"})
        snapshot = await self.read_snapshot(socket, lambda item: item["alert"] is not None)
        self.assertEqual(snapshot["alert"]["sound"], "urgent")
        self.assertNotIn("sleep 150", json.dumps(snapshot))
        await socket.send_json({"type": "ack", "alert_id": snapshot["alert"]["alert_id"]})
        await self.read_snapshot(socket, lambda item: item["alert"] is None and bool(item["sessions"]))
        self.assertEqual(self.engine.sessions["claude-code:live"].state, "waiting")
        await self.post("PostToolUse", tool_use_id="tool", tool_name="Bash", tool_input={"command": "sleep 150"})
        await self.wait_session("running")
        await self.post("Stop")
        await self.wait_session("done")
        await socket.close()

    async def test_wrong_token_and_non_local_routes_are_rejected(self):
        async with self.client.get("/ws?token=wrong") as response:
            self.assertEqual(response.status, 403)
        with patch("bridge.server.local_request", return_value=False):
            for method, path in (("GET", "/state"), ("POST", "/hook/claude-code"), ("POST", "/debug/simulate")):
                async with self.client.request(method, path, json={}) as response:
                    self.assertEqual(response.status, 403)

    async def test_codex_review_hooks_remain_silent_in_device_snapshots(self):
        socket = await self.client.ws_connect("/ws?token=" + self.config.token)
        await socket.receive_json()
        stamp = time.time_ns() // 1000
        events = [
            ("UserPromptSubmit", {}),
            ("PreToolUse", {"tool_use_id": "cx-call", "tool_name": "Bash", "tool_input": {"command": "true"}}),
            ("PermissionRequest", {"tool_name": "Bash", "tool_input": {"command": "true", "description": "automatic review"}}),
            ("PostToolUse", {"tool_use_id": "cx-call", "tool_name": "Bash", "tool_input": {"command": "true"}}),
        ]
        for i, (name, values) in enumerate(events):
            payload = dict(session_id="cx-auto", cwd="/tmp/project", turn_id="cx-turn", hook_event_name=name, **values)
            async with self.client.post("/hook/codex", json=payload, headers={"X-Hook-Ts": str((stamp + i) / 1_000_000)}) as response:
                self.assertEqual(response.status, 204)
        await self.wait_for(lambda: self.engine.stats["kind.tool_end"] == 1)
        snapshot = await self.read_snapshot(socket, lambda item: bool(item["sessions"]))
        self.assertEqual(snapshot["sessions"][0]["state"], "running")
        self.assertEqual(snapshot["sessions"][0]["detail"], "执行命令")
        self.assertEqual(snapshot["current_sound_seq"], 0)
        self.assertIsNone(snapshot["alert"])
        self.assertEqual(self.engine.stats["kind.permission_check"], 1)
        self.assertFalse(self.engine.sessions["codex:cx-auto"].pending_waits)
        await socket.close()

    async def test_device_snapshot_is_bounded_and_preserves_total_count(self):
        stamp = time.time_ns() // 1000
        for i in range(6):
            event = dict(agent="codex", session_id=f"bounded-{i}", project="项目" * 100,
                         kind="turn_start", hook_ts=stamp + i)
            async with self.client.post("/debug/simulate", json=event) as response:
                self.assertEqual(response.status, 204)
        await self.wait_for(lambda: len(self.engine.sessions) == 6)
        socket = await self.client.ws_connect("/ws?token=" + self.config.token)
        snapshot = await socket.receive_json()
        self.assertEqual(snapshot["total_sessions"], 6)
        self.assertEqual(len(snapshot["sessions"]), 4)
        self.assertLess(len(json.dumps(snapshot).encode()), 65536)
        async with self.client.get("/state") as response:
            self.assertEqual(len((await response.json())["snapshot"]["sessions"]), 6)
        await socket.close()

    async def test_shutdown_closes_active_device_before_waiting_for_handlers(self):
        socket = await self.client.ws_connect("/ws?token=" + self.config.token)
        await socket.receive_json()
        receiving = asyncio.create_task(socket.receive())
        await asyncio.wait_for(self.client.server.close(), 2)
        await asyncio.wait_for(receiving, 1)
        self.assertTrue(socket.closed)

    async def test_short_completion_reaches_websocket_once_per_turn(self):
        socket = await self.client.ws_connect("/ws?token=" + self.config.token)
        await socket.receive_json()  # Establish the device's silent baseline first.
        await self.post("UserPromptSubmit")
        await self.wait_session("running")
        await self.post("Stop")
        page = await self.read_snapshot(socket, lambda s: s["alert"] is not None)
        self.assertEqual(page["alert"]["kind"], "done")
        self.assertEqual(page["alert"]["sound"], "soft")
        self.assertEqual(page["current_sound_seq"], 1)
        self.assertLess(page["sessions"][0]["turn_duration_seconds"], 60)
        await self.post("Stop")
        await self.wait_for(lambda: self.engine.stats["closed_turn_dropped"] == 1)
        self.assertEqual(self.engine.sound_seq, 1)
        await self.post("UserPromptSubmit", prompt_id="second")
        await self.wait_session("running")
        await self.post("Stop", prompt_id="second")
        page = await self.read_snapshot(socket, lambda s: s["current_sound_seq"] == 2)
        self.assertEqual(page["alert"]["sound"], "soft")
        await socket.close()

    async def test_paged_device_can_reach_hidden_sessions_without_changing_alerts(self):
        stamp=time.time_ns()//1000
        for i in range(10):
            async with self.client.post('/debug/simulate',json=dict(agent='codex',session_id=f'paged-{i}',project=f'repo-{i}',kind='turn_start',hook_ts=stamp+i)) as response:
                self.assertEqual(response.status,204)
        await self.wait_for(lambda:len(self.engine.sessions)==10)
        socket=await self.client.ws_connect('/ws?token='+self.config.token)
        self.assertEqual(len((await socket.receive_json())['sessions']),4) # Older firmware compatibility.
        await socket.send_json(dict(type='hello',fw='0.5.0',paging=True,auto_page=True))
        page=await self.read_snapshot(socket,lambda s:'page' in s)
        self.assertEqual(page['page']['count'],3) # Plain status pages have four cards.
        seen={r['key'] for r in page['sessions']}
        for index in (1,2):
            await socket.send_json(dict(type='page',action='next'))
            page=await self.read_snapshot(socket,lambda s:s.get('page',{}).get('index')==index)
            seen.update(r['key'] for r in page['sessions'])
        self.assertEqual(len(seen),10)
        self.assertEqual(page['current_sound_seq'],0)
        self.assertIsNone(page['alert'])
        await socket.send_json(dict(type='page',action='toggle_auto'))
        await self.read_snapshot(socket,lambda s:s.get('page',{}).get('auto') is False)
        pager=next(iter(self.client.app[SERVICE].pagers.values()))
        self.assertFalse(pager.auto)
        await socket.send_json(dict(type='page',action='toggle_auto'))
        await self.read_snapshot(socket,lambda s:s.get('page',{}).get('auto') is True)
        pager.hold_until=0
        pager.next_at=time.monotonic()-1
        page=await self.read_snapshot(socket,lambda s:s.get('page',{}).get('index')==0)
        self.assertEqual(page['current_sound_seq'],0)
        async with self.client.get('/state') as response:
            debug=(await response.json())['device_pages'][0]
            self.assertEqual(debug['auto_rotations'],1)
        hidden_key=pager.order[-1]
        async with self.client.post('/debug/simulate',json=dict(agent='codex',session_id=hidden_key.split(':',1)[1],kind='waiting',wait_kind='question',hook_ts=time.time_ns()//1000)) as response:
            self.assertEqual(response.status,204)
        urgent=await self.read_snapshot(socket,lambda s:s.get('page',{}).get('waiting') is True)
        self.assertIn(hidden_key,[row['key'] for row in urgent['sessions']])
        focused=pager.index
        await socket.send_json(dict(type='page',action='next'))
        await asyncio.sleep(.1)
        self.assertEqual(pager.index,focused)
        self.assertTrue(self.engine.sessions[hidden_key].pending_waits)
        await socket.send_json(dict(type='ack',alert_id=urgent['alert']['alert_id']))
        await self.read_snapshot(socket,lambda s:s.get('page',{}).get('waiting') is False and s['alert'] is None)
        self.assertEqual(self.engine.sessions[hidden_key].state,'waiting')
        await socket.close()
        await self.wait_for(lambda:not self.client.app[SERVICE].pagers)

    async def test_manual_sound_is_local_and_does_not_change_alert_state(self):
        socket = await self.client.ws_connect("/ws?token=" + self.config.token)
        await socket.receive_json()
        await socket.send_json({"type": "hello", "fw": "0.5.0"})
        await self.wait_for(lambda: bool(self.client.app[SERVICE].device_versions))
        before = self.engine.export()
        async with self.client.post("/debug/sound", json={"sound": "urgent"}) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["delivered"], 1)
        message = await socket.receive_json()
        self.assertEqual(message["type"], "sound_test")
        self.assertEqual(message["sound"], "urgent")
        after = self.engine.export()
        before.pop("saved_at")
        after.pop("saved_at")
        self.assertEqual(after, before)
        async with self.client.post("/debug/sound", json={"sound": "invalid"}) as response:
            self.assertEqual(response.status, 400)
        with patch("bridge.server.local_request", return_value=False):
            async with self.client.post("/debug/sound", json={"sound": "soft"}) as response:
                self.assertEqual(response.status, 403)
        await socket.close()

    async def test_manual_sound_excludes_old_firmware(self):
        socket = await self.client.ws_connect("/ws?token=" + self.config.token)
        await socket.receive_json()
        await socket.send_json({"type": "hello", "fw": "0.1.0"})
        await self.wait_for(lambda: bool(self.client.app[SERVICE].device_versions))
        async with self.client.post("/debug/sound", json={"sound": "soft"}) as response:
            self.assertEqual((await response.json())["delivered"], 0)
        await socket.close()

    async def test_content_firmware_hello_and_manual_sound_compatibility(self):
        socket = await self.client.ws_connect("/ws?token=" + self.config.token)
        await socket.receive_json()
        await socket.send_json({"type": "hello", "fw": "0.3.0"})
        await self.wait_for(lambda: bool(self.client.app[SERVICE].device_versions))
        async with self.client.get("/state") as response:
            self.assertEqual((await response.json())["device_connections"], {"active": 1, "firmware": ["0.3.0"]})
        async with self.client.post("/debug/sound", json={"sound": "soft"}) as response:
            self.assertEqual((await response.json())["delivered"], 1)
        self.assertEqual((await socket.receive_json())["type"], "sound_test")
        await socket.close()

    async def test_vibe_content_reaches_device_but_is_not_persisted(self):
        cache = Path(self.directory.name) / "vibe.json"
        cache.write_text(json.dumps({"codex-content": dict(
            source="codex", cwd="/tmp/project", status="processing",
            lastActivityAt=time.time() - APPLE_EPOCH,
            customTitle="检查屏幕内容", lastUserMessage="USER PREVIEW token=SECRET",
            lastAssistantMessage="ASSISTANT PREVIEW", currentTool="Bash",
        )}))
        service = self.client.app[SERVICE]
        service.vibe = VibeCache(str(cache))
        socket = await self.client.ws_connect("/ws?token=" + self.config.token)
        snapshot = await self.read_snapshot(socket, lambda s: bool(s["sessions"]))
        card = snapshot["sessions"][0]
        self.assertEqual(card["title"], "检查屏幕内容")
        self.assertEqual(card["current_tool"], "Bash")
        self.assertEqual(card["assistant_preview"], "ASSISTANT PREVIEW")
        self.assertNotIn("SECRET", json.dumps(snapshot))
        self.assertIsNone(snapshot["alert"])
        await service.persist()
        persisted = Path(self.config.state_path).read_text()
        self.assertNotIn("USER PREVIEW", persisted)
        self.assertNotIn("ASSISTANT PREVIEW", persisted)
        self.assertEqual(json.loads(persisted)["sessions"], {})
        await socket.close()

    async def test_invalid_hook_is_silent_and_server_survives(self):
        async with self.client.post("/hook/claude-code", data="{broken", headers={"Content-Type": "application/json"}) as response:
            self.assertEqual(response.status, 204)
        async with self.client.post("/hook/unknown", json={}) as response:
            self.assertEqual(response.status, 204)
        async with self.client.get("/state") as response:
            self.assertEqual(response.status, 200)
            data = await response.json()
            self.assertEqual(data["stats"]["invalid_hook"], 1)
            self.assertEqual(data["stats"]["ignored_hook"], 1)

    async def test_gemini_idless_native_payload_round_trip_and_safe_summary(self):
        socket = await self.client.ws_connect("/ws?token=" + self.config.token)
        await socket.receive_json()
        async def relay(name, **values):
            payload = dict(session_id="gemini-native", cwd="/private/project", hook_event_name=name)
            payload.update(values)
            process = await asyncio.create_subprocess_exec(
                "/bin/zsh", str(RELAY), "gemini",
                env=dict(os.environ, AGENT_DISPLAY_PORT=str(self.client.server.port)),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(json.dumps(payload).encode()), 2)
            self.assertEqual(json.loads(stdout), {})
            self.assertEqual(stderr, b"")
            self.assertEqual(process.returncode, 0)
        await relay("BeforeAgent", prompt="PRIVATE PROMPT")
        await self.read_snapshot(socket, lambda s: bool(s["sessions"]))
        arguments = {"absolute_path": "/private/customer/app.py"}
        await relay("BeforeTool", tool_name="read_file", tool_input=arguments)
        snapshot = await self.read_snapshot(socket, lambda s: s["sessions"][0]["detail"] == "读取 app.py")
        self.assertEqual(snapshot["sessions"][0]["agent"], "gemini")
        self.assertNotIn("customer", json.dumps(snapshot))
        await relay("Notification", notification_type="ToolPermission", details={"tool_name": "read_file", "tool_input": arguments})
        await self.read_snapshot(socket, lambda s: s["sessions"][0]["state"] == "waiting")
        await relay("AfterTool", tool_name="read_file", tool_input=arguments, tool_response={"content": "PRIVATE FILE CONTENT"})
        snapshot = await self.read_snapshot(socket, lambda s: s["sessions"][0]["state"] == "running")
        self.assertIsNone(snapshot["alert"])
        await relay("AfterAgent", prompt="PRIVATE PROMPT", prompt_response="PRIVATE ANSWER")
        snapshot = await self.read_snapshot(socket, lambda s: s["sessions"][0]["state"] == "done")
        self.assertEqual(snapshot["sessions"][0]["detail"], "读取 app.py")
        self.assertNotIn("PRIVATE", json.dumps(self.engine.debug_state()))
        await socket.close()

    async def test_oversized_hook_is_discarded(self):
        async with self.client.post("/hook/claude-code", data=io.BytesIO(b"x" * 1_100_000), headers={"Content-Type": "application/json"}) as response:
            self.assertEqual(response.status, 204)
        self.assertEqual(self.engine.stats["invalid_hook"], 1)
        self.assertFalse(self.engine.sessions)

    async def test_reorder_buffer_applies_turn_events_in_timestamp_order(self):
        stamp = time.time_ns() // 1000
        events = [
            dict(agent="claude-code", session_id="order", project="blog", turn_id="t", kind="turn_end", hook_ts=stamp + 2),
            dict(agent="claude-code", session_id="order", project="blog", turn_id="t", kind="tool_start", tool_use_id="tool", hook_ts=stamp + 1),
            dict(agent="claude-code", session_id="order", project="blog", turn_id="t", kind="turn_start", hook_ts=stamp),
        ]
        for event in events:
            async with self.client.post("/debug/simulate", json=event) as response:
                self.assertEqual(response.status, 204)
        await self.wait_for(lambda: "claude-code:order" in self.engine.sessions)
        self.assertEqual(self.engine.sessions["claude-code:order"].state, "done")

    async def test_persist_restart_websocket_restores_silent_stale_wait(self):
        await self.post("UserPromptSubmit")
        await self.post("PreToolUse", tool_use_id="tool", tool_name="Bash", tool_input={"command": "test"})
        await self.post("PermissionRequest", tool_name="Bash", tool_input={"command": "test"})
        await self.wait_session("waiting")
        await self.client.app[SERVICE].persist()
        await self.client.close()
        self.client = TestClient(TestServer(create_app(self.config)))
        await self.client.start_server()
        socket = await self.client.ws_connect("/ws?token=" + self.config.token)
        snapshot = await socket.receive_json()
        self.assertTrue(snapshot["sessions"][0]["stale"])
        self.assertEqual(snapshot["alert"]["sound"], "none")
        self.assertEqual(snapshot["current_sound_seq"], 1)
        await socket.close()

    async def test_real_relay_forwards_large_stdin_and_returns_no_decision(self):
        payload = dict(
            session_id="relay", cwd="/tmp/blog", prompt_id="relay-turn",
            hook_event_name="UserPromptSubmit", prompt="SENSITIVE-TEST-" * 6000,
        )
        environment = dict(os.environ, AGENT_DISPLAY_PORT=str(self.client.server.port))
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            "/bin/zsh", str(RELAY), "claude-code", env=environment,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(json.dumps(payload).encode()), 2)
        elapsed = time.monotonic() - started
        self.assertEqual(process.returncode, 0)
        self.assertEqual(stdout, b"")
        self.assertEqual(stderr, b"")
        self.assertLess(elapsed, 0.5)
        await self.wait_for(lambda: "claude-code:relay" in self.engine.sessions)
        self.assertNotIn("SENSITIVE-TEST", json.dumps(self.engine.debug_state()))

    async def test_relay_with_stopped_bridge_is_fast_and_gemini_output_is_json(self):
        environment = dict(os.environ, AGENT_DISPLAY_PORT="1")
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            "/bin/zsh", str(RELAY), "gemini", env=environment,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(b"{}"), 2)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(json.loads(stdout), {})
        self.assertEqual(stderr, b"")
        self.assertLess(time.monotonic() - started, 0.5)

    async def test_relay_payload_is_not_visible_in_process_arguments(self):
        received, release = asyncio.Event(), asyncio.Event()
        marker = "AGENT_DISPLAY_PRIVATE_PAYLOAD_MARKER_7129"

        async def sink(request):
            body = await request.read()
            self.assertTrue(marker.encode() in body)
            received.set()
            await release.wait()
            return web.Response(status=204)

        app = web.Application()
        app.router.add_post("/hook/claude-code", sink)
        server = TestServer(app)
        await server.start_server()
        try:
            environment = dict(os.environ, AGENT_DISPLAY_PORT=str(server.port))
            process = await asyncio.create_subprocess_exec(
                "/bin/zsh", str(RELAY), "claude-code", env=environment,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await process.communicate(json.dumps({"prompt": marker}).encode())
            await asyncio.wait_for(received.wait(), 2)
            listing = await asyncio.create_subprocess_exec(
                "/bin/ps", "-axo", "args",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            arguments, _ = await listing.communicate()
            self.assertFalse(marker.encode() in arguments, "payload was visible in process arguments")
        finally:
            release.set()
            await server.close()

    def test_peer_address_uses_actual_connection_not_forwarded_header(self):
        self.assertTrue(local_request(SimpleNamespace(remote="127.0.0.1")))
        self.assertTrue(local_request(SimpleNamespace(remote="::1")))
        self.assertFalse(local_request(SimpleNamespace(remote="192.0.2.1")))
        self.assertFalse(local_request(SimpleNamespace(remote=None)))


if __name__ == "__main__":
    unittest.main()
