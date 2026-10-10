# Longleaf roadmap

Longleaf is a service product: Yellowhammer builds a client's flow, and the
client gets an offline Player exe. Features are judged on two questions —
does it cut the time to build a client's flow, or does it make the support
contract worth paying for? Anything that turns Longleaf into software we
have to host and operate needs a client asking for it first.

Status: ✅ done · 🔜 next · 💤 only if asked / earned

## 1. ✅ Engine, validation and reports

- Fixed `go_back` (was replaying by label), blank result on a dangling link, and trap loops passing validation.
- Structured validation (`Tree.check()`), live status and jump-to-step in the Editor, build refuses flows with errors.
- Step-ID history, `SessionRecord`, reports as txt / md / html / json, ticket / technician / notes on the Player result screen.
- Server API mapped out in [`docs/API.md`](docs/API.md) (design only).

## 2. ✅ Branding and rich step content

Highest perceived value for the least work: the client is paying for "their" tool.

- Per-client branding (name, accent colour, logo) in a `branding` block of the flow, editable in the Editor and applied by the Player.
- Screenshots on steps and endings (bundled into the exe by `build_client_release.py`), multi-line text, clickable links. See the README's "Branding and rich content".
- Known gaps: very dark accent colours give low-contrast button text; no image zoom; reports don't include screenshots.

## 3. ✅ Read-only graph view in the Editor

- Auto-laid-out graph of the flow (flows are graphs, not trees — merges and loops must lay out cleanly).
- Click a node to select that step; highlight the Test pane's current step and path.
- Show validation visually: unreachable steps, dead ends, missing links.
- Export PNG / SVG for client sign-off during scoping.

Worth most on flows of roughly 15+ steps; for small flows it is mainly a demo and sign-off tool.

Known gaps: a step with 5+ answers gets crowded edge labels; labels are truncated (full text in the tooltip); very large flows are untested beyond the shipped examples; it is read-only by design (see the editable canvas in section 5).

## 4. ✅ Local feedback capture

No server. The Player asks "Did this solve it?" with an optional comment, stores records locally, and an Export button produces a file the client sends back. The Editor imports those files and overlays traffic per branch, helpful-rate per ending, and comments pinned to steps. The record shape already existed (`SessionRecord.feedback`, `engine.set_feedback()`). See the README's "Feedback loop".

Known gaps: the client has to send the file by hand (by design); no per-version filter on import (everything imported is measured against the flow currently open); no trend over time; sessions are matched by step id, so reusing an id for a different question mixes their data (see docs/API.md).

This is also the basis for a recurring flow-review offering on the support contract.

## 5. 💤 Only if asked, or earned by using the above

| Item | Build it when |
|---|---|
| Editable graph canvas (drag to connect and move) | after using the read-only view on real client flows, you find yourself wanting it |
| Hosted server | several clients ask for it — endpoints are already mapped in `docs/API.md` |
| Opt-in upload queue in the Player | the server exists |

## Anytime

- ~~Editor undo/redo and autosave / crash recovery~~ — done (see README "Undo and crash recovery"). Not covered: undo of image files copied into `images/`, and recovery when two Editors run at once.
- One-click "new step from this answer" in the step editor (today: add a step, then pick it from a dropdown).
- AI-drafted first pass from a client's SOP: paste a document, get draft flow JSON, then validate and hand-edit. Internal-only, so no client data path.
- Duplicate step, step templates, flow version shown in the Player's about box.

## Not planned

User accounts, cloud-hosted flows, and real-time collaboration. They would turn a service business into a SaaS product to run.

## Decisions that need real-world numbers

How many clients we expect in the next year and how large their flows get. Small flows demote the graph view to a demo feature; few clients keep feedback file-based indefinitely.
