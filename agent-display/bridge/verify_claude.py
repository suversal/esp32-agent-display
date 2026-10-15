#!/usr/bin/env python3
"""Run a real Claude CLI read-only smoke test with temporary per-session hooks."""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import tempfile
import time
from pathlib import Path

from aiohttp import web

from bridge.config import Config
from bridge.server import SERVICE, create_app
from install_hooks import run as install


async def verify(timeout: int, offline: bool) -> dict:
    cli = shutil.which("claude")
    if not cli:
        raise RuntimeError("本机未安装 Claude Code")
    with tempfile.TemporaryDirectory(prefix="agent-display-claude-") as directory:
        root = Path(directory)
        config = Config(token="isolated-verification-token-only", host="127.0.0.1", port=0, quiet_hours="", reorder_window_ms=50, state_path=str(root / "state.json"), vibe_island_path="")
        app = create_app(config)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        home = root / "temporary-hook-home"
        install("install", home, ["claude-code"], port)
        settings = home / ".claude/settings.json"
        fixture = root / "fixture.txt"
        fixture.write_text("BRIDGE_OK\n")
        if offline:
            await runner.cleanup()
        prompt = f"Use Read once to read {fixture}. Then reply with only BRIDGE_OK. Do not run commands or use other tools."
        command = [
            cli, "--print", "--settings", str(settings),
            "--setting-sources", "", "--strict-mcp-config",
            "--mcp-config", '{"mcpServers":{}}', "--tools", "Read",
            "--no-chrome", "--no-session-persistence", "--max-budget-usd", "0.50",
            "--output-format", "stream-json", "--include-hook-events", "--verbose",
            "--system-prompt", "Perform the requested read-only smoke test. Reply with only the fixture word.",
            prompt,
        ]
        started = time.monotonic()
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command, cwd=root,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            exchange = asyncio.create_task(process.communicate())
            timed_out = False
            try:
                stdout, stderr = await asyncio.wait_for(asyncio.shield(exchange), timeout)
            except TimeoutError:
                import os
                import signal
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    stdout, stderr = await asyncio.wait_for(asyncio.shield(exchange), 5)
                except TimeoutError:
                    os.killpg(process.pid, signal.SIGKILL)
                    stdout, stderr = await exchange
            if not offline:
                await asyncio.sleep(0.3)
                app[SERVICE].flush()
            records = []
            for line in stdout.splitlines():
                try:
                    item = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(item, dict):
                    records.append(item)
            results = [item for item in records if item.get("type") == "result"]
            result = results[-1] if results else {}
            retries = [item for item in records if item.get("subtype") == "api_retry"]
            hook_events = [item for item in records if str(item.get("subtype", "")).startswith("hook_")]
            kinds = dict(app[SERVICE].engine.stats)
            hook_failures = sum(
                item.get("exit_code", 0) not in (None, 0)
                for item in hook_events if item.get("subtype") == "hook_response"
            )
            report = {
                "bridge": "stopped" if offline else "running",
                "timed_out": timed_out,
                "cli_exit_code": process.returncode,
                "result_is_error": bool(result.get("is_error", True)),
                "fixture_read_confirmed": result.get("result", "").strip() == "BRIDGE_OK",
                "duration_seconds": round(time.monotonic() - started, 2),
                "hook_event_records": len(hook_events),
                "stream_event_types": sorted({str(item.get("type", "")) + ":" + str(item.get("subtype", "")) for item in records}),
                "api_retry_status_codes": [
                    item.get("error_status") or item.get("status_code")
                    for item in retries
                    if isinstance(item.get("error_status") or item.get("status_code"), int)
                ],
                "api_retry_field_names": sorted({key for item in retries for key in item}),
                "hook_failures": hook_failures,
                "bridge_stats": kinds,
                "stderr_bytes": len(stderr),
            }
            if not offline and kinds.get("events", 0) == 0:
                report["observation_error"] = "没有收到真实 hook 事件"
            return report
        finally:
            if process and process.returncode is None:
                import os
                import signal
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.communicate(), 5)
                except TimeoutError:
                    os.killpg(process.pid, signal.SIGKILL)
                    await process.communicate()
            if not offline:
                await runner.cleanup()
            install("uninstall", home, ["claude-code"], port)


def main() -> None:
    parser = argparse.ArgumentParser(description="用临时会话 hooks 验证真实 Claude CLI；不安装到用户配置")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--offline", action="store_true", help="先停掉 bridge，验证 Claude 仍能正常完成")
    args = parser.parse_args()
    try:
        result = asyncio.run(verify(args.timeout, args.offline))
    except (RuntimeError, TimeoutError, OSError) as error:
        print(json.dumps({"verification_error": type(error).__name__}, ensure_ascii=False))
        raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["cli_exit_code"] != 0 or result["result_is_error"] or result.get("observation_error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
