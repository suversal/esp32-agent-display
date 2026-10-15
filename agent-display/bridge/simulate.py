#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import time
import uuid
import re

import aiohttp


async def run(url: str, interval: float, clear: bool = False) -> None:
    if clear:
        async with aiohttp.ClientSession() as client:
            async with client.get(f"{url}/state") as response:
                response.raise_for_status()
                state = await response.json()
            removed = 0
            for session in state["sessions"].values():
                if not re.fullmatch(r"demo-(claude|codex|gemini)(-[0-9a-f]{8})?", session["session_id"]):
                    continue
                if session["agent"] not in {"claude-code", "codex", "gemini"}:
                    continue
                payload = dict(agent=session["agent"], session_id=session["session_id"],
                               kind="session_end", hook_ts=time.time_ns() // 1000)
                async with client.post(f"{url}/debug/simulate", json=payload) as response:
                    response.raise_for_status()
                removed += 1
            await asyncio.sleep(0.7)
            print(f"SIMULATION_CLEARED sessions={removed}")
        return
    # Each run needs fresh identities because ended turns/sessions are tombstoned.
    run_id = uuid.uuid4().hex[:8]
    events = [
        ("claude-code", "demo-claude", "blog", "session_start", {}),
        ("claude-code", "demo-claude", "blog", "turn_start", {"turn_id": "demo-turn"}),
        ("claude-code", "demo-claude", "blog", "tool_start", {"turn_id": "demo-turn", "tool_use_id": "demo-tool", "tool_name": "Bash", "tool_input_fp": "demo-fingerprint", "detail": "执行命令"}),
        ("claude-code", "demo-claude", "blog", "waiting", {"turn_id": "demo-turn", "tool_name": "Bash", "tool_input_fp": "demo-fingerprint", "wait_kind": "permission"}),
        ("codex", "demo-codex", "api-server", "turn_start", {"turn_id": "demo-codex-turn"}),
        ("gemini", "demo-gemini", "notes", "turn_start", {}),
        ("gemini", "demo-gemini", "notes", "turn_end", {}),
    ]
    async with aiohttp.ClientSession() as client:
        for agent, session, project, kind, extra in events:
            payload = dict(agent=agent, session_id=f"{session}-{run_id}", project=project, kind=kind, hook_ts=time.time_ns() // 1000, **extra)
            async with client.post(f"{url}/debug/simulate", json=payload) as response:
                response.raise_for_status()
            print(f"{agent}: {project} → {kind}")
            await asyncio.sleep(interval)
        async with client.get(f"{url}/state") as response:
            response.raise_for_status()
            state = await response.json()
            for session in state["snapshot"]["sessions"]:
                print(f'{session["agent"]}: {session["project"]} / {session["label"]}')


def main() -> None:
    parser = argparse.ArgumentParser(description="向本地 bridge 注入多会话模拟事件")
    parser.add_argument("--url", default="http://127.0.0.1:8787")
    parser.add_argument("--interval", type=float, default=0.4)
    parser.add_argument("--clear", action="store_true", help="仅移除本模拟器创建的 demo 会话")
    args = parser.parse_args()
    asyncio.run(run(args.url, args.interval, args.clear))


if __name__ == "__main__":
    main()
