# Longleaf server API (design — not implemented)

Longleaf ships as an offline Player exe. **Nothing here is built.** This
is the contract for the day a client wants a hosted Longleaf (central
flow updates, usage data, feedback review), written down now so the Player,
Editor and engine data shapes are already compatible with it.

Two things make this cheap to add later:

- `engine.py` has no GUI imports. A server can `import engine` to validate
  flows (`Tree.check()`) and render reports (`SessionRecord.render()`) with
  exactly the code the apps use — no second implementation to drift.
- Every payload below is already what the engine produces today
  (`Tree.to_dict()`, `Issue.to_dict()`, `SessionRecord.to_dict()`).
  The example in "Session record" is parsed by a test
  (`tests/test_api_contract.py`), so the doc can't silently go stale.

## Conventions

- Base path `/api/v1`. JSON in and out, UTF-8. Timestamps are ISO-8601 with a UTC offset.
- Auth: `Authorization: Bearer <key>`. Keys are per client and carry a **scope**:

  | Scope | Who holds it | Can do |
  |---|---|---|
  | `player` | baked into a client's exe | read that client's published flows; write that client's sessions + feedback |
  | `editor` | Yellowhammer staff | everything `player` can, plus validate/publish flows and read sessions, reports, analytics |
  | `admin`  | Yellowhammer only | all of the above across every client; key management |

  A key inside an exe **can be extracted**, so `player` is deliberately
  low-power: it can add data for its own client and read that client's flow,
  nothing else. Never ship an `editor` or `admin` key.
- Errors: `{"error": {"code": "FLOW_INVALID", "message": "…", "issues": [ … ]}}` with the usual
  status codes (400 malformed, 401/403 auth, 404, 409 conflict, 422 semantically invalid, 429).
  `issues` is only present on validation failures.
- Lists are cursor-paginated: `?limit=` (default 50, max 200) and `?cursor=`; responses carry `next_cursor` (or `null`).
- **Offline-first.** The Player must keep working with no network. It queues finished
  records locally and uploads when it can. `session_id` is a client-generated UUID and
  `PUT /sessions/{id}` is idempotent, so retries and duplicate uploads are harmless.
- Privacy: `notes`, `ticket_ref` and feedback `comment` are free text and can contain
  customer details. A hosted version needs a retention setting per client and the ability to
  delete a session.

## Endpoints

### Health
| | |
|---|---|
| `GET /health` | `200 {"status":"ok","api":"v1"}`. No auth. |

### Flows

A flow is identified by a stable `flow_id` (slug, e.g. `acme-hvac-no-network`). Published
versions are **immutable**: fixing a typo means publishing a new version.

| Endpoint | Scope | Purpose |
|---|---|---|
| `POST /flows/validate` | editor | Body: a flow (`Tree.to_dict()`). Always `200 {"valid": bool, "errors": n, "warnings": n, "issues": [Issue]}` for a parseable flow; `400` if it isn't a flow at all. Stateless — same result as `Tree.check()`. |
| `GET /flows` | player, editor | Flows visible to the caller's client: `[{"flow_id","title","latest_version"}]`. |
| `GET /flows/{flow_id}` | player, editor | The latest published version (a flow). |
| `GET /flows/{flow_id}/versions` | editor | `[{"version","published_at","published_by"}]`, newest first. |
| `GET /flows/{flow_id}/versions/{version}` | player, editor | One specific version. |
| `PUT /flows/{flow_id}/versions/{version}` | editor | Publish. Server re-runs `Tree.check()`: any **error** → `422 FLOW_INVALID` with `issues`; warnings are allowed (and returned). Re-publishing byte-identical content is `200`; different content under an existing version is `409 VERSION_EXISTS`. First publish is `201`. |

The server stamps `version` (and `client`, if empty) into the flow it stores, mirroring what
`build_client_release.py` does for the exe, so a report always names the build that produced it.

### Sessions (Player → server)

A session is one pass through a flow — the "session record" below.

| Endpoint | Scope | Purpose |
|---|---|---|
| `PUT /sessions/{session_id}` | player, editor | Create or replace a record. `201` new / `200` replaced. `session_id` in the path must equal the body's; the record's `flow.client` must match the key's client (`403` otherwise). Allowed to arrive in progress and be replaced when finished. |
| `PATCH /sessions/{session_id}/feedback` | player, editor | Body `{"helpful": true\|false\|null, "comment": ""}`. Lets a tech rate an ending after the record has already been uploaded. Sets the record's `feedback`. |
| `GET /sessions` | editor | Filters: `flow_id`, `version`, `outcome` (`resolved`\|`in_progress`\|`error`), `ticket_ref`, `since`, `until`, `has_feedback=true`, `helpful=true\|false`. Returns `{"items":[SessionRecord], "next_cursor"}`. |
| `GET /sessions/{session_id}` | editor | One record. |
| `DELETE /sessions/{session_id}` | editor | Hard delete (privacy). `204`. |
| `GET /sessions/{session_id}/report?format=txt\|md\|html\|json` | editor | The rendered report, `SessionRecord.render(format)`, with the matching `Content-Type`. Same bytes the Player's Export button writes. |

### Analytics (server → Editor)

| Endpoint | Scope | Purpose |
|---|---|---|
| `GET /flows/{flow_id}/analytics` | editor | Aggregates over sessions. Optional `version` (omit for all), `since`, `until`. Shape below. |

```json
{
  "flow_id": "acme-hvac-no-network",
  "version": "1.0.0",
  "sessions": 128,
  "outcomes": {"resolved": 117, "in_progress": 9, "error": 2},
  "median_duration_seconds": 74,
  "steps": [
    {"step_id": "step_1", "visits": 128,
     "answers": [{"option_index": 0, "label": "No network access at all", "count": 71}]}
  ],
  "endings": [
    {"step_id": "step_3", "option_index": 1, "count": 40, "helpful": 31, "not_helpful": 4, "no_rating": 5}
  ]
}
```

`steps` and `endings` are keyed by `step_id` + `option_index`, which is why the session
record stores them (labels and question text are kept only so reports stay readable). The
Editor overlays this on the flow: traffic per branch, helpful-rate per ending, and the
free-text comments (via `GET /sessions?has_feedback=true`) pinned to the step they came from.
**Step ids are therefore identity** — don't reuse an id for a different question between
versions, or the history gets merged.

## Session record

This is `SessionRecord.to_dict()`. `schema_version` bumps only on incompatible changes;
adding optional fields doesn't. `feedback` is `null` until a tech rates the ending (the
Player asks "Did this solve it?" and stores it via `set_feedback()`; today the records travel as a file, see the README's "Feedback loop").

<!-- session-record-example -->
```json
{
  "schema_version": 1,
  "session_id": "0b6f0c1e-6f2a-4c0e-9d57-3a2f1c8e7b11",
  "flow": {"title": "No Network Connectivity", "client": "acme-hvac", "version": "1.0.0"},
  "started_at": "2026-10-06T14:02:11-05:00",
  "finished_at": "2026-10-06T14:03:40-05:00",
  "outcome": "resolved",
  "resolution": "Turn Wi-Fi on and connect to the correct SSID, then retest.",
  "ticket_ref": "INC-1042",
  "operator": "Sam",
  "notes": "Laptop was on the guest network.",
  "feedback": {"helpful": true, "comment": "Fixed it first try."},
  "history": [
    {"step_id": "step_1", "step_question": "What's the symptom on the device?", "option_index": 0,
     "chosen_label": "No network access at all", "answered_at": "2026-10-06T14:02:20-05:00"},
    {"step_id": "step_2", "step_question": "Is the device on Wi-Fi or Ethernet?", "option_index": 0,
     "chosen_label": "Wi-Fi", "answered_at": "2026-10-06T14:02:45-05:00"},
    {"step_id": "step_3", "step_question": "Is Wi-Fi turned on and connected to the correct network?", "option_index": 1,
     "chosen_label": "No, or wrong network selected", "answered_at": "2026-10-06T14:03:20-05:00"}
  ]
}
```

`outcome` is `resolved` (reached a real ending), `in_progress`, or `error` (the flow sent the
tech to a step that doesn't exist; `resolution` then holds the explanation).

## Issue

One entry of `POST /flows/validate`'s `issues` (and of the `422` body), from `Issue.to_dict()`:

```json
{"severity": "error", "code": "MISSING_TARGET",
 "message": "'a' option 'go' points at a missing step ('ghost').",
 "step_id": "a", "option_index": 0}
```

`severity` is `error` (blocks publishing and client builds) or `warning`. `step_id` /
`option_index` are `null` when an issue isn't tied to one.

| Code | Severity | Meaning |
|---|---|---|
| `NO_STEPS` | error | The flow has no steps. |
| `NO_START` | error | No valid starting step. |
| `ID_MISMATCH` | error | A step is stored under a different id than its own `id`. |
| `EMPTY_QUESTION` | error | A step has no question text. |
| `DEAD_END` | error | A step has no answers. |
| `EMPTY_LABEL` | error | An answer has no label. |
| `DUPLICATE_LABEL` | error | Two answers on one step read the same (ignoring case/spacing). |
| `MISSING_TARGET` | error | An answer points at a step that doesn't exist. |
| `NO_RESOLUTION` | error | An answer ends the flow but has no resolution text. |
| `NO_EXIT` | error | A reachable step can never reach an ending — the tech is trapped in a loop or at a missing step. |
| `UNREACHABLE` | warning | No path from the start reaches this step. |
| `SELF_LINK` | warning | An answer leads back to its own step. |
| `IGNORED_RESOLUTION` | warning | An answer has both a next step and a resolution; the resolution is never shown. |
| `CYCLE` | warning | Steps that can loop back on each other (a way out exists). Often intentional ("try again"). |

## What would have to be built

Not in scope until a client asks, but so the cost is visible: a small HTTP service over the
endpoints above, a store (SQLite is enough to start) for flows, sessions and keys, per-client
key issuing, and in the Player an opt-in upload queue plus (separately) a "Did this solve it?"
prompt wired to `set_feedback()`. The Editor's analytics overlay is the other half.
