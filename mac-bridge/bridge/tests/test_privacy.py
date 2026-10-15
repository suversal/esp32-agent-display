import unittest

from bridge.privacy import redact, safe_text, summarize


class PrivacyTests(unittest.TestCase):
    def test_defaults_hide_commands_patterns_urls_and_task_descriptions(self):
        self.assertEqual(summarize("Bash", {"command": "password=SECRET"}), "执行命令")
        self.assertEqual(summarize("Grep", {"pattern": "PRIVATE"}), "搜索代码")
        self.assertEqual(summarize("WebFetch", {"url": "https://private.test"}), "访问网页")
        self.assertEqual(summarize("Task", {"description": "PRIVATE"}), "子任务")

    def test_file_summary_only_contains_basename(self):
        self.assertEqual(summarize("Read", {"file_path": "/private/customer/config.ts"}), "读取 config.ts")

    def test_gemini_absolute_path_and_namespaced_codex_tools(self):
        self.assertEqual(summarize("read_file", {"absolute_path": "/private/customer/config.ts"}), "读取 config.ts")
        self.assertEqual(summarize("functions.exec_command", {"cmd": "token=SECRET"}), "执行命令")
        self.assertEqual(summarize("functions.update_plan", {"plan": "PRIVATE"}), "更新计划")

    def test_codex_patch_summary_excludes_patch_content_and_directory(self):
        patch = "*** Begin Patch\n*** Update File: /private/customer/app.py\n@@\n+TOKEN=SECRET\n*** End Patch"
        self.assertEqual(summarize("apply_patch", {"command": patch}), "编辑 app.py")
        self.assertEqual(summarize("functions.apply_patch", patch), "编辑 app.py")
        self.assertEqual(summarize("apply_patch", {}), "编辑")

    def test_redaction_precedes_truncation(self):
        detail = summarize("Bash", {"command": "curl --password 'SECRET' https://user:pass@example.test"}, detailed=True)
        self.assertNotIn("SECRET", detail)
        self.assertNotIn("user:pass", detail)
        self.assertLessEqual(len(detail), 40)

    def test_authorization_and_long_tokens_are_redacted(self):
        self.assertNotIn("my-token", redact("Authorization: Bearer my-token"))
        self.assertEqual(redact("token=SECRET"), "token=***")
        self.assertEqual(redact("a" * 32), "***")

    def test_unicode_truncation_and_control_filtering(self):
        self.assertEqual(safe_text("中" * 50, 40), "中" * 39 + "…")
        self.assertEqual(safe_text("name\ninjected\x1b"), "nameinjected")


if __name__ == "__main__":
    unittest.main()
