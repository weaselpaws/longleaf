"""Persona discovery tests — pure Python, no Qt. Run: python -m pytest tests"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from persona import DEFAULT_TOOLS, discover_personas, load_persona  # noqa: E402

FLOW = {"title": "Help desk", "client": "acme-hvac", "root_id": "a",
        "steps": {"a": {"id": "a", "question": "Q", "options": [{"label": "x", "resolution": "r"}]}}}


def make(root, folder, flow=None, persona=None, raw_persona=None):
    d = Path(root) / folder
    d.mkdir(parents=True)
    if flow is not False:
        (d / "flow.json").write_text(json.dumps(FLOW if flow is None else flow), encoding="utf-8")
    if persona is not None:
        (d / "persona.json").write_text(json.dumps(persona), encoding="utf-8")
    if raw_persona is not None:
        (d / "persona.json").write_text(raw_persona, encoding="utf-8")
    return d


def test_a_folder_with_a_flow_is_a_persona_with_the_default_tools(tmp_path):
    make(tmp_path, "acme-hvac")
    (p,) = discover_personas(tmp_path)
    assert (p.id, p.name, p.tools, p.error, p.warnings) == ("acme-hvac", "acme-hvac", DEFAULT_TOOLS, "", [])
    assert p.flow_path.endswith("acme-hvac/flow.json") and p.usable


def test_name_comes_from_persona_json_then_branding_then_client_then_title(tmp_path):
    make(tmp_path, "a", persona={"name": "  Acme Heating & Air "})
    make(tmp_path, "b", flow={**FLOW, "branding": {"name": "Brand Name"}})
    make(tmp_path, "c")
    make(tmp_path, "d", flow={**FLOW, "client": ""})
    make(tmp_path, "e", flow={"root_id": "a", "steps": FLOW["steps"]})
    names = {p.id: p.name for p in discover_personas(tmp_path)}
    assert names == {"a": "Acme Heating & Air", "b": "Brand Name", "c": "acme-hvac", "d": "Help desk", "e": "Untitled Flow"}


def test_tools_default_can_be_emptied_and_unknown_ones_are_reported(tmp_path):
    make(tmp_path, "none", persona={"tools": []})
    make(tmp_path, "mixed", persona={"tools": ["notepad", "calculator", "notepad"]})
    make(tmp_path, "bad", persona={"tools": "notepad"})
    got = {p.id: p for p in discover_personas(tmp_path)}
    assert got["none"].tools == () and got["none"].warnings == []
    assert got["mixed"].tools == ("notepad",) and "calculator" in got["mixed"].warnings[0]
    assert got["bad"].tools == DEFAULT_TOOLS and got["bad"].warnings


def test_broken_files_are_reported_not_raised(tmp_path):
    make(tmp_path, "badjson", raw_persona="{nope")
    make(tmp_path, "notobject", raw_persona="[1]")
    make(tmp_path, "brokenflow", flow=False)
    (tmp_path / "brokenflow" / "flow.json").write_text("{not json", encoding="utf-8")
    make(tmp_path, "wrongshape", flow={"steps": []})
    got = {p.id: p for p in discover_personas(tmp_path)}
    assert got["badjson"].usable and got["badjson"].tools == DEFAULT_TOOLS and "couldn't be read" in got["badjson"].warnings[0]
    assert got["notobject"].usable and got["notobject"].warnings
    assert not got["brokenflow"].usable and "can't be read" in got["brokenflow"].error
    assert not got["wrongshape"].usable


def test_non_persona_folders_and_files_are_ignored_and_missing_roots_are_empty(tmp_path):
    make(tmp_path, "empty-folder", flow=False)
    (tmp_path / "notes.txt").write_text("hi")
    make(tmp_path, "real")
    assert [p.id for p in discover_personas(tmp_path)] == ["real"]
    assert discover_personas(tmp_path / "missing") == [] and discover_personas(tmp_path / "notes.txt") == []


def test_sorted_by_name_and_ids_stay_unique(tmp_path):
    make(tmp_path, "Zed Co", persona={"name": "Zed"})
    make(tmp_path, "alpha", persona={"name": "alpha"})
    make(tmp_path, "Beta!!", persona={"name": "Beta"})
    make(tmp_path, "Beta??", persona={"name": "Beta Two"})
    got = discover_personas(tmp_path)
    assert [p.name.lower() for p in got] == sorted(p.name.lower() for p in got)
    assert len({p.id for p in got}) == len(got)


def test_load_persona_works_on_one_folder(tmp_path):
    d = make(tmp_path, "My Flow")
    p = load_persona(d)
    assert p.id == "My-Flow" and p.usable
    assert not load_persona(tmp_path / "nowhere").usable
