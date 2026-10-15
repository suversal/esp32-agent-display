#!/usr/bin/env python3
"""Inspect hooks with Codex's own parser; trust only the reviewed display relay."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
from pathlib import Path

from install_hooks import SOURCE, backup, owned


async def inspect_hooks(cli: str, cwd: Path, trust: bool = False) -> dict:
    process = await asyncio.create_subprocess_exec(
        cli, "app-server", "--stdio", cwd=cwd,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    counter = 0

    async def request(method: str, params: dict) -> dict:
        nonlocal counter
        counter += 1
        identifier = counter
        process.stdin.write((json.dumps(dict(id=identifier, method=method, params=params)) + "\n").encode())
        await process.stdin.drain()
        async with asyncio.timeout(20):
            while line := await process.stdout.readline():
                record = json.loads(line)
                if record.get("id") == identifier:
                    if "error" in record:
                        raise RuntimeError(f"Codex RPC {method} failed: {record['error'].get('code')}")
                    return record.get("result", {})
        raise RuntimeError("Codex app-server closed unexpectedly")

    try:
        await request("initialize", {"clientInfo": {"name": "agent-display-hook-check", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}})
        process.stdin.write(b'{"method":"initialized"}\n')
        await process.stdin.drain()
        metadata = await request("hooks/list", {"cwds": [str(cwd)]})
        entries = metadata.get("data", [])
        script = Path.home() / ".local/bin/agent-display-hook"
        config_path = Path.home() / ".codex/config.toml"
        hooks_path = Path.home() / ".codex/hooks.json"
        selected = [hook for entry in entries for hook in entry.get("hooks", []) if owned(
            {"type": hook.get("handlerType"), "command": hook.get("command", "")}, script, "codex"
        )]
        edits = []
        if trust:
            if script.is_symlink() or not script.exists() or script.read_bytes() != SOURCE.read_bytes():
                raise ValueError("Installed relay differs from the reviewed workspace source")
            for hook in selected:
                if hook["sourcePath"] != str(hooks_path) or hook["isManaged"] or not hook["enabled"]:
                    raise ValueError("Refusing to change non-user or disabled hooks")
                if hook["trustStatus"] != "trusted":
                    edits.append({"keyPath": "hooks.state." + json.dumps(hook["key"]) + ".trusted_hash", "value": hook["currentHash"], "mergeStrategy": "replace"})
            if edits:
                backup(config_path)
                await request("config/batchWrite", {"edits": edits, "filePath": str(config_path), "reloadUserConfig": True})
                metadata = await request("hooks/list", {"cwds": [str(cwd)]})
                selected = [hook for entry in metadata.get("data", []) for hook in entry.get("hooks", []) if owned(
                    {"type": hook.get("handlerType"), "command": hook.get("command", "")}, script, "codex"
                )]
        return {
            "handlers": [{"event": hook["eventName"], "enabled": hook["enabled"], "trust": hook["trustStatus"]} for hook in selected],
            "trusted_changes": len(edits),
            "errors": sum(len(entry.get("errors", [])) for entry in metadata.get("data", [])),
            "relay_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        }
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 3)
        except TimeoutError:
            process.terminate()
            await process.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--cli", default=shutil.which("codex"))
    parser.add_argument("--trust-reviewed-relay", action="store_true")
    args = parser.parse_args()
    if not args.cli:
        parser.error("Codex is not installed")
    result = asyncio.run(inspect_hooks(args.cli, args.cwd.resolve(), args.trust_reviewed_relay))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
