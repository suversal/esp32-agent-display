"""Exercise a >4KiB device snapshot and overflow count using temporary sessions."""
import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path
import aiohttp
from bridge.config import load_config

async def run(url, hold):
    config = load_config(Path.home() / ".config/agent-display/config.toml")
    run_id = uuid.uuid4().hex[:8]
    sessions = [("容量测试" * 50 + "-" + run_id + f"-{i}",
                 "turn_start" if i < 3 else "session_start") for i in range(5)]
    async with aiohttp.ClientSession() as client:
        async def state():
            async with client.get(url + "/state") as response:
                response.raise_for_status()
                return await response.json()
        async def post(session, kind):
            payload = dict(agent="codex", session_id=session, project="中文容量测试" * 30,
                           detail="测试内容" * 40, kind=kind, hook_ts=time.time_ns() // 1000)
            async with client.post(url + "/debug/simulate", json=payload) as response:
                response.raise_for_status()
        before = await state()
        before_count = len(before["snapshot"]["sessions"])
        waiting = any(s["state"] == "waiting" for s in before["snapshot"]["sessions"])
        print(json.dumps({"before_sessions": before_count, "alert_cleared": before["snapshot"]["alert"] is None,
                          "waiting_retained": waiting}), flush=True)
        try:
            for session, kind in sessions:
                await post(session, kind)
            await asyncio.sleep(1)
            async with client.ws_connect(url.replace("http://", "ws://") + "/ws", params={"token": config.token}) as socket:
                message = await socket.receive(timeout=3)
                snapshot = json.loads(message.data)
                frame_bytes = len(message.data.encode())
                assert snapshot["total_sessions"] == before_count + 5
                assert len(snapshot["sessions"]) == 4
                assert frame_bytes > 4096, frame_bytes
                print(json.dumps({"device_frame_bytes": frame_bytes, "visible_cards": 4,
                                  "total_sessions": snapshot["total_sessions"]}), flush=True)
            # Leave time for the physical device's independent WebSocket to receive it.
            await asyncio.sleep(hold)
        finally:
            for session, _ in sessions:
                await post(session, "session_end")
            await asyncio.sleep(1)
            after = await state()
            assert len(after["snapshot"]["sessions"]) == before_count
            print("PAYLOAD_CHECK_OK temporary sessions removed", flush=True)

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8787")
parser.add_argument("--hold", type=float, default=8)
args = parser.parse_args()
asyncio.run(run(args.url, args.hold))
