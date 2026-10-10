"""
Longleaf - undo/redo history for the Editor (no GUI).

Whole-flow snapshots (the dict from `Tree.to_dict()`): simple, and it covers
every kind of edit - typing, adding/deleting steps, branding - without each
one needing its own undo command. Flows are small, so storing a few hundred
snapshots is cheap.

Editor only; the Player never imports this (see build_client_release.py).
"""

from __future__ import annotations

import copy
import time
from typing import Optional

COALESCE_SECONDS = 1.0   # edits with the same key closer together than this share one undo step
MAX_STEPS = 200


class UndoStack:
    def __init__(self, initial: dict, max_steps: int = MAX_STEPS):
        self.max_steps = max_steps
        self._current = copy.deepcopy(initial)
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._last_key: Optional[str] = None
        self._last_time = 0.0

    @property
    def current(self) -> dict:
        return copy.deepcopy(self._current)

    def reset(self, snapshot: dict):
        """Start a new history (file opened / new flow)."""
        self._current = copy.deepcopy(snapshot)
        self._undo.clear()
        self._redo.clear()
        self._last_key = None

    def record(self, snapshot: dict, key: Optional[str] = None, now: Optional[float] = None) -> bool:
        """Note that the flow is now `snapshot`. Returns True if that is a change.
        A `key` (e.g. 'title', 'step:a') lets a burst of typing in one place
        collapse into a single undo step; keyless edits always get their own."""
        if snapshot == self._current:
            return False
        now = time.monotonic() if now is None else now
        coalesce = (key is not None and key == self._last_key and now - self._last_time < COALESCE_SECONDS
                    and bool(self._undo))
        if not coalesce:
            self._undo.append(self._current)
            del self._undo[:-self.max_steps]
        self._current = copy.deepcopy(snapshot)
        self._redo.clear()
        self._last_key, self._last_time = key, now
        return True

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> Optional[dict]:
        if not self._undo:
            return None
        self._redo.append(self._current)
        self._current = self._undo.pop()
        self._last_key = None      # the next edit starts a fresh step
        return self.current

    def redo(self) -> Optional[dict]:
        if not self._redo:
            return None
        self._undo.append(self._current)
        self._current = self._redo.pop()
        self._last_key = None
        return self.current
