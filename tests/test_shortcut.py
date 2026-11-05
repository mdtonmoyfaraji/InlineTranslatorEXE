import unittest

from app.shortcut import (KeyInfo, SequenceDetector, ShortcutConfig, format_shortcut,
                          validate_shortcut, vk_to_code)


def cfg(**kw):
    return ShortcutConfig(**kw)


class SequenceTests(unittest.TestCase):
    def test_combo_single_press(self):
        d = SequenceDetector(cfg())
        self.assertEqual(d.on_key_down(KeyInfo("KeyY", ctrl=True, shift=True), 0), "completed")

    def test_combo_wrong_modifiers(self):
        d = SequenceDetector(cfg())
        self.assertEqual(d.on_key_down(KeyInfo("KeyY", ctrl=True), 0), "reset")

    def test_repeat_ignored(self):
        d = SequenceDetector(cfg())
        self.assertEqual(d.on_key_down(KeyInfo("KeyY", ctrl=True, shift=True, repeat=True), 0), "ignored")

    def test_double_press_within_interval(self):
        d = SequenceDetector(cfg(press_count=2, max_interval_ms=300))
        k = KeyInfo("KeyY", ctrl=True, shift=True)
        self.assertEqual(d.on_key_down(k, 0), "progress")
        self.assertEqual(d.on_key_down(k, 200), "completed")

    def test_double_press_too_slow(self):
        d = SequenceDetector(cfg(press_count=2, max_interval_ms=300))
        k = KeyInfo("KeyY", ctrl=True, shift=True)
        d.on_key_down(k, 0)
        self.assertEqual(d.on_key_down(k, 900), "progress")

    def test_other_key_resets(self):
        d = SequenceDetector(cfg(press_count=2))
        k = KeyInfo("KeyY", ctrl=True, shift=True)
        d.on_key_down(k, 0)
        d.on_key_down(KeyInfo("KeyA"), 50)
        self.assertEqual(d.on_key_down(k, 100), "progress")

    def test_modifier_between_presses_does_not_reset(self):
        d = SequenceDetector(cfg(press_count=2))
        k = KeyInfo("KeyY", ctrl=True, shift=True)
        d.on_key_down(k, 0)
        self.assertEqual(d.on_key_down(KeyInfo("ControlLeft", ctrl=True), 50), "ignored")
        self.assertEqual(d.on_key_down(k, 100), "completed")

    def test_modifier_only_double_tap(self):
        d = SequenceDetector(cfg(code="Control", ctrl=False, shift=False, press_count=2))
        for t in (0, 150):
            self.assertEqual(d.on_key_down(KeyInfo("ControlLeft", ctrl=True), t), "ignored")
            r = d.on_key_up(KeyInfo("ControlLeft"), t + 40)
        self.assertEqual(r, "completed")

    def test_modifier_only_dirty_tap(self):
        d = SequenceDetector(cfg(code="Control", ctrl=False, shift=False, press_count=2))
        d.on_key_down(KeyInfo("ControlLeft", ctrl=True), 0)
        d.on_key_down(KeyInfo("KeyC", ctrl=True), 10)  # Ctrl+C is not a tap
        self.assertEqual(d.on_key_up(KeyInfo("ControlLeft"), 20), "ignored")

    def test_disabled(self):
        d = SequenceDetector(cfg(enabled=False))
        self.assertEqual(d.on_key_down(KeyInfo("KeyY", ctrl=True, shift=True), 0), "ignored")


class ValidationTests(unittest.TestCase):
    def test_default_is_valid(self):
        self.assertEqual(validate_shortcut(cfg()).errors, [])

    def test_ctrl_c_rejected(self):
        self.assertTrue(validate_shortcut(cfg(code="KeyC", shift=False)).errors)

    def test_win_rejected(self):
        self.assertTrue(validate_shortcut(cfg(meta=True)).errors)

    def test_single_modifier_tap_rejected(self):
        self.assertTrue(validate_shortcut(cfg(code="Control", ctrl=False, shift=False, press_count=1)).errors)

    def test_modifier_double_tap_ok(self):
        v = validate_shortcut(cfg(code="Control", ctrl=False, shift=False, press_count=2))
        self.assertEqual(v.errors, [])
        self.assertTrue(v.warnings)

    def test_plain_key_needs_ack(self):
        c = cfg(code="KeyJ", ctrl=False, shift=False, press_count=3)
        self.assertTrue(validate_shortcut(c).errors)
        c.acknowledged_bare_key_risk = True
        self.assertEqual(validate_shortcut(c).errors, [])

    def test_format(self):
        self.assertEqual(format_shortcut(cfg()), "Ctrl+Shift+Y")
        self.assertEqual(format_shortcut(cfg(code="Control", ctrl=False, shift=False, press_count=2)), "Ctrl × 2")

    def test_vk_names(self):
        self.assertEqual(vk_to_code(0x59), "KeyY")
        self.assertEqual(vk_to_code(0xA2), "ControlLeft")
        self.assertEqual(vk_to_code(0x78), "F9")
        self.assertEqual(vk_to_code(0x31), "Digit1")

    def test_from_dict_sanitises(self):
        c = ShortcutConfig.from_dict({"press_count": 99, "max_interval_ms": "x", "code": "", "enabled": "yes"})
        self.assertEqual(c.press_count, 5)
        self.assertEqual(c.max_interval_ms, 400)
        self.assertEqual(c.code, "KeyY")
        self.assertTrue(c.enabled)


if __name__ == "__main__":
    unittest.main()
