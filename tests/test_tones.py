import tempfile
import unittest
from pathlib import Path

from app.ai import AIError, build_translation_messages
from app.languages import AUTO, NONE, is_valid_target_code, language_name
from app.settings import SettingsStore, sanitize
from app.tones import (MAX_CUSTOM_TONE_LENGTH, TONE_DEFAULT, TONES, is_valid_tone_code,
                       make_custom_tone_code, search_tones, tone_instruction, tone_name)


class ToneTests(unittest.TestCase):
    def test_builtin_tones_match_the_extension(self):
        self.assertEqual([t.code for t in TONES],
                         ["improve", "advanced", "formal", "short", "tribal", "corp", "biblical", "viking", "zen", "emojify"])
        self.assertIn("Odin", tone_instruction("viking").instruction)

    def test_validation(self):
        self.assertTrue(is_valid_tone_code(TONE_DEFAULT))
        self.assertTrue(is_valid_tone_code("formal"))
        self.assertTrue(is_valid_tone_code("custom:pirate"))
        self.assertFalse(is_valid_tone_code("custom:"))
        self.assertFalse(is_valid_tone_code("nonsense"))
        self.assertFalse(is_valid_tone_code("custom:" + "x" * (MAX_CUSTOM_TONE_LENGTH + 1)))
        self.assertFalse(is_valid_tone_code(5))

    def test_custom_tone_code_is_normalised_and_capped(self):
        self.assertEqual(make_custom_tone_code("  friendly   but  firm "), "custom:friendly but firm")
        self.assertEqual(len(make_custom_tone_code("y" * 200)) - len("custom:"), MAX_CUSTOM_TONE_LENGTH)
        self.assertEqual(tone_name("custom:pirate"), "pirate")
        self.assertIn('"pirate"', tone_instruction("custom:pirate").instruction)

    def test_search(self):
        self.assertEqual([t.name for t in search_tones("vik")], ["Viking"])
        self.assertIn("Zen", [t.name for t in search_tones("calm")])  # matches the hint
        self.assertEqual(len(search_tones("")), len(TONES))

    def test_none_target(self):
        self.assertTrue(is_valid_target_code(NONE))
        self.assertFalse(is_valid_target_code(AUTO))
        self.assertEqual(language_name(NONE), "No translation")


class PromptTests(unittest.TestCase):
    def sys_prompt(self, *a):
        return build_translation_messages("hello", *a)[0]["content"]

    def test_translate_only(self):
        p = self.sys_prompt("en", "fr")
        self.assertIn("translation engine", p)
        self.assertNotIn("Tone:", p)

    def test_translate_with_tone(self):
        p = self.sys_prompt("en", "fr", "formal")
        self.assertIn("Then write the result in French with this tone: Formal", p)
        self.assertIn("Tone: Formal", p)

    def test_tone_only(self):
        p = self.sys_prompt(AUTO, NONE, "zen")
        self.assertIn("SAME language", p)
        self.assertIn("Do NOT translate", p)

    def test_tone_only_without_tone_is_rejected(self):
        with self.assertRaises(AIError):
            build_translation_messages("hello", AUTO, NONE, TONE_DEFAULT)

    def test_user_message_wraps_text(self):
        self.assertEqual(build_translation_messages("hi", "en", "fr")[1]["content"], "<text>\nhi\n</text>")


class SettingsToneTests(unittest.TestCase):
    def test_sanitize(self):
        s = sanitize({"prefs": {"target_lang": "none", "tone": "custom:pirate",
                                "tone_favorites": ["formal", "formal", "default", "bad", "custom:x"],
                                "tone_recent": ["zen"]}})
        self.assertEqual(s.prefs.target_lang, NONE)
        self.assertEqual(s.prefs.tone, "custom:pirate")
        self.assertEqual(s.prefs.tone_favorites, ["formal", "custom:x"])
        self.assertEqual(s.prefs.tone_recent, ["zen"])

    def test_bad_values_fall_back(self):
        s = sanitize({"prefs": {"target_lang": "auto", "tone": "nope"}})
        self.assertNotEqual(s.prefs.target_lang, AUTO)
        self.assertEqual(s.prefs.tone, TONE_DEFAULT)

    def test_recent_rules(self):
        with tempfile.TemporaryDirectory() as d:
            st = SettingsStore(Path(d) / "s.json")
            st.push_recent("en", "fr", "formal")
            self.assertEqual(st.settings.prefs.recent, ["fr", "en"])
            self.assertEqual(st.settings.prefs.tone_recent, ["formal"])
            st.push_recent("auto", NONE, "zen")  # tone only: languages untouched
            self.assertEqual(st.settings.prefs.recent, ["fr", "en"])
            self.assertEqual(st.settings.prefs.tone_recent, ["zen", "formal"])
            st.push_recent("auto", "de", TONE_DEFAULT)  # no tone: tone list untouched
            self.assertEqual(st.settings.prefs.tone_recent, ["zen", "formal"])
            st2 = SettingsStore(Path(d) / "s.json")
            self.assertEqual(st2.settings.prefs.tone_recent, ["zen", "formal"])


if __name__ == "__main__":
    unittest.main()
