#!/usr/bin/env python3
"""Check the live bridge with disposable synthetic sessions; never print its token."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
import tomllib
import uuid
from pathlib import Path

import aiohttp


async def check(path: Path) -> dict:
    config = tomllib.loads(path.read_text())
    base = f'http://127.0.0.1:{config.get("port", 8787)}'
    prefix = "runtime-check-" + uuid.uuid4().hex[:12]
    sessions = [("claude-code", prefix + "-claude"), ("codex", prefix + "-codex"), ("gemini", prefix + "-gemini")]
    async with aiohttp.ClientSession() as client:
        async with client.ws_connect(base + "/ws", params={"token": config["token"]}) as socket:
            first = await socket.receive_json(timeout=3)
            if "current_sound_seq" not in first:
                raise ValueError("missing global sound sequence")

            async def post(agent, session, kind, **values):
                payload = dict(
                    agent=agent, session_id=session, project="runtime-check",
                    kind=kind, hook_ts=time.time_ns() // 1000, **values,
                )
                async with client.post(base + "/debug/simulate", json=payload) as response:
                    response.raise_for_status()

            async def receive(predicate):
                async with asyncio.timeout(5):
                    while True:
                        snapshot = await socket.receive_json()
                        subset = [item for item in snapshot["sessions"] if prefix in item["key"]]
                        if predicate(snapshot, subset):
                            return snapshot, subset

            try:
                await post(*sessions[0], "turn_start", turn_id="t")
                await post(*sessions[0], "tool_start", turn_id="t", tool_use_id="x", tool_name="Bash", tool_input_fp="test", detail="执行命令")
                await post(*sessions[0], "waiting", turn_id="t", tool_name="Bash", tool_input_fp="test", wait_kind="permission")
                await post(*sessions[1], "turn_start", turn_id="cx")
                await post(*sessions[2], "turn_start")
                await post(*sessions[2], "turn_end")
                snapshot, subset = await receive(lambda item, rows: len(rows) == 3)
                states = sorted(item["state"] for item in subset)
                if states != ["done", "running", "waiting"]:
                    raise ValueError("incorrect simulated states")
                own_alerts = [
                    item for item in (snapshot["alert"],)
                    if item is not None and prefix in item["session_key"]
                ]
                acknowledged = False
                if own_alerts:
                    await socket.send_json({"type": "ack", "alert_id": own_alerts[0]["alert_id"]})
                    await receive(lambda item, rows: item["alert"] is None or item["alert"]["alert_id"] != own_alerts[0]["alert_id"])
                    acknowledged = True
                return {
                    "http_state": 200, "websocket_connected": True,
                    "simulated_states": states, "ack_round_trip": acknowledged,
                    "global_sound_sequence_present": True,
                }
            finally:
                for agent, session in sessions:
                    await post(agent, session, "session_end")
                await asyncio.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("~/.config/agent-display/config.toml").expanduser())
    args = parser.parse_args()
    try:
        report = asyncio.run(check(args.config))
    except Exception as error:
        print(json.dumps({"runtime_check_error": type(error).__name__}))
        raise SystemExit(1)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
