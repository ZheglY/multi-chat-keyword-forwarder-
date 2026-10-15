import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from utils.monitor_settings import DEFAULT_SETTINGS_PATH, MonitorSettings, MonitorSettingsError


class MonitorSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "settings.json"
        self.settings = MonitorSettings(self.path)

    def test_missing_file_defaults_without_writing(self):
        self.assertEqual(self.settings.get_mode(), "simple")
        self.assertEqual(self.settings.get_chats(), [])
        self.assertIsNone(self.settings.get_chat(-1001))
        self.assertFalse(self.settings.delete_chat(-1001))
        self.assertFalse(self.path.exists())

    def test_default_path_is_project_relative_not_cwd(self):
        previous = Path.cwd()
        try:
            os.chdir(self.directory.name)
            settings = MonitorSettings()
        finally:
            os.chdir(previous)
        expected = Path(__file__).resolve().parents[1] / "config" / "monitor_settings.json"
        self.assertTrue(settings.file_path.is_absolute())
        self.assertEqual(settings.file_path, expected)
        self.assertEqual(settings.file_path, DEFAULT_SETTINGS_PATH)

    def test_save_update_delete_and_reload(self):
        self.settings.save_chat(-1001, "Чат", "https://t.me/example")
        self.settings.save_chat(-1002, "Second")
        self.settings.save_chat(-1001, "Updated", "https://t.me/renamed")
        reloaded = MonitorSettings(self.path)
        self.assertEqual(len(reloaded.get_chats()), 2)
        self.assertEqual(reloaded.get_chat(-1001)["title"], "Updated")
        self.assertTrue(reloaded.delete_chat(-1001))
        self.assertIsNone(MonitorSettings(self.path).get_chat(-1001))
        self.assertEqual(MonitorSettings(self.path).get_chat(-1002)["title"], "Second")

    def test_mode_switch_preserves_chats_across_restarts(self):
        self.settings.save_chat(-1001, "Чат")
        expected = self.settings.get_chats()
        for mode in ("advanced", "simple"):
            self.settings.set_mode(mode)
            self.settings = MonitorSettings(self.path)
            self.assertEqual(self.settings.get_mode(), mode)
            self.assertEqual(self.settings.get_chats(), expected)

    def test_invalid_inputs_do_not_modify_file(self):
        self.settings.save_chat(-1001)
        before = self.path.read_bytes()
        for operation in (
            lambda: self.settings.set_mode("unknown"),
            lambda: self.settings.save_chat(True),
            lambda: self.settings.save_chat("-1001"),
            lambda: self.settings.save_chat(-1002, title=None),
        ):
            with self.assertRaises(ValueError):
                operation()
            self.assertEqual(self.path.read_bytes(), before)

    def test_corrupt_files_are_preserved_and_reported(self):
        for content in (b"", b"{broken", b"\xff", b"null", b"{}",
                        b'{"mode":"other","chats":[]}',
                        b'{"mode":"simple","chats":[{"id":true}]}'):
            self.path.write_bytes(content)
            for operation in (
                self.settings.get_mode, self.settings.get_chats,
                lambda: self.settings.get_chat(-1001),
                lambda: self.settings.set_mode("advanced"),
                lambda: self.settings.save_chat(-1001),
                lambda: self.settings.delete_chat(-1001),
            ):
                with self.subTest(content=content, operation=operation):
                    with self.assertRaises(MonitorSettingsError):
                        operation()
                    self.assertEqual(self.path.read_bytes(), content)

    def test_failed_atomic_replace_preserves_previous_file(self):
        self.settings.save_chat(-1001)
        before = self.path.read_bytes()
        with patch("utils.monitor_settings.os.replace", side_effect=OSError("failure")):
            with self.assertRaises(OSError):
                self.settings.set_mode("advanced")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_atomic_replace_receives_complete_json_in_same_directory(self):
        replace = os.replace

        def inspect_replace(source, destination):
            self.assertEqual(Path(source).parent, self.path.parent)
            self.assertEqual(json.loads(Path(source).read_text(encoding="utf-8")),
                             {"mode": "advanced", "chats": []})
            replace(source, destination)

        with patch("utils.monitor_settings.os.replace", side_effect=inspect_replace) as mocked:
            self.settings.set_mode("advanced")
        mocked.assert_called_once()
        self.assertEqual(MonitorSettings(self.path).get_mode(), "advanced")

    def test_returned_records_cannot_mutate_stored_settings(self):
        self.settings.save_chat(-1001, "Original")
        self.settings.get_chat(-1001)["title"] = "Changed"
        self.settings.get_chats().clear()
        self.assertEqual(self.settings.get_chat(-1001)["title"], "Original")


if __name__ == "__main__":
    unittest.main()
