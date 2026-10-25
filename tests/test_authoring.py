import pytest

from engine import Tree
from outline_import import OutlineError, import_outline

OUTLINE = """# power flow
Does the PC power on?  [tags: power, boot]
  - Yes
    Does it reach the login screen?
      - Yes => Run the update again from Safe Mode.
      - No => Escalate to hardware.
  - No => Check the power cable.
"""


def test_outline_builds_a_valid_flow():
    t = Tree()
    steps = import_outline(t, OUTLINE)
    assert [s.question for s in steps] == ["Does the PC power on?", "Does it reach the login screen?"]
    assert t.root_id == steps[0].id and steps[0].tags == ["power", "boot"]
    yes, no = steps[0].options
    assert yes.next_id == steps[1].id and no.resolution == "Check the power cable."
    assert [o.resolution for o in steps[1].options] == ["Run the update again from Safe Mode.", "Escalate to hardware."]
    assert t.errors() == []


def test_outline_appends_without_clobbering_ids_or_root():
    t = Tree()
    first = t.add_step("Existing")
    new = import_outline(t, "Another?\n  - A => x\n")
    assert new[0].id != first.id and t.root_id == first.id and len(t.steps) == 2


def test_outline_accepts_tabs_and_star_bullets():
    t = Tree()
    import_outline(t, "Q1\n\t* A\n\t\tQ2\n\t\t\t* B => done\n\t* C => ok\n")
    assert len(t.steps) == 2 and t.errors() == []


@pytest.mark.parametrize("text,msg", [
    ("", "empty"),
    ("- orphan answer\n", "Line 1"),
    ("Q\n  - A => x\n    Q2\n", "Line 3"),
    ("Q\n  - \n", "Line 2"),
])
def test_outline_errors_name_the_line_and_add_nothing(text, msg):
    t = Tree()
    with pytest.raises(OutlineError, match=msg):
        import_outline(t, text)
    assert not t.steps


def test_duplicate_step_copies_content_with_new_id():
    t = Tree()
    import_outline(t, OUTLINE)
    src = t.steps[t.root_id]
    copy = t.duplicate_step(src.id)
    assert copy.id != src.id and copy.question == src.question + " (copy)"
    assert copy.tags == src.tags and [o.label for o in copy.options] == [o.label for o in src.options]
    copy.options[0].label = "changed"
    assert src.options[0].label == "Yes"          # a real copy, not shared


def test_new_step_from_answer_links_and_clears_ending():
    t = Tree()
    s = t.add_step("Q")
    from engine import Option
    s.options.append(Option(label="A", resolution="old"))
    new = t.new_step_from_answer(s.id, 0)
    assert s.options[0].next_id == new.id and s.options[0].resolution is None
