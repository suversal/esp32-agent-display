#!/usr/bin/env python3
"""Read-only real Codex CLI smoke test; prints no raw client payloads."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import tempfile
import time
import tomllib
from pathlib import Path

import aiohttp

from bridge.privacy import redact, safe_text


async def verify(cli: str, timeout: int) -> dict:
    config = tomllib.loads((Path.home() / ".config/agent-display/config.toml").read_text())
    user_config = tomllib.loads((Path.home() / ".codex/config.toml").read_text())
    base = f"http://127.0.0.1:{config.get('port', 8787)}"
    with tempfile.TemporaryDirectory(prefix="codex-check-") as directory:
        root = Path(directory)
        fixture = root / "fixture.txt"
        fixture.write_text("BRIDGE_OK\n")
        command = [cli, "--no-daemon", "exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only", "--json", "--color", "never", "-C", str(root)]
        for name in user_config.get("mcp_servers", {}):
            if "." not in name:
                command.extend(["-c", "mcp_servers." + name + ".enabled=false"])
        for name in user_config.get("plugins", {}):
            if "." not in name:
                command.extend(["-c", "plugins." + name + ".enabled=false"])
        command.append(f"This is a read-only status-display smoke test. Use exec_command exactly once to run a Python command that reads {fixture}, prints its content and then sleeps for 4 seconds. After the tool finishes, reply with only BRIDGE_OK. Do not read other files or use other tools.")
        observed = []
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(base + "/ws", params={"token": config["token"]}) as socket:
                await socket.receive_json(timeout=3)
                async def observe():
                    async for message in socket:
                        if message.type != aiohttp.WSMsgType.TEXT:
                            continue
                        snapshot = json.loads(message.data)
                        for item in snapshot.get("sessions", []):
                            if item["agent"] == "codex" and item["project"] == root.name:
                                record = {"state": item["state"], "detail": item["detail"]}
                                if record not in observed:
                                    observed.append(record)
                watching = asyncio.create_task(observe())
                started = time.monotonic()
                process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
                exchange = asyncio.create_task(process.communicate())
                timed_out = False
                try:
                    stdout, stderr = await asyncio.wait_for(asyncio.shield(exchange), timeout)
                except TimeoutError:
                    timed_out = True
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        stdout, stderr = await asyncio.wait_for(asyncio.shield(exchange), 5)
                    except TimeoutError:
                        os.killpg(process.pid, signal.SIGKILL)
                        stdout, stderr = await exchange
                await asyncio.sleep(.6)
                watching.cancel()
                try:
                    await watching
                except asyncio.CancelledError:
                    pass
                records = []
                for line in stdout.splitlines():
                    try:
                        record = json.loads(line)
                        if isinstance(record, dict):
                            records.append(record)
                    except (ValueError, UnicodeError):
                        pass
                items = [record.get("item", {}) for record in records if record.get("type") == "item.completed"]
                return {
                    "cli_exit_code": process.returncode, "timed_out": timed_out,
                    "duration_seconds": round(time.monotonic() - started, 2),
                    "fixture_reply_confirmed": any(item.get("type") == "agent_message" and item.get("text", "").strip() == "BRIDGE_OK" for item in items),
                    "command_completed": any(item.get("type") == "command_execution" and item.get("exit_code") == 0 for item in items),
                    "device_snapshots": observed,
                    "event_types": sorted({record.get("type", "") for record in records}),
                    "stderr_bytes": len(stderr),
                    "error_summary": safe_text(redact(stderr.decode(errors="replace")), 400) if process.returncode else "",
                }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", default="/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex")
    parser.add_argument("--timeout", type=int, default=75)
    args = parser.parse_args()
    report = asyncio.run(verify(args.cli, args.timeout))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["cli_exit_code"] != 0 or not report["fixture_reply_confirmed"] or not report["device_snapshots"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
