"""Graph layout tests — pure Python, no Qt. Run: python -m pytest tests"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import Tree  # noqa: E402
from graph_layout import layout  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def assert_no_overlap(placed):
    slots = [(p.layer, p.row) for p in placed.values()]
    assert len(slots) == len(set(slots))


def test_chain_goes_left_to_right():
    p = layout(list("abc"), [("a", "b"), ("b", "c")], "a")
    assert [p[n].layer for n in "abc"] == [0, 1, 2]


def test_merge_sits_right_of_every_parent():
    # a -> b -> c -> d and a -> d: d must be right of c, not right of a.
    p = layout(list("abcd"), [("a", "b"), ("b", "c"), ("c", "d"), ("a", "d")], "a")
    assert p["d"].layer == 3
    assert_no_overlap(p)


def test_loops_do_not_hang_or_stretch():
    p = layout(list("abc"), [("a", "b"), ("b", "c"), ("c", "b"), ("b", "b")], "a")
    assert [p[n].layer for n in "abc"] == [0, 1, 2]


def test_unreachable_steps_get_a_separate_band_below():
    p = layout(list("abxy"), [("a", "b"), ("x", "y")], "a")
    assert min(p["x"].row, p["y"].row) > max(p["a"].row, p["b"].row) + 1
    assert p["x"].layer == 0 and p["y"].layer == 1
    assert_no_overlap(p)


def test_unreachable_cycle_is_still_placed():
    p = layout(list("axy"), [("x", "y"), ("y", "x")], "a")
    assert set(p) == set("axy")
    assert_no_overlap(p)


def test_missing_or_absent_start_still_places_everything():
    assert set(layout(list("ab"), [("a", "b")], None)) == set("ab")
    assert set(layout(list("ab"), [("a", "b")], "zzz")) == set("ab")
    assert layout([], [], None) == {}


def test_unknown_nodes_in_edges_are_ignored():
    assert set(layout(["a"], [("a", "ghost")], "a")) == {"a"}


def test_deterministic():
    nodes, edges = list("abcdefg"), [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"), ("d", "e"), ("c", "f")]
    assert layout(nodes, edges, "a") == layout(nodes, edges, "a")


def test_crossing_reduction_untangles_a_simple_swap():
    # a -> {b, c}; b -> y, c -> x with x listed before y: sweeps should line b/y and c/x up.
    p = layout(list("abcxy"), [("a", "b"), ("a", "c"), ("b", "y"), ("c", "x")], "a")
    assert (p["b"].row < p["c"].row) == (p["y"].row < p["x"].row)


@pytest.mark.parametrize("path", sorted(ROOT.glob("examples/*.json")) + [ROOT / "sample_tree.json"])
def test_shipped_flows_lay_out_without_overlap(path):
    t = Tree.load(str(path))
    edges = [(sid, o.next_id) for sid, s in t.steps.items() for o in s.options if o.next_id]
    p = layout(list(t.steps), edges, t.root_id)
    assert set(p) == set(t.steps)
    assert_no_overlap(p)
    assert p[t.root_id].layer == 0
