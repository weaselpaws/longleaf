# Decisions and standing rules

Why Longleaf is built the way it is. Things that are easy to undo by accident, or hard to
rediscover from the code alone. Add to this when a decision is made; don't rewrite history.
For what is built and what is next, see [`ROADMAP.md`](../ROADMAP.md).

## Business model (shapes every feature call)

- Service model: Yellowhammer builds a client's flow; the client gets a Player. **The Editor never
  ships.** `build_client_release.py` refuses to build if the Player's import graph can reach any
  Editor-only module, and the list of those modules (`FORBIDDEN_MODULES`) must grow with every new
  Editor-only file.
- A feature is judged by whether it cuts the time to build a client's flow, or makes a support
  contract worth paying for. Anything that makes us host or operate software needs a client asking.
- Local install, flows on the client's own drive, no per-seat subscription, is the wedge against
  the cloud decision-tree tools. No server is built; keep it possible (below).

## Data and schema rules

- **Schema changes are additive.** No `SCHEMA_VERSION` bump. New fields are omitted from saved JSON
  when unused, so existing flows stay byte-identical, and old session records load without them.
- `docs/API.md` and `tests/test_api_contract.py` move together: documented session-record keys,
  issue codes and outcome-log events are checked against the real code.
- **IDs are identity** (flows, steps, shared resolutions, KB articles, personas). Never reuse an id
  for a different thing; analytics join on them.
- **Nothing is dropped.** A session that is reset, parked, abandoned, or taken back from its ending
  is saved as it stands (in progress) and logged. Start Over part-way is a `session.reset` with a
  restart count, never a silent discard, so "how often do agents start this flow over" stays
  answerable.
- Shared endings: an answer ends at a shared resolution (`resolution_id`, no `next_id`); inline text
  still works; the shared one wins. Analytics group endings by `resolution_id` so two paths to one
  ending count as one.

## Keep the server possible without building it

- Every outcome-log event leaves the Player through **one function** (`PlayerWidget`'s
  `event_sink`; `OutcomeLog.emit` in the app), so swapping the file for an HTTPS call is one change.
  Events are append-only and carry a session id.
- `engine.py`, `feedback.py`, `outcome_log.py`, `analytics.py`, `search.py`, `persona.py` stay
  GUI-free and unit-tested without Qt.

## Personas (the call-center case)

- A **persona is one whole business** an agent speaks for: its flow, branding, tools, and its own
  session and log folders. It is a folder beside the exe (`personas/<name>/flow.json`, optional
  `persona.json` with `name` and `tools`), so adding a business is copying a folder, no rebuild. The
  bundled flow, if any, is the first persona and keeps its old storage folder name.
- **Swapping parks the call**: it stays exactly where it is, notes included, is saved and logged as
  parked, and resumes when the agent swaps back. A ● marks personas with a call open.
- Tools (today only the notepad) are chosen per persona. Roles stay simple config, not code.
- Not built: per-agent login, a remembered default persona, more tools.

## Privacy

- Free text can hold customer details: notes, ticket ids, comments, and what a tech searches for.
  The outcome log holds ids and outcomes, **not** notes, comments, names or fix wording; the ticket
  id and search query are the exceptions and are documented as such.
- The agent's name is personal data. Remembering it between launches must be opt-in (a checkbox
  next to the name field), stored on the machine only.
- Customer info panels (planned) are personal data; they tie into the encryption plans (stage 5).
- Any AI feature is strictly opt-in, never default, and the organisation brings its own.

## Analytics

- It is an **internal Editor mode** for a recurring flow-review service; the exported summary is the
  deliverable. A client-facing viewer would break "clients only get the Player", so it waits until a
  client asks.
- Statuses are never told apart by colour alone: every one has a glyph, a label with its count, and
  "didn't solve it" is hatched. Keep it that way for any new chart.
- Reads outcome logs only; the session files behind the feedback overlay (notes, comments) are a
  separate path.

## Engineering habits

- Run `python -m pytest tests` and `python smoke_test.py` (offscreen, needs PySide6) before every
  commit. Keep tests green on **Windows**: the first Windows run found a lost-write bug in the log
  and two tests that only passed on Linux.
- One feature per PR; stack a PR only when it truly depends on another, and retarget it to `main`
  when the base merges.
- Windows builds come from the workflow (Actions → *Windows demo build*, run on `main`); it uploads
  `Longleaf-Windows-demo` (Player, Editor, `personas/`, sample data, `TRY-ME.txt`).

## Open risks (not yet checked on a real machine)

- Nothing has been run on a real Windows desktop; CI only proves the exes build and stay up offscreen.
- The onefile exe unpacks to a temp folder on every launch (slow starts, antivirus flags are common),
  and an unsigned exe triggers SmartScreen's "unknown publisher". A signed folder build or installer
  may be needed for client deliveries.
- Two Players writing one outcome log on a network share is untested (best effort across processes).
- `build_client_release.py` does not bundle a `personas/` folder; for a call-center build it is placed
  next to the exe by hand.

## Next, in order

1. Faster flow authoring: "new step from this answer", duplicate step, an outline-text importer.
2. A flow quality check in Validate (steps with no tags, empty endings, unused articles).
3. `docs/AUTHORING.md`: how to write and tag a good flow.
4. A "client-ready Player" PR: keyboard answer keys (1–9, Backspace), a crash log and About box,
   remembering the agent (opt-in), and a settings file for network-share paths.
