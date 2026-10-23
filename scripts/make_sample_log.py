"""Write a realistic synthetic outcome log (about a month of calls across three flows) to try the
Editor's Analytics view without waiting for real data. Deterministic for a given seed.

Usage: python scripts/make_sample_log.py <out.jsonl> [sessions-per-flow] [days] [seed]
The events use the same shapes the Player writes (see docs/API.md, "Outcome log"). It is made-up data:
never mix it with a client's real log.
"""
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import outcome_log as olog  # noqa: E402
from engine import OPTION_OK, TroubleshootEngine, Tree  # noqa: E402
from search import search  # noqa: E402

FLOWS = (  # (file, client label, how much techs like the fixes at first, how much that improves over the month)
    ("examples/it_helpdesk_no_network.json", "acme-it", 0.55, 0.25),
    ("examples/customer_support_triage.json", "globex-support", 0.70, 0.05),
    ("examples/shared_resolutions_and_kb.json", "initech-print", 0.60, 0.10),
)
NOT_FOUND = ("blue screen", "vpn token", "keyboard sticky", "monitor flicker", "badge reader")


def simulate(tree: Tree, client: str, sessions: int, days: int, rng: random.Random, base_yes: float,
             improve: float, start: datetime) -> list[dict]:
    tree.client = client
    tree.version = "1.0.0"
    events: list[dict] = []
    step_ids = list(tree.steps)
    weights = {sid: [rng.uniform(0.3, 1.0) for _ in tree.steps[sid].options] for sid in step_ids}
    hard_step = rng.choice(step_ids[1:] or step_ids)                      # a step techs tend to give up on
    first_end = next(((sid, i) for sid in step_ids for i, o in enumerate(tree.steps[sid].options) if o.is_terminal), None)
    for _ in range(sessions):
        day = rng.random()
        t = start + timedelta(days=day * days, seconds=rng.randint(0, 40000))
        progress = day                                                      # 0 at the start of the month, 1 at the end
        e = TroubleshootEngine(tree)
        e.session_id = f"{rng.getrandbits(48):012x}"         # the engine's own ids are random; keep the log reproducible
        sid = e.session_id
        clock = [t]

        def emit(kind, **fields):
            clock[0] += timedelta(seconds=rng.randint(3, 40))
            events.append(olog.make_event(kind, sid, tree.title, tree.client, tree.version, at=clock[0].isoformat(), **fields))

        started = False

        def start_once(**fields):
            nonlocal started
            if not started:
                started = True
                emit(olog.STARTED, entry_step_id=e.entry_step_id, search_query=e.search_query,
                     restarted_from=fields.get("restarted_from"), restart_count=fields.get("restart_count", 0))

        resets = 0
        if rng.random() < 0.06:                                             # a search that finds nothing
            emit(olog.NO_RESULTS, query=rng.choice(NOT_FOUND))
        if rng.random() < 0.28 and len(step_ids) > 1:                       # starts from a search
            sid_pick = rng.choice(step_ids[1:])
            words = (tree.steps[sid_pick].tags or [w for w in tree.steps[sid_pick].question.split() if len(w) > 3])[:2]
            query = " ".join(words)
            hits = search(tree, query)
            if hits:
                e.start_at(hits[0].step_id, query)
                start_once()
        left = False
        while not e.is_finished and not left:
            step = e.current_step
            states = e.option_states()
            ok = [i for i, st in enumerate(states) if st == OPTION_OK]
            if not ok:
                e.escalate()
                break
            leave_p = 0.45 if step.id == hard_step else 0.03
            if rng.random() < leave_p:
                start_once()
                if rng.random() < 0.4 and resets < 2:                       # Start Over, then try again
                    resets += 1
                    emit(olog.RESET, last_step_id=step.id, answers=len(e.history), restart_count=resets)
                    e.reset()
                    e.session_id = f"{rng.getrandbits(48):012x}"
                    sid = e.session_id
                    started = False
                    start_once(restarted_from=events[-1]["session_id"], restart_count=resets)
                    continue
                emit(olog.ABANDONED, last_step_id=step.id, answers=len(e.history))
                left = True
                break
            idx = rng.choices(ok, weights=[weights[step.id][i] for i in ok])[0]
            start_once()
            e.choose(step.options[idx])
            emit(olog.ANSWERED, step_id=e.history[-1].step_id, option_index=idx)
            if e.history and rng.random() < 0.06 and e.can_go_back() and not e.is_finished:
                emit(olog.BACK, from_step_id=e.current_id)
                e.go_back()
            if e.is_finished and e.can_reject():
                last = e.history[-1]
                bad = first_end == (last.step_id, last.option_index)
                if rng.random() < (0.6 if bad else 0.1):
                    rej = e.reject_current_ending()
                    emit(olog.REJECTED, resolution_id=rej.resolution_id, step_id=rej.step_id, option_index=rej.option_index)
                    emit(olog.REOPENED)
        if left or not e.is_finished:
            continue
        yes_p = min(0.95, base_yes + improve * progress)
        roll = rng.random()
        helpful = True if roll < yes_p * 0.85 else False if roll < 0.9 else None
        ticket = f"INC-{rng.randint(1000, 9999)}" if rng.random() < 0.5 else ""
        art = next((a.article_id for a in e.article_events if a.action == "resolution"), None)
        common = dict(outcome=e.outcome, resolution_id=e.resolution_id, escalated=e.escalated, article_id=art,
                      answers=len(e.history), rejected=len(e.rejected))
        emit(olog.FINISHED, helpful=None, ticket_ref="", **common)
        if helpful is not None or ticket:
            emit(olog.UPDATED, helpful=helpful, ticket_ref=ticket, **common)
    return events


def generate(sessions: int = 120, days: int = 30, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    start = datetime(2026, 9, 20, 8, 0, tzinfo=timezone(timedelta(hours=-5)))
    events: list[dict] = []
    for path, client, yes, improve in FLOWS:
        tree = Tree.load(str(ROOT / path))
        n = int(sessions * rng.uniform(0.5, 1.3))
        events += simulate(tree, client, n, days, rng, yes, improve, start)
    return sorted(events, key=lambda ev: ev["at"])


def main(argv):
    if not argv:
        sys.exit(__doc__)
    out = Path(argv[0])
    events = generate(int(argv[1]) if len(argv) > 1 else 120, int(argv[2]) if len(argv) > 2 else 30,
                      int(argv[3]) if len(argv) > 3 else 7)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    log = olog.OutcomeLog(out.parent)
    log.path = out
    for ev in events:
        log.emit(ev)
    print(f"wrote {len(events)} events to {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
