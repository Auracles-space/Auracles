# Phase 4b — Attestation (design spec)

## Context

Phase 4a (Projects) shipped and its review fixes are verified. Phase 4 is
complete only when Attestation (4b) also ships. Attestation is the platform's
trust layer: independent Attestors verify Frameworks, Contributor profiles,
Operator organizations, and Credentials; formal signed reports become public
trust signals and (later) feed Reputation. Maps to FRD §7 (FR-ATT-001..011,
BR-ATT-001..005) and the attestation escrow flows in §8 (FR-FIN-006, FR-FIN-013;
`escrows.ref_type="attestation"`, `transactions.type="attestation_fee"`).

4b reuses infrastructure already built: `EscrowService` (hold/release/refund/
split), the notifications module + `dispatch_project_notification`, realtime
pub/sub, the presigned POST upload-session pattern from workspaces, audit log,
Celery Beat scaffolding, the WeasyPrint worker (invoice PDFs), and the admin 2FA
+ config pattern. The existing `workspace_upload_sessions` table itself is
project-bound and must **not** be reused for attestations/credentials; 4b creates
attestation-specific upload sessions with the same security properties. The
Attestor role + admin-approval gating (`UserRole.approved_at`, audit
`attestor_approved`) already exist but carry no application data.

## Locked decisions

| # | Decision | Value |
|---|---|---|
| 1 | Matching | Cohort of N (default 3, configurable). Offer to a cohort simultaneously; first-accept wins via request row-lock; 48h timeout/all-decline → Beat advances to next cohort; cohorts exhausted → `needs_admin` (Admin manual-assign or refund). |
| 2 | Escrow release timing | Report submission publishes but escrow stays **held**. Releases on requestor **accept-report** (early) OR **14d** auto (Beat). Dispute in-window freezes escrow → Admin resolves release/refund/split. |
| 3 | Config home | Fees (per target_type), cohort size, completion SLAs (per target_type), accept-window hours, dispute-window days all live in `platform_config`, tuned via existing `PATCH /v1/admin/config` (2FA + audit). **No env vars.** |
| 4 | Attestor onboarding | `attestor_applications` (full payload, status, feedback — one row per submission → re-apply history) → on approve copy specializations/jurisdictions into `attestor_profiles` (active, matcher-queried) + flip `UserRole.approved_at`. |
| 5 | Targets | All 4: framework, contributor, operator, + new user-owned `credentials` entity (CRUD). |
| 6 | Completion SLA | Per target_type, configurable. Miss → Beat revokes assignment + returns request to matching; escrow stays held. |
| 7 | Report | Structured DB fields (summary, scope, evidence_references, outcome) + WeasyPrint-generated PDF `report_url`. Evidence-file uploads private to requestor+assigned attestor+admin; public profile renders the report + PDF only as `pending_acceptance` until release/closure. |
| 8 | Disputes | New `attestation_disputes` table (not the project-coupled 4a table). Admin resolve reuses `EscrowService.release/refund/split`. |
| 9 | Self-attest (BR-ATT-001) | Ownership-only: attestor ≠ framework.contributor / target user / credential owner (cohort exclusion + request rejection). True "affiliated org" detection deferred (no org-membership model) — flagged gap. |
| 10 | Reputation (BR-ATT-005) | Emit/audit attestation-outcome events now; scoring math stays Phase 5 (matches 4a). |
| 11 | Currency | USD only (matches Phase 3/4a lock). |
| 12 | API namespace | Use `/v1/attestations`, `/v1/attestor`, and `/v1/credentials`; this supersedes the older singular `/v1/attestation` route sketch in the TDD. |
| 13 | Matching inputs | Requestor chooses `requested_specializations[]` and `requested_jurisdictions[]` at request time, defaulted from target metadata when available. Matching uses those stored request fields, not live target metadata, so cohort decisions are reproducible. |

## Money path (critical — same class as the 4a milestone bug)

- Request → `transactions(type=attestation_fee, status=pending, payer=requestor,
  payee=NULL, ref_type=attestation, ref_id=attestation_id)` + Stripe
  PaymentIntent (`metadata.kind=escrow`, `release_conditions.kind=attestation`).
  **Payee is NULL at funding** — the Attestor is unknown until accept.
- Webhook (extend `_handle_escrow_succeeded` for `ref_type="attestation"`):
  `EscrowService.hold` → escrow `held`, txn `completed`, attestation
  `pending_fee → matching`; kick off cohort offer after Slice 5 exists. During
  Slice 4, it is acceptable to stop at `matching` and audit that matching is
  pending.
- Webhook failure/cancel path: extend the escrow payment failure handler for
  `ref_type="attestation"` so a failed/cancelled PaymentIntent marks the
  attestation funding transaction `failed`, transitions the attestation to
  `cancelled`, audits `attestation_fee_failed`, and notifies the requestor. Do
  not route attestation funding failures through the purchase-only failure path.
- **On accept: stamp `funding_txn.payee_id = attestor_id`.** This single step lets
  `EscrowService.release/refund/split` and the earnings calc work unchanged.
- Release (accept-report or 14d): `EscrowService.release` flips escrow
  `released`; the funding txn (payee=attestor, completed) becomes payable.
- Refund (dispute): Stripe refund + `EscrowService.refund` (funding txn →
  refunded, attestor not credited). Split: `EscrowService.split` (writes
  release txn at release_amount to attestor + refund txn; Stripe refund portion).
- **Earnings extension** (`financials/service.py:_sum_transactions`): add an OR-arm
  `type=='attestation_fee' & ref_type=='attestation' & <released escrow exists>`,
  alongside the existing milestone arm. Without it, released attestation fees are
  stranded (the exact 4a defect). Commission applied at payout (BR-FIN-001).

## Schema (new tables)

- **`attestor_applications`** — id, user_id FK, status `attestor_application_status`
  (pending|approved|rejected|withdrawn), specializations TEXT[], jurisdictions
  TEXT[], credentials_summary TEXT, sample_work JSONB, professional_references TEXT,
  admin_feedback TEXT NULL, reviewed_by FK NULL, reviewed_at NULL, created_at.
  Partial UNIQUE (user_id) WHERE status='pending' (one open application).
- **`attestor_profiles`** — id, user_id FK UNIQUE, specializations TEXT[],
  jurisdictions TEXT[], active BOOL, approved_at, created/updated_at. GIN index on
  specializations + jurisdictions for matching.
- **`credentials`** — id, user_id FK, title, issuer, issued_date, expires_date NULL,
  evidence_file_keys TEXT[], created_at, updated_at. INDEX (user_id).
- **`attestations`** — id, target_type `attestation_target_enum`
  (framework|contributor|operator|credential), target_id UUID, requestor_id FK,
  attestor_id FK NULL, status `attestation_status_enum`, outcome
  `attestation_outcome_enum` NULL (approved|conditional|rejected),
  requested_specializations TEXT[], requested_jurisdictions TEXT[], summary TEXT
  NULL, scope TEXT NULL, evidence_references JSONB NULL, report_key TEXT NULL,
  escrow_id FK NULL, fee_amount NUMERIC(12,2), currency CHECK='USD', accepted_at
  NULL, completion_due_at NULL, issued_at NULL, dispute_window_ends_at NULL,
  closed_at NULL, created_at, updated_at. INDEX (target_type, target_id),
  (attestor_id, status), (status, dispute_window_ends_at),
  (status, completion_due_at). GIN index requested_specializations +
  requested_jurisdictions if query plans need it after Slice 5 tests.
  `attestation_status_enum`: pending_fee, matching, offered, accepted,
  report_submitted, released, disputed, resolved, needs_admin, refunded, closed,
  cancelled.
- **`attestation_offers`** — id, attestation_id FK, attestor_id FK, cohort_index
  INT, status `attestation_offer_status` (offered|accepted|declined|expired|
  superseded), offered_at, responded_at NULL, expires_at. Per-attestor cohort
  audit trail. UNIQUE (attestation_id, attestor_id).
  INDEX (status, expires_at) for Beat.
- **`attestation_disputes`** — id, attestation_id FK, raised_by FK, reason,
  status (open|under_review|resolved), resolution_type (release|refund|split)
  NULL, release_amount NULL, refund_amount NULL, admin_id NULL, resolution_notes
  NULL, escalated_at NULL, resolved_at NULL, created_at. CHECK split⇒both amounts.
  INDEX (status, created_at).
- **`attestation_upload_sessions`** — id, attestation_id FK NULL, credential_id
  FK NULL, user_id FK, purpose `attestation_upload_purpose`
  (report_evidence|credential_evidence), s3_key TEXT UNIQUE, content_type,
  size_limit, consumed_at NULL, expires_at, created_at. CHECK exactly one of
  attestation_id/credential_id is set. INDEX (attestation_id, user_id,
  consumed_at), (credential_id, user_id, consumed_at), (expires_at). Presigned
  POST must enforce `content-length-range`.

**`platform_config` new rows:** `attestation_fee_{framework,contributor,operator,
credential}`, `attestation_cohort_size` (3), `attestation_completion_sla_days_*`
(per type), `attestation_offer_accept_hours` (48), `attestation_dispute_window_days`
(14). All admin-tunable; `PATCH /v1/admin/config` allowed-keys + range validation
extended.

Default/range lock:

| Key pattern | Default | Valid range |
|---|---:|---:|
| `attestation_fee_framework` | `250.00` | `25.00`-`100000.00` |
| `attestation_fee_contributor` | `300.00` | `25.00`-`100000.00` |
| `attestation_fee_operator` | `300.00` | `25.00`-`100000.00` |
| `attestation_fee_credential` | `100.00` | `10.00`-`100000.00` |
| `attestation_cohort_size` | `3` | `1`-`10` |
| `attestation_completion_sla_days_{framework,contributor,operator,credential}` | `7` | `1`-`30` |
| `attestation_offer_accept_hours` | `48` | `1`-`168` |
| `attestation_dispute_window_days` | `14` | `1`-`30` |

## State machine (attestation.status)

```
pending_fee → matching → offered → accepted → report_submitted → released → closed
offered  ─(48h / all decline)→ matching(next cohort)
matching ─(cohorts exhausted)→ needs_admin → (admin assign → accepted | refund → refunded → closed)
accepted ─(completion SLA miss)→ matching(re-offer)
report_submitted ─(accept-report | 14d)→ released → closed
report_submitted ─(dispute in 14d)→ disputed → resolved(release|refund|split) → closed
```

`closed` is a terminal bookkeeping state, not a second business approval. Set it
in the same transaction after release/refund/split has completed and all audit
rows are written; `closed_at` records that archive boundary.

## Module layout

```
backend/app/modules/attestation/
├── router.py            # /v1/attestations/*, /v1/attestor/*, /v1/credentials/*
├── service.py           # request + lifecycle orchestration
├── matching_service.py  # cohort build + offer + accept/decline + reassign
├── application_service.py # attestor apply/withdraw + admin review → profile
├── dispute_service.py   # attestation dispute + admin resolve (reuse EscrowService)
├── report.py            # structured report persist + PDF render dispatch
├── models.py            # 7 tables
├── schemas.py
└── dependencies.py      # require_attestor (approved), require_requestor_roles
backend/app/workers/tasks/
├── attestation_beat.py  # expire_offers, revoke_overdue, auto_release, escalate_disputes
└── attestation_pdf.py   # WeasyPrint report render (reuse invoice pipeline)
```

## API surface

| Verb | Path | Auth |
|---|---|---|
| POST | /v1/attestor/applications | any auth user |
| GET | /v1/attestor/applications/mine | self |
| PATCH | /v1/attestor/applications/{id}/withdraw | author |
| GET | /v1/admin/attestor/applications | admin |
| POST | /v1/admin/attestor/applications/{id}/review | admin + 2FA |
| GET/POST | /v1/credentials, /v1/credentials/{id} (PATCH/DELETE) | self |
| POST | /v1/attestations | contributor or operator (+ ownership/self-attest checks) |
| GET | /v1/attestations?role=requestor\|attestor | self |
| GET | /v1/attestations/{id} | requestor, assigned/cohort attestor, or admin |
| POST | /v1/attestations/{id}/accept · /decline | cohort attestor |
| POST | /v1/attestations/{id}/report | assigned attestor |
| POST | /v1/attestations/{id}/uploads | assigned attestor (evidence presigned POST via `attestation_upload_sessions`) |
| POST | /v1/attestations/{id}/accept-report | requestor (early release) |
| POST | /v1/attestations/{id}/disputes | requestor (≤14d) |
| GET | /v1/attestor/assignments | attestor (offered + accepted) |
| POST | /v1/admin/attestations/{id}/assign · /refund | admin + 2FA (needs_admin) |
| POST | /v1/admin/attestation-disputes/{id}/resolve | admin + 2FA |
| GET (ext) | Explore framework card/detail + contributor profile | public — attestation badges (FR-ATT-011) |
| WS/Beat | reuse | offer/status push via notifications + pub/sub |

## Security

- RBAC via deps: `require_role("attestor")` + approved-profile check on accept/
  report; `require_role("contributor"|"operator")` on request; admin + 2FA on
  review / resolve / manual assign / refund.
- Self-attest block (BR-ATT-001): exclude requestor-owned targets from cohort +
  reject at request. Ownership resolved per target_type (framework.contributor_id,
  target user id, credential.user_id; operator = target user).
- Escrow funded before assignment (BR-ATT-002): request → pending_fee; matching
  only starts after webhook confirms hold.
- Every multi-table write in `async with db.begin()`; `with_for_update()` on the
  attestation row (accept race), escrow, dispute.
- Evidence files private (presigned GET only to requestor, assigned attestor, and
  admin). Report PDF is public through Explore/profile only after
  `report_submitted`; UI must label it `pending_acceptance` until the attestation
  closes. No secrets/PII in logs.
- Audit: attestor_application_submitted/withdrawn/approved/rejected,
  attestation_requested, attestation_fee_funded, attestation_offered,
  attestation_accepted/declined/offer_expired, attestation_reassigned,
  attestation_needs_admin, attestation_report_submitted, attestation_published,
  attestation_released, attestation_disputed, attestation_dispute_resolved,
  attestation_refunded, credential_created/deleted.

## Celery Beat tasks

| Task | Cadence | Action |
|---|---|---|
| `expire_attestation_offers` | hourly | Offered cohort past accept-window with no accept → mark offers expired, advance to next cohort or `needs_admin`; notify. |
| `revoke_overdue_attestations` | hourly | Accepted past `completion_due_at` → revoke assignment (offer failed, audit), return to matching (re-offer). Escrow held. |
| `auto_release_attestations` | hourly | `report_submitted` past `dispute_window_ends_at` with no open dispute → `EscrowService.release` + status `released` then `closed`; notify. Idempotent. |
| `escalate_attestation_disputes` | hourly | Open dispute aged → under_review, escalated_at, notify admins. |

## Slice plan (~12)

1. Schema foundation — 7 tables + enums + platform_config seeds/range validation + ORM + placeholders + migration up/down smoke test.
2. Attestor application + admin review — apply/withdraw/list/mine, admin review (approve→copy into `attestor_profiles` + `UserRole.approved_at`; reject+feedback). Audit.
3. Credentials CRUD — user-owned create/list/update/delete + credential evidence upload sessions.
4. Attestation request + fee escrow funding — request (ownership/self-attest/fee lookup, stored matching inputs), pending_fee + Stripe PI; extend webhook success for `ref_type="attestation"` → hold → matching, and extend failure/cancel path → failed transaction + cancelled attestation.
5. Matching + cohort offers — cohort build from stored requested_specializations∩requested_jurisdictions, exclude owner, offer, **row-lock accept + stamp funding_txn.payee**, decline, `expire_attestation_offers` Beat, needs_admin.
6. Completion SLA + `revoke_overdue_attestations` Beat.
7. Report submission + PDF + publish — structured fields, evidence upload sessions (scan), WeasyPrint render task, status report_submitted + dispute_window_ends_at, public report_key labelled pending acceptance.
8. Release flow — requestor accept-report + `auto_release_attestations` Beat + status `released→closed` + **earnings `_sum_transactions` attestation_fee arm**. Tests assert attestor balance credited.
9. Attestation disputes + admin resolve — raise (≤14d), `escalate_attestation_disputes` Beat, admin resolve release/refund/split then close (reuse EscrowService), admin manual assign/refund for needs_admin. 2FA-gated.
10. Reputation events + notifications wiring — emit attestation-outcome events/audit (scoring deferred Phase 5); wire in-app + email + realtime for all attestation events.
11. Explore badges (FR-ATT-011) — attestation badge + outcome on framework cards/detail + contributor profile; filter by attestation status (FR-EXP-004).
12. OpenAPI sync + FE + E2E — attestor dashboard (applications, assignments, accept/decline, report form), requestor (request, view report, dispute, accept-report), credentials UI, admin (review, resolve, manual assign), badges. `attestation.spec.ts` E2E full flow against Stripe test mode.

## Risk flags

- **Earnings must count attestation_fee** (slice 8) — identical to the fixed 4a milestone-stranding bug. Test the attestor-paid path explicitly.
- **Funding-txn payee NULL until accept** — stamp payee on accept; without it release/split credit no one.
- **Cohort accept race** — request row-lock; late accepts → 409.
- **Affiliation gap** (BR-ATT-001) — ownership-only; org-affiliation deferred.
- **needs_admin path** — must support both manual assign and full refund.
- **Multiple attestations per target** (BR-ATT-004) — allowed; block only a duplicate *in-flight* request by the same requestor on the same target.
- **Payment failure path** — attestation PaymentIntent failures must not be
  handled as failed purchases.
- **Upload-session ownership** — do not reuse project-bound
  `workspace_upload_sessions`; create attestation-specific sessions.
- **Badge semantics** — public report display before escrow release must be
  labelled pending acceptance to avoid overstating trust.
- **PDF worker load** — reuse invoice WeasyPrint stage; no new image deps.

## Verification (after slice 12)

1. `docker compose up`.
2. Backend: `uv run pytest --cov=app/modules/attestation --cov=app/workers/tasks/attestation_beat` ≥ 80%.
3. Frontend: `pnpm test` + `pnpm exec playwright test tests/e2e/attestation.spec.ts`.
4. Manual smoke (Stripe test mode): apply→admin approve→requestor requests framework attestation→fund fee→cohort offered→attestor accepts→submits report (PDF generated, published with pending-acceptance label, badge shows)→requestor accept-report→escrow releases→attestation closes→attestor withdraws via payout. Then: second attestation→report→requestor disputes→admin splits 60/40→ledger + Stripe refund verified. Then: offer 48h timeout→reassign→cohort exhausted→admin refund.

## Out of scope (later phases)

- Partner API attestation endpoints (FR-DEV-014/016) — Phase 5.
- Reputation scoring math — Phase 5 (events emitted here).
- True org-affiliation conflict detection (needs org-membership model).
- Multi-currency.
