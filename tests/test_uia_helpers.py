import unittest

from app.uia import (anchor_from_element, anchor_from_ui_rects, anchor_from_window, is_plausible_screen_rect,
                     looks_like_line_copy)
from app.winapi import Rect

SCREENS = [Rect(0, 0, 1920, 1080), Rect(1920, 0, 3840, 1080)]


class AnchorTests(unittest.TestCase):
    def test_caret_rect(self):
        r = anchor_from_ui_rects([(500.0, 300.0, 1.0, 20.0)])
        self.assertEqual((r.left, r.top, r.bottom), (501, 300, 320))

    def test_multi_line_selection_uses_end_of_last_line(self):
        r = anchor_from_ui_rects([(100.0, 100.0, 400.0, 20.0), (100.0, 120.0, 150.0, 20.0)])
        self.assertEqual((r.left, r.top, r.bottom), (250, 120, 140))

    def test_empty_or_degenerate(self):
        self.assertIsNone(anchor_from_ui_rects([]))
        self.assertIsNone(anchor_from_ui_rects([(10.0, 10.0, 5.0, 0.0)]))
        self.assertIsNone(anchor_from_ui_rects([(10.0, 10.0, 5.0, 900.0)]))

    def test_element_anchor(self):
        small = anchor_from_element(Rect(100, 100, 500, 130))
        self.assertEqual((small.top, small.bottom), (100, 130))
        big = anchor_from_element(Rect(0, 0, 1000, 800))
        self.assertLess(big.bottom, 100)  # near the top-left, not below the whole page
        self.assertIsNone(anchor_from_element(Rect(0, 0, 0, 0)))
        self.assertIsNone(anchor_from_element(None))

    def test_window_anchor(self):
        r = anchor_from_window(Rect(0, 0, 1000, 800))
        self.assertEqual(r.left, 500)
        self.assertGreater(r.top, 100)

    def test_plausibility(self):
        self.assertTrue(is_plausible_screen_rect(Rect(100, 100, 101, 120), SCREENS))
        self.assertTrue(is_plausible_screen_rect(Rect(2500, 100, 2501, 120), SCREENS))
        self.assertFalse(is_plausible_screen_rect(Rect(0, 0, 0, 0), SCREENS))
        self.assertFalse(is_plausible_screen_rect(Rect(-5000, 100, -4999, 120), SCREENS))
        self.assertFalse(is_plausible_screen_rect(Rect(100, 100, 101, 900), SCREENS))
        self.assertFalse(is_plausible_screen_rect(None, SCREENS))

    def test_line_copy_heuristic(self):
        self.assertTrue(looks_like_line_copy("const x = 1;\r\n"))
        self.assertFalse(looks_like_line_copy("hello"))
        self.assertFalse(looks_like_line_copy("a\nb\n"))  # a real multi-line selection
        self.assertFalse(looks_like_line_copy("a\r\nb"))


if __name__ == "__main__":
    unittest.main()
