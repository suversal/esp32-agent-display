"""Read Vibe Island's display cache. Conversation excerpts stay in RAM."""
from __future__ import annotations

import json
import re
import stat as stat_module
import time
from pathlib import Path

from .privacy import redact, safe_text

APPLE_EPOCH = 978307200


def excerpt(value, limit=240):
    if not isinstance(value, str):
        return ""
    return safe_text(re.sub(r"\s+", " ", redact(value)).strip(), limit)


class VibeCache:
    def __init__(self, path: str):
        self.path = Path(path).expanduser()
        self.signature = None
        self.entries: dict[str, dict] = {}
        self.modified_at = 0.0

    def refresh(self) -> bool:
        try:
            stat = self.path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            if signature == self.signature:
                return False
            if not stat_module.S_ISREG(stat.st_mode) or stat.st_size > 1_048_576:
                return False
            with self.path.open("rb") as stream:
                data = json.loads(stream.read(1_048_577))
            if not isinstance(data, dict):
                return False
            entries = {}
            for cache_id, value in list(data.items())[:128]:
                if not isinstance(cache_id, str) or not isinstance(value, dict):
                    continue
                source = value.get("source")
                if not isinstance(source, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", source):
                    continue
                agent = "claude-code" if source == "claude" else source
                sid = value.get("codexNotifyThreadId") if source == "codex" else None
                sid = sid or cache_id.removeprefix(source + "-")
                if not isinstance(sid, str) or not sid or len(sid) > 256:
                    continue
                stamp = value.get("lastActivityAt")
                if not isinstance(stamp, (int, float)) or isinstance(stamp, bool):
                    continue
                activity = stamp + APPLE_EPOCH
                if not 0 < activity <= time.time() + 60:
                    continue
                cwd = value.get("cwd", "")
                cwd = cwd if isinstance(cwd, str) else ""
                project = safe_text(Path(cwd).name, 40) or "unknown"
                user = excerpt(value.get("lastUserMessage") or value.get("firstUserMessage"))
                title = excerpt(value.get("customTitle") or value.get("firstUserMessage"), 100) or project
                status = value.get("status", "")
                key = f"{agent}:{sid}"
                entries[key] = {
                    "key": key, "agent": agent, "project": project, "title": title,
                    "user_preview": user, "assistant_preview": excerpt(value.get("lastAssistantMessage")),
                    "current_tool": safe_text(value.get("currentTool"), 40) if isinstance(value.get("currentTool"), str) else "",
                    "client": excerpt(value.get("bundleIdentifier"), 60),
                    "activity": activity, "vibe_status": status if isinstance(status, str) else "",
                }
        except (OSError, ValueError, TypeError):
            # Preserve the last good snapshot during a concurrent partial write.
            return False
        changed = entries != self.entries
        self.entries, self.signature, self.modified_at = entries, signature, stat.st_mtime
        return changed

    def decorate(self, snapshot: dict, now: float, max_age: float, hung_seconds: float, native_activity=None) -> dict:
        native_activity = native_activity or {}
        rows = {row["key"]: dict(row) for row in snapshot["sessions"]}
        for key, entry in self.entries.items():
            age = max(0, now - entry["activity"])
            if age > max_age:
                continue
            row = rows.get(key)
            if row is None:
                state, label = {
                    "processing": ("running", "运行中"),
                    "running_tool": ("running", "运行中"),
                    "waiting_for_input": ("idle", "等待输入"),
                    "waiting_for_permission": ("waiting", "等待授权"),
                }.get(entry["vibe_status"], ("idle", "状态待确认"))
                stale = state in {"running", "waiting"} and age >= hung_seconds
                if stale and state == "running":
                    label = "状态待更新"
                row = rows[key] = {
                    "key": key, "agent": entry["agent"], "project": entry["project"],
                    "state": state, "label": label, "detail": "", "elapsed": int(age),
                    "turn_duration_seconds": None, "stale": stale, "activity_age": True,
                }
            elif (row["state"] == "running" and key in native_activity
                  and now - native_activity[key] >= hung_seconds and entry["activity"] > native_activity[key]):
                # Stale hook state cannot overrule newer observed activity. Only
                # repair non-actionable activity state; real waits/alerts remain
                # authoritative and never get approved or cleared by the cache.
                if entry["vibe_status"] in {"processing", "running_tool", "waiting_for_input"}:
                    idle = entry["vibe_status"] == "waiting_for_input"
                    stale = not idle and age >= hung_seconds
                    row.update(state="idle" if idle else "running",
                               label="等待输入" if idle else "状态待更新" if stale else "运行中",
                               stale=stale, elapsed=int(age), activity_age=True, turn_duration_seconds=None)
            # Native hooks retain control of actionable waits and alerts.
            for field in ("title", "user_preview", "assistant_preview", "current_tool", "client"):
                row[field] = entry[field]
        order = {"waiting": 0, "running": 1, "done": 2, "idle": 3}
        snapshot["sessions"] = sorted(rows.values(), key=lambda r: (
            order[r["state"]], -max(native_activity.get(r["key"], 0), self.entries.get(r["key"], {}).get("activity", 0)), r["key"]
        ))
        return snapshot
