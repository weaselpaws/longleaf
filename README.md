# Longleaf

*A Yellowhammer product — internal tooling for a service business.*

Longleaf is how Yellowhammer builds and delivers custom decision-flow
tools for clients: troubleshooting trees, support-ticket triage,
marketing-ops checklists, onboarding flows — any "ask a question, branch
on the answer, end at an outcome" process. It is **not** sold as
standalone software. The service is: Yellowhammer builds a client's flow
(one-time setup fee, optional ongoing support), and the client receives
a working Player exe with their flow baked in. They never see or need
the Editor.

Two apps, one engine, one look — but very different distribution:

- **Player** (`player_main.py`) — what a client receives. Opens a bundled
  `flow.json` and walks it: one question at a time, click an answer, get
  a final resolution and a copyable/exportable report. No editing
  capability, and — see "Editor never ships" below — no code path to any.
  This is the **only** thing that ever leaves Yellowhammer.
- **Editor** (`editor_main.py`) — Yellowhammer's internal authoring tool,
  used to build each client's flow. Outline of every step on the left, a
  form to edit the selected step's question/answers/branches in the
  middle, and a **live Test pane** on the right running the exact same
  Player widget. **Never packaged for or given to a client.**

Both are plain PySide6 desktop apps. Only the Player is ever built for
distribution — see "Building a client release" below.

## Editor never ships

`player_main.py`'s import graph cannot reach `editor_main.py` or any of
the editor-only widgets (`widgets/editor_widget.py`,
`widgets/step_editor.py`, `widgets/option_row.py`, `widgets/image_picker.py`, `widgets/graph_view.py`, `graph_layout.py`) — verified two ways:

1. `build_client_release.py` statically re-checks this before every
   build and refuses to build if it's ever no longer true.
2. Confirmed against the actual built exe: PyInstaller's own archive
   listing (`python -m PyInstaller.utils.cliutils.archive_viewer -r`)
   contains `engine`, `theme`, `widgets.answer_button`, and
   `widgets.player_widget` — and nothing matching `editor`, `option_row`,
   or `step_editor`, anywhere in the bundle, nested PYZ contents included.

## Data model (`engine.py`)

A **Tree** is just a title, a starting step id, and a flat dict of
**Step**s. Each Step has a question and a list of **Option**s; an Option
either points at another step (`next_id`) or ends the flow right there
with a `resolution` string. It's plain-old JSON, so flows can be written,
versioned, and reviewed without opening the Editor at all. A flow also
carries optional `client` and `version` fields that get stamped into
every report.

### Validation

`Tree.check()` returns structured `Issue`s (severity, code, step, answer).
**Errors** mean the flow is broken — an answer to a missing step, a
step with no answers, duplicate answer labels, an ending with no
resolution text, or a loop a tech can never get out of. **Warnings**
are probable mistakes that still run (unreachable steps, loops that do
have a way out, a resolution that's never shown). The Editor shows a live
error/warning count, marks broken steps in the outline, and its Validate
dialog jumps to the offending step. `build_client_release.py` refuses to
build a flow with errors.

### Branding and rich content

A flow can carry a `branding` block — all fields optional — that makes the
Player look like the client's own tool:

```json
"branding": {"name": "Acme Assist", "accent": "#3366CC", "logo": "images/logo.png"}
```

`name` replaces "Longleaf" in the window title, `accent` (`#RRGGBB`) replaces
the gold (its brighter/dimmer shades are derived from it), and `logo` shows
in the Player's header. Set it in the Editor via **Branding…**.

Steps take an optional `image` (a screenshot shown under the question), and
answers that end the flow take one too (shown with the resolution). Question,
note and resolution text can span several lines, and bare `http(s)://` links
become clickable; nothing typed is ever interpreted as markup. Image paths are
relative to the flow file, must stay inside its folder, and are checked by
validation (`MISSING_IMAGE`, `BAD_IMAGE_PATH`, `BAD_ACCENT`). The Editor's
image picker copies a file from elsewhere into an `images/` folder beside the
flow. `build_client_release.py` bundles every referenced image into the exe.
A screenshot that fails to load at runtime is skipped, never an error screen.
Reports stay text-only.

### Shared endings and KB articles

An answer can end the flow inline (its own `resolution` text) or at a **shared
resolution** (`"resolution_id": "…"`) defined once in the flow's top-level
`resolutions` dict, so many paths finish at the same ending and the fix is
edited in one place. Steps and resolutions can also offer **KB articles**
(`"articles": ["…"]`, defined in the top-level `articles` dict) that a tech can
read, attach to the ticket, or use as the resolution. Both are optional and
flows without them are unchanged. See `examples/shared_resolutions_and_kb.json`
and the "Shared resolutions and KB articles" section of
[`docs/API.md`](docs/API.md).

In the Editor, **Shared…** (title bar) opens the dialog to create, edit and delete
shared resolutions (text, screenshot, offered articles) and KB articles; Cancel
changes nothing and OK is one undo step. On an answer that ends the flow, the
**ending** drop-down chooses "Written here" (inline text) or a shared resolution
(with a preview and **Edit shared…**), or **+ New shared resolution from this
text…** to promote what you just typed. Pointing an answer at a next step clears
its shared resolution. Each step has **KB articles offered here → Choose…**.

In the Player, a step or ending that offers articles shows a **Knowledge base**
list under the answers. **Read** expands the article in place; **Attach to
ticket** copies its title and link (or its text, when it has no link) to the
clipboard and notes it as attached (it then appears in the report as "KB
attached"); **Use as resolution** finishes the session with the article as the
answer (steps only; **Back** undoes just that and returns to the step). Each is
logged through `record_article()` / `use_article_as_resolution()`, so it lands in
the saved session and the feedback export.

**Rejected endings.** A real ending has **This didn't work — try something else**.
Clicking it remembers that resolution for the rest of the session (it goes in the
record as `rejected_resolutions`) and returns the tech to the step it came from.
Answers that lead only to rejected endings stay on screen, dimmed and marked
"already tried", so the tech can't be sent round again — including by a different
path to the same shared resolution. When nothing is left on a step, an **escalate**
button finishes the session with the flow's escalation card: a shared resolution
designated in the Editor (**Shared… → Escalation card**, `escalation_resolution` in
the flow), or a plain default. The result screen and reports list what was tried.
In the Editor's graph and import summary, an ending rejected in at least half of
3+ sightings is flagged (orange) as one techs keep rejecting.

### Session records and reports

Every pass through a flow is a `SessionRecord` (`engine.record()`): the
path as step ids + answer indexes, timestamps, outcome, and optional
ticket / technician / notes entered on the Player's result screen. Reports
render from it as `.txt`, `.md`, `.html` or `.json` (the Player's Export
button offers all four). The same record is the payload of the planned
server API — see [`docs/API.md`](docs/API.md) (a design only; nothing there
is built).

See [`ROADMAP.md`](ROADMAP.md) for what's done, what's next, and what we've decided not to build.

## Undo and crash recovery (Editor)

**Edit → Undo / Redo** (Ctrl+Z, Ctrl+Y or Ctrl+Shift+Z) covers every edit to the
flow — typing, adding or deleting steps and answers, start step, branding — as
one history. It works while the cursor is in a text box, and a burst of typing
in one place is one step. Undo stays available after a save, and undoing back to
the saved state clears the unsaved mark. History is cleared on New/Open.
(`undo_stack.py`, GUI-free.)

While there are unsaved changes the Editor writes a recovery copy two seconds
after the last edit, to `editor-autosave/` under the app-data folder
(`LONGLEAF_DATA_DIR` overrides, as for the Player). The flow file itself is
never touched. Saving, or closing and choosing Save/Discard, deletes the copy;
anything still there at the next launch means the Editor died, and it offers to
recover it. Image files you picked are already copied into `images/`, so they
survive a crash. (`autosave.py`, GUI-free.)

## Outcome log (Player)

Beside the full session files, the Player keeps one plain log per client:
`outcome-log.jsonl` in the app-data folder (`logs/<client>/`), one JSON event per
line, append-only. It records that a session started, each answer (step id and
answer index), endings the tech rejected, how the session finished (resolved or
not from the "Did this solve it?" answer, the optional ticket or call id, an
escalation, a KB article used as the answer), a rating or ticket change after the
fact, going Back from an ending, **resets** (Start Over part-way, with a count of how many
before the call ended), **parked and resumed** calls, **abandoned sessions** (another flow,
or closing the app part-way), every Back press, and searches that matched nothing. **File → Export
Outcome Log…** copies it for the client to send back; **Clear Saved Sessions…**
removes it too. Events hold ids and outcomes, not notes, comments, names or fix
wording; the ticket id and search query are what a tech typed, so treat the file
like the session files. Every event leaves through one function
(`outcome_log.OutcomeLog.emit`, passed to the `PlayerWidget` as `event_sink`), so
swapping the file for an HTTPS call later is one change. `outcome_log.fold_sessions`
turns the stream into one summary per session (resolved / not resolved / finished /
abandoned / in progress) for the analytics viewer. Event formats are in
[`docs/API.md`](docs/API.md#outcome-log).

## Search (Player)

A step can have **search tags** (Editor → step → "Search tags", comma-separated).
On the Player's start screen the cursor is in a search box: type what you're
seeing ("wifi keeps dropping") and the best-matching steps are offered, each with
why it matched; Enter takes the top one, or click another. The session then starts
at that step, **Back** returns to the start screen, and the report and saved
session record the query and the landing step (`entry_step_id`, `search_query`).
Search matches tags first, then the question, note, answers, the fixes the
answers end at and the KB articles offered; every word must match (prefixes and
simple plurals count), and if none match everything, steps matching some words
are shown. Only steps reachable from the start are offered. It is plain word
matching in `search.py` (GUI-free, unit-tested) — predictable to tune with tags,
no typo tolerance yet. The query is free text, so it can hold customer details
like the notes can.

## Graph view (Editor)

The Editor's right pane has a **Graph** tab beside Live Test: an auto-laid-out,
read-only picture of the flow. Steps are boxes, answers are labelled arrows,
endings are green pills, and a link to a missing step is a red dashed pill.
Click a step to select it in the outline. It also shows validation (red/amber
outlines, dashed + dimmed unreachable steps), the Test pane's current step and
the path taken so far (gold), and exports the whole graph as PNG or SVG for
client sign-off. Ctrl+wheel zooms; drag pans. Layout is a small layered
(Sugiyama-style) algorithm in `graph_layout.py` — GUI-free and unit-tested —
that handles merges and loops: loops are drawn underneath and never stretch
the layout.

## Feedback loop (no server)

The Player keeps what happened, and the client sends it back as a file:

1. **Rating.** On a real ending the result screen asks **"Did this solve it?"**
   (Yes / No, plus an optional comment). Clicking the lit button again clears it.
2. **Saved locally.** Every finished session (with its ticket, technician, notes
   and rating) is saved as a small JSON file the moment it finishes and updated
   as the tech types, under the app-data folder, one folder per client
   (`LONGLEAF_DATA_DIR` overrides the location). Records are never dropped:
   going back from an ending, Start Over part-way, swapping persona, or leaving for another
   flow keeps the session, saved as it stands (in progress), so the Editor's overlay shows where
   techs leave a flow. The Editor's Test pane never records anything.
3. **Export.** **File → Export Feedback…** writes every saved session into one
   `longleaf_feedback_<client>_<date>.json` for the client to send back
   (exports are cumulative; the Editor ignores repeats). **File → Clear Saved
   Sessions…** deletes them from the machine. Notes and comments can contain
   customer details, so the dialog says what the file includes.
4. **Import (Editor).** **Feedback → Import feedback files…** takes one or more
   of those files, merges them without double-counting, and overlays them on
   the Graph tab: arrows thicken with traffic and never-taken answers fade,
   steps show visit counts, endings show session count and helpful-rate (red
   under 50%), and a numbered badge marks steps with comments. The step editor
   gets a read-only panel with that step's counts and comments, and a summary
   lists the endings techs found unhelpful. Sessions are matched to the flow by
   step id + answer index, so feedback from older versions still lines up where
   the ids survive; ones that don't are counted as "didn't match", and files
   from a different client or flow trigger a warning.

All of this is plain code in `feedback.py` (no Qt), unit-tested in
`tests/test_feedback.py`. The file is `{"kind": "longleaf-feedback",
"schema_version", "flow", "sessions": [SessionRecord…]}`, the same session
record as in [`docs/API.md`](docs/API.md), so a hosted version could ingest the
same data later.

## Example flows (`examples/`)

Three worked examples across different verticals, used as starting
points/demos while scoping a client's flow — not shipped to clients
as-is:

- `it_helpdesk_no_network.json` — network-connectivity troubleshooting
- `marketing_campaign_blocker.json` — diagnosing why a campaign launch is stuck
- `customer_support_triage.json` — routing an incoming support ticket

Open any of them in the Editor, or point a dev build of the Player at
one with File → Open Flow.

## Setup

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Tests

```
pip install -r requirements-dev.txt
python -m pytest tests          # engine, validation, reports, API-doc contract (no Qt needed)
python smoke_test.py            # GUI smoke test (offscreen Qt)
```

## Run (internal use)

```
venv\Scripts\activate
python editor_main.py     # build/edit a client's flow
python player_main.py     # preview it as the client will see it
```

## Building a client release

The only supported way to produce something that leaves Yellowhammer:

```
venv\Scripts\activate
python build_client_release.py <client-slug> <version> <path-to-flow.json>
```

e.g. `python build_client_release.py acme-hvac 1.0.0 clients\acme-hvac\flow.json`
produces `dist\Longleaf-Player-acme-hvac-v1.0.0.exe` — the client's flow
baked in via PyInstaller's `datas`, nothing else. The script validates the flow
first (errors abort the build, warnings are printed) and stamps the release
version into the bundled copy so exported reports name the exact build. This is a local,
manual script by design — there's no CI pipeline and no public
GitHub Release for these; each client's exe is a one-off handed to that
client directly. See "Editor never ships" above for how the script
guarantees the Editor can't end up in that exe.

`Longleaf-Editor.spec` and `Longleaf-Player.spec` still exist for quick
internal dev builds (`pyinstaller Longleaf-Editor.spec`) — the Player
spec bundles the repo's own `flow.json`, which is dev/test data, not a
client's. Never distribute a build made from these specs directly.
