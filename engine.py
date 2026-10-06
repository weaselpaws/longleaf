"""
Longleaf - decision-tree engine (no GUI).

A tree is a flat dict of Steps keyed by id, plus a root_id. Each Step
has a question and a list of Options; each Option either points at
another step (`next_id`) or ends the flow with a `resolution` note.

Kept deliberately dumb and GUI-free: the Player and Editor both wrap
this same engine, and it's also the thing that gets serialized to/from
JSON so trees are just data, not code. Nothing here imports Qt, so a
future Longleaf server can import this module as-is to validate flows
and render reports (see docs/API.md).
"""

from __future__ import annotations

import html
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

# Bump when the flow file or session record shape changes incompatibly.
# Additive changes (new optional fields) do not bump it.
SCHEMA_VERSION = 1

BRAND_LINE = "Longleaf — a Yellowhammer product"

OUTCOME_RESOLVED = "resolved"
OUTCOME_IN_PROGRESS = "in_progress"
OUTCOME_ERROR = "error"      # the flow itself is broken (e.g. an answer points at a missing step)


class FlowFormatError(ValueError):
    """A flow file couldn't be understood at all (as opposed to merely failing validation)."""


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
        if not isinstance(d, dict) or "label" not in d:
            raise FlowFormatError(f"Answer option is missing a 'label': {d!r}")
        return Option(label=d["label"], next_id=d.get("next_id") or None, resolution=d.get("resolution"))


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
    def from_dict(d: dict, default_id: str = "") -> "Step":
        if not isinstance(d, dict):
            raise FlowFormatError(f"Step '{default_id}' is not an object.")
        return Step(
            id=d.get("id") or default_id,
            question=d.get("question", ""),
            note=d.get("note", ""),
            options=[Option.from_dict(o) for o in d.get("options", [])],
        )


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------

SEVERITY_ERROR = "error"      # the flow is broken; don't ship it
SEVERITY_WARNING = "warning"  # probably a mistake, but the flow still runs


@dataclass(frozen=True)
class Issue:
    """One validation finding. Structured so the Editor can jump to the
    offending step and a server can return it verbatim as JSON."""
    severity: str
    code: str
    message: str
    step_id: Optional[str] = None
    option_index: Optional[int] = None

    @property
    def is_error(self) -> bool:
        return self.severity == SEVERITY_ERROR

    def to_dict(self) -> dict:
        return asdict(self)


def _norm(label: str) -> str:
    return " ".join((label or "").split()).casefold()


@dataclass
class Tree:
    title: str = "Untitled Flow"
    root_id: str = ""
    steps: dict[str, Step] = field(default_factory=dict)
    version: str = ""   # flow/release version, stamped into every report
    client: str = ""    # client name or slug, stamped into every report

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "title": self.title,
            "client": self.client,
            "version": self.version,
            "root_id": self.root_id,
            "steps": {sid: s.to_dict() for sid, s in self.steps.items()},
        }

    @staticmethod
    def from_dict(d: dict) -> "Tree":
        if not isinstance(d, dict):
            raise FlowFormatError("A flow file must contain a JSON object.")
        raw_steps = d.get("steps", {})
        if not isinstance(raw_steps, dict):
            raise FlowFormatError("'steps' must be an object keyed by step id.")
        return Tree(
            title=d.get("title", "Untitled Flow"),
            root_id=d.get("root_id", ""),
            steps={sid: Step.from_dict(s, default_id=sid) for sid, s in raw_steps.items()},
            version=str(d.get("version", "") or ""),
            client=str(d.get("client", "") or ""),
        )

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @staticmethod
    def load(path: str) -> "Tree":
        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                raise FlowFormatError(f"Not valid JSON: {e}") from e
        return Tree.from_dict(data)

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

    # ---------- graph analysis ----------

    def _targets(self, sid: str) -> list[str]:
        """Existing steps that `sid` links to (dangling links are skipped)."""
        step = self.steps.get(sid)
        if not step:
            return []
        return [o.next_id for o in step.options if o.next_id and o.next_id in self.steps]

    def reachable_ids(self) -> set[str]:
        if not self.root_id or self.root_id not in self.steps:
            return set()
        seen, stack = set(), [self.root_id]
        while stack:
            sid = stack.pop()
            if sid in seen or sid not in self.steps:
                continue
            seen.add(sid)
            stack.extend(self._targets(sid))
        return seen

    def steps_that_can_finish(self) -> set[str]:
        """Steps from which at least one sequence of answers reaches a real
        ending (an answer with no next step). Fixed-point over the graph."""
        finishing = {
            sid for sid, s in self.steps.items()
            if any(o.is_terminal for o in s.options)
        }
        changed = True
        while changed:
            changed = False
            for sid in self.steps:
                if sid not in finishing and any(t in finishing for t in self._targets(sid)):
                    finishing.add(sid)
                    changed = True
        return finishing

    def cycles(self) -> list[list[str]]:
        """Groups of reachable steps that can loop back on themselves
        (strongly connected components of size > 1, plus self-links),
        each in a stable order. Iterative Tarjan so deep flows can't
        blow the recursion limit."""
        reachable = self.reachable_ids()
        index: dict[str, int] = {}
        low: dict[str, int] = {}
        on_stack: set[str] = set()
        stack: list[str] = []
        counter = 0
        out: list[list[str]] = []
        order = {sid: i for i, sid in enumerate(self.steps)}

        for start in self.steps:  # dict order keeps output deterministic
            if start not in reachable or start in index:
                continue
            work = [(start, iter(self._targets(start)))]
            index[start] = low[start] = counter
            counter += 1
            stack.append(start)
            on_stack.add(start)
            while work:
                node, it = work[-1]
                advanced = False
                for nxt in it:
                    if nxt not in index:
                        index[nxt] = low[nxt] = counter
                        counter += 1
                        stack.append(nxt)
                        on_stack.add(nxt)
                        work.append((nxt, iter(self._targets(nxt))))
                        advanced = True
                        break
                    if nxt in on_stack:
                        low[node] = min(low[node], index[nxt])
                if advanced:
                    continue
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index[node]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        comp.append(w)
                        if w == node:
                            break
                    if len(comp) > 1 or node in self._targets(node):
                        out.append(sorted(comp, key=order.__getitem__))
        out.sort(key=lambda c: order[c[0]])
        return out

    # ---------- validation ----------

    def check(self) -> list[Issue]:
        """Every problem found in the flow, structured. Errors mean the
        flow is broken and shouldn't ship; warnings are probable mistakes."""
        issues: list[Issue] = []
        add = lambda *a, **k: issues.append(Issue(*a, **k))  # noqa: E731

        if not self.steps:
            return [Issue(SEVERITY_ERROR, "NO_STEPS", "Tree has no steps.")]

        root_ok = bool(self.root_id) and self.root_id in self.steps
        if not root_ok:
            add(SEVERITY_ERROR, "NO_START", "No valid starting step is set.", step_id=self.root_id or None)

        reachable = self.reachable_ids()
        can_finish = self.steps_that_can_finish()

        for sid, step in self.steps.items():
            if step.id != sid:
                add(SEVERITY_ERROR, "ID_MISMATCH",
                    f"'{sid}' is stored under a different id than its own ('{step.id}').", step_id=sid)
            if not step.question.strip():
                add(SEVERITY_ERROR, "EMPTY_QUESTION", f"'{sid}' has no question text.", step_id=sid)
            if not step.options:
                add(SEVERITY_ERROR, "DEAD_END", f"'{sid}' has no answer options (dead end).", step_id=sid)

            seen_labels: dict[str, int] = {}
            for i, o in enumerate(step.options):
                shown = o.label.strip() or f"#{i + 1}"
                if not o.label.strip():
                    add(SEVERITY_ERROR, "EMPTY_LABEL",
                        f"'{sid}' answer #{i + 1} has no label.", step_id=sid, option_index=i)
                else:
                    key = _norm(o.label)
                    if key in seen_labels:
                        add(SEVERITY_ERROR, "DUPLICATE_LABEL",
                            f"'{sid}' has two answers labelled '{shown}' — a tech can't tell them apart.",
                            step_id=sid, option_index=i)
                    else:
                        seen_labels[key] = i

                if o.next_id:
                    if o.next_id not in self.steps:
                        add(SEVERITY_ERROR, "MISSING_TARGET",
                            f"'{sid}' option '{shown}' points at a missing step ('{o.next_id}').",
                            step_id=sid, option_index=i)
                    elif o.next_id == sid:
                        add(SEVERITY_WARNING, "SELF_LINK",
                            f"'{sid}' option '{shown}' leads back to the same step.",
                            step_id=sid, option_index=i)
                    if (o.resolution or "").strip():
                        add(SEVERITY_WARNING, "IGNORED_RESOLUTION",
                            f"'{sid}' option '{shown}' has both a next step and a resolution — "
                            f"the resolution will never be shown.", step_id=sid, option_index=i)
                elif not (o.resolution or "").strip():
                    add(SEVERITY_ERROR, "NO_RESOLUTION",
                        f"'{sid}' option '{shown}' ends the flow but has no resolution text.",
                        step_id=sid, option_index=i)

            # A reachable step with answers, none of which can ever lead to an
            # ending, traps the tech in a loop (or at a missing step) forever.
            if sid in reachable and step.options and sid not in can_finish:
                add(SEVERITY_ERROR, "NO_EXIT",
                    f"'{sid}' can never reach an ending — every path from it loops or hits a missing step.",
                    step_id=sid)

        for sid in self.steps:
            if sid not in reachable and root_ok:
                add(SEVERITY_WARNING, "UNREACHABLE", f"'{sid}' is unreachable from the start step.", step_id=sid)

        for comp in self.cycles():
            # A loop is fine if there's a way out; NO_EXIT already covers the trapped case.
            if len(comp) > 1 and comp[0] in can_finish:
                add(SEVERITY_WARNING, "CYCLE",
                    "These steps can loop back on each other: " + ", ".join(comp) + ".",
                    step_id=comp[0])

        return issues

    def errors(self) -> list[Issue]:
        return [i for i in self.check() if i.is_error]

    def validate(self) -> list[str]:
        """Human-readable messages for every issue; empty list means clean.
        (Kept for callers that only want strings — see check() for detail.)"""
        return [i.message for i in self.check()]


# ---------------------------------------------------------------------
# Sessions & reports
# ---------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def _fmt_clock(iso: Optional[str]) -> str:
    return datetime.fromisoformat(iso).strftime("%H:%M:%S") if iso else ""


def _fmt_stamp(iso: Optional[str]) -> str:
    return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M") if iso else ""


def _fmt_duration(start: Optional[str], end: Optional[str]) -> str:
    if not (start and end):
        return ""
    secs = max(0, int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()))
    m, s = divmod(secs, 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


@dataclass
class HistoryEntry:
    step_id: str
    step_question: str
    option_index: int
    chosen_label: str
    answered_at: str  # ISO-8601 with UTC offset

    @property
    def timestamp(self) -> str:
        """Wall-clock time of day, for display."""
        return _fmt_clock(self.answered_at)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "HistoryEntry":
        return HistoryEntry(
            step_id=d["step_id"],
            step_question=d.get("step_question", ""),
            option_index=int(d.get("option_index", -1)),
            chosen_label=d.get("chosen_label", ""),
            answered_at=d.get("answered_at", ""),
        )


@dataclass
class SessionRecord:
    """A finished (or in-progress) pass through a flow, as plain data.

    This is the unit that gets exported from the Player today and that a
    server would store and aggregate later. Step ids + option indexes make
    the path unambiguous even if question wording changes between versions;
    the question/label text is kept alongside so reports stay readable.
    All reports render from this, never from live engine state.
    """
    session_id: str
    flow_title: str
    flow_client: str
    flow_version: str
    started_at: str
    finished_at: Optional[str]
    outcome: str
    resolution: Optional[str]
    history: list[HistoryEntry]
    ticket_ref: str = ""
    operator: str = ""
    notes: str = ""
    feedback: Optional[dict] = None   # {"helpful": bool | None, "comment": str} — reserved, see docs/API.md
    schema_version: int = SCHEMA_VERSION

    # ---- serialization ----

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "flow": {"title": self.flow_title, "client": self.flow_client, "version": self.flow_version},
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "outcome": self.outcome,
            "resolution": self.resolution,
            "ticket_ref": self.ticket_ref,
            "operator": self.operator,
            "notes": self.notes,
            "feedback": self.feedback,
            "history": [h.to_dict() for h in self.history],
        }

    @staticmethod
    def from_dict(d: dict) -> "SessionRecord":
        flow = d.get("flow", {})
        return SessionRecord(
            session_id=d["session_id"],
            flow_title=flow.get("title", ""),
            flow_client=flow.get("client", ""),
            flow_version=flow.get("version", ""),
            started_at=d["started_at"],
            finished_at=d.get("finished_at"),
            outcome=d.get("outcome", OUTCOME_IN_PROGRESS),
            resolution=d.get("resolution"),
            history=[HistoryEntry.from_dict(h) for h in d.get("history", [])],
            ticket_ref=d.get("ticket_ref", ""),
            operator=d.get("operator", ""),
            notes=d.get("notes", ""),
            feedback=d.get("feedback"),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    # ---- reports ----

    def _result_line(self) -> str:
        if self.outcome == OUTCOME_RESOLVED:
            return self.resolution or ""
        if self.outcome == OUTCOME_ERROR:
            return f"FLOW ERROR — {self.resolution}"
        return "(in progress)"

    def _meta_rows(self) -> list[tuple[str, str]]:
        rows = [
            ("Flow version", self.flow_version),
            ("Client", self.flow_client),
            ("Ticket", self.ticket_ref),
            ("Technician", self.operator),
            ("Started", _fmt_stamp(self.started_at)),
            ("Duration", _fmt_duration(self.started_at, self.finished_at)),
            ("Session", self.session_id[:8]),
        ]
        return [(k, v) for k, v in rows if v]

    def to_text(self) -> str:
        lines = [f"Longleaf — {self.flow_title}", ""]
        meta = [f"{k}: {v}" for k, v in self._meta_rows()]
        lines.extend(meta + [""] if meta else [])
        for i, h in enumerate(self.history, 1):
            lines.append(f"{i}. [{h.timestamp}] {h.step_question}")
            lines.append(f"   -> {h.chosen_label}")
        lines.append("")
        lines.append(f"Result: {self._result_line()}")
        if self.notes.strip():
            lines.extend(["", "Notes:", self.notes.strip()])
        lines.extend(["", BRAND_LINE])
        return "\n".join(lines)

    def to_markdown(self) -> str:
        esc = lambda s: s.replace("|", "\\|")  # noqa: E731
        out = [f"# {self.flow_title}", ""]
        for k, v in self._meta_rows():
            out.append(f"- **{k}:** {v}")
        out.extend(["", "## Path taken", ""])
        for i, h in enumerate(self.history, 1):
            out.append(f"{i}. **{h.step_question}** → {h.chosen_label} _({h.timestamp})_")
        out.extend(["", "## Result", "", self._result_line()])
        if self.notes.strip():
            out.extend(["", "## Notes", "", self.notes.strip()])
        out.extend(["", f"_{BRAND_LINE}_", ""])
        return "\n".join(out)

    def to_html(self) -> str:
        e = html.escape
        meta = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in self._meta_rows())
        steps = "".join(
            f"<li><strong>{e(h.step_question)}</strong><br>→ {e(h.chosen_label)} "
            f"<span class=t>{e(h.timestamp)}</span></li>"
            for h in self.history
        )
        notes = f"<h2>Notes</h2><p>{e(self.notes.strip())}</p>" if self.notes.strip() else ""
        cls = {"resolved": "ok", "error": "bad"}.get(self.outcome, "")
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{e(self.flow_title)} — Longleaf report</title>"
            "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;color:#222}"
            "th{text-align:left;padding-right:1rem;color:#666;font-weight:600}.t{color:#888;font-size:.85em}"
            ".ok{color:#1e7d32}.bad{color:#b3261e}.result{font-size:1.1em;font-weight:600}"
            "footer{margin-top:2rem;color:#888;font-size:.85em}</style></head><body>"
            f"<h1>{e(self.flow_title)}</h1><table>{meta}</table>"
            f"<h2>Path taken</h2><ol>{steps}</ol>"
            f"<h2>Result</h2><p class='result {cls}'>{e(self._result_line())}</p>"
            f"{notes}<footer>{e(BRAND_LINE)}</footer></body></html>"
        )

    def render(self, fmt: str) -> str:
        try:
            return {"txt": self.to_text, "md": self.to_markdown,
                    "html": self.to_html, "json": self.to_json}[fmt]()
        except KeyError:
            raise ValueError(f"Unknown report format {fmt!r}; use txt, md, html or json.") from None


class TroubleshootEngine:
    """Runs one live pass through a Tree, tracking the path taken."""

    def __init__(self, tree: Tree):
        self.tree = tree
        self.current_id: Optional[str] = None
        self.history: list[HistoryEntry] = []
        self.resolution: Optional[str] = None
        self.outcome: str = OUTCOME_IN_PROGRESS
        self.session_id: str = ""
        self.started_at: str = ""
        self.finished_at: Optional[str] = None
        self.ticket_ref: str = ""
        self.operator: str = ""
        self.notes: str = ""
        self.feedback: Optional[dict] = None
        self.reset()

    def reset(self):
        self.current_id = self.tree.root_id or None
        self.history = []
        self.resolution = None
        self.outcome = OUTCOME_IN_PROGRESS
        self.session_id = str(uuid.uuid4())
        self.started_at = _now().isoformat()
        self.finished_at = None
        self.ticket_ref = ""
        self.operator = ""
        self.notes = ""
        self.feedback = None

    @property
    def current_step(self) -> Optional[Step]:
        if self.current_id and self.current_id in self.tree.steps:
            return self.tree.steps[self.current_id]
        return None

    @property
    def is_finished(self) -> bool:
        return self.resolution is not None or self.current_step is None

    def choose(self, option: Option):
        """Answer the current step. `option` must be one of its options."""
        step = self.current_step
        if not step or self.is_finished:
            return
        idx = next((i for i, o in enumerate(step.options) if o is option), None)
        if idx is None:
            idx = next((i for i, o in enumerate(step.options) if o == option), None)
        if idx is None:
            raise ValueError(f"Option {option.label!r} does not belong to step {step.id!r}.")

        self.history.append(HistoryEntry(
            step_id=self.current_id,   # the key we navigated by, not the step's self-reported id
            step_question=step.question,
            option_index=idx,
            chosen_label=option.label,
            answered_at=_now().isoformat(),
        ))
        if option.next_id and option.next_id in self.tree.steps:
            self.current_id = option.next_id
        elif option.next_id:
            # Authoring error: the answer links to a step that doesn't exist.
            # End visibly instead of leaving a blank "finished" screen.
            self.current_id = None
            self.outcome = OUTCOME_ERROR
            self.resolution = (
                f"This answer leads to a step that doesn't exist ('{option.next_id}'). "
                f"Please report this flow error to whoever maintains it."
            )
            self.finished_at = _now().isoformat()
        else:
            self.current_id = None
            self.outcome = OUTCOME_RESOLVED
            self.resolution = option.resolution or "(No resolution text was set for this ending.)"
            self.finished_at = _now().isoformat()

    def can_go_back(self) -> bool:
        return len(self.history) > 0

    def go_back(self):
        """Undo the last answer and return to the step it was asked from."""
        if not self.history:
            return
        entry = self.history.pop()
        self.current_id = entry.step_id
        self.resolution = None
        self.outcome = OUTCOME_IN_PROGRESS
        self.finished_at = None
        self.feedback = None

    def set_feedback(self, helpful: Optional[bool], comment: str = ""):
        """Record the tech's rating of this ending. Not wired to any UI yet;
        exists so the session record shape is final before a server needs it."""
        self.feedback = {"helpful": helpful, "comment": comment}

    def record(self) -> SessionRecord:
        return SessionRecord(
            session_id=self.session_id,
            flow_title=self.tree.title,
            flow_client=self.tree.client,
            flow_version=self.tree.version,
            started_at=self.started_at,
            finished_at=self.finished_at,
            outcome=self.outcome,
            resolution=self.resolution,
            history=list(self.history),
            ticket_ref=self.ticket_ref,
            operator=self.operator,
            notes=self.notes,
            feedback=self.feedback,
        )

    def report_text(self) -> str:
        return self.record().to_text()
