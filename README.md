# Longleaf

*A Yellowhammer product.*

A branching decision-flow tool — not just IT troubleshooting; any team
that walks people through "ask a question, branch on the answer, end at
an outcome" (support triage, marketing ops, onboarding checklists) can
build and ship one. Shipped as two separate apps that share one engine
and one look:

- **Player** (`player_main.py`) — what a field tech runs. Opens a `.json`
  flow file (a `flow.json` bundled next to the exe by default) and walks
  it: one question at a time, click an answer, get a final resolution and
  a copyable/exportable report of the path taken. No editing capability.
- **Editor** (`editor_main.py`) — what you use to build/maintain flows.
  Outline of every step on the left, a form to edit the selected step's
  question/answers/branches in the middle, and a **live Test pane** on the
  right running the exact same Player widget — so testing a flow while
  you build it is immediate, and the outline highlights whichever step
  the live test is currently on.

Both are plain PySide6 desktop apps, packaged independently as Windows
`.exe` files with PyInstaller.

## Data model (`engine.py`)

A **Tree** is just a title, a starting step id, and a flat dict of
**Step**s. Each Step has a question and a list of **Option**s; an Option
either points at another step (`next_id`) or ends the flow right there
with a `resolution` string. It's plain-old JSON, so flows can be written,
versioned, and reviewed without opening the Editor at all.

## Example flows (`examples/`)

Three worked examples across different verticals, to show this isn't
IT-only:

- `it_helpdesk_no_network.json` — network-connectivity troubleshooting
- `marketing_campaign_blocker.json` — diagnosing why a campaign launch is stuck
- `customer_support_triage.json` — routing an incoming support ticket

Open any of them in the Editor, or point the Player at one with
File → Open Flow.

## Setup

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```
venv\Scripts\activate
python editor_main.py     # authoring
python player_main.py     # playback (looks for flow.json next to it)
```

## Build a Windows .exe

```
venv\Scripts\activate
pyinstaller Longleaf-Editor.spec
pyinstaller Longleaf-Player.spec
```

The Player build bundles `flow.json` alongside the exe as its default
flow (via the spec's `datas`) — replace that file before building to ship
a different default, or use File → Open Flow at runtime to load another.
