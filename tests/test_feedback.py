"""Local feedback capture tests — pure Python, no Qt. Run: python -m pytest tests"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import Option, Step, Tree, TroubleshootEngine, OUTCOME_ERROR  # noqa: E402
from feedback import (  # noqa: E402
    FeedbackFormatError, FlowFeedback, SessionStore, analyze, foreign_sessions, step_feedback_text, build_bundle, load_bundle, merge_records, summarize, write_bundle,
)


def flow() -> Tree:
    a = Step("a", "Powered on?", [Option("Yes", "b"), Option("No", None, "Plug it in.")])
    b = Step("b", "Screen lit?", [Option("Yes", None, "All good."), Option("No", None, "Replace panel.")])
    return Tree(title="T", client="acme", version="1.0", root_id="a", steps={"a": a, "b": b})


def run(tree, answers, helpful=None, comment="", ticket=""):
    """A finished session that picked answers[i] at each step in turn."""
    e = TroubleshootEngine(tree)
    for idx in answers:
        e.choose(e.current_step.options[idx])
    e.ticket_ref = ticket
    if helpful is not None or comment:
        e.set_feedback(helpful, comment)
    return e.record()


# ---------- store ----------

def test_store_round_trip_and_replace(tmp_path):
    t, store = flow(), SessionStore(tmp_path / "sessions")
    r = run(t, [0, 0])
    assert store.save(r) and store.count() == 1
    r.notes = "updated"
    r.feedback = {"helpful": True, "comment": "nice"}
    assert store.save(r) and store.count() == 1          # same session -> replaced, not duplicated
    (got,) = store.load_all()
    assert got.notes == "updated" and got.feedback == {"helpful": True, "comment": "nice"}


def test_store_discard_clear_and_junk(tmp_path):
    t, store = flow(), SessionStore(tmp_path)
    a, b = run(t, [1]), run(t, [0, 1])
    store.save(a)
    store.save(b)
    (tmp_path / "junk.json").write_text("{not json")
    (tmp_path / "other.json").write_text('{"x": 1}')
    assert store.count() == 2                             # unreadable / foreign files are skipped
    store.discard(a.session_id)
    store.discard("never-existed")
    assert [r.session_id for r in store.load_all()] == [b.session_id]
    assert store.clear() == 3                             # junk files go too
    assert store.load_all() == []


def test_store_on_missing_or_unwritable_folder_never_raises(tmp_path):
    assert SessionStore(tmp_path / "nope").load_all() == []
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert SessionStore(blocker / "sub").save(run(flow(), [1])) is False   # can't mkdir under a file


# ---------- bundle ----------

def test_bundle_round_trip(tmp_path):
    t = flow()
    recs = [run(t, [1], helpful=True, comment="ok"), run(t, [0, 1], helpful=False)]
    path = tmp_path / "fb.json"
    assert write_bundle(path, recs, t) == 2
    data = json.loads(path.read_text())
    assert data["kind"] == "longleaf-feedback" and data["flow"] == {"title": "T", "client": "acme", "version": "1.0"}
    back = load_bundle(path)
    assert [r.to_dict() for r in back] == [r.to_dict() for r in recs]


@pytest.mark.parametrize("content,msg", [
    ("nope", "not valid JSON"),
    ("[]", "not a Longleaf feedback file"),
    ('{"kind": "something-else"}', "not a Longleaf feedback file"),
    ('{"kind": "longleaf-feedback", "schema_version": 99, "sessions": []}', "newer Longleaf"),
    ('{"kind": "longleaf-feedback", "schema_version": 1}', "no 'sessions'"),
    ('{"kind": "longleaf-feedback", "schema_version": 1, "sessions": [{"oops": 1}]}', "malformed"),
])
def test_bad_bundles_are_refused_with_a_reason(tmp_path, content, msg):
    p = tmp_path / "x.json"
    p.write_text(content)
    with pytest.raises(FeedbackFormatError, match=msg):
        load_bundle(p)


def test_missing_file_is_a_format_error(tmp_path):
    with pytest.raises(FeedbackFormatError):
        load_bundle(tmp_path / "absent.json")


def test_merge_dedupes_and_keeps_the_newer_copy():
    t = flow()
    r = run(t, [1])
    older = SessionRecord_copy(r, finished_at="2026-01-01T10:00:00+00:00", comment="old")
    newer = SessionRecord_copy(r, finished_at="2026-01-01T11:00:00+00:00", comment="new")
    store: dict = {}
    assert merge_records(store, [older]) == 0
    assert merge_records(store, [newer, older]) == 2       # both are repeats of an already-seen session
    assert store[r.session_id].feedback["comment"] == "new"


def SessionRecord_copy(r, finished_at, comment):
    from engine import SessionRecord
    d = r.to_dict()
    d["finished_at"], d["feedback"] = finished_at, {"helpful": True, "comment": comment}
    return SessionRecord.from_dict(d)


# ---------- analysis ----------

def test_traffic_and_endings():
    t = flow()
    recs = [run(t, [0, 0], helpful=True), run(t, [0, 0], helpful=True), run(t, [0, 1], helpful=False), run(t, [1])]
    fb = analyze(t, recs)
    assert fb.sessions == 4 and fb.resolved == 4 and fb.unmatched == 0
    assert fb.step_visits == {"a": 4, "b": 3}
    assert fb.edge_counts == {("a", 0): 3, ("b", 0): 2, ("b", 1): 1, ("a", 1): 1}
    assert fb.endings[("b", 0)].helpful == 2 and fb.endings[("b", 0)].helpful_rate == 1.0
    assert fb.endings[("b", 1)].unhelpful == 1 and fb.endings[("b", 1)].helpful_rate == 0.0
    assert fb.endings[("a", 1)].rated == 0 and fb.endings[("a", 1)].helpful_rate is None
    assert (fb.helpful, fb.unhelpful, fb.helpful_rate) == (2, 1, pytest.approx(2 / 3))
    assert fb.max_edge_count == 3


def test_comments_pin_to_the_step_that_ended_the_flow():
    t = flow()
    fb = analyze(t, [run(t, [0, 1], helpful=False, comment="Panel was fine, cable was loose", ticket="INC-9"),
                     run(t, [1], comment="   ")])          # blank comments are ignored
    assert list(fb.comments) == ["b"]
    (c,) = fb.comments["b"]
    assert (c.text, c.helpful, c.ticket_ref) == ("Panel was fine, cable was loose", False, "INC-9")


def test_records_from_an_older_flow_are_split_into_matched_and_unmatched():
    old = flow()
    through_b_1, through_b_2, only_a = run(old, [0, 1]), run(old, [0, 0]), run(old, [1])
    now = flow()                                            # step b has since been removed
    del now.steps["b"]
    now.steps["a"].options[0] = Option("Yes", None, "Now ends here")
    fb = analyze(now, [through_b_1, through_b_2, only_a])
    assert fb.unmatched == 2 and fb.sessions == 1           # only the path that stays on step a survives


def test_a_session_whose_final_answer_now_continues_counts_traffic_but_not_an_ending():
    old_flow, t = flow(), flow()
    rec = run(old_flow, [1])                                # ended at a -> "No"
    t.steps["a"].options[1] = Option("No", "b")             # ...which now leads on to step b
    fb = analyze(t, [rec])
    assert fb.sessions == 1 and fb.edge_counts == {("a", 1): 1} and fb.endings == {} and fb.resolved == 0


def test_flow_errors_and_empty_sessions_are_not_endings():
    t = flow()
    t.steps["a"].options[0].next_id = "ghost"
    e = TroubleshootEngine(t)
    e.choose(e.current_step.options[0])
    assert e.outcome == OUTCOME_ERROR
    fb = analyze(flow(), [e.record(), TroubleshootEngine(flow()).record()])
    assert fb.resolved == 0 and fb.endings == {} and fb.unmatched == 1   # the empty session has no history


def test_summary_text():
    t = flow()
    recs = [run(t, [0, 1], helpful=False, comment="bad"), run(t, [0, 1], helpful=False), run(t, [0, 0], helpful=True)]
    text = summarize(t, analyze(t, recs), duplicates=1)
    assert "3 sessions matched" in text and "1 duplicate skipped" in text
    assert "Helpful: 33% of 3 rated" in text
    assert "b → “No”: 0% helpful of 2" in text and "1 comment," in text
    assert "didn't match" not in text
    assert "2 didn't match" in summarize(t, FlowFeedback(unmatched=2))


def test_step_feedback_text():
    t = flow()
    fb = analyze(t, [run(t, [0, 1], helpful=False, comment="Cable, not panel", ticket="INC-9"), run(t, [0, 0], helpful=True)])
    text = step_feedback_text(t, fb, "b")
    assert text.startswith("2 visits from imported sessions.")
    assert "“Yes”: 1  —  ends here, 100% helpful of 1" in text and "“No”: 1  —  ends here, 0% helpful of 1" in text
    assert "▼ Cable, not panel  (INC-9)" in text
    assert step_feedback_text(t, fb, "nope") == ""
    assert step_feedback_text(t, FlowFeedback(), "a").startswith("0 visits")


def test_foreign_sessions_are_detected_by_client_then_title():
    t = flow()                                              # client "acme", title "T"
    mine = run(t, [1])
    other = flow()
    other.client = "globex"
    theirs = run(other, [1])
    assert foreign_sessions(t, [mine, theirs]) == 1
    t.client = ""                                           # client unknown on our side -> compare titles
    other.client, other.title = "", "Different flow"
    assert foreign_sessions(t, [mine, run(other, [1])]) == 1
    assert "WARNING: 2 sessions came from a different client" in summarize(t, FlowFeedback(), foreign=2)
