from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .config import Config
from .privacy import safe_text, summarize


KINDS = {
    "session_start", "turn_start", "tool_start", "tool_end", "waiting",
    "wait_resolved", "permission_check", "turn_end", "interrupted", "session_end", "turn_failed",
}


@dataclass(frozen=True)
class Event:
    agent: str
    session_id: str
    kind: str
    hook_ts: int
    seq: int = 0
    project: str = ""
    cwd: str = ""
    turn_id: str = ""
    tool_use_id: str = ""
    subagent_id: str = ""
    tool_name: str = ""
    tool_input_fp: str = ""
    detail: str = ""
    wait_kind: str = ""
    source: str = ""
    notification: bool = False

    @property
    def key(self) -> str:
        return f"{self.agent}:{self.session_id}"


COMMON = {
    "SessionStart": "session_start", "UserPromptSubmit": "turn_start",
    "PreToolUse": "tool_start", "PostToolUse": "tool_end",
    "PostToolUseFailure": "tool_end", "PermissionRequest": "waiting",
    "PermissionDenied": "wait_resolved", "Stop": "turn_end",
    "StopFailure": "turn_failed", "Interrupt": "interrupted",
    "SessionEnd": "session_end",
}
GEMINI = {
    "SessionStart": "session_start", "BeforeAgent": "turn_start",
    "BeforeTool": "tool_start", "AfterTool": "tool_end",
    "AfterAgent": "turn_end", "SessionEnd": "session_end",
}
NOTIFICATIONS = {
    "permission_prompt": "permission", "elicitation_dialog": "question",
    "elicitation_url_dialog": "question", "agent_needs_input": "question",
    "idle_prompt": "idle",
}


def normalize(agent: str, payload: Any, hook_ts: int, seq: int, config: Config) -> Event | None:
    if agent not in {"claude-code", "codex", "gemini"} or not isinstance(payload, dict):
        return None
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id or len(session_id) > 256:
        return None
    name = payload.get("hook_event_name")
    kind = (GEMINI if agent == "gemini" else COMMON).get(name)
    wait_kind = "permission" if name == "PermissionRequest" else ""
    if agent == "codex" and name == "PermissionRequest":
        # This runs before hooks/auto-review decide. It does not prove that a
        # human approval prompt is visible, and carries no tool_use_id.
        kind, wait_kind = "permission_check", ""
    notification = name == "Notification"
    if notification:
        notification_type = payload.get("notification_type")
        if agent == "claude-code":
            wait_kind = NOTIFICATIONS.get(notification_type, "")
        elif agent == "gemini" and notification_type == "ToolPermission":
            wait_kind = "permission"
        else:
            return None
        if not wait_kind:
            return None
        kind = "waiting"
    if kind is None:
        return None
    cwd = safe_text(payload.get("cwd", ""), 1024)
    project = cwd.rstrip("/").rsplit("/", 1)[-1] or "unknown"
    project = safe_text(config.project_alias.get(project, project))
    details = payload.get("details") if agent == "gemini" and notification else {}
    details = details if isinstance(details, dict) else {}
    tool = safe_text(payload.get("tool_name", details.get("tool_name", details.get("toolName", ""))), 128)
    arguments = payload.get("tool_input", details.get("tool_input", details.get("toolInput")))
    fingerprint = (
        hashlib.sha256(json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        if arguments is not None else ""
    )
    return Event(
        agent=agent, session_id=session_id, kind=kind, hook_ts=hook_ts, seq=seq,
        cwd=cwd, project=project,
        turn_id=safe_text(payload.get("prompt_id" if agent == "claude-code" else "turn_id", ""), 128),
        tool_use_id=safe_text(payload.get("tool_use_id", ""), 128),
        subagent_id=safe_text(payload.get("agent_id", ""), 128),
        tool_name=tool, tool_input_fp=fingerprint,
        detail=summarize(tool, arguments, config.show_command_text) if tool else "",
        wait_kind=wait_kind, source=safe_text(payload.get("source", ""), 32),
        notification=notification,
    )


def simulated_event(payload: Any, seq: int) -> Event:
    if not isinstance(payload, dict):
        raise ValueError("event must be an object")
    allowed = Event.__dataclass_fields__.keys()
    if set(payload) - set(allowed):
        raise ValueError("unsupported event fields")
    values = dict(payload, seq=seq)
    if values.get("kind") not in KINDS:
        raise ValueError("unsupported event kind")
    if not isinstance(values.get("hook_ts"), int):
        raise ValueError("hook_ts must be integer microseconds")
    for name in allowed - {"hook_ts", "seq", "notification"}:
        if name in values:
            values[name] = safe_text(values[name], 256)
    if not values.get("session_id") or not values.get("agent"):
        raise ValueError("agent and session_id required")
    return Event(**values)
