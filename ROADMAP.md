# Longleaf roadmap

Longleaf is a service product: Yellowhammer builds a client's flow, and the
client gets an offline Player exe. Features are judged on two questions —
does it cut the time to build a client's flow, or does it make the support
contract worth paying for? Anything that turns Longleaf into software we
have to host and operate needs a client asking for it first.

Status: ✅ done · 🟡 partly done · 🔜 next · 💤 only if asked / earned

## Positioning

- Dedicated decision-tree competitors exist (Zingtree, Yonyx, Stonly, Process Shepherd, PixieBrix); all are cloud subscriptions priced per seat.
- **Wedge:** a local install with flows on the client's own network drive, no per-seat subscription, a lightweight installer. Cloud hosting is an optional add-on, never required.
- Design from the user's point of view on both sides: the person working the flow and the person reviewing analytics. A comparable tool at a former employer was right over 75% of the time, but poor UX killed adoption, so clicks and cognitive load are the cost to minimise.

## Path to the MVP prototype

The MVP is stages 1 and 2: a Player that finds the right card fast and logs the outcome, plus a way to read the logs. Sections 1–4 below (engine, branding, graph view, local feedback) and the Editor and Player work listed here are what we have built so far.

| MVP item | Status | Where it stands |
|---|---|---|
| **Search** over card tags and keywords, landing in the right node instead of the root | ✅ | `tags` on steps (Editor field) and a search box on the Player start screen that jumps to the best-matching step; the query and landing step are logged. Plain word matching; no typo tolerance yet, and no analytics on what techs search for. |
| **Notepad** for extra ticket notes, exported under "additional notes" | 🟡 | The result screen already takes ticket, technician and notes and exports them in all four formats. Missing: a notepad available *during* the flow, and the "additional notes" heading. |
| **One-click outcome logging**: resolved or not, optional ticket or call ID, to a plain log file | 🟡 | "Did this solve it?" Yes/No with a comment, ticket reference, and every finished session saved locally and exportable. Missing: the single append-only log file behind one swappable function (today it is one JSON file per session), and logging an unresolved or abandoned session. |
| **Roles / profiles**: a user can have several roles, each deciding which tools appear beside the flow | 🔜 | Not started. Keep roles as simple config files. |
| **Analytics viewer** reading the logs: flow usage ranking, resolution rate, per-card hits, trends | 🟡 | The Editor already overlays traffic per branch, helpful-rate per ending and comments on the graph, and endings are grouped by shared resolution. Missing: usage ranking across flows, trend over time, and the open decision below (a separate exe, or an internal Editor mode). |

**Open decision:** is analytics a third, client-facing exe, or an internal Editor mode used for a recurring flow-review service? This roadmap currently assumes the internal overlay; a client-facing viewer changes the "clients only get the Player" model.

### Smaller items

| Item | Status | Where it stands |
|---|---|---|
| Knowledge base articles: read, attach to the ticket, use as the resolution | ✅ (Player UI in review) | Engine, Editor dialog and step/resolution pickers, and the Player list with Read / Attach / Use as resolution are built. |
| Likes/dislikes feedback, surfaced in analytics | ✅ | Player rating and comment; helpful-rate in the Editor overlay. |
| Shared endings (different paths, one resolution) | ✅ | Shared resolutions in the engine and Editor; analytics count them as one ending. |
| Handling users bounced back to the same failed resolution | 🔜 (in progress) | "This didn't work" per session, skip or escalate, flag high-rejection endings in the overlay. |
| Any AI feature is strictly opt-in, never default, and organisations bring their own | rule | Applies to the AI-drafted first pass under "Anytime" and anything after it. |

### New ideas (October 22)

All 🔜, none started. They build on each other, so the order matters:

1. **Optional customer info panel**: name, phone, account details, entered by hand or filled by a plugin. Personal data, so see "Things to watch".
2. **Adaptive flows**: tag what the agent already knows (device model, steps tried) and skip questions already answered. The signature end-user feature; it needs the info panel and tags first.
3. **Generic connector layer**: ID in, bundle of fields out. HubSpot is the first plugin, SolarWinds likely second. To confirm: an API token with contact read access.
4. **Role-based toolkits**: small generic tools per role (help desk notepad, sales calculator and tax rates), added as clients ask. Rides on roles/profiles.

## Things to watch

- Customer info means personal data. That matters for HIPAA-minded clients and ties into the encryption plans.
- Every toolkit is something to maintain, so keep roles as simple config files and add tools only as clients ask.
- Free-text fields (notes, ticket references, comments) can already hold customer details; mind that before any hosted mode.

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

## Later stages

- **Stage 3**: an optional local HTTPS server (port 443) that takes over log writing and the search index. Only set the stage for it (stable ids, append-only events with a session id, all logging behind one function); don't build it. The real trigger is several Players writing one shared log.
- **Stage 4**: Editor upgrades. Partly there already: graph view, validation with jump-to-step, a live Test pane, undo/redo and autosave. Still to come: version history and a deliberate pass on dead-end and orphan checks as flows grow.
- **Stage 5**: paid tier with optional at-rest encryption tied to a client account, callback-window resolution tracking (a flow only counts as working if the same issue doesn't return within about 15 days, which needs ticket or call ids from the client), and later script-adherence monitoring. Enterprise-only ideas such as call monitoring stay out of the MVP.

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

## Business model

- Service model: custom flows built per client, only the Player delivered; the Editor never ships.
- Pricing is hourly (around $75–100) with a per-client cap for the first two or three clients, then flat packages based on the real average hours.
- Target market is broader than CompTIA study: IT help desk, healthcare intake, HR onboarding, compliance checklists.
- Flow updates default to a network path (UNC share), not a hosted server.

## Not planned

User accounts, cloud-hosted flows, and real-time collaboration. They would turn a service business into a SaaS product to run.

## Decisions that need real-world numbers

How many clients we expect in the next year and how large their flows get. Small flows demote the graph view to a demo feature; few clients keep feedback file-based indefinitely.
