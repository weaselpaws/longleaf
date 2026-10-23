"""
Longleaf - analytics over outcome logs (no GUI).

Reads the outcome-log files the Player exports (outcome_log.py) and answers the
questions a flow-review service is paid to answer: which flows get used, how often
they resolve the problem, which cards techs hit and where they give up, which
endings keep getting rejected, what techs search for (and fail to find), and how all
of that is moving over time.

Editor only: it reads client data, so it never ships in a Player (see
build_client_release.py).
"""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

import outcome_log as olog
from feedback import HIGH_REJECTION_MIN, HIGH_REJECTION_RATE   # one definition of "keeps getting rejected"
from outcome_log import SessionSummary

FlowKey = tuple   # (flow_client, flow_title)

RESOLVED, NOT_RESOLVED, FINISHED = olog.STATUS_RESOLVED, olog.STATUS_NOT_RESOLVED, olog.STATUS_FINISHED
ABANDONED, RESET, ERROR = olog.STATUS_ABANDONED, olog.STATUS_RESET, olog.STATUS_ERROR
OPEN = "open"            # in progress or parked: still under way, or the app died
STATUS_ORDER = (RESOLVED, NOT_RESOLVED, FINISHED, ABANDONED, RESET, ERROR, OPEN)

HIGH_DROP_OFF_RATE = 0.3
HIGH_DROP_OFF_MIN = 3


def bucket(status: str) -> str:
    return OPEN if status in (olog.STATUS_IN_PROGRESS, olog.STATUS_PARKED) else status


def ending_key(resolution_id: Optional[str], step_id: Optional[str], option_index: Optional[int]) -> str:
    """The ending an event points at: the shared resolution's id, else 'step_id#answer_index'."""
    return resolution_id or f"{step_id}#{option_index}"


@dataclass
class EndingRow:
    key: str
    finished: int = 0       # sessions that finished here
    resolved: int = 0       # ...and the tech said it solved the problem
    not_resolved: int = 0
    rejected: int = 0       # times a tech reached it, marked it "didn't work" and carried on
    escalated: int = 0

    @property
    def reached(self) -> int:
        return self.finished + self.rejected

    @property
    def rated(self) -> int:
        return self.resolved + self.not_resolved

    @property
    def helpful_rate(self) -> Optional[float]:
        return self.resolved / self.rated if self.rated else None

    @property
    def rejection_rate(self) -> Optional[float]:
        return self.rejected / self.reached if self.reached else None

    @property
    def high_rejection(self) -> bool:
        return self.reached >= HIGH_REJECTION_MIN and self.rejection_rate >= HIGH_REJECTION_RATE


@dataclass
class StepRow:
    step_id: str
    visits: int = 0
    left_here: int = 0       # sessions abandoned or reset while on this step

    @property
    def drop_off_rate(self) -> Optional[float]:
        return self.left_here / self.visits if self.visits else None

    @property
    def high_drop_off(self) -> bool:
        return self.visits >= HIGH_DROP_OFF_MIN and self.drop_off_rate >= HIGH_DROP_OFF_RATE


@dataclass
class FlowAnalytics:
    key: FlowKey
    versions: set = field(default_factory=set)
    sessions: int = 0
    statuses: Counter = field(default_factory=Counter)        # bucketed (see STATUS_ORDER)
    resets: int = 0                                            # session.reset events
    max_restarts: int = 0                                      # most Start Overs on one call
    parks: int = 0
    backs: int = 0
    escalations: int = 0
    steps: dict = field(default_factory=dict)                  # step_id -> StepRow
    answers: Counter = field(default_factory=Counter)          # (step_id, option_index) -> times chosen
    endings: dict = field(default_factory=dict)                # key -> EndingRow
    searches: Counter = field(default_factory=Counter)         # queries that landed on a step
    no_results: Counter = field(default_factory=Counter)       # queries that matched nothing
    daily: dict = field(default_factory=dict)                  # date -> Counter of bucketed statuses
    first_day: Optional[date] = None
    last_day: Optional[date] = None

    @property
    def client(self) -> str:
        return self.key[0]

    @property
    def title(self) -> str:
        return self.key[1]

    @property
    def name(self) -> str:
        return " — ".join(p for p in (self.key[0], self.key[1]) if p) or "(unnamed flow)"

    @property
    def rated(self) -> int:
        return self.statuses[RESOLVED] + self.statuses[NOT_RESOLVED]

    @property
    def resolution_rate(self) -> Optional[float]:
        """Of the sessions where the tech answered "Did this solve it?", the share that said yes."""
        return self.statuses[RESOLVED] / self.rated if self.rated else None

    @property
    def completion_rate(self) -> Optional[float]:
        """Share of sessions that reached an ending at all (rated or not)."""
        done = self.statuses[RESOLVED] + self.statuses[NOT_RESOLVED] + self.statuses[FINISHED]
        return done / self.sessions if self.sessions else None

    @property
    def abandon_rate(self) -> Optional[float]:
        return (self.statuses[ABANDONED] + self.statuses[RESET]) / self.sessions if self.sessions else None

    def trend(self, days: int = 7) -> Optional[tuple]:
        """(resolution rate in the last `days`, in the `days` before that), measured back from the
        newest day in the data. None if either window has no rated session."""
        if not self.last_day:
            return None
        def rate(start: date, end: date):
            res = sum(c[RESOLVED] for d, c in self.daily.items() if start <= d <= end)
            tot = res + sum(c[NOT_RESOLVED] for d, c in self.daily.items() if start <= d <= end)
            return (res / tot) if tot else None
        recent_start = self.last_day - timedelta(days=days - 1)
        prev_end = recent_start - timedelta(days=1)
        recent, previous = rate(recent_start, self.last_day), rate(prev_end - timedelta(days=days - 1), prev_end)
        return None if recent is None or previous is None else (recent, previous)


@dataclass
class Analytics:
    flows: dict = field(default_factory=dict)       # FlowKey -> FlowAnalytics
    events: int = 0
    sessions: int = 0

    def ranked(self) -> list[FlowAnalytics]:
        """Flows by use, busiest first."""
        return sorted(self.flows.values(), key=lambda f: (-f.sessions, f.name.lower()))

    def combined(self) -> FlowAnalytics:
        """Everything as one pseudo-flow, for an 'all flows' view. Step ids aren't comparable across
        flows, so only the totals, trends, searches and statuses are filled in."""
        total = FlowAnalytics(("", "All flows"))
        for f in self.flows.values():
            total.versions |= f.versions
            total.sessions += f.sessions
            total.statuses += f.statuses
            total.resets += f.resets
            total.max_restarts = max(total.max_restarts, f.max_restarts)
            total.parks += f.parks
            total.backs += f.backs
            total.escalations += f.escalations
            total.searches += f.searches
            total.no_results += f.no_results
            for d, c in f.daily.items():
                total.daily.setdefault(d, Counter()).update(c)
            for d in (f.first_day, f.last_day):
                if d:
                    total.first_day = min(total.first_day or d, d)
                    total.last_day = max(total.last_day or d, d)
        return total


def _day(iso: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(iso).date()
    except (TypeError, ValueError):
        return None


def load_logs(paths: Iterable[str | os.PathLike]) -> tuple[list[dict], list[str]]:
    """Events from several exported log files, with exact duplicates dropped (so importing the same
    export twice, or two overlapping exports, never double-counts) and a note for each unusable file."""
    seen: set[str] = set()
    events: list[dict] = []
    problems: list[str] = []
    for p in paths:
        got = olog.read_events(p)
        if not got:
            problems.append(f"{os.path.basename(str(p))}: no outcome-log events found in it.")
            continue
        for e in got:
            k = json.dumps(e, sort_keys=True, ensure_ascii=False)
            if k not in seen:
                seen.add(k)
                events.append(e)
    return events, problems


def analyze(events: Iterable[dict]) -> Analytics:
    events = list(events)
    result = Analytics(events=len(events))
    sessions = olog.fold_sessions(events)
    result.sessions = len(sessions)
    flow_of: dict[str, FlowKey] = {}
    for e in events:
        flow_of.setdefault(e["session_id"], (e.get("flow_client", "") or "", e.get("flow_title", "") or ""))

    def flow(sid: str) -> FlowAnalytics:
        key = flow_of[sid]
        if key not in result.flows:
            result.flows[key] = FlowAnalytics(key)
        return result.flows[key]

    for sid, s in sessions.items():
        f = flow(sid)
        f.sessions += 1
        f.versions.add(s.flow_version)
        status = bucket(s.status)
        f.statuses[status] += 1
        f.max_restarts = max(f.max_restarts, s.restart_count)
        f.parks += s.parks
        f.backs += s.backs
        if s.escalated:
            f.escalations += 1
        d = _day(s.started_at) or _day(s.last_at)
        if d:
            f.daily.setdefault(d, Counter())[status] += 1
            f.first_day = min(f.first_day or d, d)
            f.last_day = max(f.last_day or d, d)
        for step_id, idx in s.steps:
            f.steps.setdefault(step_id, StepRow(step_id)).visits += 1
            f.answers[(step_id, idx)] += 1
        if status in (ABANDONED, RESET) and s.last_step_id:
            row = f.steps.setdefault(s.last_step_id, StepRow(s.last_step_id))
            row.visits += 1          # they were on it even though they never answered it
            row.left_here += 1
        if s.status in (RESOLVED, NOT_RESOLVED, FINISHED) and s.steps:
            last_step, last_idx = s.steps[-1]
            key = ending_key(s.resolution_id, last_step, last_idx)
            row = f.endings.setdefault(key, EndingRow(key))
            row.finished += 1
            row.resolved += s.status == RESOLVED
            row.not_resolved += s.status == NOT_RESOLVED
            row.escalated += bool(s.escalated)
        if s.search_query:
            f.searches[s.search_query.strip().lower()] += 1

    for e in events:
        kind, sid = e["event"], e["session_id"]
        if kind == olog.RESET:
            flow(sid).resets += 1
        elif kind == olog.REJECTED:
            key = ending_key(e.get("resolution_id"), e.get("step_id"), e.get("option_index"))
            flow(sid).endings.setdefault(key, EndingRow(key)).rejected += 1
        elif kind == olog.NO_RESULTS and e.get("query"):
            flow(sid).no_results[str(e["query"]).strip().lower()] += 1
    return result


def pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{round(x * 100)}%"


def to_markdown(flow: FlowAnalytics, names=None, top: int = 8) -> str:
    """A shareable summary for one flow (or 'All flows'), for the recurring flow-review service.
    `names(step_id) -> str` and `ending_name(key) -> str` may be given as attributes of a small
    object, or left None to show the raw ids."""
    nm = (lambda sid: names.step(sid)) if names else (lambda sid: sid)
    en = (lambda key: names.ending(key)) if names else (lambda key: key)
    lines = [f"# Flow review — {flow.name}", ""]
    if flow.first_day and flow.last_day:
        lines += [f"{flow.first_day} to {flow.last_day} · {flow.sessions} session{'s' if flow.sessions != 1 else ''}"
                  + (f" · version{'s' if len(flow.versions) > 1 else ''} {', '.join(sorted(v for v in flow.versions if v))}"
                     if any(flow.versions) else ""), ""]
    c = flow.statuses
    lines += ["## At a glance", "",
              f"- Resolved: **{pct(flow.resolution_rate)}** of {flow.rated} rated session{'s' if flow.rated != 1 else ''}"
              f" ({c[RESOLVED]} yes, {c[NOT_RESOLVED]} no)",
              f"- Reached an ending: {pct(flow.completion_rate)} · left or started over: {pct(flow.abandon_rate)}"
              f" ({c[ABANDONED]} abandoned, {c[RESET]} reset)",
              f"- Start Overs on one call, at most: {flow.max_restarts} · Back presses: {flow.backs}"
              f" · calls parked: {flow.parks} · escalations: {flow.escalations}"]
    t = flow.trend()
    if t:
        lines.append(f"- Last 7 days vs the 7 before: {pct(t[0])} vs {pct(t[1])} resolved "
                     f"({'up' if t[0] > t[1] else 'down' if t[0] < t[1] else 'level'})")
    leaving = sorted((s for s in flow.steps.values() if s.left_here), key=lambda s: (-s.left_here, s.step_id))[:top]
    if leaving:
        lines += ["", "## Where techs give up", "", "| Step | Visits | Left here | Share |", "|---|---|---|---|"]
        lines += [f"| {nm(s.step_id)} | {s.visits} | {s.left_here} | {pct(s.drop_off_rate)}{' ⚠' if s.high_drop_off else ''} |"
                  for s in leaving]
    rejected = sorted((e for e in flow.endings.values() if e.rejected), key=lambda e: (-e.rejected, e.key))[:top]
    if rejected:
        lines += ["", "## Fixes techs reject", "", "| Ending | Reached | Rejected | Rate |", "|---|---|---|---|"]
        lines += [f"| {en(e.key)} | {e.reached} | {e.rejected} | {pct(e.rejection_rate)}{' ⚠' if e.high_rejection else ''} |"
                  for e in rejected]
    unhelpful = sorted((e for e in flow.endings.values() if e.rated and e.helpful_rate < 0.5),
                       key=lambda e: (e.helpful_rate, -e.rated))[:top]
    if unhelpful:
        lines += ["", "## Endings techs found unhelpful", ""]
        lines += [f"- {en(e.key)}: {pct(e.helpful_rate)} helpful of {e.rated}" for e in unhelpful]
    if flow.no_results:
        lines += ["", "## Searches that found nothing (add tags for these)", ""]
        lines += [f"- “{q}” ×{n}" for q, n in flow.no_results.most_common(top)]
    if flow.searches:
        lines += ["", "## What techs search for", ""]
        lines += [f"- “{q}” ×{n}" for q, n in flow.searches.most_common(top)]
    busy = sorted(((nm(sid), s.visits) for sid, s in flow.steps.items()), key=lambda x: -x[1])[:top]
    if busy:
        lines += ["", "## Busiest cards", ""] + [f"- {name}: {n} visit{'s' if n != 1 else ''}" for name, n in busy]
    return "\n".join(lines) + "\n"
