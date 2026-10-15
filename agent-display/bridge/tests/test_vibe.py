import json
import tempfile
import time
import unittest
from pathlib import Path

from bridge.vibe import APPLE_EPOCH, VibeCache


class VibeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "sessions.json"
        self.now = time.time()
        self.cache = VibeCache(str(self.path))

    def tearDown(self):
        self.directory.cleanup()

    def write(self, **values):
        item = dict(source="codex", cwd="/private/apple-pickup-watcher", customTitle="检查接口状态",
                    status="processing", lastActivityAt=self.now - APPLE_EPOCH,
                    lastUserMessage="帮我看看接口 token=SECRET", lastAssistantMessage="正在核对接口。",
                    lastAssistantMessageFull="DO NOT COPY FULL TRANSCRIPT", currentTool="Bash")
        item.update(values)
        self.path.write_text(json.dumps({"codex-thread": item}))

    def test_cache_only_card_has_title_excerpt_tool_and_activity_time(self):
        self.write()
        self.assertTrue(self.cache.refresh())
        snapshot = self.cache.decorate({"sessions": [], "alert": None, "current_sound_seq": 7}, self.now, 7200, 900)
        card = snapshot["sessions"][0]
        self.assertEqual(card["key"], "codex:thread")
        self.assertEqual(card["project"], "apple-pickup-watcher")
        self.assertEqual(card["title"], "检查接口状态")
        self.assertEqual(card["assistant_preview"], "正在核对接口。")
        self.assertEqual(card["current_tool"], "Bash")
        self.assertTrue(card["activity_age"])
        self.assertNotIn("SECRET", json.dumps(snapshot))
        self.assertNotIn("DO NOT COPY", json.dumps(snapshot))
        self.assertIsNone(snapshot["alert"])
        self.assertEqual(snapshot["current_sound_seq"], 7)

    def test_enrichment_does_not_override_native_wait_or_duplicate_card(self):
        self.write(codexNotifyThreadId="thread",status="waiting_for_input")
        self.cache.refresh()
        row = dict(key="codex:thread", agent="codex", state="waiting", label="需要授权", detail="执行命令", project="alias")
        alert = {"alert_id": "actual-native-alert"}
        snapshot = self.cache.decorate({"sessions": [row], "alert": alert}, self.now, 7200, 900,
                                      {"codex:thread":self.now-2700})
        self.assertEqual(len(snapshot["sessions"]), 1)
        card = snapshot["sessions"][0]
        self.assertEqual(card["state"], "waiting")
        self.assertEqual(card["project"], "alias")
        self.assertEqual(card["title"], "检查接口状态")
        self.assertIs(snapshot["alert"], alert)
        self.assertNotIn("title", row)

    def test_partial_write_preserves_last_good_cache(self):
        self.write()
        self.cache.refresh()
        self.path.write_text('{"unfinished":')
        self.assertFalse(self.cache.refresh())
        self.assertIn("codex:thread", self.cache.entries)

    def test_long_dialogue_is_bounded_and_redacted_before_device_display(self):
        self.write(customTitle="题" * 300, lastUserMessage="token=SECRET " + "问" * 500,
                   lastAssistantMessage="答" * 500)
        self.cache.refresh()
        entry = self.cache.entries["codex:thread"]
        self.assertEqual(len(entry["title"]), 100)
        self.assertEqual(len(entry["user_preview"]), 240)
        self.assertEqual(len(entry["assistant_preview"]), 240)
        self.assertNotIn("SECRET", entry["user_preview"])
        self.assertTrue(entry["user_preview"].endswith("…"))
        self.assertLess(len(entry["assistant_preview"].encode()), 768)

    def test_old_cache_does_not_reintroduce_inactive_cards(self):
        self.write(lastActivityAt=self.now - APPLE_EPOCH - 8000)
        self.cache.refresh()
        self.assertEqual(self.cache.decorate({"sessions": []}, self.now, 7200, 900)["sessions"], [])

    def test_stale_processing_is_marked_uncertain_and_claude_status_maps(self):
        self.write(lastActivityAt=self.now - APPLE_EPOCH - 1000)
        self.cache.refresh()
        row = self.cache.decorate({"sessions": []}, self.now, 7200, 900)["sessions"][0]
        self.assertTrue(row["stale"])
        self.assertEqual(row["label"], "状态待更新")
        self.write(source="claude", status="waiting_for_input")
        self.cache.refresh()
        row = self.cache.decorate({"sessions": []}, self.now, 7200, 900)["sessions"][0]
        self.assertEqual(row["agent"], "claude-code")
        self.assertEqual(row["state"], "idle")

    def test_idle_cache_does_not_need_periodic_activity_heartbeat(self):
        self.write(status="waiting_for_input", lastActivityAt=self.now - APPLE_EPOCH - 3600)
        self.cache.refresh()
        self.cache.modified_at = self.now - 3600
        row = self.cache.decorate({"sessions": []}, self.now, 7200, 900)["sessions"][0]
        self.assertEqual(row["state"], "idle")
        self.assertFalse(row["stale"])

    def test_newer_activity_repairs_stale_running_hooks_without_inventing_duration(self):
        self.write(lastActivityAt=self.now - APPLE_EPOCH - 2)
        self.cache.refresh()
        native=dict(key='codex:thread',state='running',label='状态待更新',stale=True,elapsed=2700)
        row=self.cache.decorate(dict(sessions=[native]),self.now,7200,900,{'codex:thread':self.now-2700})['sessions'][0]
        self.assertEqual(row['label'],'运行中')
        self.assertFalse(row['stale'])
        self.assertTrue(row['activity_age'])
        self.assertEqual(row['elapsed'],2)
        self.assertIsNone(row['turn_duration_seconds'])
        self.assertEqual(native['label'],'状态待更新')
        self.write(status='waiting_for_input',lastActivityAt=self.now-APPLE_EPOCH-1000)
        self.cache.refresh()
        row=self.cache.decorate(dict(sessions=[native]),self.now,7200,900,{'codex:thread':self.now-2700})['sessions'][0]
        self.assertEqual(row['state'],'idle')
        self.assertEqual(row['label'],'等待输入')
        self.assertFalse(row['stale'])

    def test_cache_does_not_override_fresh_hooks_or_use_older_activity(self):
        self.write(status='waiting_for_input',lastActivityAt=self.now-APPLE_EPOCH-2)
        self.cache.refresh()
        native=dict(key='codex:thread',state='running',label='运行中',stale=False,elapsed=60)
        row=self.cache.decorate(dict(sessions=[native]),self.now,7200,900,{'codex:thread':self.now-10})['sessions'][0]
        self.assertEqual(row['state'],'running')
        native.update(label='状态待更新',stale=True)
        self.write(status='processing',lastActivityAt=self.now-APPLE_EPOCH-3000)
        self.cache.refresh()
        row=self.cache.decorate(dict(sessions=[native]),self.now,7200,900,{'codex:thread':self.now-2700})['sessions'][0]
        self.assertEqual(row['label'],'状态待更新')
        self.assertTrue(row['stale'])

    def test_observed_running_tool_status_is_active_with_or_without_stale_hooks(self):
        self.write(status='running_tool',lastActivityAt=self.now-APPLE_EPOCH-2)
        self.cache.refresh()
        only=self.cache.decorate(dict(sessions=[]),self.now,7200,900)['sessions'][0]
        self.assertEqual(only['state'],'running')
        self.assertEqual(only['label'],'运行中')
        native=dict(key='codex:thread',state='running',label='状态待更新',stale=True)
        merged=self.cache.decorate(dict(sessions=[native]),self.now,7200,900,{'codex:thread':self.now-3000})['sessions'][0]
        self.assertEqual(merged['label'],'运行中')
        self.assertFalse(merged['stale'])

    def test_missing_or_invalid_cache_is_optional(self):
        self.assertFalse(self.cache.refresh())
        self.path.write_text(json.dumps({"bad": {"source": [], "lastActivityAt": 1}}))
        self.cache.refresh()
        self.assertEqual(self.cache.entries, {})

    def test_native_recency_is_preserved_when_cache_has_no_matching_entry(self):
        snapshot = {"sessions": [
            dict(key="codex:older", state="running"),
            dict(key="codex:newer", state="running"),
        ]}
        rows = self.cache.decorate(snapshot, self.now, 7200, 900,
                                   {"codex:older": self.now - 60, "codex:newer": self.now})["sessions"]
        self.assertEqual(rows[0]["key"], "codex:newer")
