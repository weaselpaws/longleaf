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
`widgets/step_editor.py`, `widgets/option_row.py`) — verified two ways:

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

### Session records and reports

Every pass through a flow is a `SessionRecord` (`engine.record()`): the
path as step ids + answer indexes, timestamps, outcome, and optional
ticket / technician / notes entered on the Player's result screen. Reports
render from it as `.txt`, `.md`, `.html` or `.json` (the Player's Export
button offers all four). The same record is the payload of the planned
server API — see [`docs/API.md`](docs/API.md) (a design only; nothing there
is built).

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
