"""Engine tests — pure Python, no Qt. Run: python -m pytest tests"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import (  # noqa: E402
    ARTICLE_ATTACH, ARTICLE_READ, ARTICLE_RESOLUTION, Article, Resolution,
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


# ---------- branding & rich content ----------

from engine import Branding, rich_html, shade  # noqa: E402


def test_branding_round_trips_and_is_omitted_when_empty():
    t = tree_of(Step("a", "Q", [end()]))
    assert "branding" not in t.to_dict()
    t.branding = Branding(name="Acme Assist", accent="#3366CC", logo="img/logo.png")
    again = Tree.from_dict(json.loads(json.dumps(t.to_dict())))
    assert again.branding == t.branding


def test_branding_must_be_an_object():
    with pytest.raises(FlowFormatError):
        Tree.from_dict({"branding": "blue", "steps": {}})


@pytest.mark.parametrize("accent", ["blue", "#12345", "#GGGGGG", "123456"])
def test_bad_accent_is_an_error(accent):
    t = tree_of(Step("a", "Q", [end()]), branding=Branding(accent=accent))
    assert "BAD_ACCENT" in codes(t)


def test_good_accent_is_clean():
    assert tree_of(Step("a", "Q", [end()]), branding=Branding(accent="#3366cc")).check() == []


def test_shade_keeps_hue_and_clamps():
    assert shade("#C9952A", 1.0) == "#FFFFFF"
    assert shade("#C9952A", -1.0) == "#000000"
    assert shade("#808080", 0) == "#808080"


def test_images_round_trip_and_are_collected():
    t = tree_of(Step("a", "Q", [Option("x", "b"), end()], image="shots/a.png"),
                Step("b", "Q2", [Option("done", None, "ok", image="shots/fixed.png")]),
                branding=Branding(logo="logo.png"))
    t.steps["a"].options[1].image = "shots/a.png"   # duplicate on purpose
    again = Tree.from_dict(json.loads(json.dumps(t.to_dict())))
    assert again.steps["a"].image == "shots/a.png"
    assert again.steps["b"].options[0].image == "shots/fixed.png"
    assert again.asset_paths() == ["logo.png", "shots/a.png", "shots/fixed.png"]


@pytest.mark.parametrize("rel", ["/etc/passwd", "C:\\x.png", "\\\\host\\share\\x.png", "../x.png", "a/../../x.png"])
def test_unsafe_image_paths_are_errors(rel):
    assert "BAD_IMAGE_PATH" in codes(tree_of(Step("a", "Q", [end()], image=rel)))


def test_missing_image_only_checked_with_a_base_dir(tmp_path):
    t = tree_of(Step("a", "Q", [end()], image="shots/a.png"))
    assert t.check() == []                       # no folder to look in -> not checked
    assert "MISSING_IMAGE" in {i.code for i in t.check(str(tmp_path))}
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "a.png").write_bytes(b"x")
    assert t.check(str(tmp_path)) == []


def test_resolution_image_follows_the_chosen_ending_and_go_back():
    t = tree_of(Step("a", "Q", [Option("fix", None, "Fixed", image="f.png"), Option("no", None, "Nope")]))
    e = TroubleshootEngine(t)
    e.choose(t.steps["a"].options[0])
    assert e.resolution_image == "f.png"
    e.go_back()
    assert e.resolution_image == ""
    e.choose(t.steps["a"].options[1])
    assert e.resolution_image == ""


def test_rich_html_escapes_links_and_keeps_line_breaks():
    out = rich_html("Use <b>this</b> & see https://example.com/help.\nThen retry (https://x.io/a?b=1).")
    assert "&lt;b&gt;this&lt;/b&gt; &amp;" in out
    assert '<a href="https://example.com/help">https://example.com/help</a>.<br>' in out
    assert '(<a href="https://x.io/a?b=1">https://x.io/a?b=1</a>).' in out
    assert "<b>" not in out


def test_rich_html_cannot_inject_through_a_url():
    # The URL ends at the quote, so the rest stays inert text outside the tag.
    assert rich_html('go to https://x.io/"onmouseover="alert(1)') == \
        'go to <a href="https://x.io/">https://x.io/</a>"onmouseover="alert(1)'


def test_build_stages_assets_at_their_relative_paths(tmp_path):
    from build_client_release import stage_assets
    flow_dir, staging = tmp_path / "flow", tmp_path / "stage"
    (flow_dir / "shots").mkdir(parents=True)
    (flow_dir / "shots" / "a.png").write_bytes(b"a")
    (flow_dir / "logo.png").write_bytes(b"l")
    t = tree_of(Step("a", "Q", [end()], image="shots/a.png"), branding=Branding(logo="logo.png"))
    pairs = stage_assets(t.to_dict(), flow_dir, staging)
    assert sorted((p.relative_to(staging).as_posix(), d) for p, d in pairs) == [("logo.png", "."), ("shots/a.png", "shots")]
    assert (staging / "shots" / "a.png").read_bytes() == b"a"


# ---------- shared resolutions ----------

def shared_tree(**kw) -> Tree:
    """Two different paths (a->b, a->c) that finish at the same shared ending."""
    return tree_of(
        Step("a", "Q a", [Option("left", "b"), Option("right", "c")]),
        Step("b", "Q b", [Option("done", None, resolution_id="fix")]),
        Step("c", "Q c", [Option("done", None, resolution_id="fix")]),
        resolutions={"fix": Resolution("fix", "Reseat the cable.", image="shots/fix.png")},
        **kw,
    )


def test_unused_features_are_omitted_from_saved_flows():
    d = tree_of(Step("a", "Q", [end()])).to_dict()
    assert "resolutions" not in d and "articles" not in d
    assert "articles" not in d["steps"]["a"] and "resolution_id" not in d["steps"]["a"]["options"][0]


def test_shared_resolution_round_trips():
    t = shared_tree()
    again = Tree.from_dict(json.loads(json.dumps(t.to_dict())))
    assert again.to_dict() == t.to_dict()
    assert again.steps["b"].options[0].resolution_id == "fix"
    assert again.resolutions["fix"].text == "Reseat the cable."
    assert t.check() == []


def test_two_paths_reach_the_same_ending_and_record_it_once():
    t = shared_tree()
    seen = []
    for first in (0, 1):
        e = TroubleshootEngine(t)
        e.choose(e.current_step.options[first])
        e.choose(e.current_step.options[0])
        assert e.outcome == OUTCOME_RESOLVED
        assert (e.resolution, e.resolution_image, e.resolution_id) == ("Reseat the cable.", "shots/fix.png", "fix")
        rec = e.record()
        assert rec.resolution_id == "fix" and rec.resolution == "Reseat the cable."
        seen.append((rec.resolution_id, [h.step_id for h in rec.history]))
    assert seen == [("fix", ["a", "b"]), ("fix", ["a", "c"])]    # different paths, same ending id


def test_inline_ending_has_no_resolution_id_and_go_back_clears_it():
    e = TroubleshootEngine(shared_tree())
    e.choose(e.current_step.options[0])
    e.choose(e.current_step.options[0])
    assert e.resolution_id == "fix"
    e.go_back()
    assert e.resolution_id is None and e.resolution is None and e.record().resolution_id is None
    t = tree_of(Step("a", "Q", [end()]))
    e2 = TroubleshootEngine(t)
    e2.choose(t.steps["a"].options[0])
    assert e2.record().resolution_id is None


def test_shared_resolution_screenshot_is_a_build_asset_and_option_image_is_the_fallback():
    t = shared_tree()
    assert t.asset_paths() == ["shots/fix.png"]
    t.resolutions["fix"].image = ""
    t.steps["b"].options[0].image = "shots/b.png"
    assert t.ending_for(t.steps["b"].options[0]).image == "shots/b.png"
    assert t.ending_for(t.steps["c"].options[0]).image == ""


def test_missing_shared_resolution_is_an_error_and_ends_visibly():
    t = tree_of(Step("a", "Q", [Option("x", None, resolution_id="ghost")]))
    assert "MISSING_RESOLUTION" in codes(t) and "NO_RESOLUTION" not in codes(t)
    e = TroubleshootEngine(t)
    e.choose(t.steps["a"].options[0])
    assert e.outcome == OUTCOME_ERROR and "ghost" in e.resolution and e.resolution_id is None


def test_shared_resolution_validation_codes():
    only = lambda t, code: [i for i in t.check() if i.code == code]   # noqa: E731
    t = tree_of(Step("a", "Q", [Option("x", "b", resolution_id="r"), Option("y", None, "inline", resolution_id="r")]),
                Step("b", "B", [end()]),
                resolutions={"r": Resolution("r", "shared"), "empty": Resolution("empty", "  "), "unused": Resolution("unused", "t")})
    assert [(i.severity, i.option_index) for i in only(t, "IGNORED_RESOLUTION")] == [(SEVERITY_WARNING, 0), (SEVERITY_WARNING, 1)]
    assert only(t, "EMPTY_RESOLUTION")[0].severity == SEVERITY_ERROR
    assert only(t, "UNUSED_RESOLUTION")[0].severity == SEVERITY_WARNING
    assert [("empty" in i.message, "unused" in i.message) for i in only(t, "UNUSED_RESOLUTION")] == [(True, False), (False, True)]
    t.resolutions["r"] = Resolution("other", "shared")
    assert "ID_MISMATCH" in codes(t)


def test_delete_resolution_unlinks_answers():
    t = shared_tree()
    t.delete_resolution("fix")
    assert t.steps["b"].options[0].resolution_id is None
    assert "NO_RESOLUTION" in codes(t)
    assert t.add_resolution("x").id == "res_1" and t.add_resolution("y").id == "res_2"


# ---------- KB articles ----------

def kb_tree() -> Tree:
    return tree_of(
        Step("a", "Q a", [Option("go", "b")], articles=["kb_net"]),
        Step("b", "Q b", [Option("done", None, resolution_id="fix")]),
        resolutions={"fix": Resolution("fix", "Reseat the cable.", articles=["kb_cable", "kb_net"])},
        articles={"kb_net": Article("kb_net", "Network basics", "Body text", "https://kb.example.com/net"),
                  "kb_cable": Article("kb_cable", "Cable seating")},
    )


def test_articles_round_trip_and_validate_clean():
    t = kb_tree()
    again = Tree.from_dict(json.loads(json.dumps(t.to_dict())))
    assert again.to_dict() == t.to_dict()
    assert again.steps["a"].articles == ["kb_net"] and again.articles["kb_net"].url == "https://kb.example.com/net"
    assert t.check() == []


def test_articles_on_offer_follow_the_step_then_the_ending():
    e = TroubleshootEngine(kb_tree())
    assert [a.id for a in e.articles_here()] == ["kb_net"]
    e.choose(e.current_step.options[0])
    assert e.articles_here() == []                       # step b offers none
    e.choose(e.current_step.options[0])
    assert [a.id for a in e.articles_here()] == ["kb_cable", "kb_net"]
    e.go_back()
    assert e.articles_here() == [] and e.current_id == "b"


def test_article_validation_codes():
    t = tree_of(Step("a", "Q", [end()], articles=["ghost"]),
                resolutions={"r": Resolution("r", "t", articles=["ghost2"])},
                articles={"blank": Article("blank", " "), "unused": Article("unused", "t")})
    got = {(i.code, i.severity) for i in t.check()}
    assert {("MISSING_ARTICLE", SEVERITY_ERROR), ("EMPTY_ARTICLE", SEVERITY_ERROR), ("UNUSED_ARTICLE", SEVERITY_WARNING)} <= got
    assert sum(i.code == "MISSING_ARTICLE" for i in t.check()) == 2    # one on the step, one on the resolution
    t.articles["x"] = Article("y", "t")
    assert "ID_MISMATCH" in codes(t)


def test_delete_article_removes_every_reference():
    t = kb_tree()
    t.delete_article("kb_net")
    assert t.steps["a"].articles == [] and t.resolutions["fix"].articles == ["kb_cable"]
    assert "MISSING_ARTICLE" not in codes(t)
    assert t.add_article().id == "kb_1"


def test_record_article_logs_reads_and_attaches_once():
    e = TroubleshootEngine(kb_tree())
    e.record_article("kb_net", ARTICLE_READ)
    e.record_article("kb_net", ARTICLE_READ)
    e.record_article("kb_net", ARTICLE_ATTACH)
    e.record_article("kb_net", ARTICLE_ATTACH)       # idempotent
    assert [(x.article_id, x.action, x.title) for x in e.record().articles] == [
        ("kb_net", ARTICLE_READ, "Network basics"), ("kb_net", ARTICLE_READ, "Network basics"),
        ("kb_net", ARTICLE_ATTACH, "Network basics")]
    with pytest.raises(ValueError):
        e.record_article("nope", ARTICLE_READ)
    with pytest.raises(ValueError):
        e.record_article("kb_net", ARTICLE_RESOLUTION)   # that has its own method
    with pytest.raises(ValueError):
        e.record_article("kb_net", "shred")


def test_article_as_resolution_finishes_the_session_and_go_back_undoes_only_that():
    e = TroubleshootEngine(kb_tree())
    e.record_article("kb_net", ARTICLE_ATTACH)
    e.choose(e.current_step.options[0])
    e.use_article_as_resolution("kb_net")
    assert e.is_finished and e.outcome == OUTCOME_RESOLVED and e.resolution_id is None
    assert e.resolution == "KB article: Network basics (https://kb.example.com/net)"
    assert [x.action for x in e.record().articles] == [ARTICLE_ATTACH, ARTICLE_RESOLUTION]
    e.go_back()
    assert [x.action for x in e.record().articles] == [ARTICLE_ATTACH]
    assert not e.is_finished
    with pytest.raises(ValueError):
        e.use_article_as_resolution("nope")


def test_article_events_survive_json_and_show_in_reports_only_when_attached():
    e = TroubleshootEngine(kb_tree())
    e.record_article("kb_cable", ARTICLE_READ)
    assert "KB attached" not in e.record().to_text()
    e.record_article("kb_net", ARTICLE_ATTACH)
    e.choose(e.current_step.options[0])
    e.choose(e.current_step.options[0])
    rec = e.record()
    again = SessionRecord.from_dict(json.loads(rec.to_json()))
    assert again.to_dict() == rec.to_dict() and again.resolution_id == "fix"
    assert "KB attached: Network basics" in rec.to_text()
    assert "**KB attached:** Network basics" in rec.to_markdown()
    assert "Network basics" in rec.to_html()


def test_old_session_records_without_the_new_fields_still_load():
    rec = TroubleshootEngine(tree_of(Step("a", "Q", [end()]))).record().to_dict()
    del rec["resolution_id"], rec["articles"]
    again = SessionRecord.from_dict(rec)
    assert again.resolution_id is None and again.articles == []


@pytest.mark.parametrize("bad", [
    {"resolutions": ["a"], "steps": {}},
    {"articles": "kb", "steps": {}},
    {"steps": {"a": {"question": "Q", "articles": "kb_net", "options": []}}},
    {"steps": {"a": {"question": "Q", "articles": [1], "options": []}}},
    {"resolutions": {"r": "text"}, "steps": {}},
    {"resolutions": {"r": {"text": "t", "articles": "kb"}}, "steps": {}},
    {"articles": {"k": ["x"]}, "steps": {}},
])
def test_malformed_shared_content_raises_flow_format_error(bad):
    with pytest.raises(FlowFormatError):
        Tree.from_dict(bad)
