import unittest

from app.gesture import SelectionGesture


class GestureTests(unittest.TestCase):
    def test_drag_is_a_selection(self):
        g = SelectionGesture()
        g.on_down(100, 100, 0)
        self.assertTrue(g.on_up(180, 104, 300))

    def test_single_click_is_not(self):
        g = SelectionGesture()
        g.on_down(100, 100, 0)
        self.assertFalse(g.on_up(101, 100, 60))

    def test_double_click_selects_a_word(self):
        g = SelectionGesture()
        g.on_down(100, 100, 0)
        g.on_up(100, 100, 50)
        g.on_down(101, 100, 200)
        self.assertTrue(g.on_up(101, 100, 250))

    def test_two_slow_clicks_are_not_a_double_click(self):
        g = SelectionGesture()
        g.on_down(100, 100, 0)
        g.on_up(100, 100, 50)
        g.on_down(100, 100, 2000)
        self.assertFalse(g.on_up(100, 100, 2050))

    def test_clicks_far_apart_are_not_a_double_click(self):
        g = SelectionGesture()
        g.on_down(100, 100, 0)
        g.on_up(100, 100, 50)
        g.on_down(400, 300, 200)
        self.assertFalse(g.on_up(400, 300, 250))

    def test_triple_click(self):
        g = SelectionGesture()
        for t in (0, 150, 300):
            g.on_down(50, 50, t)
            res = g.on_up(50, 50, t + 40)
        self.assertTrue(res)

    def test_up_without_down(self):
        self.assertFalse(SelectionGesture().on_up(1, 1, 5))


if __name__ == "__main__":
    unittest.main()
