import json
import tempfile
import unittest
from pathlib import Path

from install_hooks import AGENTS, merge, run


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.home = Path(self.directory.name)
        self.path = self.home / ".claude/settings.json"

    def tearDown(self):
        self.directory.cleanup()

    def write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data))

    def test_install_idempotent_uninstall_preserves_other_hooks_and_settings(self):
        original = {
            "theme": "dark",
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "existing-check"}]}]},
        }
        self.write(original)
        run("install", self.home, ["claude-code"], 8787)
        installed = json.loads(self.path.read_text())
        run("install", self.home, ["claude-code"], 8787)
        self.assertEqual(json.loads(self.path.read_text()), installed)
        run("uninstall", self.home, ["claude-code"], 8787)
        self.assertEqual(json.loads(self.path.read_text()), original)
        self.assertFalse((self.home / ".local/bin/agent-display-hook").exists())
        self.assertTrue(list(self.path.parent.glob("settings.json.bak-*")))

    def test_empty_original_hooks_are_preserved(self):
        original = {"hooks": {"Stop": []}}
        self.write(original)
        run("install", self.home, ["claude-code"], 8787)
        run("uninstall", self.home, ["claude-code"], 8787)
        self.assertEqual(json.loads(self.path.read_text()), original)

    def test_original_without_hooks_round_trips(self):
        original = {"theme": "dark"}
        self.write(original)
        run("install", self.home, ["claude-code"], 8787)
        run("uninstall", self.home, ["claude-code"], 8787)
        self.assertEqual(json.loads(self.path.read_text()), original)

    def test_new_config_is_removed_on_uninstall(self):
        run("install", self.home, ["claude-code"], 8787)
        self.assertTrue(self.path.exists())
        run("uninstall", self.home, ["claude-code"], 8787)
        self.assertFalse(self.path.exists())

    def test_invalid_json_does_not_install_anything(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{invalid")
        with self.assertRaises(ValueError):
            run("install", self.home, ["claude-code"], 8787)
        self.assertFalse((self.home / ".local/bin/agent-display-hook").exists())

    def test_dry_run_has_no_writes(self):
        run("install", self.home, ["claude-code"], 8787, dry_run=True)
        self.assertFalse(self.path.exists())
        self.assertFalse((self.home / ".local").exists())

    def test_new_user_settings_added_after_install_survive(self):
        run("install", self.home, ["claude-code"], 8787)
        data = json.loads(self.path.read_text())
        data["userAdded"] = True
        self.path.write_text(json.dumps(data))
        run("uninstall", self.home, ["claude-code"], 8787)
        self.assertEqual(json.loads(self.path.read_text()), {"userAdded": True})

    def test_codex_timeout_and_gemini_stdout_config(self):
        for agent in ("codex", "gemini"):
            data = merge({}, agent, self.home / "relay")
            event = AGENTS[agent]["events"][0]
            handler = data["hooks"][event][0]["hooks"][0]
            self.assertEqual(handler["timeout"], 3000 if agent == "gemini" else 3)

    def test_codex_session_end_is_synchronous_and_existing_hooks_preserved(self):
        original = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "existing-hook"}]}]}}
        data = merge(original, "codex", self.home / "relay")
        self.assertFalse(data["hooks"]["SessionEnd"][0]["hooks"][0]["async"])
        self.assertEqual(data["hooks"]["SessionStart"][0], original["hooks"]["SessionStart"][0])


if __name__ == "__main__":
    unittest.main()
