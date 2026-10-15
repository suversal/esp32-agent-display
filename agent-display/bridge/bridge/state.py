from __future__ import annotations

import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable

from .config import Config
from .events import Event


@dataclass
class Session:
    key: str
    agent: str
    session_id: str
    project: str
    cwd: str
    state: str = "idle"
    label: str = "等你输入"
    detail: str = ""
    state_since: float = 0
    last_event_at: float = 0
    last_event_ts: int = 0
    turn_id: str = ""
    turn_state: str = "idle"
    turn_started_at: float | None = None
    turn_started_ts: int = 0
    turn_duration_seconds: int | None = None
    closed_turns: dict[str, int] = field(default_factory=dict)
    tools: dict[str, dict] = field(default_factory=dict)
    pending_waits: list[dict] = field(default_factory=list)
    restored: bool = False


@dataclass
class Alert:
    alert_id: str
    session_key: str
    kind: str
    text: str
    sound: str
    sound_seq: int
    sound_at: float
    created_at: float
    wait_id: str = ""
    acked: bool = False


class Engine:
    """Consumes normalized events only; never stores tool arguments or responses."""

    def __init__(self, config: Config, clock: Callable[[], float] = time.time):
        self.config = config
        self.clock = clock
        self.sessions: dict[str, Session] = {}
        self.alerts: dict[str, Alert] = {}
        self.ended_keys: dict[str, dict] = {}
        self.sound_seq = 0
        self.revision = 0
        self.stats: Counter = Counter()

    def _changed(self) -> None:
        self.revision += 1

    def _quiet(self, now: float) -> bool:
        interval = self.config.quiet_hours
        if not interval:
            return False
        start, end = interval.split("-")
        minute = datetime.fromtimestamp(now).hour * 60 + datetime.fromtimestamp(now).minute
        to_minutes = lambda value: int(value[:2]) * 60 + int(value[3:])
        left, right = to_minutes(start), to_minutes(end)
        if left == right:
            return True
        return left <= minute < right if left < right else minute >= left or minute < right

    def _alert(self, session: Session, kind: str, text: str, wait_id: str = "") -> None:
        now = self.clock()
        sound = "urgent" if kind == "waiting" else "soft"
        if self._quiet(now):
            sound = "none"
            sequence = 0
        else:
            self.sound_seq += 1
            sequence = self.sound_seq
        item = Alert(
            alert_id="a-" + uuid.uuid4().hex[:16], session_key=session.key,
            wait_id=wait_id, kind=kind, text=text, sound=sound,
            sound_seq=sequence, sound_at=now, created_at=now,
        )
        self.alerts[item.alert_id] = item
        if len(self.alerts) > 512:
            for key, alert in list(self.alerts.items()):
                if alert.acked or alert.kind == "done":
                    del self.alerts[key]
                    if len(self.alerts) <= 512:
                        break

    def _resolve(self, session: Session, wait_ids: set[str] | None = None) -> None:
        selected = {item["wait_id"] for item in session.pending_waits} if wait_ids is None else wait_ids
        session.pending_waits = [item for item in session.pending_waits if item["wait_id"] not in selected]
        for alert in self.alerts.values():
            if alert.session_key == session.key and alert.wait_id in selected:
                alert.acked = True

    def _ack_session(self, session: Session) -> None:
        for alert in self.alerts.values():
            if alert.session_key == session.key:
                alert.acked = True

    def ack(self, alert_id: str) -> bool:
        alert = self.alerts.get(alert_id)
        if alert is None or alert.acked:
            return False
        alert.acked = True
        # Acknowledging a sound never approves a tool or resolves the waiting state.
        self._changed()
        return True

    @staticmethod
    def _matches(tool: dict, wait: dict) -> bool:
        return (
            bool(wait["tool_input_fp"])
            and tool["turn_id"] == wait["turn_id"]
            and tool["subagent_id"] == wait["subagent_id"]
            and tool["tool_name"] == wait["tool_name"]
            and tool["tool_input_fp"] == wait["tool_input_fp"]
        )

    def _reconcile(self, session: Session) -> None:
        resolved = set()
        for wait in session.pending_waits:
            explicit_id = wait.get("explicit_tool_use_id", "")
            candidates = [
                (key, tool) for key, tool in session.tools.items()
                if (key == explicit_id and tool["turn_id"] == wait["turn_id"]
                    and tool["subagent_id"] == wait["subagent_id"] if explicit_id else self._matches(tool, wait))
            ]
            if len(candidates) > 1:
                wait["tool_use_id"] = ""
                if not wait["ambiguous"]:
                    wait["ambiguous"] = True
                    self.stats["ambiguous_binding"] += 1
            elif len(candidates) == 1 and not wait["ambiguous"]:
                key, tool = candidates[0]
                wait["tool_use_id"] = key
                if tool["ended"] and tool["ended_ts"] >= wait["hook_ts"]:
                    resolved.add(wait["wait_id"])
        self._resolve(session, resolved)
        # Tool results may establish that all restored waits are resolved.
        if session.restored and not any(item["restored"] for item in session.pending_waits):
            if resolved:
                session.restored = False

    def _refresh(self, session: Session, now: float) -> bool:
        previous = (session.state, session.label, session.detail)
        if session.pending_waits:
            state = "waiting"
            first = min(session.pending_waits, key=lambda item: item["since"])
            expired = first["restored"] or now - first["since"] >= self.config.permission_confirm_seconds
            if now - first["since"] >= self.config.waiting_stale_minutes * 60:
                label = "等待已久"
            elif first["wait_kind"] == "question":
                label = "需要回答" if not expired else "回答待确认"
            else:
                label = "授权待确认" if expired else "需要授权"
            session.detail = first["detail"]
        elif session.turn_state == "active":
            state, label = "running", "运行中"
            if now - session.last_event_at >= self.config.hung_minutes * 60:
                label = "状态待更新"
        elif session.turn_state in {"done", "interrupted", "failed"}:
            state = "done"
            label = {"done": "完成", "interrupted": "已中断", "failed": "运行失败"}[session.turn_state]
        else:
            state, label = "idle", "等你输入"
        if state != session.state:
            session.state_since = now
        session.state, session.label = state, label
        return previous != (session.state, session.label, session.detail)

    def _bootstrap_turn(self, session: Session, event: Event) -> None:
        if session.turn_state == "idle":
            session.turn_state = "active"
            session.turn_id = event.turn_id or f"observed-{event.seq}-{event.hook_ts}"
            # Starting the bridge mid-turn does not establish the full turn duration.
            session.turn_started_at = None

    def _close_turn(self, session: Session, event: Event) -> None:
        if session.turn_id:
            session.closed_turns[session.turn_id] = event.hook_ts
            while len(session.closed_turns) > 64:
                del session.closed_turns[next(iter(session.closed_turns))]
        self._resolve(session)
        session.turn_state = {"turn_end": "done", "interrupted": "interrupted", "turn_failed": "failed"}[event.kind]
        now = self.clock()
        session.turn_duration_seconds = (
            max(0, int(now - session.turn_started_at)) if session.turn_started_at is not None else None
        )
        session.restored = False
        if event.kind == "turn_end" and (
            self.config.done_alert_min_seconds == 0 or (
                session.turn_duration_seconds is not None
                and session.turn_duration_seconds >= self.config.done_alert_min_seconds
            )
        ):
            self._alert(session, "done", f"{session.project} 完成")

    def apply(self, event: Event) -> None:
        self.stats["events"] += 1
        self.stats[f"kind.{event.kind}"] += 1
        now = self.clock()
        tombstone = self.ended_keys.get(event.key)
        if tombstone and now >= tombstone["expires_at"]:
            del self.ended_keys[event.key]
            tombstone = None
        if tombstone:
            if event.kind == "session_start" and event.source == "resume" and event.hook_ts > tombstone["hook_ts"]:
                del self.ended_keys[event.key]
            else:
                self.stats["tombstone_dropped"] += 1
                return
        if event.kind == "session_end":
            self.sessions.pop(event.key, None)
            for key in [key for key, alert in self.alerts.items() if alert.session_key == event.key]:
                del self.alerts[key]
            self.ended_keys[event.key] = {
                "hook_ts": event.hook_ts, "expires_at": now + self.config.session_tombstone_minutes * 60,
            }
            self._changed()
            return
        session = self.sessions.get(event.key)
        if session is None:
            if len(self.sessions) >= self.config.max_sessions:
                self.stats["capacity_dropped"] += 1
                return
            session = Session(event.key, event.agent, event.session_id, event.project, event.cwd, state_since=now, last_event_at=now)
            self.sessions[event.key] = session
        if event.turn_id in session.closed_turns and event.kind != "session_start":
            if event.kind == "tool_end":
                tool = session.tools.get(event.tool_use_id)
                if tool:
                    tool["ended"] = True
                    tool["ended_ts"] = event.hook_ts
            self.stats["closed_turn_dropped"] += 1
            return
        if (
            event.kind not in {"session_start", "turn_start"} and event.turn_id
            and session.turn_id and event.turn_id != session.turn_id
        ):
            self.stats["other_turn_dropped"] += 1
            return
        if (
            event.kind in {"tool_start", "waiting", "permission_check", "turn_start"}
            and event.hook_ts < session.turn_started_ts
            and event.turn_id != session.turn_id
        ):
            self.stats["older_event_dropped"] += 1
            return
        if session.turn_state in {"done", "interrupted", "failed"} and event.kind in {"tool_start", "waiting", "permission_check", "tool_end", "wait_resolved", "turn_end", "turn_failed", "interrupted"}:
            self.stats["terminal_event_dropped"] += 1
            return
        session.last_event_at = now
        session.last_event_ts = max(session.last_event_ts, event.hook_ts)
        if event.project:
            session.project, session.cwd = event.project, event.cwd
        if event.kind == "session_start":
            # A delayed async SessionStart must not erase a turn already observed.
            if session.turn_state == "idle" and not session.pending_waits:
                self._resolve(session)
                self._ack_session(session)
                session.turn_state, session.turn_id = "idle", ""
                session.turn_started_at = None
                session.tools.clear()
                session.detail = ""
                session.restored = False
        elif event.kind == "turn_start":
            turn_id = event.turn_id or f"turn-{event.seq}-{event.hook_ts}"
            if turn_id != session.turn_id:
                if session.turn_id:
                    session.closed_turns[session.turn_id] = event.hook_ts
                    while len(session.closed_turns) > 64:
                        del session.closed_turns[next(iter(session.closed_turns))]
                self._resolve(session)
                self._ack_session(session)
                session.tools.clear()
                session.detail = ""
            session.turn_id, session.turn_state = turn_id, "active"
            session.turn_started_at = event.hook_ts / 1_000_000
            session.turn_started_ts = event.hook_ts
            session.turn_duration_seconds = None
            session.restored = False
        elif event.kind in {"tool_start", "tool_end"}:
            self._bootstrap_turn(session, event)
            tool_id = event.tool_use_id
            if not tool_id and event.kind == "tool_start":
                tool_id = f"observed-{event.seq}-{event.hook_ts}"
            elif not tool_id and event.kind == "tool_end":
                # Gemini has no call id. Bind only one unambiguous observed call.
                candidates = [key for key, tool in session.tools.items() if not tool["ended"] and self._matches(tool, {
                    "turn_id": event.turn_id or session.turn_id, "subagent_id": event.subagent_id,
                    "tool_name": event.tool_name, "tool_input_fp": event.tool_input_fp,
                })]
                if len(candidates) == 1:
                    tool_id = candidates[0]
                else:
                    self.stats["unmatched_tool_end"] += 1
            if tool_id:
                old = session.tools.get(tool_id)
                if event.kind == "tool_start" and old:
                    self.stats["duplicate_tool_start"] += 1
                elif event.kind == "tool_end" and old and old["ended"]:
                    self.stats["duplicate_tool_end"] += 1
                if len(session.tools) < 512 or old:
                    old = old or {}
                    session.tools[tool_id] = {
                        "turn_id": old.get("turn_id") or event.turn_id or session.turn_id,
                        "subagent_id": old.get("subagent_id") or event.subagent_id,
                        "tool_name": old.get("tool_name") or event.tool_name,
                        "tool_input_fp": old.get("tool_input_fp") or event.tool_input_fp,
                        "detail": old.get("detail") or event.detail,
                        "started_at": old.get("started_at", now),
                        "ended": old.get("ended", False) or event.kind == "tool_end",
                        "ended_ts": max(old.get("ended_ts", 0), event.hook_ts if event.kind == "tool_end" else 0),
                    }
                self._reconcile(session)
            if event.detail:
                session.detail = event.detail
        elif event.kind == "permission_check":
            # Permission review can complete without ever asking the user.
            # Keep observing the turn; never create a waiting alert from it.
            self._bootstrap_turn(session, event)
            if event.detail:
                session.detail = event.detail
        elif event.kind == "waiting":
            if event.wait_kind == "idle":
                self._refresh(session, now)
                self._changed()
                return
            self._bootstrap_turn(session, event)
            signature = (
                event.turn_id or session.turn_id, event.subagent_id,
                event.tool_name, event.tool_input_fp, event.wait_kind, event.tool_use_id,
            )
            duplicate = any(
                (item["turn_id"], item["subagent_id"], item["tool_name"], item["tool_input_fp"], item["wait_kind"], item.get("explicit_tool_use_id", "")) == signature
                for item in session.pending_waits
            )
            if event.notification and any(
                item["turn_id"] == signature[0] and item["wait_kind"] == event.wait_kind
                for item in session.pending_waits
            ):
                duplicate = True
            if not duplicate:
                wait = {
                    "wait_id": "w-" + uuid.uuid4().hex[:16], "turn_id": signature[0],
                    "subagent_id": event.subagent_id, "tool_name": event.tool_name,
                    "tool_input_fp": event.tool_input_fp, "tool_use_id": "",
                    "explicit_tool_use_id": event.tool_use_id,
                    "wait_kind": event.wait_kind, "detail": event.detail or session.detail,
                    "since": now, "hook_ts": event.hook_ts, "restored": False, "ambiguous": False,
                }
                session.pending_waits.append(wait)
                self._reconcile(session)
                if wait in session.pending_waits:
                    text = "需要回答" if event.wait_kind == "question" else "需要授权"
                    self._alert(session, "waiting", f"{session.project} {text}", wait["wait_id"])
            else:
                self.stats["duplicate_wait"] += 1
        elif event.kind == "wait_resolved":
            matches = [
                item for item in session.pending_waits
                if item["turn_id"] == (event.turn_id or session.turn_id)
                and item["subagent_id"] == event.subagent_id
                and item["tool_name"] == event.tool_name
                and item["tool_input_fp"] == event.tool_input_fp
            ]
            if len(matches) == 1:
                self._resolve(session, {matches[0]["wait_id"]})
                if not any(item["restored"] for item in session.pending_waits):
                    session.restored = False
        elif event.kind in {"turn_end", "interrupted", "turn_failed"}:
            self._close_turn(session, event)
        self._refresh(session, now)
        self._changed()

    def tick(self) -> bool:
        now = self.clock()
        changed = False
        for key, session in list(self.sessions.items()):
            changed = self._refresh(session, now) or changed
            age = now - session.last_event_at
            limit = {
                "running": self.config.running_stale_minutes * 60,
                "waiting": self.config.waiting_drop_hours * 3600,
                "done": self.config.done_retention_minutes * 60,
                "idle": self.config.idle_stale_minutes * 60,
            }[session.state]
            elapsed = now - session.state_since if session.state == "done" else age
            if session.state == "waiting":
                elapsed = now - min(item["since"] for item in session.pending_waits)
            if elapsed >= limit:
                del self.sessions[key]
                self._ack_session(session)
                changed = True
        for key, tombstone in list(self.ended_keys.items()):
            if now >= tombstone["expires_at"]:
                del self.ended_keys[key]
                changed = True
        if changed:
            self._changed()
        return changed

    def snapshot(self) -> dict:
        now = self.clock()
        order = {"waiting": 0, "running": 1, "done": 2, "idle": 3}
        sessions = sorted(self.sessions.values(), key=lambda item: (order[item.state], -item.last_event_at, item.key))
        pending = [item for item in self.alerts.values() if not item.acked and item.session_key in self.sessions]
        alert = max(pending, key=lambda item: (item.kind == "waiting", item.created_at, item.alert_id), default=None)
        selected = asdict(alert) if alert else None
        if selected and selected["kind"] == "waiting":
            session = self.sessions[selected["session_key"]]
            selected["text"] = f"{session.project} {session.label}"
        return {
            "type": "snapshot", "v": 2, "server_time": int(now),
            "tz_offset": int(datetime.fromtimestamp(now).astimezone().utcoffset().total_seconds()),
            "current_sound_seq": self.sound_seq,
            "sessions": [
                {
                    "key": item.key, "agent": item.agent, "project": item.project,
                    "state": item.state, "label": item.label, "detail": item.detail,
                    "elapsed": max(0, int(now - (item.last_event_at if item.state == "running" and now - item.last_event_at >= self.config.hung_minutes * 60 else item.state_since))),
                    "turn_duration_seconds": item.turn_duration_seconds,
                    "stale": item.restored or (item.state == "running" and now - item.last_event_at >= self.config.hung_minutes * 60),
                    **({"activity_age": True} if item.state == "running" and now - item.last_event_at >= self.config.hung_minutes * 60 else {}),
                } for item in sessions
            ],
            "alert": selected,
        }

    def export(self) -> dict:
        return {
            "v": 1, "sound_seq": self.sound_seq, "saved_at": self.clock(),
            "sessions": {key: asdict(item) for key, item in self.sessions.items()},
            "alerts": {key: asdict(item) for key, item in self.alerts.items()},
            "ended_keys": self.ended_keys,
        }

    def restore(self, data: dict) -> None:
        if data.get("v") != 1 or not isinstance(data.get("sessions"), dict):
            raise ValueError("unsupported state format")
        now = self.clock()
        self.sound_seq = max(0, int(data["sound_seq"]))
        sessions = {}
        unconfirmed_waits = set()
        for key, value in list(data["sessions"].items())[: self.config.max_sessions]:
            item = Session(**value)
            if key != item.key or now - item.last_event_at >= self.config.restore_max_age_minutes * 60:
                continue
            item.restored = True
            if item.agent == "codex":
                # Older versions treated PermissionRequest as a visible prompt.
                # Its input hash also differed from Pre/PostToolUse, leaving
                # completed automatic reviews stuck indefinitely. Remove only
                # this unsupported inference, preserving questions/other agents.
                removed = {wait["wait_id"] for wait in item.pending_waits if wait["wait_kind"] == "permission"}
                unconfirmed_waits.update((key, wait_id) for wait_id in removed)
                item.pending_waits = [wait for wait in item.pending_waits if wait["wait_id"] not in removed]
                self.stats["unconfirmed_codex_waits_discarded"] += len(removed)
            for wait in item.pending_waits:
                wait["restored"] = True
            self._refresh(item, now)
            sessions[key] = item
        alerts = {}
        for key, value in data.get("alerts", {}).items():
            item = Alert(**value)
            if item.session_key in sessions:
                item.sound = "none"
                if (item.session_key, item.wait_id) in unconfirmed_waits:
                    item.acked = True
                alerts[key] = item
        tombstones = {
            key: value for key, value in data.get("ended_keys", {}).items()
            if value["expires_at"] > now
        }
        self.sessions, self.alerts, self.ended_keys = sessions, alerts, tombstones
        self._changed()

    def debug_state(self) -> dict:
        return {
            "snapshot": self.snapshot(),
            "sessions": {key: asdict(item) for key, item in self.sessions.items()},
            "stats": dict(self.stats), "ended_keys": self.ended_keys,
        }
