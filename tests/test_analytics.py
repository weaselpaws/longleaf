"""Outcome-log analytics tests — pure Python, no Qt. Run: python -m pytest tests"""

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import analytics as A  # noqa: E402
import outcome_log as olog  # noqa: E402
from outcome_log import make_event  # noqa: E402


def ev(kind, sid, day="2026-10-01", client="acme", title="Flow", version="1.0", **fields):
    return make_event(kind, sid, title, client, version, at=f"{day}T10:00:00-05:00", **fields)


def session(sid, steps, end=None, day="2026-10-01", **kw):
    """started, answered..., then end: 'yes' | 'no' | 'unrated' | 'abandon' | 'reset' | None."""
    out = [ev(olog.STARTED, sid, day, **kw)]
    out += [ev(olog.ANSWERED, sid, day, step_id=s, option_index=i) for s, i in steps]
    if end in ("yes", "no", "unrated"):
        out.append(ev(olog.FINISHED, sid, day, outcome="resolved", resolution_id=None,
                      escalated=False, article_id=None, helpful={"yes": True, "no": False, "unrated": None}[end],
                      ticket_ref="", answers=len(steps), rejected=0))
    elif end == "abandon":
        out.append(ev(olog.ABANDONED, sid, day, last_step_id="c", answers=len(steps)))
    elif end == "reset":
        out.append(ev(olog.RESET, sid, day, last_step_id="c", answers=len(steps), restart_count=1))
    return out


def test_statuses_rates_and_ranking_across_flows():
    events = (session("a1", [("a", 0)], "yes") + session("a2", [("a", 0)], "yes") + session("a3", [("a", 1)], "no")
              + session("a4", [("a", 0)], "unrated") + session("a5", [("a", 0)], "abandon") + session("a6", [("a", 0)], "reset")
              + session("a7", [("a", 0)]) + session("b1", [("x", 0)], "yes", client="globex", title="Other"))
    got = A.analyze(events)
    big, small = got.ranked()
    assert (big.name, small.name) == ("acme — Flow", "globex — Other")
    assert big.sessions == 7 and (small.sessions, got.sessions) == (1, 8)
    c = big.statuses
    assert (c[A.RESOLVED], c[A.NOT_RESOLVED], c[A.FINISHED], c[A.ABANDONED], c[A.RESET], c[A.OPEN]) == (2, 1, 1, 1, 1, 1)
    assert big.rated == 3 and big.resolution_rate == pytest.approx(2 / 3)
    assert big.completion_rate == pytest.approx(4 / 7) and big.abandon_rate == pytest.approx(2 / 7)
    assert small.resolution_rate == 1.0
    assert A.analyze([]).ranked() == [] and A.analyze([]).combined().sessions == 0


def test_cards_visits_answers_and_where_techs_leave():
    events = (session("s1", [("a", 0), ("b", 1)], "yes") + session("s2", [("a", 0)], "abandon")
              + session("s3", [("a", 1)], "reset") + session("s4", [("a", 0)], "abandon"))
    f = A.analyze(events).flows[("acme", "Flow")]
    assert f.answers[("a", 0)] == 3 and f.answers[("a", 1)] == 1 and f.answers[("b", 1)] == 1
    assert (f.steps["a"].visits, f.steps["a"].left_here) == (4, 0)
    c = f.steps["c"]                                                        # three left on 'c' without answering it
    assert (c.visits, c.left_here, c.drop_off_rate) == (3, 3, 1.0) and c.high_drop_off
    assert not f.steps["a"].high_drop_off and f.steps["b"].drop_off_rate == 0.0


def test_endings_group_shared_resolutions_and_count_rejections():
    def fin(sid, step, idx, res, helpful):
        return [ev(olog.STARTED, sid), ev(olog.ANSWERED, sid, step_id=step, option_index=idx),
                ev(olog.FINISHED, sid, outcome="resolved", resolution_id=res, escalated=False, article_id=None,
                   helpful=helpful, ticket_ref="", answers=1, rejected=0)]
    events = fin("1", "p", 0, "fix", True) + fin("2", "q", 3, "fix", False) + fin("3", "q", 1, None, True)
    for n in range(3):
        events.append(ev(olog.REJECTED, f"r{n}", resolution_id="fix", step_id="p", option_index=0))
    events.append(ev(olog.REJECTED, "r9", resolution_id=None, step_id="q", option_index=1))
    f = A.analyze(events).flows[("acme", "Flow")]
    fix = f.endings["fix"]                                                  # two different paths, one ending
    assert (fix.finished, fix.resolved, fix.not_resolved, fix.rejected, fix.reached) == (2, 1, 1, 3, 5)
    assert fix.helpful_rate == 0.5 and fix.rejection_rate == pytest.approx(0.6) and fix.high_rejection
    inline = f.endings["q#1"]
    assert (inline.finished, inline.rejected, inline.reached) == (1, 1, 2) and not inline.high_rejection   # too few sightings


def test_searches_resets_backs_parks_and_escalations():
    events = (session("a", [("a", 0)], "yes", entry_step_id="s2", search_query="  Wifi Down ")
              + session("b", [("a", 0)], "yes", entry_step_id="s2", search_query="wifi down")
              + [ev(olog.NO_RESULTS, "n1", query="Blue Screen"), ev(olog.NO_RESULTS, "n2", query="blue screen"),
                 ev(olog.RESET, "r1", last_step_id="a", answers=1, restart_count=1),
                 ev(olog.RESET, "r2", last_step_id="a", answers=1, restart_count=2),
                 ev(olog.STARTED, "r3", restarted_from="r2", restart_count=2),
                 ev(olog.BACK, "a", from_step_id="a"), ev(olog.PARKED, "a"), ev(olog.RESUMED, "a"),
                 ev(olog.FINISHED, "e", outcome="resolved", resolution_id="esc", escalated=True, article_id=None,
                    helpful=None, ticket_ref="", answers=1, rejected=2)])
    f = A.analyze(events).flows[("acme", "Flow")]
    assert f.searches == {"wifi down": 2} and f.no_results == {"blue screen": 2}
    assert f.resets == 2 and f.max_restarts == 2 and f.backs == 1 and f.parks == 1 and f.escalations == 1


def test_daily_series_and_the_week_over_week_trend():
    events = []
    for n in range(5):                                                      # previous week: 2 of 5 resolved
        events += session(f"p{n}", [("a", 0)], "yes" if n < 2 else "no", day="2026-10-04")
    for n in range(4):                                                      # last week: 3 of 4
        events += session(f"l{n}", [("a", 0)], "yes" if n < 3 else "no", day="2026-10-12")
    f = A.analyze(events).flows[("acme", "Flow")]
    assert (f.first_day, f.last_day) == (date(2026, 10, 4), date(2026, 10, 12))
    assert f.daily[date(2026, 10, 4)][A.RESOLVED] == 2 and f.daily[date(2026, 10, 12)][A.NOT_RESOLVED] == 1
    recent, previous = f.trend()
    assert recent == pytest.approx(0.75) and previous == pytest.approx(0.4)
    assert A.analyze(session("x", [("a", 0)], "yes")).flows[("acme", "Flow")].trend() is None   # only one week of data


def test_combined_view_adds_flows_up():
    events = session("a", [("a", 0)], "yes", day="2026-10-01") + session("b", [("a", 0)], "no", day="2026-10-09", client="g", title="T")
    total = A.analyze(events).combined()
    assert total.sessions == 2 and total.rated == 2 and total.resolution_rate == 0.5
    assert (total.first_day, total.last_day) == (date(2026, 10, 1), date(2026, 10, 9)) and total.steps == {}


def test_load_logs_dedupes_exact_repeats_and_reports_bad_files(tmp_path):
    log = olog.OutcomeLog(tmp_path)
    for e in session("a", [("a", 0)], "yes"):
        log.emit(e)
    copy = tmp_path / "copy.jsonl"
    copy.write_text(log.path.read_text(encoding="utf-8"), encoding="utf-8")        # the same export twice
    junk = tmp_path / "junk.jsonl"
    junk.write_text("not a log\n", encoding="utf-8")
    events, problems = A.load_logs([log.path, copy, junk, tmp_path / "missing.jsonl"])
    assert len(events) == 3 and len(problems) == 2 and "junk.jsonl" in problems[0]
    assert A.analyze(events).sessions == 1


def test_markdown_summary_covers_the_sections_and_uses_names():
    events = []
    for n in range(4):
        events += session(f"g{n}", [("a", 0)], "abandon")
    events += session("y", [("a", 0)], "no", entry_step_id="a", search_query="vpn")
    events += [ev(olog.NO_RESULTS, "z", query="badge reader")]
    for n in range(4):
        events.append(ev(olog.REJECTED, f"r{n}", resolution_id="fix", step_id="a", option_index=0))
    f = A.analyze(events).flows[("acme", "Flow")]

    class Names:
        step = staticmethod(lambda sid: {"c": "Is the cable seated?"}.get(sid, sid))
        ending = staticmethod(lambda key: "Reseat the cable" if key == "fix" else key)

    md = A.to_markdown(f, Names)
    assert md.startswith("# Flow review — acme — Flow")
    for part in ("## At a glance", "## Where techs give up", "Is the cable seated?", "## Fixes techs reject", "Reseat the cable",
                 "## Searches that found nothing", "badge reader", "## What techs search for", "vpn", "## Busiest cards"):
        assert part in md, part
    assert "⚠" in md and "version 1.0" in md
    assert "## Where techs give up" not in A.to_markdown(A.analyze(session("q", [("a", 0)], "yes")).flows[("acme", "Flow")])


def test_generated_sample_log_folds_and_has_something_to_find():
    import make_sample_log as gen
    events = gen.generate(sessions=40, days=30, seed=3)
    assert events == gen.generate(sessions=40, days=30, seed=3)             # deterministic
    got = A.analyze(events)
    assert len(got.flows) == 3 and got.sessions > 60
    assert {e["event"] for e in events} >= {olog.STARTED, olog.ANSWERED, olog.FINISHED, olog.UPDATED}
    assert any(f.no_results for f in got.flows.values()) and any(f.resets for f in got.flows.values())
    for f in got.flows.values():
        assert f.resolution_rate is not None and f.first_day < f.last_day
