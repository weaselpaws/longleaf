"""Editor undo history tests — pure Python, no Qt. Run: python -m pytest tests"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from undo_stack import MAX_STEPS, UndoStack  # noqa: E402


def snap(n):
    return {"title": f"v{n}"}


def test_undo_and_redo_walk_the_history():
    u = UndoStack(snap(0))
    assert not u.can_undo() and not u.can_redo() and u.undo() is None and u.redo() is None
    u.record(snap(1))
    u.record(snap(2))
    assert u.undo() == snap(1) and u.undo() == snap(0) and u.undo() is None
    assert u.redo() == snap(1) and u.redo() == snap(2) and u.redo() is None


def test_a_new_edit_clears_redo():
    u = UndoStack(snap(0))
    u.record(snap(1))
    u.undo()
    assert u.can_redo()
    u.record(snap(9))
    assert not u.can_redo() and u.undo() == snap(0)


def test_unchanged_snapshots_are_not_edits():
    u = UndoStack(snap(0))
    assert u.record(snap(0)) is False and not u.can_undo()
    assert u.record(snap(1)) is True


def test_typing_with_the_same_key_collapses_into_one_step():
    u = UndoStack(snap(0))
    for i, t in enumerate((10.0, 10.2, 10.4)):
        u.record(snap(i + 1), key="title", now=t)
    assert u.undo() == snap(0) and not u.can_undo()          # all three keystrokes undo together
    assert u.redo() == snap(3)


def test_keys_collapse_only_when_same_key_and_close_in_time():
    u = UndoStack(snap(0))
    u.record(snap(1), key="title", now=10.0)
    u.record(snap(2), key="meta", now=10.1)                  # different place
    u.record(snap(3), key="meta", now=20.0)                  # same place, long pause
    u.record(snap(4), now=20.1)                              # keyless never merges
    u.record(snap(5), now=20.2)
    got = []
    while (s := u.undo()) is not None:
        got.append(s)
    assert got == [snap(4), snap(3), snap(2), snap(1), snap(0)]


def test_undo_ends_a_typing_burst():
    u = UndoStack(snap(0))
    u.record(snap(1), key="title", now=1.0)
    u.undo()
    u.record(snap(2), key="title", now=1.1)                  # must not merge into the undone step
    assert u.undo() == snap(0) and not u.can_undo()


def test_reset_starts_over_and_snapshots_are_copies():
    u = UndoStack(snap(0))
    u.record(snap(1))
    u.reset(snap(5))
    assert not u.can_undo() and not u.can_redo() and u.current == snap(5)
    s = {"title": "x", "steps": {"a": 1}}
    u.record(s)
    s["steps"]["a"] = 2                                      # caller mutating later must not rewrite history
    assert u.undo() == snap(5)
    assert u.redo() == {"title": "x", "steps": {"a": 1}}


def test_history_is_capped():
    u = UndoStack(snap(0), max_steps=5)
    for i in range(1, 20):
        u.record(snap(i))
    n = 0
    while u.undo() is not None:
        n += 1
    assert n == 5 and MAX_STEPS >= 50
