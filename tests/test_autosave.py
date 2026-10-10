"""Editor autosave / crash-recovery tests — pure Python, no Qt. Run: python -m pytest tests"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autosave import AutosaveStore  # noqa: E402

TREE = {"title": "My flow", "root_id": "a", "steps": {}}


def test_write_pending_and_discard(tmp_path):
    s = AutosaveStore(tmp_path / "auto")
    assert s.pending() == []                                   # folder doesn't exist yet
    flow = str(tmp_path / "clients" / "acme" / "flow.json")
    assert s.write(flow, TREE)
    (rec,) = s.pending()
    assert rec.flow_path == flow and rec.tree == TREE and rec.title == "My flow"
    assert "flow.json" in rec.label and "autosaved" in rec.label
    s.write(flow, {**TREE, "title": "Edited"})                 # replaced, not duplicated
    assert [r.title for r in s.pending()] == ["Edited"]
    s.discard(flow)
    s.discard(flow)                                            # idempotent
    assert s.pending() == []


def test_unsaved_flows_use_a_per_session_slot_and_survive_a_restart(tmp_path):
    first = AutosaveStore(tmp_path)
    first.write(None, TREE)
    second = AutosaveStore(tmp_path)                           # the next launch
    assert second.slot_for(None) != first.slot_for(None)
    (rec,) = second.pending()
    assert rec.flow_path is None and rec.label.startswith("My flow")
    second.discard_slot(rec.slot)
    assert second.pending() == []


def test_different_flows_get_different_slots(tmp_path):
    s = AutosaveStore(tmp_path)
    s.write("/a/flow.json", TREE)
    s.write("/b/flow.json", {**TREE, "title": "Other"})
    assert len(s.pending()) == 2


def test_newest_first_and_junk_is_ignored(tmp_path):
    s = AutosaveStore(tmp_path)
    s.write("/a/flow.json", TREE)
    s.write("/b/flow.json", TREE)
    for p in tmp_path.glob("*.autosave.json"):
        d = json.loads(p.read_text())
        d["saved_at"] = "2026-01-01T00:00:00+00:00" if d["flow_path"] == "/a/flow.json" else "2026-02-01T00:00:00+00:00"
        p.write_text(json.dumps(d))
    (tmp_path / "bad.autosave.json").write_text("{not json")
    (tmp_path / "other.autosave.json").write_text('{"kind": "something-else", "tree": {}}')
    (tmp_path / "notree.autosave.json").write_text('{"kind": "longleaf-autosave"}')
    assert [r.flow_path for r in s.pending()] == ["/b/flow.json", "/a/flow.json"]


def test_unwritable_folder_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    s = AutosaveStore(blocker / "sub")                         # a file is in the way
    assert s.write(None, TREE) is False
    s.discard(None)
    assert s.pending() == []
