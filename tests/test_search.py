"""Flow search tests — pure Python, no Qt. Run: python -m pytest tests"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import (  # noqa: E402
    Article, Option, Resolution, SessionRecord, Step, Tree, TroubleshootEngine, OUTCOME_IN_PROGRESS, OUTCOME_RESOLVED,
)
from search import search, tokens  # noqa: E402


def flow() -> Tree:
    return Tree(title="Help desk", root_id="start", steps={
        "start": Step("start", "What is the symptom?", [Option("Can't get online", "wifi"), Option("Can't print", "printer"),
                                                         Option("Computer won't start", "boot")]),
        "wifi": Step("wifi", "Does the Wi-Fi icon show as connected?",
                     [Option("Yes", None, "Power cycle the router."), Option("No", None, resolution_id="join")],
                     tags=["wifi", "no internet", "wireless"]),
        "printer": Step("printer", "Does the printer show as offline?", [Option("Yes", None, "Restart the spooler.")],
                        tags=["printer", "printing"], articles=["kb_spool"]),
        "boot": Step("boot", "Does the screen stay black?", [Option("Yes", None, "Reseat the RAM.")],
                     tags=["blue screen", "bsod", "boot"], note="Listen for beeps."),
        "orphan": Step("orphan", "Old wifi question nobody reaches", [Option("x", None, "y")], tags=["wifi"]),
    }, resolutions={"join": Resolution("join", "Join the company network.")},
        articles={"kb_spool": Article("kb_spool", "Restarting the Print Spooler")})


def ids(query, tree=None, **kw):
    return [h.step_id for h in search(tree or flow(), query, **kw)]


def test_tokens_are_lowercase_words():
    assert tokens("Wi-Fi keeps DROPPING!  (again)") == ["wi", "fi", "keeps", "dropping", "again"]
    assert tokens("") == [] and tokens("...") == []


def test_a_tag_wins_and_unreachable_steps_are_never_offered():
    assert ids("wifi")[0] == "wifi"
    assert "orphan" not in ids("wifi")                 # tagged "wifi" too, but nothing leads to it


def test_every_word_must_match_first_and_partial_matches_are_the_fallback():
    assert ids("printer offline") == ["printer"]                       # both words, one step
    hits = ids("wireless dropping")                                    # 'dropping' matches nothing: fall back to 'wireless'
    assert hits == ["wifi"]
    assert ids("zzzz qqqq") == [] and ids("") == [] and ids("  ?! ") == []


def test_prefix_and_plural_matching_and_case():
    assert ids("PRINTERS")[0] == "printer"             # plural of the tag
    assert ids("spool")[0] == "printer"                # prefix of the offered article's title
    assert ids("print")[0] == "printer"                # prefix of the tag
    assert ids("a") == []                              # one letter is not a search


def test_multi_word_tag_phrase_beats_scattered_words():
    hits = search(flow(), "blue screen")
    assert hits[0].step_id == "boot" and hits[0].why == "Tag: blue screen"
    assert ids("no internet")[0] == "wifi"


def test_matches_answers_fixes_notes_and_say_why():
    assert search(flow(), "beeps")[0].why == "Note" and search(flow(), "beeps")[0].step_id == "boot"
    assert search(flow(), "router")[0].step_id == "wifi" and search(flow(), "router")[0].why == "Fix"
    assert search(flow(), "company network")[0].step_id == "wifi"       # the shared resolution's text counts
    assert search(flow(), "symptom")[0].step_id == "start" and search(flow(), "symptom")[0].why == "Question"
    assert search(flow(), "online")[0].why == "Answer: Can't get online"


def test_ties_go_to_the_step_nearer_the_start_then_flow_order():
    t = Tree(title="T", root_id="a", steps={
        "a": Step("a", "Start", [Option("x", "b"), Option("y", "c")]),
        "b": Step("b", "Next", [Option("go", "d")], tags=["cable"]),
        "c": Step("c", "Other", [Option("go", "d")], tags=["cable"]),
        "d": Step("d", "Deep", [Option("done", None, "Fixed.")], tags=["cable"]),
    })
    assert ids("cable", t) == ["b", "c", "d"]
    assert ids("cable", t, limit=2) == ["b", "c"]


def test_a_broken_flow_never_raises():
    assert search(Tree(), "anything") == []
    t = Tree(title="T", root_id="ghost", steps={"a": Step("a", "Q wifi", [Option("x", "nowhere")])})
    assert search(t, "wifi") == []


def test_tags_are_additive_in_the_flow_file():
    plain = Tree(title="T", root_id="a", steps={"a": Step("a", "Q", [Option("x", None, "r")])}).to_dict()
    assert "tags" not in plain["steps"]["a"]
    t = flow()
    again = Tree.from_dict(json.loads(json.dumps(t.to_dict())))
    assert again.steps["wifi"].tags == ["wifi", "no internet", "wireless"] and again.to_dict() == t.to_dict()
    from engine import FlowFormatError
    with pytest.raises(FlowFormatError):
        Tree.from_dict({"steps": {"a": {"question": "Q", "tags": "wifi", "options": []}}})


# ---------- starting a session from a search result ----------

def test_start_at_jumps_to_the_step_and_records_it():
    e = TroubleshootEngine(flow())
    assert e.can_start_at() and not e.can_go_back()
    e.start_at("printer", " printer offline ")
    assert e.current_id == "printer" and e.entry_step_id == "printer" and e.search_query == "printer offline"
    assert e.can_go_back() and not e.can_start_at()
    e.choose(e.current_step.options[0])
    assert e.outcome == OUTCOME_RESOLVED and [h.step_id for h in e.history] == ["printer"]
    rec = e.record()
    assert (rec.entry_step_id, rec.search_query, rec.resolution) == ("printer", "printer offline", "Restart the spooler.")
    assert "Searched for: printer offline" in rec.to_text()
    again = SessionRecord.from_dict(json.loads(rec.to_json()))
    assert again.to_dict() == rec.to_dict()


def test_back_from_a_search_landing_returns_to_the_start_step():
    e = TroubleshootEngine(flow())
    e.start_at("boot", "blue screen")
    e.choose(e.current_step.options[0])
    e.go_back()                                                   # undo the answer: still at the landing step
    assert e.current_id == "boot" and e.entry_step_id == "boot" and e.can_go_back()
    e.go_back()                                                   # now back to the start
    assert (e.current_id, e.entry_step_id, e.search_query) == ("start", None, "") and not e.can_go_back()
    assert e.outcome == OUTCOME_IN_PROGRESS and e.can_start_at()


def test_start_at_the_root_just_keeps_the_query_and_only_works_before_the_first_answer():
    e = TroubleshootEngine(flow())
    e.start_at("start", "symptom")
    assert e.current_id == "start" and e.entry_step_id is None and e.search_query == "symptom" and not e.can_go_back()
    e.choose(e.current_step.options[0])
    with pytest.raises(ValueError):
        e.start_at("printer")
    e.reset()
    assert e.search_query == "" and e.entry_step_id is None
    with pytest.raises(ValueError):
        e.start_at("ghost")


def test_old_records_without_search_fields_load():
    rec = TroubleshootEngine(flow()).record().to_dict()
    del rec["entry_step_id"], rec["search_query"]
    again = SessionRecord.from_dict(rec)
    assert again.entry_step_id is None and again.search_query == ""
