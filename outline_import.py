"""
Outline importer — turn an indented text outline into steps (Editor-only authoring aid).

    Does the PC power on?  [tags: power, boot]
      - Yes
        Does it reach the login screen?
          - Yes => Reboot into Safe Mode and run the update again.
          - No
            Is there a beep code?
              - Yes => Reseat the RAM.
              - No => Escalate to hardware.
      - No => Check the power cable and wall socket.

A line starting with "-" (or "*") is an answer; any other line is a question. An answer's
question goes indented under it. "=> text" after an answer ends the flow there with that text.
Indentation may be spaces or tabs; blank lines and lines starting with "#" are ignored.
GUI-free so it stays unit-testable.
"""

import re

from engine import Option, Step, Tree

_TAGS = re.compile(r"\s*\[tags?:\s*([^\]]*)\]\s*$", re.IGNORECASE)
_BULLET = re.compile(r"^[-*•](\s+|$)")


class OutlineError(ValueError):
    """The outline couldn't be read; the message names the line."""


def _split(raw: str) -> tuple[int, str]:
    expanded = raw.expandtabs(4)
    body = expanded.lstrip(" ")
    return len(expanded) - len(body), body.rstrip()


def import_outline(tree: Tree, text: str) -> list[Step]:
    """Add the outline's steps to `tree` (the first becomes the start step if there is none).
    Returns the new steps in order. Nothing is added if the outline has an error."""
    parsed: list[tuple[int, int, bool, str]] = []   # (line no, indent, is_answer, text)
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent, body = _split(raw)
        m = _BULLET.match(body)
        parsed.append((n, indent, bool(m), body[m.end():].strip() if m else body))
    if not parsed:
        raise OutlineError("The outline is empty.")

    new_steps: list[Step] = []
    stack: list[tuple[int, object]] = []   # (indent, Step | Option)
    taken = set(tree.steps)

    def fresh_id() -> str:
        n = 1
        while f"step_{n}" in taken:
            n += 1
        taken.add(f"step_{n}")
        return f"step_{n}"

    for n, indent, is_answer, body in parsed:
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else None
        if is_answer:
            if not isinstance(parent, Step):
                raise OutlineError(f"Line {n}: an answer must sit under a question.")
            label, _, resolution = body.partition("=>")
            label = label.strip()
            if not label:
                raise OutlineError(f"Line {n}: this answer has no label.")
            option = Option(label=label, resolution=resolution.strip() or None)
            parent.options.append(option)
            stack.append((indent, option))
        else:
            tags: list[str] = []
            m = _TAGS.search(body)
            if m:
                tags = [t.strip() for t in m.group(1).split(",") if t.strip()]
                body = body[:m.start()].strip()
            if not body:
                raise OutlineError(f"Line {n}: this question has no text.")
            if isinstance(parent, Option):
                if parent.resolution:
                    raise OutlineError(f"Line {n}: that answer already ends the flow ('=>'), so it can't lead to a question.")
                if parent.next_id:
                    raise OutlineError(f"Line {n}: that answer already leads to a question; an answer goes to one step.")
            step = Step(id=fresh_id(), question=body, tags=tags)
            new_steps.append(step)
            if isinstance(parent, Option):
                parent.next_id = step.id
            stack.append((indent, step))

    for step in new_steps:
        tree.steps[step.id] = step
    if not tree.root_id or tree.root_id not in tree.steps:
        tree.root_id = new_steps[0].id
    return new_steps
