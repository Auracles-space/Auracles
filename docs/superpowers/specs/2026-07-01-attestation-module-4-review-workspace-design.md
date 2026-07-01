# Attestation Module 4 — Review Workspace · Design Spec

**Date:** 2026-07-01
**Status:** Approved for planning
**Source of truth:** `docs/Auracles Attestation — Product Development Workflow.md` §4.1–4.7
**Predecessors:** Module 1 (Onboarding), Module 2a/2b (Request + Access Package), Module 3 (AMM Matching)
**Downstream:** Module 5 (Delivery, Acceptance & Dispute) — already partly built (dispute window, auto-accept, disputes)

---

## 1. Purpose

The Review Workspace is the assigned Attestor's working environment from assignment to report
submission. It turns the current one-shot report POST into a persistent, structured review that
produces a rubric-scored, annotation-backed, multi-section report gated by an automated quality
check.

This module **extends the existing report flow in place** — it does not rebuild it. The state
machine, escrow, dispute window, Celery PDF renderer, and Module 5 delivery already work and are
integration-tested; Module 4 layers rubric scoring, clause-level annotations, clarification
requests with SLA pause, and a submission quality gate onto that spine.

Maps to: FR-ATT-* (Review Workspace). BR-ATT-* enforced at the service layer.

---

## 2. Scope

### In scope (backend)

- New working status `in_review` between `accepted` and `report_submitted`.
- Rubric definitions (seeded, per review_type, all four types) + per-attestation rubric scores.
- Free-anchor clause-level annotations.
- Clarification requests with SLA pause (extend-deadline model) + expiry beat.
- Submission quality gate (inline, itemized 422).
- Grace-then-revoke SLA policy reconciling §4.7 with the Module 3 revoke-beat.
- Report generation grown to §4.6's eight sections, sourced from rubric + annotations.
- Late-submission flag (per-attestation truth + profile counter).

### Out of scope

- Frontend split-screen workspace UI (separate later phase).
- Left-panel framework content viewer delivery — **already built** in Module 2b
  (`access_service.request_artifact_access`, entitlement-checked presigned URL +
  `AttestationArtifactAccess` audit). Module 4 reuses it; annotations reference `artifact_id`.
- Admin CRUD for rubric templates (YAGNI — seed via migration, change via migration).
- Coordinate/bounding-box PDF annotation overlays.
- ML/toxicity prohibited-content scanning (MVP = contact-leak regex only).
- Module 5 changes (delivery, acceptance rating, dispute) — untouched; report_submitted still
  the trigger it already consumes.

---

## 3. Data model

### 3.1 Status machine change

Add enum value `in_review` to `attestation_status_enum` via `ALTER TYPE ... ADD VALUE`
(non-transactional; own migration step, mirrors the Module 1 pattern).

```
accepted --POST /start-review--> in_review --submit (gate pass)--> report_submitted
```

**Integration consequences (must be handled, not optional):**

- `matching_service.revoke_overdue_attestations` currently selects `status == 'accepted'`. It must
  select `status IN ('accepted', 'in_review')` or overdue in-review work escapes SLA revocation.
- `report.submit_report` precondition `allowed_statuses={'accepted'}` becomes `{'in_review'}`
  (submit is only reachable after the workspace is opened).
- Any Module 2/3 test asserting the post-accept status stays `accepted` up to submission is
  reviewed; acceptance itself still lands on `accepted` (Q7 decision A — explicit start-review
  transition, acceptance unchanged).

### 3.2 New Attestation columns

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `review_started_at` | `timestamptz` | yes | set on `POST /start-review` |
| `rubric_version` | `integer` | yes | snapshot of the rubric version used, stamped at submit |
| `conditions` | `text` | yes | mandatory iff `outcome = 'conditional'` |
| `submitted_late` | `boolean` | no, default false | durable report/audit truth |

Existing `summary`, `scope`, `outcome`, `evidence_references`, `report_key`, `issued_at`,
`dispute_window_ends_at`, `completion_due_at` are reused.

### 3.3 New AttestorProfile column

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `late_submission_count` | `integer` | no, default 0 | incremented on each late submit; match-time AMM signal (read by Module 3 scoring later) |

### 3.4 `attestation_rubric_dimensions` (seeded, migration-only)

Durable reference so a published report reproduces the exact rubric it used, forever.

| Column | Type | Notes |
|--------|------|-------|
| `id` | uuid PK | |
| `review_type` | `attestation_review_type_enum` | quality/compliance/expert/provenance |
| `key` | text | stable machine key, unique within (review_type, version) |
| `label` | text | display name |
| `weight` | `numeric(4,3)` | per review_type weights sum to 1.000 |
| `display_order` | integer | |
| `version` | integer | default 1 |
| `methodology_text` | text | canned §4.6(c) methodology, same for every dimension row of a type; stored once per type (see 3.4.1) |

Unique constraint `(review_type, version, key)`. Index `(review_type, version, display_order)`.

**3.4.1 Methodology storage.** Methodology is per review_type, not per dimension. Store it in a
small companion seeded table `attestation_rubric_methodology (review_type, version, text)` rather
than duplicating on every dimension row. (Keeps 3.4 clean.)

### 3.4.2 Seeded rubric content (all four types, version 1)

Score scale 1–5 on every dimension. Weighted overall = `Σ(weight × score)` ∈ [1.00, 5.00],
stored `numeric(3,2)`.

**Quality** (8 dims, §4.2 verbatim set):

| key | label | weight |
|-----|-------|--------|
| completeness | Completeness | 0.18 |
| implementability | Implementability | 0.18 |
| accuracy | Accuracy | 0.18 |
| clarity | Clarity | 0.12 |
| version_currency | Version Currency | 0.10 |
| appropriate_scope | Appropriate Scope | 0.10 |
| risk_flags | Risk Flags | 0.08 |
| recommended_use_cases | Recommended Use Cases | 0.06 |

**Compliance** (6 dims):

| key | label | weight |
|-----|-------|--------|
| regulatory_alignment | Regulatory Alignment | 0.25 |
| jurisdictional_coverage | Jurisdictional Coverage | 0.20 |
| control_adequacy | Control Adequacy | 0.20 |
| evidence_traceability | Evidence Traceability | 0.15 |
| gap_identification | Gap Identification | 0.12 |
| update_currency | Update Currency | 0.08 |

**Expert** (6 dims):

| key | label | weight |
|-----|-------|--------|
| technical_soundness | Technical Soundness | 0.25 |
| methodological_rigor | Methodological Rigor | 0.20 |
| domain_accuracy | Domain Accuracy | 0.20 |
| practical_applicability | Practical Applicability | 0.15 |
| innovation_value | Innovation Value | 0.10 |
| limitations_disclosure | Limitations Disclosure | 0.10 |

**Provenance** (5 dims):

| key | label | weight |
|-----|-------|--------|
| authorship_verification | Authorship Verification | 0.30 |
| source_integrity | Source Integrity | 0.25 |
| originality | Originality | 0.20 |
| chain_of_custody | Chain of Custody | 0.15 |
| attribution_completeness | Attribution Completeness | 0.10 |

Each type's weights sum to exactly 1.000 (asserted in a unit test).

### 3.5 `attestation_rubric_scores`

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `id` | uuid PK | | |
| `attestation_id` | uuid FK → attestations (CASCADE) | no | |
| `dimension_id` | uuid FK → attestation_rubric_dimensions | no | |
| `score` | smallint | yes | 1–5, CHECK; nullable in draft |
| `comment` | text | yes | nullable in draft; mandatory at gate |
| `created_at` / `updated_at` | timestamptz | | fine-grained forensic timestamps |

Unique `(attestation_id, dimension_id)`. Score CHECK `score BETWEEN 1 AND 5`.

### 3.6 `attestation_annotations`

Free-anchor (Q3 decision A) — no clause-parsing pipeline exists; frameworks are file artifacts.

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `id` | uuid PK | | |
| `attestation_id` | uuid FK → attestations (CASCADE) | no | |
| `artifact_id` | uuid FK → artifacts | yes | which file, if any |
| `location_label` | text | no | attestor-typed, e.g. "Section 3.2, para 2" |
| `quoted_excerpt` | text | yes | optional quoted snippet |
| `annotation_type` | new enum | no | endorsement / concern / jurisdictional_caveat / revision_recommended |
| `comment` | text | no | |
| `created_at` / `updated_at` | timestamptz | | |

New enum `attestation_annotation_type_enum`. Index `(attestation_id)`.

### 3.7 `attestation_clarifications`

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `id` | uuid PK | | |
| `attestation_id` | uuid FK → attestations (CASCADE) | no | |
| `question` | text | no | attestor → requestor |
| `response` | text | yes | requestor → attestor |
| `sent_at` | timestamptz | no | |
| `response_due_at` | timestamptz | no | sent_at + 48h (config) |
| `responded_at` | timestamptz | yes | set on response or expiry-close |
| `status` | new enum `attestation_clarification_status_enum` | no | open / answered / expired |

Max 2 rows per attestation (enforced by count in service → 422 on third). Index
`(status, response_due_at)` for the expiry beat.

---

## 4. Behaviour

### 4.1 Start review — `POST /v1/attestations/{id}/start-review`

Assigned-Attestor-only. Preconditions: `status == 'accepted'`, requesting user == `attestor_id`
(else 404), content-ack present, CoI still valid. Effect: `status → in_review`,
`review_started_at = now`, audit `attestation_review_started`. Idempotent: if already
`in_review`, return current workspace (200), no re-stamp.

### 4.2 Rubric scoring — `PUT /v1/attestations/{id}/rubric/{dimension_key}`

Upsert `(attestation_id, dimension_id)` with `score` and/or `comment`. Partial allowed in draft.
Validates dimension_key belongs to the attestation's `review_type` current version. 404 on
non-assigned. No AuditLog row per edit (Q10 A) — `updated_at` carries forensics.

### 4.3 Annotations — `POST` / `PATCH` / `DELETE /v1/attestations/{id}/annotations[/{aid}]`

CRUD for the assigned Attestor during `in_review`. Free-anchor fields (3.6). Optional in general;
becomes mandatory (≥1) at the gate when outcome ∈ {conditional, rejected}.

### 4.4 Clarifications

- `POST /v1/attestations/{id}/clarifications` — Attestor sends a question. Rejects (422) if 2 already
  exist, or if an `open` clarification is already outstanding. Sets `response_due_at = now + 48h`
  (config `attestation_clarification_response_hours`). **SLA pause:** on send, no immediate deadline
  change is required because the pause is settled on resume (see below) — but to keep the revoke
  beat honest while a clarification is open, `completion_due_at` is extended by the full 48h window
  up front, then trimmed back on early response. (Deadline is only ever pushed out, never pulled in
  before a response arrives — so the revoke-beat cannot wrongly fire mid-clarification.)
- `POST /v1/attestations/{id}/clarifications/{cid}/respond` — **Requestor-only** (read/respond scope,
  not the Attestor). Sets `response`, `responded_at`, `status = answered`. Resume math:
  `completion_due_at -= (response_due_at - responded_at)` (return the unused pause remainder).
- Beat `expire_attestation_clarifications` (hourly): `open` past `response_due_at` → `status = expired`,
  `responded_at = now`. Deadline already carried the full 48h, so no further adjustment. Notifies both.
- **Submit is blocked (422) while any clarification is `open`.**
- Notifications both directions via `dispatch_project_notification`.

### 4.5 Overall determination

`outcome` ∈ {approved, conditional, rejected} (existing `attestation_outcome_enum`, values
approved/conditional/rejected). Set as part of the submit payload. `conditional` requires
non-empty `conditions`.

### 4.6 Submit — extend `report.submit_report`

Precondition status `in_review`. Runs the quality gate (4.7) inside the same transaction before
any state change; gate failure → `HTTPException(422)` with an itemized `detail` list, no mutation.

On pass, in one transaction:
- `status → report_submitted`, `outcome`, `summary`, `scope`, `conditions`, `evidence_references`,
  `report_key` (deterministic key, unchanged), `issued_at = now`, `dispute_window_ends_at`,
  `rubric_version` snapshot.
- Late handling (4.8): if `now > completion_due_at`, set `submitted_late = true`, increment
  `AttestorProfile.late_submission_count`, audit `attestation_late_submission`.
- Audit `attestation_report_submitted` (+ existing published/outcome audits).
- After commit: `render_attestation_report_pdf.delay(...)` + `notify_report_submitted`.

Submission is final (§4.7) — no post-submit edits except via Module 5 dispute.

### 4.7 Quality gate (inline, itemized 422)

All checks run; the 422 lists every failure (not first-fail), so the Attestor fixes in one pass:

1. Every dimension of the attestation's `review_type` (current version) has a `score` (1–5) **and**
   non-empty `comment`.
2. `outcome` set; `conditions` non-empty iff `outcome == conditional`.
3. ≥1 annotation iff `outcome ∈ {conditional, rejected}`.
4. Word count of (all rubric comments + summary + conditions) ≥ `attestation_report_min_words`
   (config, default 150).
5. Contact-leak check: report text contains no email / phone / URL
   (config `attestation_report_block_contact_info`, default on) — enforces §4.4 "via platform,
   not direct email".
6. No `open` clarification.

### 4.8 SLA: grace-then-revoke (reconciles §4.7 with Module 3)

- `completion_due_at` unchanged at accept.
- Grace window `attestation_completion_grace_hours` (config, default 24).
- Attestor may submit while `in_review` even past `completion_due_at`, up to
  `completion_due_at + grace` → submission stamped late (4.6).
- `revoke_overdue_attestations` beat widened: selects `status IN ('accepted','in_review')` **and**
  `completion_due_at + grace < now`. Only then is the assignment revoked/reassigned.
- Because clarifications push `completion_due_at` out, the grace math automatically respects pauses.

### 4.9 Report PDF (grow existing WeasyPrint template → §4.6 eight sections)

Renderer already selects the Attestation joined to requestor+attestor. Extend the query to load
rubric scores (+ dimension labels/weights), annotations, and `AttestorProfile.verification_level`
+ credentials. Sections:

(a) Executive Summary ← `summary` · (b) Scope of Review ← `scope` · (c) Methodology ← canned per
type (3.4.1) · (d) Dimension Scores ← rubric rows + weighted overall · (e) Key Findings ←
annotations (typed, located, quoted) · (f) Conditions ← `conditions` (only if conditional) ·
(g) Overall Determination ← `outcome` + weighted score · (h) Attestor identity ← name +
verification level + credentials · plus an optional supplementary-notes block.

---

## 5. Security

- Every workspace endpoint: assigned-Attestor-only, mismatch → **404** (hide existence), reusing the
  `_load_assigned_attestation_for_update` pattern. Clarification-respond is **Requestor-only**.
- RBAC at the FastAPI dependency layer, never in service (CLAUDE.md).
- No secrets/PII in audit metadata — ids, counts, enums, booleans, numbers only.
- Presigned artifact delivery only (Module 2b), never proxied.
- Money/escrow untouched; report_submitted still the sole Module 5 trigger; dispute window logic
  unchanged.
- All new migrations nullable/reversible; `ALTER TYPE ADD VALUE` steps isolated and irreversible-safe
  (documented downgrade no-op for the enum value, per existing Module 1 precedent).

---

## 6. Testing (TDD, per slice)

**Unit (service):**
- Rubric weights per type sum to 1.000; weighted-overall math.
- Gate: each of the six checks fails in isolation and passes when satisfied; 422 aggregates all
  failures.
- Start-review: valid transition, idempotency, 404 on non-assigned, reject when not `accepted`.
- Clarification: max-2 → 422; pause extends deadline; respond trims remainder; expiry beat closes
  and leaves deadline extended; submit blocked while open.
- Late: submit within grace stamps `submitted_late` + increments profile counter; revoke-beat only
  fires past `completion_due_at + grace`; in_review included in revoke selection.
- Determination: conditional without conditions → gate fail; non-approved without annotation → gate
  fail.

**Integration (endpoints):**
- Full happy path: accept → start-review → score all dims → annotate → submit → report_submitted +
  PDF enqueued + dispute window set.
- 404 for a non-assigned attestor on every workspace endpoint.
- Requestor responds to clarification; Attestor cannot respond (403/404).
- Submit past deadline within grace → late-stamped; past grace → revoke-beat reassigns.

**Beat:** `expire_attestation_clarifications` idempotent no-op on empty; closes an overdue open row.

**Migrations:** `alembic upgrade head` + `downgrade -1` per new migration; enum-add step verified.

---

## 7. Slice breakdown (each = its own review cycle)

1. **Rubric foundations** — `in_review` enum; new Attestation + AttestorProfile columns; rubric
   dimensions + methodology + scores + annotation-type enum tables; migration(s); seed all four
   rubrics; `rubrics.py` constants + weighted-overall helper + weight-sum tests.
2. **Workspace CRUD** — `start-review`, rubric-score upsert, annotation CRUD; RBAC dependency +
   transition audit; OpenAPI.
3. **Clarifications + SLA pause** — model + send/respond endpoints + pause math +
   `expire_attestation_clarifications` beat; widen revoke-beat to include `in_review`; OpenAPI.
4. **Submit gate + report generation** — extend `submit_report` (gate, conditions, late-stamp,
   rubric_version), grace-then-revoke widening, grow PDF template to eight sections; OpenAPI.

Frontend split-screen workspace = separate later phase.

---

## 8. Open dependencies / notes for the planner

- Module 3 AMM scoring uses a flat `REPUTATION_BASELINE`; `late_submission_count` is written here but
  **not** consumed by scoring until a later reputation module. This slice only produces the signal.
- `attestation_outcome_enum` already carries approved/conditional/rejected — no enum change for
  determination.
- The PDF renderer's status filter (`report_submitted`, `released`, `closed`) is unchanged; only its
  data loading + template grow.
