"""Keeps docs/API.md honest: its examples must parse with, and round-trip
through, the real engine types."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import Issue, Option, SessionRecord, Step, Tree, TroubleshootEngine  # noqa: E402

DOC = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")


def _json_block_after(marker: str) -> dict:
    m = re.search(re.escape(marker) + r"\s*```json\n(.*?)```", DOC, re.S)
    assert m, f"no json block after {marker}"
    return json.loads(m.group(1))


def test_session_record_example_roundtrips_exactly():
    example = _json_block_after("<!-- session-record-example -->")
    assert SessionRecord.from_dict(example).to_dict() == example


def test_engine_record_has_exactly_the_documented_keys():
    example = _json_block_after("<!-- session-record-example -->")
    t = Tree(title="T", root_id="a", steps={"a": Step("a", "Q", [Option("x", None, "r")])})
    e = TroubleshootEngine(t)
    e.choose(t.steps["a"].options[0])
    d = e.record().to_dict()
    assert set(d) == set(example)
    assert set(d["flow"]) == set(example["flow"])
    assert set(d["history"][0]) == set(example["history"][0])


def test_every_documented_issue_code_exists_and_vice_versa():
    documented = set(re.findall(r"^\| `([A-Z_]+)` \| (?:error|warning) \|", DOC, re.M))
    # Trigger every code the engine can emit with one deliberately awful flow.
    t = Tree(title="T", root_id="a", steps={
        "a": Step("a", "", [Option("Yes", "b"), Option(" yes", "ghost"), Option("", None, ""),
                            Option("self", "a"), Option("both", "b", "ignored")]),
        "b": Step("b", "B", [Option("back", "c")]),
        "c": Step("c", "C", [Option("back", "b")]),
        "orphan": Step("orphan", "O", []),
        "z": Step("zzz", "Z", [Option("x", None, "r")]),
    })
    emitted = {i.code for i in t.check()} | {i.code for i in Tree().check()}
    # CYCLE needs a loop that has an exit; NO_START needs a bad root.
    t2 = Tree(title="T", root_id="a", steps={"a": Step("a", "A", [Option("g", "b")]),
                                              "b": Step("b", "B", [Option("r", "a"), Option("e", None, "x")])})
    emitted |= {i.code for i in t2.check()}
    emitted |= {i.code for i in Tree(title="T", root_id="nope", steps=t2.steps).check()}
    assert emitted == documented, (emitted ^ documented)


def test_issue_example_shape():
    i = Issue("error", "MISSING_TARGET", "m", "a", 0)
    m = re.search(r'Issue\n.*?```json\n(.*?)```', DOC, re.S)
    assert set(json.loads(m.group(1))) == set(i.to_dict())
