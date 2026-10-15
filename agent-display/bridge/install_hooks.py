#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shlex
import shutil
import time
from pathlib import Path

from bridge.config import atomic_write


AGENTS = {
    "claude-code": {
        "cli": "claude", "config": ".claude/settings.json",
        "events": [
            "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
            "PostToolUseFailure", "PermissionRequest", "PermissionDenied",
            "Notification", "Stop", "StopFailure", "SessionEnd",
        ],
    },
    "codex": {
        "cli": "codex", "config": ".codex/hooks.json",
        "events": [
            "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
            "PermissionRequest", "Stop", "Interrupt", "SessionEnd",
        ],
    },
    "gemini": {
        "cli": "gemini", "config": ".gemini/settings.json",
        "events": [
            "SessionStart", "BeforeAgent", "BeforeTool", "AfterTool",
            "Notification", "AfterAgent", "SessionEnd",
        ],
    },
}
TOOL_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest", "PermissionDenied", "BeforeTool", "AfterTool"}
SOURCE = Path(__file__).resolve().parent / "hook/agent-display-hook"


def read_json(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError(f"拒绝替换符号链接配置：{path}")
    data = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError(f"配置必须是 JSON 对象：{path}")
    return data


def owned(handler: dict, script: Path, agent: str | None = None) -> bool:
    if not isinstance(handler, dict) or handler.get("type") != "command":
        return False
    try:
        command = shlex.split(handler.get("command", ""))
    except (ValueError, TypeError):
        return False
    return len(command) == 2 and command[0] == str(script) and command[1] in AGENTS and (agent is None or command[1] == agent)


def hook_group(agent: str, event: str, script: Path) -> dict:
    handler = {"type": "command", "command": f"{shlex.quote(str(script))} {agent}"}
    if agent == "gemini":
        handler.update(name="agent-display", timeout=3000)
    else:
        handler["async"] = event != "SessionEnd"
        if agent == "codex":
            handler["timeout"] = 3
    group = {"hooks": [handler]}
    if event in TOOL_EVENTS:
        group["matcher"] = ".*" if agent == "gemini" else "*"
    return group


def merge(data: dict, agent: str, script: Path) -> dict:
    result = copy.deepcopy(data)
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks 必须是对象")
    for event in AGENTS[agent]["events"]:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list) or any(
            not isinstance(group, dict) or not isinstance(group.get("hooks"), list)
            for group in groups
        ):
            raise ValueError(f"{event} 的 hooks 格式不正确")
        if not any(owned(handler, script, agent) for group in groups for handler in group["hooks"]):
            groups.append(hook_group(agent, event, script))
    return result


def remove(data: dict, agent: str, script: Path, original: dict) -> dict:
    result = copy.deepcopy(data)
    hooks = result.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks 必须是对象")
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        remaining = []
        changed = False
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                remaining.append(group)
                continue
            handlers = [handler for handler in group["hooks"] if not owned(handler, script, agent)]
            if len(handlers) != len(group["hooks"]):
                changed = True
                if handlers:
                    remaining.append(dict(group, hooks=handlers))
            else:
                remaining.append(group)
        if changed:
            if remaining or event in original.get("events", []):
                hooks[event] = remaining
            else:
                del hooks[event]
    if not hooks and not original.get("has_hooks", False):
        result.pop("hooks", None)
    return result


def backup(path: Path) -> None:
    if path.exists():
        destination = path.with_name(f"{path.name}.bak-{time.time_ns()}")
        shutil.copy2(path, destination)
        destination.chmod(0o600)


def run(mode: str, home: Path, agents: list[str], port: int, dry_run: bool = False) -> list[str]:
    script = home / ".local/bin/agent-display-hook"
    port_path = script.with_name("agent-display.port")
    manifest_path = home / ".local/state/agent-display/hooks-installation.json"
    manifest = read_json(manifest_path)
    installed = manifest.setdefault("agents", {})
    plans = []
    messages = []
    for agent in agents:
        path = home / AGENTS[agent]["config"]
        data = read_json(path)
        if mode == "status":
            hooks = data.get("hooks", {})
            count = sum(
                owned(handler, script, agent)
                for groups in hooks.values() if isinstance(groups, list)
                for group in groups if isinstance(group, dict)
                for handler in group.get("hooks", []) if isinstance(group.get("hooks"), list)
            ) if isinstance(hooks, dict) else 0
            messages.append(f"{agent}: {count} 个 agent-display handler")
            continue
        if mode == "install":
            changed = merge(data, agent, script)
            original = installed.get(agent, {
                "exists": path.exists(), "has_hooks": "hooks" in data,
                "events": list(data.get("hooks", {})),
            })
            plans.append((agent, path, data, changed, original))
        else:
            original = installed.get(agent, {"exists": True, "has_hooks": True, "events": []})
            plans.append((agent, path, data, remove(data, agent, script, original), original))
    if mode == "status":
        if "codex" in agents:
            messages.append("Codex 的信任状态请在客户端 /hooks 中查看。")
        return messages
    if dry_run:
        return [f"{agent}: 将{'安装/合并' if mode == 'install' else '移除'} {path}" for agent, path, *_ in plans]
    if mode == "install" and plans:
        if script.is_symlink() or port_path.is_symlink():
            raise ValueError("拒绝替换符号链接中继脚本或端口文件")
        source = SOURCE.read_text()
        if script.exists() and script.read_text() != source:
            backup(script)
        atomic_write(script, source)
        script.chmod(0o755)
        atomic_write(port_path, str(port) + "\n")
        manifest["script_sha256"] = hashlib.sha256(source.encode()).hexdigest()
    for agent, path, previous, changed, original in plans:
        if changed != previous:
            backup(path)
            if mode == "uninstall" and not changed and not original["exists"]:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, json.dumps(changed, ensure_ascii=False, indent=2) + "\n")
        if mode == "install":
            installed.setdefault(agent, original)
        else:
            installed.pop(agent, None)
        messages.append(f"{agent}: {'已安装' if mode == 'install' else '已移除'} agent-display hooks")
    if mode == "install":
        atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        if "codex" in agents:
            messages.append("请在 Codex 客户端执行 /hooks，审核并信任新增 hooks。")
    elif installed:
        atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    else:
        if script.exists() and hashlib.sha256(script.read_bytes()).hexdigest() == manifest.get("script_sha256"):
            script.unlink()
            port_path.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
    return messages


def main() -> None:
    parser = argparse.ArgumentParser(description="安装、检查或卸载观察型 hooks")
    parser.add_argument("mode", choices=["install", "uninstall", "status"])
    parser.add_argument("--agent", choices=[*AGENTS, "all"], default="all")
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port 必须为 1–65535")
    agents = list(AGENTS) if args.agent == "all" else [args.agent]
    if args.mode == "install" and args.agent == "all":
        agents = [agent for agent in agents if shutil.which(AGENTS[agent]["cli"]) or (args.home / AGENTS[agent]["config"]).parent.exists()]
    try:
        for message in run(args.mode, args.home.expanduser().resolve(), agents, args.port, args.dry_run):
            print(message)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
