"""Per-device pages. Only session keys and navigation state are retained here."""
from __future__ import annotations

import math

AUTO_SECONDS = 20
MANUAL_SECONDS = 60
STATE_PRIORITY = {"waiting": 0, "running": 1, "done": 2, "idle": 3}


class Pager:
    def __init__(self, now: float, auto: bool = True):
        self.order: list[str] = []
        self.index = 0
        self.size = 3
        self.auto = auto
        self.hold_until = 0.0
        self.next_at = now + AUTO_SECONDS
        self.waiting = False
        self.auto_rotations = 0

    @property
    def count(self) -> int:
        return max(1, math.ceil(len(self.order) / self.size))

    def due(self, now: float) -> bool:
        return self.auto and not self.waiting and self.count > 1 and now >= max(self.next_at, self.hold_until)

    def sync(self, snapshot: dict, now: float) -> None:
        rows = snapshot["sessions"]
        keys = [row["key"] for row in rows]
        live = set(keys)
        anchor = self.order[self.index * self.size] if self.index * self.size < len(self.order) else None
        known = set(self.order)
        stable = [key for key in self.order if key in live] + [key for key in keys if key not in known]
        states = {row["key"]: row["state"] for row in rows}
        self.order = sorted(stable, key=lambda key: STATE_PRIORITY.get(states[key], 4))
        priority_changed = self.order != stable
        self.size = 3 if any(row.get("title") or row.get("user_preview") or row.get("assistant_preview") for row in rows) else 4
        # Keep the selected page on state changes, so promoting running sessions
        # does not move the reader away from the first page along with old cards.
        if not priority_changed and anchor in self.order:
            self.index = self.order.index(anchor) // self.size
        self.index = min(self.index, self.count - 1)
        alert = snapshot.get("alert")
        waiting = bool(alert and alert.get("kind") == "waiting")
        if waiting:
            key = alert.get("session_key")
            if key in self.order:
                self.index = self.order.index(key) // self.size
        if waiting != self.waiting:
            self.next_at = now + AUTO_SECONDS
        self.waiting = waiting

    def request(self, action: str, now: float) -> bool:
        if action == "toggle_auto":
            self.auto = not self.auto
            self.hold_until = 0.0
            self.next_at = now + AUTO_SECONDS
        elif action == "next":
            if self.waiting:  # A page gesture must never hide an unacknowledged urgent alert.
                return False
            self.index = (self.index + 1) % self.count
            self.hold_until = now + MANUAL_SECONDS
            self.next_at = now + AUTO_SECONDS
        else:
            return False
        return True

    def view(self, snapshot: dict, now: float) -> dict:
        self.sync(snapshot, now)
        if self.due(now):
            self.index = (self.index + 1) % self.count
            self.next_at = now + AUTO_SECONDS
            self.hold_until = 0.0
            self.auto_rotations += 1
        rows = {row["key"]: row for row in snapshot["sessions"]}
        keys = self.order[self.index * self.size:(self.index + 1) * self.size]
        return dict(snapshot, sessions=[rows[key] for key in keys], total_sessions=len(self.order),
                    page=self.status(now))

    def status(self, now: float) -> dict:
        return dict(index=self.index, count=self.count, size=self.size, auto=self.auto,
                    waiting=self.waiting, hold_seconds=max(0, math.ceil(self.hold_until - now)))
