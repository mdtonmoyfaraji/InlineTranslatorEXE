"""Detects "the user just selected text with the mouse" from raw button events (pure logic)."""
from __future__ import annotations

import math


class SelectionGesture:
    """A selection gesture is a drag, or a double / triple click (word / line selection)."""

    def __init__(self, drag_px: float = 6.0, double_click_ms: int = 500, double_click_px: float = 6.0):
        self.drag_px = drag_px
        self.double_click_ms = double_click_ms
        self.double_click_px = double_click_px
        self._down: tuple[float, float] | None = None
        self._last_down: tuple[float, float, float] | None = None
        self._clicks = 0

    def on_down(self, x: float, y: float, t_ms: float) -> None:
        last = self._last_down
        if last and t_ms - last[2] <= self.double_click_ms and math.hypot(x - last[0], y - last[1]) <= self.double_click_px:
            self._clicks += 1
        else:
            self._clicks = 1
        self._last_down = (x, y, t_ms)
        self._down = (x, y)

    def on_up(self, x: float, y: float, t_ms: float) -> bool:
        """True when the button release completes a selection-like gesture."""
        down, self._down = self._down, None
        if down is None:
            return False
        if math.hypot(x - down[0], y - down[1]) > self.drag_px:
            return True
        return self._clicks >= 2

    def cancel(self) -> None:
        self._down = None
        self._last_down = None
        self._clicks = 0
