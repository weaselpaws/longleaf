"""Outcome log tests — pure Python, no Qt. Run: python -m pytest tests"""

import json
import re
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import outcome_log as olog  # noqa: E402
from outcome_log import OutcomeLog, fold_sessions, make_event, read_events, status_counts  # noqa: E402

DOC = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")


def ev(kind, sid="s1", at="2026-01-01T10:00:00+00:00", **fields):
    return make_event(kind, sid, "Flow", "acme", "1.0", at=at, **fields)


# ---------- the file sink ----------

def test_emit_appends_one_json_line_per_event_and_reads_back(tmp_path):
    log = OutcomeLog(tmp_path / "logs" / "acme")
    assert log.read() == [] and log.count() == 0
    assert log.emit(ev(olog.STARTED, entry_step_id=None, search_query=""))
    assert log.emit(ev(olog.ANSWERED, step_id="a", option_index=1))
    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and all(json.loads(x)["v"] == 1 for x in lines) and "\n" not in lines[0]
    assert [e["event"] for e in log.read()] == [olog.STARTED, olog.ANSWERED]
    assert log.clear() == 2 and not log.path.exists() and log.read() == [] and log.clear() == 0


def test_emit_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert OutcomeLog(blocker / "sub").emit(ev(olog.STARTED)) is False          # folder can't be made
    assert OutcomeLog(tmp_path).emit({"event": object()}) is False              # not serialisable


def test_reader_skips_junk_torn_and_foreign_lines(tmp_path):
    p = tmp_path / "x.jsonl"
    good = json.dumps(ev(olog.STARTED))
    p.write_text("\n".join(["", "{not json", '["a list"]', '{"event": "other.thing", "session_id": "s"}',
                            '{"event": "session.started"}', good, good[:30]]), encoding="utf-8")
    assert [e["event"] for e in read_events(p)] == [olog.STARTED]
    assert read_events(tmp_path / "missing.jsonl") == []


def test_unicode_and_two_writers_keep_whole_lines(tmp_path):
    log = OutcomeLog(tmp_path)

    def work(n):
        for i in range(50):
            log.emit(ev(olog.ANSWERED, sid=f"s{n}", step_id="é-ü", option_index=i))

    threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert log.count() == 200 and log.read()[0]["step_id"] == "é-ü"


def test_make_event_envelope_and_unknown_kinds():
    e = make_event(olog.NO_RESULTS, "s9", "T", "c", "2", query="blue screen")
    assert (e["v"], e["event"], e["session_id"], e["flow_title"], e["flow_client"], e["flow_version"], e["query"]) == \
        (1, "search.no_results", "s9", "T", "c", "2", "blue screen") and e["at"]
    with pytest.raises(ValueError):
        make_event("session.exploded", "s")


# ---------- folding events into session outcomes ----------

def test_a_resolved_session_with_a_ticket_and_a_rejection():
    events = [ev(olog.STARTED, at="t0"), ev(olog.ANSWERED, step_id="a", option_index=0),
              ev(olog.ANSWERED, step_id="b", option_index=1), ev(olog.REJECTED, resolution_id="fix", step_id="b", option_index=1),
              ev(olog.FINISHED, outcome="resolved", resolution_id="fix2", escalated=False, helpful=None, ticket_ref=""),
              ev(olog.UPDATED, outcome="resolved", resolution_id="fix2", escalated=False, helpful=True, ticket_ref="INC-1")]
    (s,) = fold_sessions(events).values()
    assert (s.status, s.ticket_ref, s.resolution_id, s.rejected) == (olog.STATUS_RESOLVED, "INC-1", "fix2", 1)
    assert s.steps == [("a", 0), ("b", 1)] and s.started_at == "t0"


@pytest.mark.parametrize("helpful,outcome,status", [
    (True, "resolved", olog.STATUS_RESOLVED), (False, "resolved", olog.STATUS_NOT_RESOLVED),
    (None, "resolved", olog.STATUS_FINISHED), (None, "error", olog.STATUS_ERROR)])
def test_finished_statuses(helpful, outcome, status):
    (s,) = fold_sessions([ev(olog.STARTED), ev(olog.FINISHED, outcome=outcome, helpful=helpful)]).values()
    assert s.status == status


def test_abandoned_reopened_and_still_open_sessions():
    events = [ev(olog.STARTED, sid="gone"), ev(olog.ANSWERED, sid="gone", step_id="a", option_index=0),
              ev(olog.ABANDONED, sid="gone", last_step_id="b", answers=1),
              ev(olog.STARTED, sid="open"), ev(olog.ANSWERED, sid="open", step_id="a", option_index=0),
              ev(olog.STARTED, sid="back"), ev(olog.FINISHED, sid="back", outcome="resolved", helpful=True),
              ev(olog.REOPENED, sid="back")]
    got = fold_sessions(events)
    assert (got["gone"].status, got["gone"].last_step_id) == (olog.STATUS_ABANDONED, "b")
    assert got["open"].status == olog.STATUS_IN_PROGRESS and got["back"].status == olog.STATUS_IN_PROGRESS   # Back undoes the finish
    assert status_counts(got.values()) == {olog.STATUS_ABANDONED: 1, olog.STATUS_IN_PROGRESS: 2}


def test_search_and_escalation_details_are_kept():
    (s,) = fold_sessions([ev(olog.STARTED, entry_step_id="step_2", search_query="wifi"),
                          ev(olog.FINISHED, outcome="resolved", escalated=True, resolution_id="esc", helpful=None)]).values()
    assert (s.entry_step_id, s.search_query, s.escalated, s.resolution_id) == ("step_2", "wifi", True, "esc")


# ---------- docs/API.md stays honest ----------

def _doc_events() -> list:
    m = re.search(r"<!-- outcome-log-example -->\s*```json\n(.*?)```", DOC, re.S)
    assert m, "no outcome log example in docs/API.md"
    return json.loads(m.group(1))


def test_documented_events_use_every_real_kind_and_the_shared_envelope():
    events = _doc_events()
    assert {e["event"] for e in events} == set(olog.EVENT_KINDS)
    envelope = set(make_event(olog.REOPENED, "s"))
    for e in events:
        assert envelope <= set(e), e["event"]
    documented = set(re.findall(r"^\| `([a-z.]+_?[a-z.]*)` \|", DOC, re.M))
    assert set(olog.EVENT_KINDS) <= documented


def test_the_documented_stream_folds_as_described():
    got = fold_sessions(_doc_events())
    assert got["8f1c0d2e"].status == olog.STATUS_ABANDONED and got["8f1c0d2e"].ticket_ref == "INC-4471"
    assert got["8f1c0d2e"].rejected == 1 and got["8f1c0d2e"].search_query == "wifi keeps dropping"
    assert got["a0b1c2d3"].status == olog.STATUS_IN_PROGRESS


def test_resets_parks_and_backs_are_counted_and_chains_are_recoverable():
    events = [
        ev(olog.STARTED, sid="one", restarted_from=None, restart_count=0), ev(olog.ANSWERED, sid="one", step_id="a", option_index=0),
        ev(olog.BACK, sid="one", from_step_id="b"), ev(olog.BACK, sid="one", from_step_id="a"),
        ev(olog.RESET, sid="one", last_step_id="a", answers=1, restart_count=1),
        ev(olog.STARTED, sid="two", restarted_from="one", restart_count=1), ev(olog.ANSWERED, sid="two", step_id="a", option_index=1),
        ev(olog.RESET, sid="two", last_step_id="a", answers=1, restart_count=2),
        ev(olog.STARTED, sid="three", restarted_from="two", restart_count=2),
        ev(olog.PARKED, sid="three", last_step_id="a", answers=0), ev(olog.RESUMED, sid="three", last_step_id="a", answers=0),
        ev(olog.PARKED, sid="three", last_step_id="a", answers=0),
        ev(olog.STARTED, sid="four", restarted_from=None, restart_count=0),
        ev(olog.PARKED, sid="four"), ev(olog.RESUMED, sid="four"),
    ]
    got = fold_sessions(events)
    assert (got["one"].status, got["one"].backs) == (olog.STATUS_RESET, 2)
    assert (got["two"].status, got["two"].restarted_from, got["two"].restart_count) == (olog.STATUS_RESET, "one", 1)
    assert (got["three"].status, got["three"].parks, got["three"].restart_count) == (olog.STATUS_PARKED, 2, 2)   # parked now
    assert got["four"].status == olog.STATUS_IN_PROGRESS and got["four"].parks == 1                              # resumed
    assert status_counts(got.values()) == {olog.STATUS_RESET: 2, olog.STATUS_PARKED: 1, olog.STATUS_IN_PROGRESS: 1}
