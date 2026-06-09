# Phase 4a — Projects (design spec)

## Context

Phase 3 shipped purchase + license + payout rails and a generic `EscrowService.hold/release/refund`. Phase 4 turns Auracles from a marketplace of frozen Framework assets into a marketplace where Operators commission custom work from Contributors. This spec covers **Phase 4a — the Projects module only**. Attestation is **Phase 4b** and ships in `docs/superpowers/specs/<date>-phase-4b-attestation-design.md`. Phase 4 is complete only when 4a and 4b both ship; 4b reuses the realtime + notifications infrastructure built here.

Maps to FRD §6 (FR-PROJ-001 through FR-PROJ-013, BR-PROJ-001 through BR-PROJ-005) and the relevant escrow flows in TDD §3 (`escrows.ref_type="project_milestone"`, `transactions.type="milestone"`).

Project state today: zero scaffolding for `projects/` or `attestation/` in `backend/app/modules/` and `frontend/src/app/`. EscrowService consumer surface is ready. No WebSocket gateway exists yet. No in-app notifications module exists; only email-via-Celery.

## Goals

- Operator posts a Project, Contributors submit Proposals, Operator accepts one.
- After accept, the parties collaborate inside a real-time **Workspace**: messages, file attachments, milestone tracker, deliverable board.
- Contributor defines Milestones; Operator funds them one at a time into Escrow; Contributor submits Deliverables; Operator approves (or revises). Escrow releases on approve.
- Either party can raise a Dispute that pauses Escrow; Admin resolves with release / refund / split.
- Either party can propose an **Amendment** to scope / budget / timeline; the other party accepts or rejects. No off-platform syncing required.
- Contributor can publish an approved Deliverable as a marketplace Framework.
- In-app notifications + email cover every off-session event.

## Architectural decisions (locked)

| Decision | Value | Rationale |
|---|---|---|
| Amendment flow | Formal `proposal_amendments` table, both-party accept, 7d auto-expire | BR-PROJ-002 requires "written agreement". A dedicated entity with an explicit accept action gives both parties an audited paper trail without dragging in Admin. Upwork confirms this is the standard freelance pattern; admin arbitration belongs on disputes, not amendment stalls. |
| Deliverable approval timeout | 14d auto-approve + Escrow auto-release | Protects Contributor from a ghosting Operator. Mirrors Upwork's well-known 14d rule. Auto-approval generates an explicit `auto_approved` deliverable status + audit + workspace system message so the change is never silent. |
| WebSocket auth | First-message handshake | Client opens `wss://api/v1/ws` with no token in the URL. Server replies `auth_required`; client sends `{type:"auth", token:"<jwt>"}`. Keeps access tokens out of access logs, proxies, and browser history. |
| WebSocket topology | One global multiplexed connection per user | `wss://api/v1/ws` carries `user:{id}` (notifications) plus N `project:{id}` channels the user subscribes to as they navigate. Single TCP connection, server-side fanout via Redis pub/sub. Survives browser per-host WS limits. |
| Workspace file processing | Virus scan only | Workspace files are collaboration artifacts, not marketplace assets. Skip PII redaction / fingerprint / rarity / thumbnail. Reuse Phase 2 ClamAV stage via a thin `scan_workspace_upload` Celery task. |
| Milestone budget invariant | Strict — `SUM(milestones.budget) == accepted_proposal.budget` | Predictable escrow exposure for Operator. Any change to total budget must go through the amendment flow, which atomically mutates `proposals.budget` and forces a re-balance of milestones. |
| Publish-as-Framework (FR-PROJ-013) | Manual prefill | Contributor clicks "Publish as Framework" on an approved deliverable. Routes to the existing `/dashboard/frameworks/new` flow with `title`, `description`, `file_keys` prefilled. Contributor edits and submits; the regular framework review pipeline applies. `frameworks.source_project_id` FK preserves provenance. No auto-publish: Operator's project deliverable could be confidential. |
| Notifications module | Full in-app module | New `app/modules/notifications/` with table, REST list/mark-read endpoints, WS push, plus Celery email dispatch. A bell + dropdown + dedicated page on the frontend. Email-only would leave the dashboard feeling broken. |
| Dispute outcomes | Release / refund / partial split | Real-world disputes are rarely clean wins. Admin picks one of: full release to Contributor, full refund to Operator, or partial split with custom amounts that sum to `escrow.amount`. Requires `EscrowService.split(...)`. Admin role + 2FA + written rationale + audit log. |
| Concurrent Project cap | 5 active per Operator (BR-PROJ-004) | Enforced at create time inside the same txn that inserts the row. Active = `status IN ('open','assigned','in_progress','delivered','disputed')`. |
| Project auto-close | 30d no accepted Proposal (BR-PROJ-005) | `projects.expires_at = created_at + 30d`. Daily Celery Beat flips `open → closed` and withdraws all pending proposals. Operator can extend via `PATCH` while project is still `open`. |
| Dispute auto-escalate | 7d (BR-PROJ-003) | Hourly Beat flips `open → under_review`, sets `escalated_at`, notifies Admin queue. |
| Workspace participants | Operator + accepted Contributor only | Phase 4a MVP. Multi-collaborator workspaces deferred. |
| Currency | USD only (matches Phase 3 lock) | `CHECK currency = 'USD'` on `projects`, `proposals`, `milestones`. NGN / multi-currency deferred. |

## Module layout

```
backend/app/
├── modules/
│   ├── projects/
│   │   ├── router.py            # /v1/projects/*
│   │   ├── service.py           # Project + Proposal + Amendment orchestration
│   │   ├── milestone_service.py # Milestone + Deliverable + Escrow integration
│   │   ├── dispute_service.py   # Dispute lifecycle + Admin resolution
│   │   ├── models.py            # ORM
│   │   ├── schemas.py           # Pydantic
│   │   └── dependencies.py      # require_project_member, require_project_owner
│   ├── workspace/
│   │   ├── router.py            # /v1/projects/{id}/messages REST
│   │   ├── service.py           # message persistence + S3 + scan dispatch
│   │   ├── models.py            # workspace_messages
│   │   └── schemas.py
│   ├── realtime/
│   │   ├── gateway.py           # /v1/ws endpoint, connection lifecycle
│   │   ├── auth.py              # first-message handshake
│   │   ├── pubsub.py            # Redis publisher + subscriber registry
│   │   ├── channels.py          # user:{id}, project:{id} resolvers + membership checks
│   │   └── service.py           # publish_to_channel(channel, payload)
│   └── notifications/
│       ├── router.py            # /v1/notifications/*
│       ├── service.py           # create + read + count
│       ├── models.py            # notifications
│       └── schemas.py
└── workers/tasks/
    ├── project_notifications.py # one task per event type, dual-emit (DB row + WS + email)
    ├── workspace_scan.py        # ClamAV scan on workspace upload
    └── projects_beat.py         # close_expired_projects, escalate_disputes,
                                 # auto_approve_deliverables, expire_amendments,
                                 # expire_open_proposals
```

## Schema

### New tables

#### `projects`
```
id                       UUID PK
operator_id              UUID NOT NULL FK users(id)
title                    TEXT NOT NULL
description              TEXT NOT NULL
category                 TEXT NOT NULL
required_deliverables    JSONB NOT NULL  -- [{name, description}], min 1 entry, validated at create
budget_min               NUMERIC(12,2) NOT NULL
budget_max               NUMERIC(12,2) NOT NULL
currency                 VARCHAR(3) NOT NULL CHECK (currency = 'USD')
deadline                 DATE NULL
status                   project_status_enum NOT NULL DEFAULT 'open'
milestone_plan_status    milestone_plan_status_enum NOT NULL DEFAULT 'draft'
expires_at               TIMESTAMPTZ NOT NULL  -- created_at + 30d
accepted_proposal_id     UUID NULL FK proposals(id) DEFERRABLE INITIALLY DEFERRED
delivered_at             TIMESTAMPTZ NULL
closed_at                TIMESTAMPTZ NULL
created_at, updated_at   TIMESTAMPTZ
CHECK (budget_min <= budget_max)
INDEX (operator_id, status)
INDEX (status, expires_at)         -- Beat scan
```
`project_status_enum`: `open, assigned, in_progress, delivered, closed, disputed`.
`milestone_plan_status_enum`: `draft, finalized`. Plan starts `draft` after proposal accept. Contributor finalises via `POST /v1/projects/{id}/milestones/finalize` once `SUM(milestones.budget) == accepted_proposal.budget`. Milestone funding is rejected (`422 plan not finalized`) until the plan is `finalized`. Amendments that change `proposal.budget` flip `milestone_plan_status` back to `draft` until milestones rebalance and re-finalise. Strict-sum invariant is enforced **only at finalize time**, not on each milestone insert.

#### `proposals`
```
id                  UUID PK
project_id          UUID NOT NULL FK projects(id) ON DELETE CASCADE
contributor_id      UUID NOT NULL FK users(id)
scope               TEXT NOT NULL
budget              NUMERIC(12,2) NOT NULL
currency            VARCHAR(3) NOT NULL CHECK (currency = 'USD')
timeline_days       INTEGER NOT NULL CHECK (timeline_days > 0)
deliverables        JSONB NOT NULL  -- [{name, description}]
status              proposal_status_enum NOT NULL DEFAULT 'pending'
withdrawn_at        TIMESTAMPTZ NULL
accepted_at         TIMESTAMPTZ NULL
created_at          TIMESTAMPTZ
UNIQUE (project_id, contributor_id) WHERE status IN ('pending','accepted')
INDEX (project_id, status)
INDEX (contributor_id, status)
```
`proposal_status_enum`: `pending, accepted, rejected, withdrawn`.

#### `proposal_amendments`
```
id              UUID PK
proposal_id     UUID NOT NULL FK proposals(id) ON DELETE CASCADE
proposed_by     UUID NOT NULL FK users(id)
change_type     amendment_change_enum NOT NULL  -- scope | budget | timeline | combo
before          JSONB NOT NULL  -- snapshot {scope, budget, timeline_days}
after           JSONB NOT NULL
reason          TEXT NOT NULL
status          amendment_status_enum NOT NULL DEFAULT 'pending'
responded_at    TIMESTAMPTZ NULL
responded_by    UUID NULL FK users(id)
expires_at      TIMESTAMPTZ NOT NULL  -- created_at + 7d
created_at      TIMESTAMPTZ
UNIQUE (proposal_id) WHERE status = 'pending'  -- one pending at a time
INDEX (status, expires_at)
```
`amendment_status_enum`: `pending, accepted, rejected, withdrawn, expired`.

#### `milestones`
```
id              UUID PK
project_id      UUID NOT NULL FK projects(id) ON DELETE CASCADE
escrow_id       UUID NULL FK escrows(id) ON DELETE RESTRICT
sequence        INTEGER NOT NULL
name            TEXT NOT NULL
description     TEXT NOT NULL
budget          NUMERIC(12,2) NOT NULL CHECK (budget > 0)
currency        VARCHAR(3) NOT NULL CHECK (currency = 'USD')
due_date        DATE NULL
status          milestone_status_enum NOT NULL DEFAULT 'pending'
funded_at       TIMESTAMPTZ NULL
submitted_at    TIMESTAMPTZ NULL
approved_at     TIMESTAMPTZ NULL
created_at      TIMESTAMPTZ
UNIQUE (project_id, sequence)
INDEX (project_id, status)
INDEX (status, submitted_at)       -- auto-approve Beat scan
```
`milestone_status_enum`: `pending, funded, submitted, approved, revision_requested, disputed, auto_approved, cancelled`. App-level invariant enforced in service **at finalize time only**: `SUM(milestones.budget WHERE project_id = X) == accepted_proposal.budget`. Dropped a redundant `in_progress` state — `funded` covers the "Operator has paid, Contributor is working" period; the milestone moves to `submitted` once the Contributor submits a deliverable. `cancelled` is the terminal state for a milestone whose dispute resolution refunded the full escrow back to the Operator (no work delivered, no money owed to Contributor).

#### `deliverables`
```
id                UUID PK
milestone_id      UUID NOT NULL FK milestones(id) ON DELETE CASCADE
contributor_id    UUID NOT NULL FK users(id)
name              TEXT NOT NULL
description       TEXT NOT NULL
file_keys         TEXT[] NOT NULL  -- S3 keys, validated against project membership
revision_notes    TEXT NULL        -- Operator's last revision request, if any
status            deliverable_status_enum NOT NULL DEFAULT 'submitted'
submitted_at      TIMESTAMPTZ NOT NULL DEFAULT now()
approved_at       TIMESTAMPTZ NULL
auto_approved     BOOLEAN NOT NULL DEFAULT FALSE
created_at        TIMESTAMPTZ
INDEX (milestone_id, status)
```
`deliverable_status_enum`: `submitted, approved, revision_requested, auto_approved`.

#### `workspace_messages`
```
id              UUID PK
project_id      UUID NOT NULL FK projects(id) ON DELETE CASCADE
sender_id       UUID NULL FK users(id)  -- NULL for system events
body            TEXT NULL
file_keys       TEXT[] NULL
scan_status     workspace_scan_status_enum NOT NULL DEFAULT 'visible'
system_event    workspace_system_event_enum NULL
system_payload  JSONB NULL
created_at      TIMESTAMPTZ
CHECK (
  (sender_id IS NOT NULL AND (body IS NOT NULL OR file_keys IS NOT NULL))
  OR
  (sender_id IS NULL AND system_event IS NOT NULL)
)
INDEX (project_id, created_at DESC)
INDEX (scan_status) WHERE scan_status = 'pending_scan'
```
`workspace_system_event_enum`: `amendment_proposed, amendment_accepted, amendment_rejected, amendment_expired, milestone_funded, deliverable_submitted, deliverable_approved, deliverable_auto_approved, deliverable_revision_requested, dispute_raised, dispute_resolved`.

`workspace_scan_status_enum`: `pending_scan, visible, quarantined`. Default `visible` because most messages are body-only with no attachments. Insert path: if `file_keys IS NOT NULL`, the service overrides the default to `pending_scan` before commit. `scan_workspace_upload` Celery task flips to `visible` on clean scan or `quarantined` on infected. GET `/v1/projects/{id}/messages` excludes `pending_scan` from the caller's view if they are not the sender, and excludes `quarantined` for everyone; the WS gateway publishes the message event only after the status flips to `visible`.

#### `workspace_upload_sessions`
```
id           UUID PK
project_id   UUID NOT NULL FK projects(id) ON DELETE CASCADE
user_id      UUID NOT NULL FK users(id)
s3_key       TEXT NOT NULL UNIQUE
content_type TEXT NOT NULL
size_limit   INTEGER NOT NULL          -- bytes; enforced by S3 via the presigned POST policy `content-length-range`
consumed_at  TIMESTAMPTZ NULL          -- set when key is attached to a message
expires_at   TIMESTAMPTZ NOT NULL       -- created_at + 5m
created_at   TIMESTAMPTZ
INDEX (project_id, user_id, consumed_at)
INDEX (expires_at)                     -- daily janitor
```
Created when the upload endpoint issues a **presigned POST** (matches the Phase 2 artifact upload pattern; PUT does not support `content-length-range` policy enforcement). The presigned POST policy pins `content-length-range`, `content-type`, and the exact `key`, so S3 rejects oversized or off-key uploads server-side. The message create endpoint validates every `file_keys` entry has an unconsumed session for the same `(user_id, project_id)`, then marks the session `consumed_at`. Prevents a malicious party from claiming `file_keys` they didn't upload.

#### `disputes`
```
id                  UUID PK
project_id          UUID NOT NULL FK projects(id) ON DELETE CASCADE
milestone_id        UUID NOT NULL FK milestones(id) ON DELETE RESTRICT
raised_by           UUID NOT NULL FK users(id)
reason              TEXT NOT NULL
status              dispute_status_enum NOT NULL DEFAULT 'open'
resolution_type     dispute_resolution_enum NULL  -- release | refund | split
release_amount      NUMERIC(12,2) NULL
refund_amount       NUMERIC(12,2) NULL
admin_id            UUID NULL FK users(id)
resolution_notes    TEXT NULL
escalated_at        TIMESTAMPTZ NULL
resolved_at         TIMESTAMPTZ NULL
created_at          TIMESTAMPTZ
CHECK (
  status != 'resolved'
  OR resolution_type IS NOT NULL
)
CHECK (
  resolution_type != 'split'
  OR (release_amount IS NOT NULL AND refund_amount IS NOT NULL)
)
INDEX (project_id, status)
INDEX (status, created_at)         -- Beat escalation scan
```
`dispute_status_enum`: `open, under_review, resolved`. Service enforces `release_amount + refund_amount == milestone.budget` when `resolution_type = 'split'`.

**Resolution → status transitions (all inside one txn alongside the EscrowService call):**

| Resolution | Escrow | Milestone | Deliverable (if any submitted) | Project | Notifications |
|---|---|---|---|---|---|
| `release` | `held → released` via `EscrowService.release` | `disputed → approved` | `submitted → approved` (if revision_requested, stays revision_requested → approved) | Recomputed after resolution using the rules below. | Contributor + Operator notified `dispute_resolved_release` |
| `refund` | `held → refunded` via `EscrowService.refund` (Stripe refund) | `disputed → cancelled` | unchanged (kept for audit) | Recomputed after resolution using the rules below. | Contributor + Operator notified `dispute_resolved_refund` |
| `split` | `held → released` via `EscrowService.split` (refund portion via Stripe) | `disputed → approved` | `submitted → approved` | Recomputed after resolution using the rules below. | Contributor + Operator notified `dispute_resolved_split` with both amounts |

After any resolution, `disputes.status` flips `under_review → resolved` and `resolved_at = now()`. Then the service recomputes `projects.status` in the same transaction: if any open/under_review dispute remains, keep `disputed`; else if any milestone is active (`funded`, `submitted`, `revision_requested`), set `in_progress`; else if all milestones are terminal (`approved`, `auto_approved`, `cancelled`), set `delivered` and `delivered_at` if not already set; else set `assigned`. Audit row `dispute_resolved` written with `resolution_type` and the milestone/project status changes captured in `metadata`.

#### `notifications`
```
id          UUID PK
user_id     UUID NOT NULL FK users(id)
type        notification_type_enum NOT NULL
title       TEXT NOT NULL
body        TEXT NOT NULL
link        TEXT NULL              -- relative app route
payload     JSONB NULL             -- structured context for frontend
dedupe_key  TEXT NULL              -- caller-supplied idempotency key
read_at     TIMESTAMPTZ NULL
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
INDEX (user_id, read_at NULLS FIRST, created_at DESC)
UNIQUE (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL
```
`notification_type_enum` covers every event listed under Celery `dispatch_project_notification` plus future Attestation events.

`dedupe_key` semantics: callers pass a deterministic key like `f"deliverable_submitted:{deliverable_id}"` or `f"amendment_proposed:{amendment_id}"`. Insert uses `ON CONFLICT (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING`. A second dispatch within or after the 60s window collapses to the first row. `NULL` dedupe_key (e.g. workspace chat messages — each is unique) bypasses dedupe and always inserts.

### Extensions to existing tables

- `frameworks` — add `source_project_id UUID NULL FK projects(id)`. Index `(source_project_id)`. Populated by FR-PROJ-013 publish flow.
- `transactions.ref_type` enum — `project_milestone` already supported (Phase 3). Confirm `metadata.kind = "escrow"` plus `metadata.release_conditions.kind = "project_milestone"` routing.
- `escrows.release_conditions` — Phase 4a writes `{kind:"project_milestone", milestone_id, project_id, approver_user_id}`.

## EscrowService additions

Existing `hold` / `release` / `refund` consumed unchanged. One new method:

```python
async def split(
    db: AsyncSession,
    *,
    escrow_id: UUID,
    release_amount: Decimal,
    refund_amount: Decimal,
    actor_id: UUID,
    reason: str,
) -> Escrow:
    """Admin-only partial settlement: split held funds between payee and payer."""
```

- Loads escrow with `with_for_update=True` inside `async with db.begin()`.
- Validates `release_amount + refund_amount == escrow.amount` (Decimal, no float).
- Calls `stripe.create_refund` for the `refund_amount` with `idempotency_key=f"escrow_split:{escrow_id}"`. Hold this network call inside the txn so the lock prevents double-splits; configure Stripe SDK timeout to 10s.
- On success, marks escrow `released`, writes `release_conditions.split = {release_amount, refund_amount}`, generates two transactions: `type=milestone` (release, amount=`release_amount`, payer=operator, payee=contributor, status=`completed`) + `type=refund` (refund, amount=`refund_amount`, payer=operator, payee=null, status=`refunded`, provider_ref=Stripe refund id).
- **Release semantics — money path:** the release portion is **not** a direct transfer to the Contributor's bank. Funds remain in Auracles' Stripe balance from the original PaymentIntent capture; the `transactions(type=milestone, status=completed)` row credits the Contributor's `available_payout_balance` (same calculation Phase 3 already runs over completed milestone rows). The Contributor pulls the funds via the existing `POST /v1/financials/payouts` 2FA-gated flow, which dispatches `process_payout` to Stripe Connect. This matches how a normal deliverable approval works (`EscrowService.release` already follows this pattern). Split simply records a smaller `release_amount` than the full `escrow.amount`.
- **No Stripe Transfer at release time.** Avoids double-handling and aligns with Phase 3 commission-at-payout rule (BR-FIN-001).
- Audit: `escrow_split_resolved` with admin_id, dispute_id, both amounts, reason.

## Realtime gateway

### Endpoint

`WS /v1/ws` — single global per user.

### Message protocol

Client → server:
```json
{"type": "auth", "token": "<jwt>"}
{"type": "subscribe", "channel": "project:<uuid>"}
{"type": "unsubscribe", "channel": "project:<uuid>"}
{"type": "ping"}
```

Server → client:
```json
{"type": "auth_required"}
{"type": "auth_ok", "user_id": "<uuid>"}
{"type": "subscribed", "channel": "<name>"}
{"type": "unsubscribed", "channel": "<name>"}
{"type": "event", "channel": "<name>", "event_type": "<name>", "payload": {...}}
{"type": "error", "code": "<code>", "detail": "<text>"}
{"type": "pong"}
```

### Close codes

`4401` unauthenticated · `4403` forbidden subscribe · `4429` rate-limited · `1000` normal close.

### Lifecycle

1. Client opens socket. Server sends `auth_required`. 5s timer; close `4401` if no auth.
2. Client sends `auth`. Server verifies access token via existing `decode_access_token`, auto-subscribes `user:{id}`, replies `auth_ok`.
3. Client sends `subscribe` on workspace open. Server runs membership check (`projects.operator_id = user_id` OR `projects.accepted_proposal_id.contributor_id = user_id`), replies `subscribed` or `error 4403`.
4. Server fans out events from Redis pub/sub to all matching connections.
5. 30s ping/pong heartbeat. Idle connections culled.

### Pub/sub layer

`app/modules/realtime/pubsub.py` exposes:

```python
async def publish_to_channel(channel: str, event_type: str, payload: dict) -> None
async def subscribe_channel(channel: str, handler: Callable) -> SubscriptionHandle
```

Redis key: `auracles:ws:{channel}`. JSON payloads. Gateway maintains an in-process registry of `{channel: [websocket, ...]}` and a single Redis subscriber per worker that forwards to local sockets.

## API surface (summary)

| Verb | Path | Auth |
|---|---|---|
| POST | /v1/projects | operator + KYC |
| GET | /v1/projects | contributor (open feed) / operator (own) — `?role=` |
| GET | /v1/projects/{id} | project member or any contributor (open) |
| PATCH | /v1/projects/{id} | project owner, status='open' only |
| POST | /v1/projects/{id}/close | project owner, status='delivered' only (manual close, skips 7d grace) |
| POST | /v1/projects/{id}/proposals | contributor + KYC |
| GET | /v1/projects/{id}/proposals | project owner |
| GET | /v1/projects/{id}/proposals/mine | contributor |
| PATCH | /v1/projects/{id}/proposals/{prop_id}/withdraw | proposal author |
| POST | /v1/projects/{id}/proposals/{prop_id}/accept | project owner |
| POST | /v1/projects/{id}/proposals/{prop_id}/amendments | project member |
| POST | /v1/projects/{id}/proposals/{prop_id}/amendments/{amend_id}/accept | counter-party |
| POST | /v1/projects/{id}/proposals/{prop_id}/amendments/{amend_id}/reject | counter-party |
| PATCH | /v1/projects/{id}/proposals/{prop_id}/amendments/{amend_id}/withdraw | proposed_by |
| POST | /v1/projects/{id}/milestones | accepted contributor |
| PATCH | /v1/projects/{id}/milestones/{m_id} | accepted contributor, status='pending' only |
| GET | /v1/projects/{id}/milestones | project member |
| POST | /v1/projects/{id}/milestones/{m_id}/fund | project owner |
| POST | /v1/projects/{id}/milestones/{m_id}/deliverables | accepted contributor |
| POST | /v1/projects/{id}/milestones/{m_id}/deliverables/{d_id}/approve | project owner |
| POST | /v1/projects/{id}/milestones/{m_id}/deliverables/{d_id}/request-revision | project owner |
| POST | /v1/projects/{id}/disputes | project member |
| GET | /v1/projects/{id}/messages | project member, `?before=<ts>&limit=50` |
| POST | /v1/projects/{id}/messages | project member |
| POST | /v1/projects/{id}/messages/uploads | project member |
| POST | /v1/admin/projects/disputes/{dispute_id}/resolve | admin + 2FA |
| GET | /v1/notifications | self |
| PATCH | /v1/notifications/{id}/read | self |
| POST | /v1/notifications/read-all | self |
| WS | /v1/ws | first-message handshake |

## State machines

**Project**
```
open → assigned → in_progress → delivered → closed
                       ↘ disputed ↗
open → closed (30d expired, Beat)
delivered → closed (Operator manual close OR 7d grace + no open disputes, Beat)
```

**Proposal** `pending → accepted | rejected | withdrawn`. Withdraw allowed only while pending.

**Amendment** `pending → accepted | rejected | withdrawn | expired (7d)`.

**Milestone** `pending → funded → submitted → approved` or `submitted → revision_requested → submitted` (loops) or `submitted → auto_approved` (14d Beat) or `* → disputed`. `pending → funded` is set **only by the Stripe webhook handler** after `EscrowService.hold` succeeds — never by the fund endpoint directly.

**Deliverable** `submitted → approved | revision_requested | auto_approved`.

**Dispute** `open → under_review (7d Beat) → resolved (release | refund | split)`.

## Celery tasks

| Task | Trigger | Action |
|---|---|---|
| `scan_workspace_upload(message_id)` | Message create endpoint after row inserted with `scan_status='pending_scan'` | Run ClamAV scan stage on each `file_keys` entry. All clean → flip `scan_status='visible'`, publish `message_visible` event via pub/sub. Any infected → flip `scan_status='quarantined'`, notify uploader, audit `workspace_file_quarantined`. |
| `dispatch_project_notification(user_id, type, payload, dedupe_key=None)` | Service emit | Insert `notifications` row via `ON CONFLICT (user_id, dedupe_key) DO NOTHING` when `dedupe_key` is set, otherwise straight INSERT. On row inserted, publish `user:{id}` WS event and dispatch email task. On conflict (duplicate), no-op return. Callers pick `dedupe_key` per event type (e.g. `f"deliverable_submitted:{deliverable_id}"`). |
| `expire_open_proposals` | Beat hourly | Withdraw pending proposals on closed projects. |
| `expire_pending_amendments` | Beat hourly | Mark amendments `expired` past `expires_at`. Workspace system message + notify both parties. |
| `close_expired_projects` | Beat daily | `UPDATE projects SET status='closed' WHERE status='open' AND expires_at < now()`. Cascade-withdraws pending proposals. |
| `auto_close_delivered_projects` | Beat daily | `UPDATE projects SET status='closed' WHERE status='delivered' AND delivered_at < now() - 7d AND NOT EXISTS (open or under_review disputes for this project)`. The 7d grace is an operational archive delay only; it does not create a post-approval dispute window. Dispute creation still rejects terminal milestones (`approved`, `auto_approved`, `cancelled`) per FRD error state. |
| `auto_approve_deliverables` | Beat hourly | Find deliverables where: `deliverables.status='submitted'` AND `submitted_at < now() - 14d` AND parent milestone status NOT IN (`disputed`, `revision_requested`, `auto_approved`, `approved`) AND no `disputes` row exists with `status IN ('open','under_review')` for that milestone. Then: mark deliverable + milestone `auto_approved`, call `EscrowService.release`, emit workspace system message, notify both parties. Idempotent — second pass over the same row no-ops. |
| `escalate_disputes` | Beat hourly | `disputes.status='open' AND created_at < now() - 7d` → `status='under_review'`, `escalated_at=now()`, notify admins. |

## Security

- Every endpoint declares its `require_role(...)` dependency before the handler runs.
- `require_project_member` and `require_project_owner` are reusable deps in `projects/dependencies.py`. They load the project once and attach it to the request scope.
- KYC required on Project create (matches Phase 3 escrow funding KYC gate), Proposal submit (Contributor cannot bid until KYC-verified — protects Operator from locking escrow against a Contributor who can never withdraw), and Milestone fund.
- Admin Dispute resolve requires admin role + 2FA + `reason` (mirrors `release_escrow_override` pattern).
- WS auth happens via the first-message handshake — no token in URL. Channel `subscribe` runs a membership check against the database; gateway never trusts the client-supplied channel name alone.
- Workspace uploads: server returns a **presigned POST** (policy pins `key`, `content-type`, `content-length-range`) with 5-minute expiry. Message create endpoint validates each `file_keys` entry against an unconsumed `workspace_upload_sessions` row owned by the requester for this project. Message persists with `scan_status='pending_scan'` and becomes visible only after `scan_workspace_upload` flips it to `visible`.
- Every multi-table write inside `async with db.begin()`. `with_for_update()` on Milestone, Escrow, Dispute, and the `accepted_proposal` row whenever they participate in a write.
- Audit log on: `project_created`, `project_extended`, `project_closed`, `proposal_submitted`, `proposal_accepted`, `proposal_rejected`, `proposal_withdrawn`, `proposal_expired`, `amendment_proposed`, `amendment_accepted`, `amendment_rejected`, `amendment_withdrawn`, `amendment_expired`, `milestone_created`, `milestone_updated`, `milestone_funded`, `milestone_approved`, `milestone_auto_approved`, `deliverable_submitted`, `deliverable_approved`, `deliverable_auto_approved`, `deliverable_revision_requested`, `dispute_raised`, `dispute_escalated`, `dispute_resolved`, `escrow_split_resolved`, `framework_published_from_project`, `workspace_file_quarantined`.

## Slice plan (12 slices)

Each slice ships with passing tests, lint, type-check, migration up/down. One commit per slice. Human reviews + commits before next slice.

| # | Slice | Output |
|---|---|---|
| 1 | Schema foundation | Migration, enums, 9 tables (incl. `workspace_upload_sessions`) + extensions, ORM models, empty router/service placeholders, `test_phase4a_schema` migration smoke test. |
| 2 | Pub/sub primitives | `app/modules/realtime/pubsub.py` with `publish_to_channel(channel, event_type, payload)` + `subscribe_channel(channel, handler)`, channel resolver in `channels.py` with membership-check protocol (callable injected later). Unit tests + integration test against real Redis. **No WS endpoint yet** — publishes are safe no-ops when nothing is subscribed. |
| 3 | Notifications module | Table (incl. `dedupe_key`), list/read/read-all endpoints, `dispatch_project_notification(user_id, type, payload, dedupe_key=None)` Celery task. Task inserts via `ON CONFLICT DO NOTHING`, publishes `user:{id}` event through pub/sub (still no WS endpoint — Redis discards), dispatches email task. |
| 4 | Project CRUD + proposal flow | Create/list/get/patch project, submit (KYC-gated) / withdraw / accept proposal, accept transitions project `open → assigned`. Concurrent Project cap enforced. `expire_open_proposals` + `close_expired_projects` Beat tasks. |
| 5 | Amendment flow | `proposal_amendments` endpoints, both-party accept/reject, withdraw, 7d Beat expiry. On accept that mutates `proposal.budget`, flip `projects.milestone_plan_status` back to `draft`. Workspace system messages emitted on every state change. |
| 6 | Milestone CRUD + finalize | Create/edit/delete milestones while `projects.milestone_plan_status='draft'`. `POST /v1/projects/{id}/milestones/finalize` validates `SUM(budget) == accepted_proposal.budget`, flips plan to `finalized`. Milestone insert path is permissive on sum; finalize endpoint is the strict gate. List endpoint. |
| 7 | Milestone funding + Escrow integration | Fund endpoint validates `milestone_plan_status='finalized'`. Creates a `transactions` row with `type='milestone'`, `status='pending'`, `ref_type='project_milestone'`, `ref_id=milestone_id`, `payer_id=operator_id`, `payee_id=contributor_id`. Creates Stripe PaymentIntent with `metadata={kind:"escrow", transaction_id:<uuid>, project_id:<uuid>, milestone_id:<uuid>, release_conditions:{kind:"project_milestone", milestone_id, project_id, approver_user_id:<operator_id>}}`. Returns `{transaction_id, client_secret}`. Milestone status stays `pending`. **Phase 3 webhook handler** is the sole writer that flips `pending → funded` after `EscrowService.hold` succeeds; extend the existing escrow branch to (a) flip `milestones.status = 'funded'`, set `funded_at = now()`, (b) flip `projects.status='in_progress'` if this is the first funded milestone in the project, (c) emit `milestone_funded` workspace system message. All inside the webhook's own DB txn. Endpoint never writes milestone status. |
| 8 | Deliverable submit / approve / revise + auto-approve + project close | Endpoints. Approve calls `EscrowService.release`. Revision-request loops back. `auto_approve_deliverables` Beat task with exclusions for disputed / revision_requested / already-approved milestones. Workspace system messages. When the last milestone reaches `(approved, auto_approved)`, service flips project `in_progress → delivered` and sets `delivered_at=now()`. `POST /v1/projects/{id}/close` Operator manual close endpoint (only valid while `delivered`, sets `closed_at` and `status='closed'`). `auto_close_delivered_projects` Beat task closes projects 7d after `delivered_at` when no open/under_review disputes exist. |
| 9 | Workspace messages + WS gateway | Now that projects + members exist, ship the full `/v1/ws` endpoint: first-message handshake, subscribe/unsubscribe with **real** membership check (operator or accepted contributor) wired into channel resolver from slice 2. List + post message REST. Presigned POST upload endpoint creates `workspace_upload_sessions` rows. Message insert validates `file_keys` against unconsumed sessions and sets `scan_status='pending_scan'`. `scan_workspace_upload` Celery flips to `visible` (publish via pub/sub) or `quarantined`. |
| 10 | Disputes + Admin resolution + `EscrowService.split` | Raise/list/get dispute endpoints. `escalate_disputes` Beat task. `EscrowService.split` method + unit tests covering Decimal sum, double-split block, Stripe idempotency, release credits Contributor balance only (no Stripe Transfer), refund hits Stripe. Admin resolve endpoint 2FA-gated. Workspace system message. |
| 11 | FR-PROJ-013 publish-as-Framework | `frameworks.source_project_id` FK migration. Service helper builds prefill payload from approved deliverables. Frontend "Publish as Framework" button on workspace deliverable card routes to existing `/dashboard/frameworks/new` with query params. |
| 12 | OpenAPI sync + FE Projects shell + E2E | Regenerate `frontend/src/lib/generated/`. Sidebar adds "Projects". Operator pages: post project, my projects list, project detail with proposals + workspace + milestones. Contributor pages: open projects feed, my proposals, workspace. WS client hook with auto-reconnect + channel manager. E2E `project.spec.ts` covering the full create → proposal → accept → milestone plan + finalize → fund → deliver → approve → escrow release flow against Stripe test mode. |

## Risk flags

- **WS gateway scaling**: a single FastAPI process holds all sockets. Render Background Worker tier supports this for Phase 1 traffic. Phase 2 scale needs sticky sessions or a dedicated gateway service.
- **Redis pub/sub durability**: Redis pub/sub does NOT persist. A subscriber that disconnects mid-event misses the message. Acceptable here because the underlying state lives in Postgres — on reconnect the client refetches via REST. Notifications inserted into Postgres first guarantee no loss.
- **Workspace upload race**: a malicious party could try to claim `file_keys` they didn't upload. Mitigation: presigned POST URLs are bound to a server-issued `workspace_upload_sessions` row recording `(user_id, project_id, s3_key, content_type, size_limit, expires_at)`. Message create endpoint validates every `file_keys` entry against an unconsumed session for the same user + project.
- **Stripe network call inside split txn**: `EscrowService.split` holds escrow row lock during Stripe refund call. Configure Stripe SDK timeout to 10s. Same tradeoff as Phase 3 refund flow.
- **14d auto-approve and amendments**: if an amendment is pending when auto-approve fires, the milestone is approved at current budget. Amendment expiry independent. Document this in the workspace system message to avoid surprise.
- **Concurrent Project cap = 5**: hard cap with no override path. Admin override deferred to Phase 5 if needed.

## Verification (end-to-end after Slice 12)

1. `docker compose up`.
2. Backend: `uv run pytest --cov=app/modules/projects --cov=app/modules/workspace --cov=app/modules/realtime --cov=app/modules/notifications --cov=app/workers/tasks/projects_beat` ≥ 80% line coverage.
3. Frontend: `pnpm test` + `pnpm exec playwright test tests/e2e/project.spec.ts`.
4. Manual smoke (Stripe test mode):
   - Operator posts a project. Contributor submits a proposal. Operator accepts. Project status `assigned`.
   - Contributor defines three milestones with sum equal to proposal budget and calls `POST .../milestones/finalize`. Operator funds milestone 1 via the fund endpoint (PaymentIntent returned). Stripe webhook fires `EscrowService.hold` and flips milestone `pending → funded` and project `assigned → in_progress`.
   - Contributor uploads a deliverable file in the workspace. ClamAV scan clears. File becomes visible.
   - Contributor submits deliverable. Operator clicks approve. `EscrowService.release` runs. Notifications fire on both sides.
   - Repeat for milestone 2. Operator goes silent on submitted deliverable — fast-forward server clock 14d; `auto_approve_deliverables` Beat task fires; deliverable marked `auto_approved`; escrow released; audit + workspace message recorded.
   - Either party raises a dispute on milestone 3. Admin resolves with a split (60/40). Two transactions written, one refund processed via Stripe. Audit `escrow_split_resolved` captured.
   - Contributor opens an approved deliverable and clicks "Publish as Framework". Pre-filled framework-create form opens; submit. New framework row has `source_project_id` populated.
   - Contributor proposes an amendment to milestone 4's budget. Operator accepts. Proposal budget mutates. Workspace system message recorded.

## Out of scope (Phase 4b or later)

- **Attestation module — Phase 4b**, separate spec at `docs/superpowers/specs/<date>-phase-4b-attestation-design.md` (not yet written). Phase 4 ships when 4a and 4b both ship. 4b reuses the realtime gateway, pub/sub primitives, notifications module, `workspace_upload_sessions` pattern, and `EscrowService` (incl. `split`) delivered here.
- Multi-collaborator workspaces (additional Operator team members).
- Workspace voice/video.
- File preview / inline rendering in workspace.
- Project templates / reusable proposal drafts.
- Multi-currency (matches Phase 3 USD-only lock).
- Admin override of the 5-project concurrency cap.
- Reputation scoring — Phase 4a emits events; scoring math ships in Phase 5.
- Watchlists table (unrelated Operator-saved-framework feature).
