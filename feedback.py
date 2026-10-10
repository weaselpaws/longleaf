"""
Longleaf - local feedback capture (no GUI, no server).

The loop, with nothing hosted:

  Player   keeps each finished session (a SessionRecord, including the
           tech's "Did this solve it?" answer) as a small JSON file on the
           client's machine (`SessionStore`), and can export them all as one
           feedback file (`build_bundle`) for the client to send back.
  Editor   imports one or more of those files (`load_bundle`), merges them
           without double-counting (`merge_records`), and analyses them
           against the current flow (`analyze`): traffic per branch,
           helpful-rate per ending, comments pinned to steps.

Everything is keyed by step id + answer index (the same identity the
session record and docs/API.md use), so records from older versions of a
flow still line up wherever the step ids still exist.

Privacy: records contain whatever the tech typed (ticket, notes, comments).
They stay on the client's machine until the client chooses to send the
exported file, and the Player can delete them.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Union

from engine import (
    OUTCOME_RESOLVED, SCHEMA_VERSION, SessionRecord, Tree, _now,
)

BUNDLE_KIND = "longleaf-feedback"


class FeedbackFormatError(ValueError):
    """A feedback file couldn't be understood."""


# ---------------------------------------------------------------------
# Local storage (Player side)
# ---------------------------------------------------------------------

class SessionStore:
    """One JSON file per session in a folder. Saving the same session again
    replaces it, so a session saved when it finished is updated in place when
    the tech later adds notes or a rating."""

    def __init__(self, folder: str | os.PathLike):
        self.folder = Path(folder)

    def _path(self, session_id: str) -> Path:
        safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
        if not safe:
            raise ValueError("empty session id")
        return self.folder / f"{safe}.json"

    def save(self, record: SessionRecord) -> bool:
        """Write the record atomically. False (never an exception) if the
        disk says no: losing a feedback record must not break a tech's work."""
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.folder, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(record.to_json())
            os.replace(tmp, self._path(record.session_id))
            return True
        except (OSError, ValueError):
            return False

    def discard(self, session_id: str) -> None:
        try:
            self._path(session_id).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass

    def load_all(self) -> list[SessionRecord]:
        """Every readable record, oldest first. Unreadable files are skipped."""
        records = []
        for p in self.folder.glob("*.json") if self.folder.is_dir() else []:
            try:
                records.append(SessionRecord.from_dict(json.loads(p.read_text(encoding="utf-8"))))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(records, key=lambda r: r.started_at)

    def count(self) -> int:
        return len(self.load_all())

    def clear(self) -> int:
        """Delete every stored session; returns how many were removed."""
        n = 0
        for p in self.folder.glob("*.json") if self.folder.is_dir() else []:
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
        return n


# ---------------------------------------------------------------------
# The file the client sends back
# ---------------------------------------------------------------------

def build_bundle(records: Iterable[SessionRecord], tree: Tree) -> dict:
    return {
        "kind": BUNDLE_KIND,
        "schema_version": SCHEMA_VERSION,
        "exported_at": _now().isoformat(),
        "flow": {"title": tree.title, "client": tree.client, "version": tree.version},
        "sessions": [r.to_dict() for r in records],
    }


def write_bundle(path: str | os.PathLike, records: Iterable[SessionRecord], tree: Tree) -> int:
    """Write a feedback file; returns how many sessions it holds."""
    bundle = build_bundle(records, tree)
    Path(path).write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    return len(bundle["sessions"])


def load_bundle(path: str | os.PathLike) -> list[SessionRecord]:
    """Read a feedback file. Raises FeedbackFormatError if it isn't one."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        raise FeedbackFormatError(f"Can't read {Path(path).name}: {e}") from e
    except json.JSONDecodeError as e:
        raise FeedbackFormatError(f"{Path(path).name} is not valid JSON: {e}") from e
    if not isinstance(data, dict) or data.get("kind") != BUNDLE_KIND:
        raise FeedbackFormatError(f"{Path(path).name} is not a Longleaf feedback file.")
    if int(data.get("schema_version", 0) or 0) > SCHEMA_VERSION:
        raise FeedbackFormatError(
            f"{Path(path).name} was made by a newer Longleaf (schema {data['schema_version']}); update the Editor.")
    sessions = data.get("sessions")
    if not isinstance(sessions, list):
        raise FeedbackFormatError(f"{Path(path).name} has no 'sessions' list.")
    records = []
    for i, s in enumerate(sessions):
        try:
            records.append(SessionRecord.from_dict(s))
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise FeedbackFormatError(f"{Path(path).name}: session #{i + 1} is malformed ({e!r}).") from e
    return records


def merge_records(existing: dict[str, SessionRecord], incoming: Iterable[SessionRecord]) -> int:
    """Add `incoming` to `existing` (keyed by session id), keeping the most
    recently updated copy of any session seen twice. Returns how many
    incoming records were duplicates."""
    def stamp(r: SessionRecord) -> str:
        return r.finished_at or r.started_at or ""

    dupes = 0
    for r in incoming:
        old = existing.get(r.session_id)
        if old is not None:
            dupes += 1
            if stamp(r) < stamp(old):
                continue
        existing[r.session_id] = r
    return dupes


# ---------------------------------------------------------------------
# Analysis (Editor side)
# ---------------------------------------------------------------------

EndingKey = Union[str, tuple]   # a shared resolution's id, or (step id, answer index) for an inline ending


def ending_key(tree: Tree, step_id: str, option_index: int) -> EndingKey:
    """Which ending an answer leads to. Answers that point at a shared
    resolution all count as the one ending, whatever path led there; inline
    endings are told apart by where they sit."""
    return tree.steps[step_id].options[option_index].resolution_id or (step_id, option_index)


@dataclass
class EndingStat:
    count: int = 0
    helpful: int = 0
    unhelpful: int = 0

    @property
    def rated(self) -> int:
        return self.helpful + self.unhelpful

    @property
    def helpful_rate(self) -> Optional[float]:
        return self.helpful / self.rated if self.rated else None


@dataclass
class Comment:
    text: str
    helpful: Optional[bool]
    session_id: str
    ticket_ref: str = ""


@dataclass
class FlowFeedback:
    """Imported sessions measured against one version of a flow."""
    sessions: int = 0                 # records that line up with the flow
    unmatched: int = 0                # records whose path uses steps/answers the flow no longer has
    resolved: int = 0
    step_visits: dict[str, int] = field(default_factory=dict)
    edge_counts: dict[tuple[str, int], int] = field(default_factory=dict)       # (step id, answer index) -> times taken
    endings: dict[EndingKey, EndingStat] = field(default_factory=dict)          # see ending_key(): resolution id, or (step id, answer index)
    comments: dict[str, list[Comment]] = field(default_factory=dict)            # step id -> comments from sessions that ended there
    durations: list[int] = field(default_factory=list)                          # seconds, resolved sessions only

    @property
    def helpful(self) -> int:
        return sum(e.helpful for e in self.endings.values())

    @property
    def unhelpful(self) -> int:
        return sum(e.unhelpful for e in self.endings.values())

    @property
    def helpful_rate(self) -> Optional[float]:
        rated = self.helpful + self.unhelpful
        return self.helpful / rated if rated else None

    @property
    def avg_duration(self) -> Optional[float]:
        return sum(self.durations) / len(self.durations) if self.durations else None

    @property
    def max_edge_count(self) -> int:
        return max(self.edge_counts.values(), default=0)


def _lines_up(tree: Tree, record: SessionRecord) -> bool:
    for h in record.history:
        step = tree.steps.get(h.step_id)
        if step is None or not 0 <= h.option_index < len(step.options):
            return False
    return True


def _seconds(record: SessionRecord) -> Optional[int]:
    try:
        return max(0, int((datetime.fromisoformat(record.finished_at)
                           - datetime.fromisoformat(record.started_at)).total_seconds()))
    except (TypeError, ValueError):
        return None


def analyze(tree: Tree, records: Iterable[SessionRecord]) -> FlowFeedback:
    fb = FlowFeedback()
    for r in records:
        if not r.history or not _lines_up(tree, r):
            fb.unmatched += 1
            continue
        fb.sessions += 1
        for h in r.history:
            fb.step_visits[h.step_id] = fb.step_visits.get(h.step_id, 0) + 1
            key = (h.step_id, h.option_index)
            fb.edge_counts[key] = fb.edge_counts.get(key, 0) + 1

        last = r.history[-1]
        ended_here = r.outcome == OUTCOME_RESOLVED and tree.steps[last.step_id].options[last.option_index].is_terminal
        if ended_here:
            fb.resolved += 1
            stat = fb.endings.setdefault(ending_key(tree, last.step_id, last.option_index), EndingStat())
            stat.count += 1
            secs = _seconds(r)
            if secs is not None:
                fb.durations.append(secs)
            rating = (r.feedback or {}).get("helpful")
            if rating is True:
                stat.helpful += 1
            elif rating is False:
                stat.unhelpful += 1
            comment = ((r.feedback or {}).get("comment") or "").strip()
            if comment:
                fb.comments.setdefault(last.step_id, []).append(
                    Comment(comment, rating if isinstance(rating, bool) else None, r.session_id, r.ticket_ref))
    return fb


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{round(x * 100)}%"


def _clip(text: str, n: int = 50) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


def foreign_sessions(tree: Tree, records: Iterable[SessionRecord]) -> int:
    """How many records name a different client (or, when a client isn't
    named on both sides, a different flow title) than `tree`. Step ids like
    'step_1' repeat across flows, so such records can match by accident."""
    def differs(r: SessionRecord) -> bool:
        if tree.client and r.flow_client:
            return r.flow_client != tree.client
        return bool(tree.title and r.flow_title) and r.flow_title != tree.title
    return sum(differs(r) for r in records)


def summarize(tree: Tree, fb: FlowFeedback, duplicates: int = 0, foreign: int = 0) -> str:
    """A short plain-text digest of an import, for the Editor's summary box."""
    lines = [f"{fb.sessions} session{'s' if fb.sessions != 1 else ''} matched this flow"
             f" ({fb.resolved} reached an ending)."]
    if duplicates:
        lines.append(f"{duplicates} duplicate{'s' if duplicates != 1 else ''} skipped (already imported).")
    if foreign:
        lines.append(f"WARNING: {foreign} session{'s' if foreign != 1 else ''} came from a different client or flow "
                     f"— check you imported the right files (Feedback → Clear imported feedback to start over).")
    if fb.unmatched:
        lines.append(f"{fb.unmatched} didn't match — they use steps or answers this flow no longer has.")
    if fb.helpful + fb.unhelpful:
        lines.append(f"Helpful: {_pct(fb.helpful_rate)} of {fb.helpful + fb.unhelpful} rated.")
    if fb.avg_duration is not None:
        m, s = divmod(int(fb.avg_duration), 60)
        lines.append(f"Average time to an ending: {m}m {s:02d}s." if m else f"Average time to an ending: {s}s.")

    rated = [(k, e) for k, e in fb.endings.items() if e.rated]
    rated.sort(key=lambda ke: (ke[1].helpful_rate, -ke[1].rated))
    weak = [(k, e) for k, e in rated if e.helpful_rate < 0.5][:5]
    if weak:
        lines += ["", "Endings techs found unhelpful:"]
        for key, e in weak:
            if isinstance(key, str):
                res = tree.resolutions.get(key)
                what = f"shared resolution “{_clip(res.text if res else key)}”"
            else:
                sid, idx = key
                what = f"{sid} → “{tree.steps[sid].options[idx].label}”"
            lines.append(f"  • {what}: {_pct(e.helpful_rate)} helpful of {e.rated}")
    n_comments = sum(len(c) for c in fb.comments.values())
    if n_comments:
        lines += ["", f"{n_comments} comment{'s' if n_comments != 1 else ''}, pinned to the steps they came from "
                      f"(hover a step in the Graph tab)."]
    return "\n".join(lines)


def step_feedback_text(tree: Tree, fb: FlowFeedback, step_id: str) -> str:
    """What imported sessions say about one step, for the step editor's
    read-only panel. Empty when there is nothing to show."""
    step = tree.steps.get(step_id)
    if step is None:
        return ""
    visits = fb.step_visits.get(step_id, 0)
    lines = [f"{visits} visit{'s' if visits != 1 else ''} from imported sessions."]
    for i, o in enumerate(step.options):
        n = fb.edge_counts.get((step_id, i), 0)
        line = f"  • “{o.label}”: {n}"
        stat = fb.endings.get(ending_key(tree, step_id, i)) if o.is_terminal else None
        if stat and stat.rated:
            line += f"  —  ends here, {_pct(stat.helpful_rate)} helpful of {stat.rated}"
        elif stat:
            line += "  —  ends here"
        lines.append(line)
    mark = {True: "▲", False: "▼", None: "•"}
    comments = fb.comments.get(step_id, [])
    if comments:
        lines += ["", "Comments:"]
        lines += [f"  {mark[c.helpful]} {c.text}" + (f"  ({c.ticket_ref})" if c.ticket_ref else "") for c in comments]
    return "\n".join(lines)
