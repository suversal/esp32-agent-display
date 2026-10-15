import json
import unittest
from dataclasses import replace
from datetime import datetime

from bridge.config import Config
from bridge.events import Event, normalize
from bridge.state import Engine


class StateTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000.0
        self.engine = Engine(Config(token="t" * 32, quiet_hours=""), lambda: self.now)
        self.sequence = 0

    def event(self, kind, **values):
        self.sequence += 1
        self.now += 0.001
        data = dict(
            agent="claude-code", session_id="session", project="blog", cwd="/tmp/blog",
            kind=kind, hook_ts=int(self.now * 1_000_000), seq=self.sequence, turn_id="turn",
        )
        data.update(values)
        event = Event(**data)
        self.engine.apply(event)
        return event

    def start(self):
        self.event("session_start", turn_id="", source="startup")
        self.event("turn_start")

    def tool(self, tool_id="tool", **values):
        return self.event("tool_start", tool_use_id=tool_id, tool_name="Bash", tool_input_fp="fingerprint", detail="执行命令", **values)

    def wait(self, **values):
        return self.event("waiting", tool_name="Bash", tool_input_fp="fingerprint", wait_kind="permission", **values)

    @property
    def session(self):
        return self.engine.sessions["claude-code:session"]

    def test_lifecycle_and_long_completion(self):
        self.start()
        self.assertEqual(self.session.state, "running")
        self.tool()
        self.now += 65
        self.event("tool_end", tool_use_id="tool")
        self.event("turn_end")
        snapshot = self.engine.snapshot()
        self.assertEqual(snapshot["sessions"][0]["state"], "done")
        self.assertGreaterEqual(snapshot["sessions"][0]["turn_duration_seconds"], 65)
        self.assertEqual(snapshot["alert"]["sound"], "soft")

    def test_mid_turn_start_does_not_invent_duration(self):
        self.tool()
        self.now += 100
        self.event("turn_end")
        self.assertIsNone(self.session.turn_duration_seconds)
        self.assertEqual(self.engine.snapshot()["alert"]["sound"], "soft")

    def test_each_short_completion_alerts_once_including_subsecond_turns(self):
        self.start()
        self.now += .2
        self.event("turn_end")
        self.assertEqual(self.session.turn_duration_seconds, 0)
        self.assertEqual(self.engine.snapshot()["alert"]["sound"], "soft")
        self.assertEqual(self.engine.sound_seq, 1)
        self.event("turn_end")
        self.engine.tick()
        self.assertEqual(self.engine.sound_seq, 1)
        self.event("turn_start", turn_id="second")
        self.now += 37
        self.event("turn_end", turn_id="second")
        self.assertEqual(self.engine.sound_seq, 2)
        self.event("turn_end", turn_id="second")
        self.assertEqual(self.engine.sound_seq, 2)

    def test_explicit_positive_completion_threshold_remains_supported(self):
        self.engine.config = replace(self.engine.config, done_alert_min_seconds=60)
        self.tool()
        self.event("turn_end")
        self.assertIsNone(self.session.turn_duration_seconds)
        self.assertIsNone(self.engine.snapshot()["alert"])
        self.event("turn_start", turn_id="short")
        self.now += 37
        self.event("turn_end", turn_id="short")
        self.assertIsNone(self.engine.snapshot()["alert"])
        self.event("turn_start", turn_id="long")
        self.now += 60
        self.event("turn_end", turn_id="long")
        self.assertEqual(self.engine.sound_seq, 1)

    def test_matching_tool_end_resolves_authorization(self):
        self.start()
        self.tool()
        self.wait()
        self.assertEqual(self.session.state, "waiting")
        self.event("tool_end", tool_use_id="tool")
        self.assertEqual(self.session.state, "running")
        self.assertFalse(self.session.pending_waits)

    def test_idless_unique_tool_end_resolves_only_matching_wait(self):
        self.start()
        self.tool("")
        self.wait()
        self.event("tool_end", tool_name="Read", tool_input_fp="other")
        self.assertEqual(self.session.state, "waiting")
        self.event("tool_end", tool_name="Bash", tool_input_fp="fingerprint")
        self.assertEqual(self.session.state, "running")
        self.assertFalse(self.session.pending_waits)

    def test_idless_identical_parallel_tools_remain_ambiguous(self):
        self.start()
        self.tool("")
        self.tool("")
        self.wait()
        self.event("tool_end", tool_name="Bash", tool_input_fp="fingerprint")
        self.assertEqual(self.session.state, "waiting")
        self.assertTrue(self.session.pending_waits[0]["ambiguous"])

    def test_explicit_call_ids_disambiguate_identical_permission_requests(self):
        self.start()
        self.tool("one")
        self.tool("two")
        self.wait(tool_use_id="one")
        self.wait(tool_use_id="two")
        self.assertEqual(len(self.session.pending_waits), 2)
        self.event("tool_end", tool_use_id="one")
        self.assertEqual(self.session.state, "waiting")
        self.assertEqual(self.session.pending_waits[0]["explicit_tool_use_id"], "two")
        self.event("tool_end", tool_use_id="two")
        self.assertEqual(self.session.state, "running")

    def test_subagent_tool_end_does_not_resolve_main_wait(self):
        self.start()
        self.tool()
        self.wait()
        self.tool("child-tool", subagent_id="child")
        self.event("tool_end", tool_use_id="child-tool", subagent_id="child")
        self.assertEqual(self.session.state, "waiting")
        self.assertEqual(len(self.session.pending_waits), 1)

    def test_unrelated_main_tool_end_does_not_resolve_wait(self):
        self.start()
        self.tool()
        self.wait()
        self.event("tool_start", tool_use_id="other", tool_name="Read", tool_input_fp="other", detail="读取 x.py")
        self.event("tool_end", tool_use_id="other")
        self.assertEqual(self.session.state, "waiting")

    def test_permission_before_tool_start_can_bind_later(self):
        self.start()
        self.wait()
        self.assertFalse(self.session.pending_waits[0]["tool_use_id"])
        self.tool()
        self.assertEqual(self.session.pending_waits[0]["tool_use_id"], "tool")
        self.event("tool_end", tool_use_id="tool")
        self.assertEqual(self.session.state, "running")

    def test_identical_parallel_tools_stay_unbound(self):
        self.start()
        self.tool("one")
        self.tool("two")
        self.wait()
        self.assertTrue(self.session.pending_waits[0]["ambiguous"])
        self.event("tool_end", tool_use_id="one")
        self.assertEqual(self.session.state, "waiting")
        self.event("tool_end", tool_use_id="two")
        self.assertEqual(self.session.state, "waiting")
        self.event("turn_end")
        self.assertEqual(self.session.state, "done")

    def test_second_late_candidate_revokes_binding(self):
        self.start()
        self.wait()
        self.tool("one")
        self.assertEqual(self.session.pending_waits[0]["tool_use_id"], "one")
        self.tool("two")
        self.assertFalse(self.session.pending_waits[0]["tool_use_id"])
        self.event("tool_end", tool_use_id="one")
        self.assertEqual(self.session.state, "waiting")

    def test_post_tool_before_late_pre_tool_preserves_completion(self):
        self.start()
        self.wait()
        self.event("tool_end", tool_use_id="tool")
        self.tool()
        self.assertEqual(self.session.state, "running")

    def test_notification_deduplicates_and_never_repeats(self):
        self.start()
        self.tool()
        self.wait()
        self.now += 6
        self.event("waiting", wait_kind="permission", notification=True)
        self.assertEqual(len(self.session.pending_waits), 1)
        self.now += 150
        self.engine.tick()
        self.assertEqual(self.session.label, "授权待确认")
        self.assertEqual(self.engine.sound_seq, 1)
        self.now += 300
        self.engine.tick()
        self.assertEqual(self.engine.sound_seq, 1)

    def test_ack_silences_alert_but_does_not_approve(self):
        self.start()
        self.tool()
        self.wait()
        alert = self.engine.snapshot()["alert"]
        self.assertTrue(self.engine.ack(alert["alert_id"]))
        self.assertEqual(self.session.state, "waiting")
        self.assertIsNone(self.engine.snapshot()["alert"])
        self.assertEqual(self.engine.snapshot()["current_sound_seq"], 1)

    def test_quiet_hours_create_visible_silent_alert(self):
        self.now = datetime.now().replace(hour=23, minute=30, second=0).timestamp()
        self.engine.config.quiet_hours = "23:00-08:00"
        self.start()
        self.tool()
        self.wait()
        self.assertEqual(self.engine.snapshot()["alert"]["sound"], "none")
        self.assertEqual(self.engine.sound_seq, 0)

    def test_short_completion_obeys_quiet_hours(self):
        self.now = datetime.now().replace(hour=23, minute=30, second=0).timestamp()
        self.engine.config.quiet_hours = "23:00-08:00"
        self.start()
        self.event("turn_end")
        self.assertEqual(self.engine.snapshot()["alert"]["kind"], "done")
        self.assertEqual(self.engine.snapshot()["alert"]["sound"], "none")
        self.assertEqual(self.engine.sound_seq, 0)

    def test_interrupted_turn_is_silent(self):
        self.start()
        self.now += 65
        self.event("interrupted")
        self.assertEqual(self.session.label, "已中断")
        self.assertIsNone(self.engine.snapshot()["alert"])

    def test_restore_keeps_wait_stale_and_silent(self):
        self.start()
        self.tool()
        self.wait()
        data = json.loads(json.dumps(self.engine.export()))
        self.engine = Engine(self.engine.config, lambda: self.now)
        self.engine.restore(data)
        self.assertTrue(self.session.restored)
        self.assertEqual(self.session.label, "授权待确认")
        self.assertEqual(self.engine.snapshot()["alert"]["sound"], "none")
        self.event("tool_end", tool_use_id="unrelated")
        self.assertTrue(self.session.restored)
        self.event("tool_end", tool_use_id="tool")
        self.assertFalse(self.session.restored)
        self.assertEqual(self.session.state, "running")

    def test_new_turn_clears_restored_wait(self):
        self.start()
        self.tool()
        self.wait()
        data = self.engine.export()
        self.engine = Engine(self.engine.config, lambda: self.now)
        self.engine.restore(data)
        self.event("turn_start", turn_id="next-turn")
        self.assertFalse(self.session.restored)
        self.assertFalse(self.session.pending_waits)

    def test_tombstone_rejects_late_events_and_allows_resume(self):
        self.start()
        self.event("session_end", turn_id="")
        self.tool()
        self.assertFalse(self.engine.sessions)
        self.event("session_start", turn_id="", source="resume")
        self.assertEqual(self.session.state, "idle")

    def test_tombstone_survives_restart(self):
        self.start()
        self.event("session_end", turn_id="")
        data = self.engine.export()
        self.engine = Engine(self.engine.config, lambda: self.now)
        self.engine.restore(data)
        self.tool()
        self.assertFalse(self.engine.sessions)

    def test_late_tool_end_does_not_reopen_completed_turn(self):
        self.start()
        self.tool()
        self.event("turn_end")
        self.event("tool_end", tool_use_id="tool")
        self.assertEqual(self.session.state, "done")

    def test_old_turn_events_do_not_change_new_turn(self):
        self.start()
        self.event("turn_end")
        self.event("turn_start", turn_id="next-turn")
        self.event("tool_end", tool_use_id="tool", turn_id="turn")
        self.assertEqual(self.session.state, "running")
        self.assertEqual(self.session.turn_id, "next-turn")

    def test_late_session_start_does_not_erase_an_active_wait(self):
        self.start()
        self.tool()
        self.wait()
        self.event("session_start", turn_id="", source="startup")
        self.assertEqual(self.session.state, "waiting")
        self.assertEqual(len(self.session.pending_waits), 1)

    def test_wait_is_retained_past_thirty_minutes(self):
        self.start()
        self.tool()
        self.wait()
        self.now += 31 * 60
        self.engine.tick()
        self.assertEqual(self.session.state, "waiting")

    def test_missing_activity_is_unknown_not_a_confirmed_interruption(self):
        self.start()
        self.tool()
        self.now+=901
        self.engine.tick()
        self.assertEqual(self.session.label,'状态待更新')
        self.assertEqual(self.session.state,'running')
        row=self.engine.snapshot()['sessions'][0]
        self.assertTrue(row['stale'])
        self.assertTrue(row['activity_age'])
        self.assertEqual(row['elapsed'],901)
        self.assertIsNone(self.engine.snapshot()['alert'])

    def test_done_retention_really_is_sixty_minutes(self):
        self.start()
        self.event("turn_end")
        self.now += 31 * 60
        self.engine.tick()
        self.assertEqual(self.session.state, "done")
        self.now += 30 * 60
        self.engine.tick()
        self.assertFalse(self.engine.sessions)

    def test_duplicate_tool_end_does_not_make_extra_alerts(self):
        self.start()
        self.tool()
        self.wait()
        self.event("tool_end", tool_use_id="tool")
        sequence = self.engine.sound_seq
        self.event("tool_end", tool_use_id="tool")
        self.assertEqual(self.engine.sound_seq, sequence)

    def test_denial_resolves_only_matching_wait(self):
        self.start()
        self.tool()
        self.wait()
        self.event("wait_resolved", tool_name="Other", tool_input_fp="other")
        self.assertEqual(self.session.state, "waiting")
        self.event("wait_resolved", tool_name="Bash", tool_input_fp="fingerprint")
        self.assertEqual(self.session.state, "running")

    def test_global_sound_baseline_includes_hidden_completion_alert(self):
        self.start()
        self.tool()
        self.wait()
        self.event("turn_start", session_id="second")
        self.now += 65
        self.event("turn_end", session_id="second")
        snapshot = self.engine.snapshot()
        self.assertEqual(snapshot["alert"]["kind"], "waiting")
        self.assertEqual(snapshot["alert"]["sound_seq"], 1)
        self.assertEqual(snapshot["current_sound_seq"], 2)
        self.engine.ack(snapshot["alert"]["alert_id"])
        self.assertEqual(self.engine.snapshot()["alert"]["kind"], "done")

    def test_normalization_never_retains_sensitive_fields(self):
        payload = {
            "session_id": "s", "cwd": "/work/blog", "prompt_id": "p",
            "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": "TOKEN=do-not-leak npm test"},
            "prompt": "private prompt", "tool_response": "private file content",
        }
        event = normalize("claude-code", payload, 123, 1, self.engine.config)
        normalized = json.dumps(event.__dict__)
        self.assertNotIn("do-not-leak", normalized)
        self.assertNotIn("private", normalized)
        self.assertEqual(event.detail, "执行命令")
        self.assertEqual(event.turn_id, "p")
        self.assertEqual(len(event.tool_input_fp), 64)

    def test_missing_session_is_ignored(self):
        self.assertIsNone(normalize("claude-code", {"hook_event_name": "Stop"}, 1, 1, self.engine.config))

    def test_codex_and_gemini_maps_are_experimental_but_separate(self):
        for agent, name in (("codex", "UserPromptSubmit"), ("gemini", "BeforeAgent")):
            event = normalize(agent, {"session_id": "same", "cwd": "/tmp/project", "hook_event_name": name}, 1, 1, self.engine.config)
            self.engine.apply(event)
        self.assertEqual(len(self.engine.sessions), 2)

    def test_gemini_notification_metadata_produces_safe_tool_summary(self):
        event = normalize("gemini", {
            "session_id": "gem", "hook_event_name": "Notification",
            "notification_type": "ToolPermission",
            "details": {"tool_name": "read_file", "tool_input": {"absolute_path": "/private/customer/app.py"}},
            "message": "PRIVATE CONTENT",
        }, 123, 1, self.engine.config)
        self.assertEqual(event.kind, "waiting")
        self.assertEqual(event.detail, "读取 app.py")
        self.assertEqual(len(event.tool_input_fp), 64)
        self.assertNotIn("PRIVATE", json.dumps(event.__dict__))

    def test_codex_automatic_reviews_never_become_human_waits_or_sounds(self):
        def native(name, **values):
            self.sequence += 1
            self.now += 0.001
            payload = dict(session_id="cx", cwd="/tmp/project", turn_id="cx-turn", hook_event_name=name)
            payload.update(values)
            event = normalize("codex", payload, int(self.now * 1_000_000), self.sequence, self.engine.config)
            self.engine.apply(event)
            return event

        native("UserPromptSubmit")
        for i in range(3):
            native("PreToolUse", tool_name="Bash", tool_use_id=f"call-{i}", tool_input={"command": f"check {i}"})
            event = native("PermissionRequest", tool_name="Bash", tool_input={"command": f"check {i}", "description": "automatic review"})
            self.assertEqual(event.kind, "permission_check")
            self.now += 20  # A slow review/command is still not proof of a UI prompt.
            self.engine.tick()
            self.assertEqual(self.engine.sessions["codex:cx"].state, "running")
            self.assertFalse(self.engine.sessions["codex:cx"].pending_waits)
            self.assertIsNone(self.engine.snapshot()["alert"])
            native("PostToolUse", tool_name="Bash", tool_use_id=f"call-{i}", tool_input={"command": f"check {i}"})
        self.assertEqual(self.engine.sound_seq, 0)
        native("Stop")
        self.assertEqual(self.engine.sessions["codex:cx"].state, "done")
        self.assertEqual(self.engine.snapshot()["alert"]["sound"], "soft")
        # A delayed async review must not reopen the completed turn.
        native("PermissionRequest", tool_name="Bash", tool_input={"command": "check 2"})
        self.assertEqual(self.engine.sessions["codex:cx"].state, "done")
        self.assertEqual(self.engine.sound_seq, 1)

    def test_restore_removes_only_legacy_codex_permission_inferences(self):
        self.start()
        self.tool()
        self.wait()
        self.wait(agent="codex", turn_id="cx-turn")
        self.event("waiting", agent="codex", wait_kind="question", turn_id="cx-turn")
        data = json.loads(json.dumps(self.engine.export()))
        sequence = self.engine.sound_seq
        self.engine = Engine(self.engine.config, lambda: self.now)
        self.engine.restore(data)
        self.assertEqual(self.session.state, "waiting")
        self.assertEqual(self.session.pending_waits[0]["wait_kind"], "permission")
        cx = self.engine.sessions["codex:session"]
        self.assertEqual([wait["wait_kind"] for wait in cx.pending_waits], ["question"])
        self.assertEqual(cx.label, "回答待确认")
        cx_alerts = [alert for alert in self.engine.alerts.values() if alert.session_key == cx.key]
        self.assertEqual(sum(not alert.acked for alert in cx_alerts), 1)
        self.assertEqual(sum(alert.acked for alert in cx_alerts), 1)
        self.assertTrue(all(alert.sound == "none" for alert in self.engine.alerts.values()))
        self.assertEqual(self.engine.stats["unconfirmed_codex_waits_discarded"], 1)
        self.assertEqual(self.engine.sound_seq, sequence)

    def test_restore_legacy_codex_permissions_returns_card_to_running(self):
        self.wait(agent="codex")
        data = self.engine.export()
        self.engine = Engine(self.engine.config, lambda: self.now)
        self.engine.restore(data)
        cx = self.engine.sessions["codex:session"]
        self.assertEqual(cx.state, "running")
        self.assertEqual(cx.label, "运行中")
        self.assertFalse(cx.pending_waits)
        self.assertIsNone(self.engine.snapshot()["alert"])
        # Migration is idempotent across subsequent supervised restarts.
        data = self.engine.export()
        self.engine.restore(data)
        self.assertIsNone(self.engine.snapshot()["alert"])
        self.assertFalse(self.engine.sessions["codex:session"].pending_waits)


if __name__ == "__main__":
    unittest.main()
