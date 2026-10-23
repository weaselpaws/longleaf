"""
Longleaf - outcome log (no GUI).

An append-only stream of small events, one JSON object per line, that says
what happened in each session: it started, which answers were given, which
endings were rejected, how it finished (resolved or not, with an optional
ticket or call id), or that it was abandoned. It is the plain log file the
analytics read, and the thing a hosted server would take over: every event
leaves the Player through ONE function (a sink, `emit(event) -> bool`), so
swapping the file for an HTTPS call later is one change.

Events carry ids and outcomes, never free text: no notes, comments,
technician names or fix wording. The ticket id is the one optional field a
client can hand us, and the search query (what a tech typed) is kept on
`session.started` / `search.no_results` because "what are people looking for"
is the whole point of search analytics; both can contain customer details if
a tech types them, so treat the file like the session files.

The full per-session records (feedback.SessionStore) stay as they are: those
carry notes and comments and feed the Editor's review overlay. This log is
the lightweight, always-on view, and the only one that also sees sessions that
were abandoned.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

SCHEMA = 1
LOG_NAME = "outcome-log.jsonl"

# event kinds
STARTED = "session.started"
ANSWERED = "step.answered"
REJECTED = "ending.rejected"
FINISHED = "session.finished"
UPDATED = "session.updated"        # a finished session's rating or ticket id changed
REOPENED = "session.reopened"      # the tech went Back from an ending
ABANDONED = "session.abandoned"    # left part-way without resetting (another flow, closing the app)
RESET = "session.reset"            # the tech pressed Start Over part-way through
PARKED = "session.parked"          # the tech swapped to another persona with this call still open
RESUMED = "session.resumed"        # ...and came back to it
BACK = "step.back"                 # the tech pressed Back
NO_RESULTS = "search.no_results"
EVENT_KINDS = (STARTED, ANSWERED, REJECTED, FINISHED, UPDATED, REOPENED, ABANDONED, RESET, PARKED, RESUMED, BACK,
               NO_RESULTS)

# how a session ends up, as folded from its events
STATUS_RESOLVED = "resolved"          # finished and the tech said it solved the problem
STATUS_NOT_RESOLVED = "not_resolved"  # finished and the tech said it did not
STATUS_FINISHED = "finished"          # reached an ending, no answer to "did this solve it?"
STATUS_ERROR = "error"                # the flow itself was broken at that point
STATUS_ABANDONED = "abandoned"        # left mid-flow
STATUS_RESET = "reset"                # the tech pressed Start Over part-way (a new session follows)
STATUS_PARKED = "parked"              # on hold while the tech works another persona
STATUS_IN_PROGRESS = "in_progress"    # no end event yet (still open, or the app died)

Sink = Callable[[dict], bool]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def make_event(kind: str, session_id: str, flow_title: str = "", flow_client: str = "", flow_version: str = "",
               at: Optional[str] = None, **fields) -> dict:
    """The envelope every event shares. Extra `fields` are the event's own data."""
    if kind not in EVENT_KINDS:
        raise ValueError(f"Unknown event kind {kind!r}.")
    return {"v": SCHEMA, "event": kind, "session_id": session_id, "at": at or now_iso(),
            "flow_title": flow_title, "flow_client": flow_client, "flow_version": flow_version, **fields}


class OutcomeLog:
    """The file sink: appends one line per event to <folder>/outcome-log.jsonl.
    `emit` never raises. A log that can't be written must not get in a tech's way."""

    def __init__(self, folder: str | os.PathLike):
        self.folder = Path(folder)
        self.path = self.folder / LOG_NAME

    def emit(self, event: dict) -> bool:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
            # One write per line, opened for append: whole lines from two Players don't interleave.
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line)
            return True
        except (OSError, TypeError, ValueError):
            return False

    def read(self) -> list[dict]:
        return read_events(self.path)

    def count(self) -> int:
        return len(self.read())

    def clear(self) -> int:
        n = self.count()
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            return 0
        return n


def read_events(path: str | os.PathLike) -> list[dict]:
    """Every readable event in file order. Blank, torn or foreign lines are skipped."""
    events = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return events
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("event") in EVENT_KINDS and d.get("session_id"):
            events.append(d)
    return events


@dataclass
class SessionSummary:
    session_id: str
    flow_title: str = ""
    flow_client: str = ""
    flow_version: str = ""
    started_at: str = ""
    last_at: str = ""
    status: str = STATUS_IN_PROGRESS
    steps: list = field(default_factory=list)      # [(step_id, option_index)] in order
    rejected: int = 0
    ticket_ref: str = ""
    resolution_id: Optional[str] = None
    entry_step_id: Optional[str] = None
    search_query: str = ""
    escalated: bool = False
    last_step_id: Optional[str] = None
    restarted_from: Optional[str] = None   # the session this one replaced when the tech pressed Start Over
    restart_count: int = 0                 # how many Start Overs came before it on this call
    parks: int = 0                         # times it was put on hold for another persona
    backs: int = 0                         # times the tech pressed Back


def _status_for(finished: dict) -> str:
    if finished.get("outcome") == "error":
        return STATUS_ERROR
    helpful = finished.get("helpful")
    return STATUS_RESOLVED if helpful is True else STATUS_NOT_RESOLVED if helpful is False else STATUS_FINISHED


def fold_sessions(events: Iterable[dict]) -> dict[str, SessionSummary]:
    """Collapse the event stream into one summary per session, in file order.
    The last event decides how a session ended, so Back from an ending (reopened)
    and a later finish both work out."""
    sessions: dict[str, SessionSummary] = {}
    for e in events:
        sid = e.get("session_id")
        if not sid or e.get("event") not in EVENT_KINDS:
            continue
        s = sessions.setdefault(sid, SessionSummary(sid, e.get("flow_title", ""), e.get("flow_client", ""),
                                                    e.get("flow_version", ""), e.get("at", "")))
        s.last_at = e.get("at", s.last_at)
        kind = e["event"]
        if kind == STARTED:
            s.started_at = e.get("at", s.started_at)
            s.entry_step_id = e.get("entry_step_id")
            s.search_query = e.get("search_query", "") or ""
            s.restarted_from = e.get("restarted_from") or None
            s.restart_count = int(e.get("restart_count") or 0)
        elif kind == ANSWERED:
            s.steps.append((e.get("step_id"), e.get("option_index")))
            s.last_step_id = e.get("step_id")
            s.status = STATUS_IN_PROGRESS
        elif kind == REJECTED:
            s.rejected += 1
        elif kind in (FINISHED, UPDATED):
            s.status = _status_for(e)
            s.ticket_ref = e.get("ticket_ref", "") or ""
            s.resolution_id = e.get("resolution_id")
            s.escalated = bool(e.get("escalated"))
        elif kind in (REOPENED, RESUMED):
            s.status = STATUS_IN_PROGRESS
        elif kind == RESET:
            s.status = STATUS_RESET
            s.last_step_id = e.get("last_step_id", s.last_step_id)
        elif kind == PARKED:
            s.status = STATUS_PARKED
            s.parks += 1
        elif kind == BACK:
            s.backs += 1
        elif kind == ABANDONED:
            s.status = STATUS_ABANDONED
            s.last_step_id = e.get("last_step_id", s.last_step_id)
    return sessions


def status_counts(sessions: Iterable[SessionSummary]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in sessions:
        counts[s.status] = counts.get(s.status, 0) + 1
    return counts
