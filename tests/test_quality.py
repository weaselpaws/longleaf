from engine import Option, Step, Tree


def test_quality_check_is_hints_only_and_skips_unreachable_steps():
    t = Tree(title="T", root_id="q1", steps={
        "q1": Step("q1", "Q1", [Option("A", None, "short"), Option("B", "q2")]),
        "q2": Step("q2", "Q2", [Option("C", None, "Do the whole thing properly."),
                                Option("D", None, "Do the other thing properly.")], tags=["x"]),
        "orphan": Step("orphan", "No tags here", [Option("x", None, "Do something useful.")]),
    })
    codes = [(i.code, i.step_id) for i in t.quality_check()]
    assert ("NO_TAGS", "q1") in codes and ("THIN_RESOLUTION", "q1") in codes
    assert not any(sid == "orphan" for _, sid in codes)
    assert ("NO_TAGS", "q2") not in codes
    assert t.errors() == []                # hints never affect validity
