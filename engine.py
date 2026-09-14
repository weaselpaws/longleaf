"""
Longleaf - decision-tree engine (no GUI).

A tree is a flat dict of Steps keyed by id, plus a root_id. Each Step
has a question and a list of Options; each Option either points at
another step (`next_id`) or ends the flow with a `resolution` note.

Kept deliberately dumb and GUI-free: the Player and Editor both wrap
this same engine, and it's also the thing that gets serialized to/from
JSON so trees are just data, not code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Option:
    label: str
    next_id: Optional[str] = None      # set -> advances to that step
    resolution: Optional[str] = None   # set (and next_id None) -> ends the flow here

    @property
    def is_terminal(self) -> bool:
        return not self.next_id

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Option":
        return Option(label=d["label"], next_id=d.get("next_id"), resolution=d.get("resolution"))


@dataclass
class Step:
    id: str
    question: str
    options: list[Option] = field(default_factory=list)
    note: str = ""  # optional tech-facing hint shown under the question

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "note": self.note,
            "options": [o.to_dict() for o in self.options],
        }

    @staticmethod
    def from_dict(d: dict) -> "Step":
        return Step(
            id=d["id"],
            question=d.get("question", ""),
            note=d.get("note", ""),
            options=[Option.from_dict(o) for o in d.get("options", [])],
        )


@dataclass
class Tree:
    title: str = "Untitled Flow"
    root_id: str = ""
    steps: dict[str, Step] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "root_id": self.root_id,
            "steps": {sid: s.to_dict() for sid, s in self.steps.items()},
        }

    @staticmethod
    def from_dict(d: dict) -> "Tree":
        return Tree(
            title=d.get("title", "Untitled Flow"),
            root_id=d.get("root_id", ""),
            steps={sid: Step.from_dict(s) for sid, s in d.get("steps", {}).items()},
        )

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @staticmethod
    def load(path: str) -> "Tree":
        with open(path, "r", encoding="utf-8") as f:
            return Tree.from_dict(json.load(f))

    # ---------- editing helpers ----------

    def new_step_id(self) -> str:
        n = 1
        while f"step_{n}" in self.steps:
            n += 1
        return f"step_{n}"

    def add_step(self, question: str = "New question") -> Step:
        step = Step(id=self.new_step_id(), question=question)
        self.steps[step.id] = step
        if not self.root_id:
            self.root_id = step.id
        return step

    def delete_step(self, step_id: str):
        self.steps.pop(step_id, None)
        for s in self.steps.values():
            for o in s.options:
                if o.next_id == step_id:
                    o.next_id = None
        if self.root_id == step_id:
            self.root_id = next(iter(self.steps), "")

    def reachable_ids(self) -> set[str]:
        if not self.root_id or self.root_id not in self.steps:
            return set()
        seen, stack = set(), [self.root_id]
        while stack:
            sid = stack.pop()
            if sid in seen or sid not in self.steps:
                continue
            seen.add(sid)
            for o in self.steps[sid].options:
                if o.next_id:
                    stack.append(o.next_id)
        return seen

    def validate(self) -> list[str]:
        """Returns human-readable warnings; empty list means the tree is clean."""
        warnings = []
        if not self.steps:
            return ["Tree has no steps."]
        if not self.root_id or self.root_id not in self.steps:
            warnings.append("No valid starting step is set.")
        for sid, step in self.steps.items():
            if not step.question.strip():
                warnings.append(f"'{sid}' has no question text.")
            if not step.options:
                warnings.append(f"'{sid}' has no answer options (dead end).")
            for o in step.options:
                if o.next_id and o.next_id not in self.steps:
                    warnings.append(f"'{sid}' option '{o.label}' points at a missing step.")
                if o.is_terminal and not (o.resolution or "").strip():
                    warnings.append(f"'{sid}' option '{o.label}' ends the flow but has no resolution text.")
        unreachable = set(self.steps) - self.reachable_ids()
        for sid in unreachable:
            warnings.append(f"'{sid}' is unreachable from the start step.")
        return warnings


@dataclass
class HistoryEntry:
    step_question: str
    chosen_label: str
    timestamp: str


class TroubleshootEngine:
    """Runs one live pass through a Tree, tracking the path taken."""

    def __init__(self, tree: Tree):
        self.tree = tree
        self.current_id: Optional[str] = None
        self.history: list[HistoryEntry] = []
        self.resolution: Optional[str] = None
        self.reset()

    def reset(self):
        self.current_id = self.tree.root_id or None
        self.history = []
        self.resolution = None

    @property
    def current_step(self) -> Optional[Step]:
        if self.current_id and self.current_id in self.tree.steps:
            return self.tree.steps[self.current_id]
        return None

    @property
    def is_finished(self) -> bool:
        return self.resolution is not None or self.current_step is None

    def choose(self, option: Option):
        step = self.current_step
        if not step:
            return
        self.history.append(HistoryEntry(
            step_question=step.question,
            chosen_label=option.label,
            timestamp=datetime.now().strftime("%H:%M:%S"),
        ))
        if option.next_id:
            self.current_id = option.next_id
        else:
            self.current_id = None
            self.resolution = option.resolution or "(No resolution text was set for this ending.)"

    def can_go_back(self) -> bool:
        return len(self.history) > 0

    def go_back(self):
        """Undo the last answer and return to the step it was asked from."""
        if not self.history:
            return
        # Find the step whose question matches the last history entry by
        # re-walking from root — simplest reliable way without storing a
        # parallel stack of step ids alongside history.
        entry = self.history.pop()
        self.resolution = None
        # rebuild current_id by replaying remaining history from root
        self.current_id = self.tree.root_id
        for h in self.history:
            step = self.tree.steps.get(self.current_id)
            if not step:
                break
            match = next((o for o in step.options if o.label == h.chosen_label), None)
            self.current_id = match.next_id if match else None
        if self.current_id is None and not self.history:
            self.current_id = self.tree.root_id

    def report_text(self) -> str:
        lines = [f"Longleaf — {self.tree.title}", ""]
        for i, h in enumerate(self.history, 1):
            lines.append(f"{i}. [{h.timestamp}] {h.step_question}")
            lines.append(f"   -> {h.chosen_label}")
        lines.append("")
        lines.append(f"Result: {self.resolution}" if self.resolution else "Result: (in progress)")
        lines.append("")
        lines.append("Longleaf — a Yellowhammer product")
        return "\n".join(lines)
