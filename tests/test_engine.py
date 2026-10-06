"""Engine tests — pure Python, no Qt. Run: python -m pytest tests"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import (  # noqa: E402
    FlowFormatError, HistoryEntry, Option, SessionRecord, Step, Tree, TroubleshootEngine,
    OUTCOME_ERROR, OUTCOME_IN_PROGRESS, OUTCOME_RESOLVED, SEVERITY_ERROR, SEVERITY_WARNING,
)

ROOT = Path(__file__).resolve().parent.parent


def tree_of(*steps, root=None, **kw) -> Tree:
    return Tree(title="T", root_id=root or steps[0].id, steps={s.id: s for s in steps}, **kw)


def end(label="done", text="Fixed it."):
    return Option(label, None, text)


def codes(tree: Tree) -> set[str]:
    return {i.code for i in tree.check()}


# ---------- shipped flows ----------

@pytest.mark.parametrize("path", sorted(ROOT.glob("examples/*.json")) + [ROOT / "flow.json", ROOT / "sample_tree.json"])
def test_shipped_flows_have_no_errors(path):
    assert Tree.load(str(path)).errors() == []


def test_legacy_flow_without_metadata_loads():
    t = Tree.from_dict({"title": "Old", "root_id": "a",
                        "steps": {"a": {"id": "a", "question": "Q", "options": [{"label": "x", "resolution": "r"}]}}})
    assert t.version == "" and t.client == "" and t.errors() == []


# ---------- engine: go_back / history ----------

def test_go_back_with_duplicate_labels_returns_to_correct_step():
    # Regression: go_back used to replay by label and land on 'b' here.
    t = tree_of(
        Step("a", "Q a", [Option("Yes", "b"), Option("Yes", "c")]),
        Step("b", "Q b", [end()]),
        Step("c", "Q c", [end()]),
    )
    e = TroubleshootEngine(t)
    e.choose(t.steps["a"].options[1])
    assert e.current_id == "c"
    e.choose(e.current_step.options[0])
    assert e.is_finished
    e.go_back()
    assert e.current_id == "c" and not e.is_finished and e.outcome == OUTCOME_IN_PROGRESS
    e.go_back()
    assert e.current_id == "a" and not e.can_go_back()


def test_history_records_step_ids_and_option_index():
    t = tree_of(Step("a", "Q a", [Option("n", "b"), Option("m", "b")]), Step("b", "Q b", [end()]))
    e = TroubleshootEngine(t)
    e.choose(t.steps["a"].options[1])
    e.choose(e.current_step.options[0])
    assert [(h.step_id, h.option_index) for h in e.history] == [("a", 1), ("b", 0)]


def test_go_back_through_a_loop():
    t = tree_of(Step("a", "A", [Option("again", "b")]), Step("b", "B", [Option("again", "a"), end()]))
    e = TroubleshootEngine(t)
    for _ in range(3):
        e.choose(e.current_step.options[0])
    assert e.current_id == "b"
    e.go_back(); assert e.current_id == "a"
    e.go_back(); assert e.current_id == "b"


def test_choose_rejects_foreign_option_and_ignores_when_finished():
    t = tree_of(Step("a", "A", [end()]), Step("z", "Z", [end("other")]))
    e = TroubleshootEngine(t)
    with pytest.raises(ValueError):
        e.choose(Option("nope", None, "x"))
    e.choose(t.steps["a"].options[0])
    n = len(e.history)
    e.choose(t.steps["a"].options[0])   # already finished: no-op
    assert len(e.history) == n


def test_dangling_link_ends_visibly_as_error():
    # Regression: used to finish with resolution=None and report "(in progress)".
    t = tree_of(Step("a", "A", [Option("go", "ghost")]))
    e = TroubleshootEngine(t)
    e.choose(t.steps["a"].options[0])
    assert e.is_finished and e.outcome == OUTCOME_ERROR
    assert "ghost" in e.resolution and e.finished_at
    assert "FLOW ERROR" in e.report_text()


def test_reset_gives_new_session():
    t = tree_of(Step("a", "A", [end()]))
    e = TroubleshootEngine(t)
    first = e.session_id
    e.ticket_ref = "T-1"
    e.reset()
    assert e.session_id != first and e.ticket_ref == ""


# ---------- validation ----------

def test_no_steps():
    assert [i.code for i in Tree().check()] == ["NO_STEPS"]


def test_missing_start():
    t = tree_of(Step("a", "A", [end()]), root="nope")
    assert "NO_START" in codes(t)


def test_empty_question_label_resolution_and_dead_end():
    t = tree_of(Step("a", " ", [Option(" ", None, " "), Option("go", "b")]), Step("b", "B", []))
    assert {"EMPTY_QUESTION", "EMPTY_LABEL", "NO_RESOLUTION", "DEAD_END"} <= codes(t)


def test_duplicate_label_is_case_and_whitespace_insensitive():
    t = tree_of(Step("a", "A", [end("Yes"), end(" yes  ")]))
    dup = [i for i in t.check() if i.code == "DUPLICATE_LABEL"]
    assert len(dup) == 1 and dup[0].option_index == 1 and dup[0].is_error


def test_missing_target_points_at_the_option():
    t = tree_of(Step("a", "A", [end(), Option("go", "ghost")]))
    i = next(i for i in t.check() if i.code == "MISSING_TARGET")
    assert (i.step_id, i.option_index) == ("a", 1)


def test_unreachable_is_warning_and_only_when_start_valid():
    t = tree_of(Step("a", "A", [end()]), Step("orphan", "O", [end()]))
    i = next(i for i in t.check() if i.code == "UNREACHABLE")
    assert i.severity == SEVERITY_WARNING and i.step_id == "orphan"
    t.root_id = "nope"
    assert "UNREACHABLE" not in codes(t)   # would just be noise on top of NO_START


def test_trap_loop_with_no_exit_is_an_error():
    # Regression: validate() used to call this clean.
    t = tree_of(Step("a", "A", [Option("go", "b")]), Step("b", "B", [Option("back", "a")]))
    assert t.validate() != []
    no_exit = {i.step_id for i in t.check() if i.code == "NO_EXIT"}
    assert no_exit == {"a", "b"}


def test_loop_with_an_exit_is_only_a_warning():
    t = tree_of(Step("a", "A", [Option("go", "b")]), Step("b", "B", [Option("back", "a"), end()]))
    cs = t.check()
    assert [i.code for i in cs] == ["CYCLE"] and cs[0].severity == SEVERITY_WARNING
    assert t.errors() == []


def test_self_link_warns_and_dead_step_reached_through_dangling_is_trapped():
    t = tree_of(Step("a", "A", [Option("again", "a"), end()]))
    assert codes(t) == {"SELF_LINK"}
    t2 = tree_of(Step("a", "A", [Option("go", "ghost")]))
    assert {"MISSING_TARGET", "NO_EXIT"} <= codes(t2)


def test_ignored_resolution_warns():
    t = tree_of(Step("a", "A", [Option("go", "b", "never shown")]), Step("b", "B", [end()]))
    assert codes(t) == {"IGNORED_RESOLUTION"}


def test_id_mismatch():
    t = Tree(title="T", root_id="a", steps={"a": Step("other", "A", [end()])})
    assert "ID_MISMATCH" in codes(t)


def test_two_independent_cycles_and_deep_chain_do_not_recurse():
    steps = [Step(f"s{i}", "Q", [Option("n", f"s{i + 1}")]) for i in range(3000)]
    steps.append(Step("s3000", "Q", [end()]))
    t = tree_of(*steps)
    assert t.errors() == [] and t.cycles() == []
    steps[10].options.append(Option("back", "s5"))        # loop 1
    steps[2000].options.append(Option("back", "s1500"))   # loop 2
    assert len(t.cycles()) == 2


def test_validate_strings_match_check():
    t = tree_of(Step("a", "", [end()]))
    assert t.validate() == [i.message for i in t.check()]


# ---------- load / save ----------

def test_roundtrip_preserves_metadata(tmp_path):
    t = tree_of(Step("a", "A", [end()]), version="1.2.0", client="acme")
    p = tmp_path / "f.json"
    t.save(str(p))
    assert json.loads(p.read_text())["schema_version"] == 1
    t2 = Tree.load(str(p))
    assert (t2.version, t2.client) == ("1.2.0", "acme") and t2.to_dict() == t.to_dict()


def test_bad_files_raise_flow_format_error(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{nope")
    with pytest.raises(FlowFormatError):
        Tree.load(str(p))
    with pytest.raises(FlowFormatError):
        Tree.from_dict([])
    with pytest.raises(FlowFormatError):
        Tree.from_dict({"steps": {"a": {"id": "a", "options": [{"next_id": "b"}]}}})   # option without label


# ---------- session record & reports ----------

def finished_engine():
    t = tree_of(Step("a", "Is it <plugged in>?", [Option("Yes", "b")]),
                Step("b", "Does it boot?", [Option("No", None, "Replace the PSU & retest.")]),
                version="2.0.1", client="Acme | HVAC")
    e = TroubleshootEngine(t)
    e.ticket_ref, e.operator, e.notes = "INC-42", "Sam", "Smelled <burnt>."
    e.choose(t.steps["a"].options[0])
    e.choose(e.current_step.options[0])
    return e


def test_record_roundtrips_through_json():
    rec = finished_engine().record()
    again = SessionRecord.from_dict(json.loads(rec.to_json()))
    assert again.to_dict() == rec.to_dict()
    d = rec.to_dict()
    assert d["outcome"] == OUTCOME_RESOLVED and d["flow"]["version"] == "2.0.1"
    assert d["history"][0]["step_id"] == "a" and d["feedback"] is None


def test_report_text_has_everything():
    txt = finished_engine().report_text()
    for needle in ("2.0.1", "Acme | HVAC", "INC-42", "Sam", "Replace the PSU", "Smelled <burnt>.", "1. [", "Duration"):
        assert needle in txt, needle


def test_in_progress_report():
    t = tree_of(Step("a", "A", [Option("go", "b")]), Step("b", "B", [end()]))
    e = TroubleshootEngine(t)
    e.choose(t.steps["a"].options[0])
    assert "Result: (in progress)" in e.report_text() and "Duration" not in e.report_text()


def test_html_report_escapes_user_text():
    h = finished_engine().record().to_html()
    assert "<burnt>" not in h and "&lt;burnt&gt;" in h and "&lt;plugged in&gt;" in h


def test_markdown_report():
    md = finished_engine().record().to_markdown()
    assert md.startswith("# T") and "**Is it <plugged in>?** → Yes" in md and "Acme | HVAC" in md


def test_render_dispatch():
    rec = finished_engine().record()
    assert rec.render("json").lstrip().startswith("{")
    with pytest.raises(ValueError):
        rec.render("pdf")


def test_feedback_is_part_of_record_and_cleared_by_go_back():
    e = finished_engine()
    e.set_feedback(True, "worked")
    assert e.record().to_dict()["feedback"] == {"helpful": True, "comment": "worked"}
    e.go_back()
    assert e.record().feedback is None
