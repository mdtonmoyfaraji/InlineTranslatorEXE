import json
import tempfile
import unittest
from pathlib import Path

from app.settings import SettingsStore, sanitize


class SettingsTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.json"
            st = SettingsStore(p)
            self.assertTrue(st.first_run)
            st.settings.api.base_url = "https://api.example.com/v1"
            st.settings.api.model = "m"
            st.settings.api.api_key = "sk-secret-123456"
            st.settings.prefs.favorites = ["bn", "fr"]
            st.settings.app.insert_method = "type"
            st.save()
            st2 = SettingsStore(p)
            self.assertFalse(st2.first_run)
            self.assertEqual(st2.settings.api.api_key, "sk-secret-123456")
            self.assertEqual(st2.settings.prefs.favorites, ["bn", "fr"])
            self.assertEqual(st2.settings.app.insert_method, "type")

    def test_garbage_file_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.json"
            p.write_text("{not json", encoding="utf-8")
            st = SettingsStore(p)
            self.assertTrue(st.settings.shortcut.enabled)
            self.assertTrue((Path(d) / "settings.broken.json").exists())

    def test_sanitize_rejects_bad_values(self):
        s = sanitize({"prefs": {"target_lang": "auto", "theme": "neon", "favorites": ["bn", "bn", "!!", 5]},
                      "app": {"insert_method": "teleport", "notifications": "yes"},
                      "api": {"timeout_s": 99999, "proxy_mode": "x"}})
        self.assertNotEqual(s.prefs.target_lang, "auto")
        self.assertEqual(s.prefs.theme, "system")
        self.assertEqual(s.prefs.favorites, ["bn"])
        self.assertEqual(s.app.insert_method, "paste")
        self.assertTrue(s.app.notifications)
        self.assertEqual(s.api.timeout_s, 300)
        self.assertEqual(s.api.proxy_mode, "system")

    def test_recent(self):
        with tempfile.TemporaryDirectory() as d:
            st = SettingsStore(Path(d) / "s.json")
            st.push_recent("en", "bn")
            st.push_recent("auto", "fr")
            self.assertEqual(st.settings.prefs.recent[:3], ["fr", "bn", "en"])


if __name__ == "__main__":
    unittest.main()
