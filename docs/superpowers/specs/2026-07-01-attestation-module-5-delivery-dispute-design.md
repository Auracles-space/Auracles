# Attestation Module 5 — Delivery, Acceptance & Dispute — Design Spec

**Date:** 2026-07-01
**Status:** Approved (grilled 2026-07-01)
**Build priority:** 5 (per attestation gap-analysis roadmap)
**Source of truth:** `docs/Auracles Attestation — Product Development Workflow.md` §5.1–5.5 + Edge Cases; gap analysis `docs/superpowers/specs/2026-06-29-attestation-research-gap-analysis-design.md` §Module 5.
**Depends on:** Modules 1–4 (onboarding, request/submission, AMM matching, review workspace) — all shipped and merged to `main`.
**Execution model:** Backend-first, TDD (RED→GREEN per behavior). Implementer agent builds each slice; a separate reviewer gates each slice.

---

## 1. Purpose

Module 5 closes the attestation loop from **report delivery** through **acceptance or dispute** to the **escrow-release trigger**. It is the completion mechanism that sits between the Review Workspace (Module 4, which ends at `report_submitted`) and Settlement (Module 6, which performs the money split, publishes the badge, and processes reputation).

Module 5 is deliberately **money-neutral on the split**: it fires the existing escrow *release* (which today pays the attestor 100%; the 90/10 platform split is Module 6.1) and *refund* paths, but introduces no new escrow math. This keeps the slice free of a new escrow sign-off surface.

---

## 2. Scope boundary (Module 5 vs Module 6)

**In Module 5:**

- Report delivery + SLA-status data (5.1).
- 5-business-day dispute window + auto-accept (5.2), replacing today's 14-calendar-day window.
- Accept → fire release; **capture** a 1–5 rating (5.3) — stored only.
- Dispute intake: 4 categories + mandatory written evidence + vexatious guard (5.4).
- Requestor abuse flag: 3 rejected disputes / rolling 12 months (5.4).
- Dispute resolution: outcomes `rejected` / `upheld_refund` / `upheld_revise`, revise-resubmit loop, formal warnings, suspension-review trigger, resolution SLA clock (5/15 business days) (5.5).
- Stamp `report_published_eligible` at each terminal transition so Module 6 knows what to publish.

**Deferred to Module 6 (out of scope here):**

- 90/10 escrow split (6.1).
- Version-locked badge **publication** to the framework page (6.3).
- Turning the captured rating into a reputation score (6.4).

**Carry-forward flag (NOT touched in M5):** completion SLA is `DEFAULT_COMPLETION_SLA_DAYS = 7` (calendar) in code, but workflow §2.2 states 10 business days. Pre-M5 discrepancy, out of scope; recorded here so it is not lost.

---

## 3. Current state (what already exists)

| Concern | Current implementation |
|---|---|
| Dispute model | `AttestationDispute` — `reason` (free text), `status` (`open`/`under_review`/`resolved`), `resolution_type` (`release`/`refund`/`split`), `release_amount`, `refund_amount`, `admin_id`, `resolution_notes`, `escalated_at`, `resolved_at`. |
| Raise dispute | `dispute_service.create_dispute` — requires `report_submitted` + window open; one active dispute per attestation; sets attestation → `disputed`. |
| Resolve dispute | `dispute_service.resolve_dispute` — admin + TOTP; release/refund/split escrow; attestation → `closed`. |
| Accept report | `release_service.accept_report` — releases escrow, attestation → `closed`. |
| Auto-release | `release_service.auto_release_attestations` beat — releases undisputed `report_submitted` past `dispute_window_ends_at` → `closed`. |
| Dispute escalation | `dispute_service.escalate_attestation_disputes` beat — `open` disputes older than **7 calendar days** → `under_review`. |
| Dispute window | Set at report submit: `dispute_window_ends_at = now + 14 calendar days`; `DEFAULT_DISPUTE_WINDOW_DAYS = 14`; config key `attestation_dispute_window_days`. |
| Attestor profile | `AttestorProfile.late_submission_count` only — no warning/suspension state. |
| Status enum | `...report_submitted, released, disputed, resolved, needs_admin, refunded, closed, cancelled`. |
| Beat jobs | `revoke_overdue_attestations`, `auto_release_attestations`, `escalate_attestation_disputes` in `app/workers/tasks/attestation_beat.py`. |

---

## 4. Locked design decisions

### 4.1 Business-day math

- New pure util `add_business_days(start: datetime, n: int) -> datetime` in `app/shared/` (e.g. `app/shared/business_days.py`).
- **Weekends-only** (skip Saturday/Sunday). **No holiday calendar** at launch — jurisdiction × locale tables are large surface for marginal fairness; deferred.
- Anchored in **UTC** (platform stamps everything UTC).
- Fully unit-tested (Friday+1 → Monday, span multiple weekends, n=0, etc.).
- Precedent note: Upwork's automated money clocks are calendar-day; "business day" here honors the written spec while staying weekend-only-simple.

### 4.2 Dispute window (5 business days)

- At report submit: `dispute_window_ends_at = add_business_days(now, window)`.
- `window` from config `attestation_dispute_window_business_days`, default **5**, minimum 1.
- Config key **renamed** from `attestation_dispute_window_days` → `attestation_dispute_window_business_days` (semantics changed from calendar to business days; rename forces intentional reconfig and blocks a stale `14` from leaking in). Migration replaces the seeded config row.
- `DEFAULT_DISPUTE_WINDOW_DAYS = 14` → `DEFAULT_DISPUTE_WINDOW_BUSINESS_DAYS = 5`.
- **In-flight rows left as-is** — `auto_release` reads the stored `dispute_window_ends_at` timestamp, not the config; already-submitted reports finish on their existing clock. No backfill (shortening a live window mid-flight is unfair).
- Auto-release semantics unchanged (undisputed + past window → release → closed); this **is** the "auto-accept" of §5.2.

### 4.3 Rating capture (5.3)

- New table **`attestation_ratings`**:
  - `id` (uuid pk), `attestation_id` (uuid fk, **unique** — one per attestation), `rated_by` (uuid fk users), `stars` (int, 1–5, checked), `comment` (text, nullable), `created_at`.
- **Decoupled** from acceptance: `accept_report` releases escrow immediately (unchanged). Rating is a separate endpoint `POST /v1/attestations/{id}/rating`. Never gate money movement on a rating prompt.
- **Eligibility:** requestor-only; once; immutable; allowed on any attestation whose report **stood** — i.e. reached a released/closed terminal via explicit accept, auto-accept, or dispute-`rejected`. Not allowed on refunded (CoI-upheld) attestations.
- Stored only in M5. Module 6.4 consumes it for reputation. Duplicate rating → 409; ineligible state → 409; non-requestor → 404 (existence-hiding, matching module convention).

### 4.4 Dispute intake hardening (5.4)

- New enum `ATTESTATION_DISPUTE_CATEGORY_ENUM`: `scope_error`, `process_violation`, `material_inaccuracy`, `conflict_of_interest`.
- `AttestationDispute` gains `category` (enum, **not null** on new rows — server_default not applicable; enforced at creation).
- Evidence: the existing `reason` column carries mandatory written evidence. Enforce **min-length** at creation from config `attestation_dispute_evidence_min_length` (default e.g. 40 chars); below → **422**. This *is* the vexatious guard — an evidence-less dispute cannot be created, so no async auto-reject job is needed.
- File-attachment evidence **deferred** (report + annotations already carry the artifact trail). Flagged for a later module.
- `create_dispute` request schema gains `category` (required) + keeps `reason` (now min-length-validated as evidence).

### 4.5 Requestor abuse flag (5.4)

- **Derived, not stored.** Helper `requestor_rejected_dispute_count(db, requestor_id, now) -> int`: count `AttestationDispute` where `raised_by == requestor_id`, `status == 'resolved'`, resolution outcome == `rejected`, `resolved_at >= now - 12 months`.
- Flag boolean = count ≥ 3.
- Rolling-window correctness by construction (no decay job, no staleness). Disputes are rare; read only at match time (already-heavy scoring cycle), not a hot path.
- New index on `attestation_disputes (raised_by, status, resolved_at)` to keep it cheap at scale.
- Surface: expose **boolean** `requestor_flagged` on the attestor-facing offer/preview payload (Module 3 read surface). Never expose raw count/history to attestors (minimum-necessary).

### 4.6 Resolution restructure + revise-resubmit loop (5.5)

**Outcome model.** Introduce a resolution **outcome** dimension distinct from the escrow op. New enum `ATTESTATION_DISPUTE_OUTCOME_ENUM`: `rejected`, `upheld_refund`, `upheld_revise`.

- **`rejected`** → escrow **release** to attestor; attestation → `closed`; `report_published_eligible = true`; requestor cannot re-dispute (state machine: closed → `create_dispute` 409). Report stands.
- **`upheld_refund`** (Conflict of Interest) → **full refund** to requestor (reuse existing Stripe refund + `escrow_service.refund`); attestor 0 fee; attestation → `refunded`/`closed`; `report_published_eligible = false`; write a formal **warning** (§4.7).
- **`upheld_revise`** (Scope Error / Material Inaccuracy) → escrow **stays held**; attestation → new status **`revision_requested`**; `revision_count += 1`; write a formal **warning**; attestor re-enters `submit_report`.

**Drop `split`.** Workflow §5.5 is binary (upheld/rejected); `split` has no §5 home and is an escrow-math complication on a money path. Remove the `split` branch from `resolve_dispute`, the `split` value from `ATTESTATION_DISPUTE_RESOLUTION_ENUM` (migration), the `ck_attestation_disputes_split_has_amounts` constraint, and associated code/tests. Admin retains `needs_admin` + full-refund tooling. **This is a deliberate removal of shipped code + tests — called out for reviewer/human attention.**

> Relationship of `resolution_type` vs new `outcome`: the new `outcome` enum is the primary §5.5 verdict. Escrow effect derives from it (`rejected`→release, `upheld_refund`→refund, `upheld_revise`→none). The plan decides whether to keep `resolution_type` as a derived/legacy escrow-op column or replace it with `outcome`; recommended: replace `resolution_type` usage with `outcome`, drop `release_amount`/`refund_amount`/split constraint (no partial amounts remain). Final column shape is a plan-level detail; the behavior above is binding.

**Revise-resubmit mechanics:**

- `revision_requested` added to `ATTESTATION_STATUS_ENUM` (migration).
- Attestor resubmits through the **existing** `report.submit_report` path → re-runs the Module 4 **quality gate** + regenerates the 8-section PDF (free via existing flow). Precondition set for submit/evidence-upload extended to include `revision_requested`.
- Resubmit sets `report_submitted` again and a **fresh** dispute window (`add_business_days(now, 5)`).
- **Revision SLA:** resubmit gets its own clock from config `attestation_revision_sla_business_days`, default **5**. Late resubmit → existing late-flag path (`submitted_late` / `late_submission_count`) applies.
- **Re-dispute allowed** on the revised report (it is materially a new report; the "no second dispute on same report" rule binds only the *same* report, enforced naturally because `rejected` closes the attestation while `upheld_revise` reopens it).
- `revision_count` (int, default 0) added to `attestations` for observability + revision SLA/late logic.
- **Loop bound:** no separate numeric cap. Each upheld → warning; 2 upheld/12mo → suspension-review (§4.7) halts the attestor naturally.

### 4.7 Formal warnings + suspension review (5.5 + Edge Cases)

- New table **`attestor_warnings`** (audit-grade — history + reason needed by the human doing suspension review):
  - `id`, `attestor_id` (uuid fk users), `dispute_id` (uuid fk, nullable — edge-case warnings may not stem from a dispute), `reason` / `category` (text), `created_at`.
- A formal warning is written on every **upheld** dispute (`upheld_refund` and `upheld_revise`), and on the edge-case CoI self-declare void.
- **Suspension-review trigger — derived** (same rolling-12mo pattern as §4.5): count warnings from upheld disputes for the attestor with `created_at >= now - 12 months`; **≥ 2** → flip suspension review.
- On trigger: set `AttestorProfile.suspension_review_at` (timestamp, nullable), write audit, notify admin. **No auto-deactivation** — suspending an attestor is a human money/reputation call (deny-by-default, but escrow/reputation actions need human sign-off). Admin uses existing tooling to actually suspend.

### 4.8 Resolution SLA clock (5.5)

- `AttestationDispute` gains `is_complex` (bool, default false, **admin-set**) and `resolution_due_at` (timestamptz, nullable).
- `resolution_due_at = add_business_days(reference, 15 if is_complex else 5)`, where `reference` is dispute creation (or escalation) time.
- **Retune** the existing `escalate_attestation_disputes` beat: instead of the arbitrary 7-calendar-day open→under_review bump, flag disputes past `resolution_due_at` — set a `resolution_overdue_at` marker, write audit, notify admin. **No auto-resolve** — money stays human.
- SLA is an ops/attention signal, not an automated action.

### 4.9 Publication eligibility (feeds Module 6)

- `attestations.report_published_eligible` (bool, default false) stamped at each terminal transition:
  - accept / auto-accept / dispute-`rejected` → **true**.
  - `upheld_refund` (CoI) → **false**.
- Set where the decision is actually made (dispute-resolution + release logic), so Module 6's badge query reads one flag instead of reverse-engineering status + dispute joins.

---

## 5. Data model changes (summary)

**New tables:** `attestation_ratings`, `attestor_warnings`.

**New enums:** `attestation_dispute_category_enum`, `attestation_dispute_outcome_enum`.

**Enum edits:** `attestation_status_enum` += `revision_requested`; `attestation_dispute_resolution_enum` −= `split`.

**Column adds:** `attestations.revision_count`, `attestations.report_published_eligible`; `attestation_disputes.category`, `.outcome`, `.is_complex`, `.resolution_due_at`, `.resolution_overdue_at`; `attestor_profiles.suspension_review_at`.

**Column/constraint removals:** `attestation_disputes` split constraint (`ck_attestation_disputes_split_has_amounts`) and, per plan, `release_amount`/`refund_amount` if `outcome` replaces `resolution_type`.

**Index add:** `attestation_disputes (raised_by, status, resolved_at)`.

**Config:** rename `attestation_dispute_window_days` → `attestation_dispute_window_business_days` (default 5); add `attestation_dispute_evidence_min_length` (default 40), `attestation_revision_sla_business_days` (default 5). Resolution-SLA counts (5/15) may be literals or config per plan.

Every change is one Alembic migration per slice, `upgrade`/`downgrade -1` both green. No column drops without the human review CLAUDE.md mandates — the `split` removal and any dispute-column drop are called out explicitly.

---

## 6. API surface (OpenAPI-first)

- `POST /v1/attestations/{id}/rating` — requestor rates a stood report (stars 1–5 + optional comment).
- `POST /v1/attestations/{id}/dispute` (existing) — request body gains required `category`; `reason`/evidence now min-length-validated.
- Admin dispute-resolve endpoint (existing) — body changes: `outcome` (`rejected`/`upheld_refund`/`upheld_revise`) replaces the `split` option; `is_complex` settable; retains TOTP.
- Attestor offer/preview payload (existing, Module 3) — gains `requestor_flagged: bool`.

Update `contracts/openapi.yaml` before implementation per each slice; regenerate frontend client (frontend is a later module — backend + contract only here).

---

## 7. Security & integrity

- Dispute-resolve stays **admin + TOTP** (unchanged). Revise/refund/reject verdicts all flow through it.
- All escrow effects inside DB transactions; refund does Stripe refund **before** local state change (existing pattern reused). No new escrow math introduced.
- Rating endpoint: requestor-only, existence-hiding 404 on mismatch, 409 on duplicate/ineligible.
- Evidence min-length = deny-by-default vexatious guard at the boundary.
- Suspension-review flags + notifies; never auto-suspends (human sign-off on reputation actions).
- Audit every: dispute raised (already), resolved w/ outcome, warning written, suspension-review flagged, rating submitted, revision requested/resubmitted, publication-eligibility stamp, resolution-overdue flag.
- `requestor_flagged` exposes a boolean only — no dispute history/PII to attestors.

---

## 8. Slice decomposition

Backend-first, TDD, one implementer builds / reviewer gates each. Each slice ends at an independently testable, committable deliverable.

1. **Business-day util + dispute window.** `add_business_days` + unit tests; 5-bd window recompute at submit; config rename migration; constant rename. (No behavior coupling to later slices beyond the shared util.)
2. **Rating capture.** `attestation_ratings` model + migration; `POST /rating` service + endpoint (decoupled, eligibility rules); schemas; OpenAPI. Unit (eligibility/dup/immutable) + integration (401/403-or-404/409/happy).
3. **Dispute intake hardening.** `category` enum + column + evidence min-length guard at creation; migration; request schema + OpenAPI. Requestor-flag derived helper + `(raised_by,status,resolved_at)` index + `requestor_flagged` on offer payload. Unit (vexatious 422, flag threshold) + integration.
4. **Resolution restructure** *(heavy)*. `outcome` enum + `revision_requested` status; drop `split` (enum + constraint + code + tests); revise-resubmit loop (`revision_count`, revision SLA, fresh window, reopened submit precondition); `report_published_eligible` stamping across all terminal paths; reuse refund/release. Migration(s). Unit per outcome + state-machine + integration.
5. **Warnings + suspension-review + resolution-SLA clock.** `attestor_warnings` table + migration; warning-on-upheld; derived suspension trigger + `suspension_review_at` + admin-notify; `is_complex` + `resolution_due_at` + escalate-beat retune (`resolution_overdue_at` + notify). Unit (trigger threshold, SLA computation) + integration + beat task tests.

---

## 9. Testing

Per CLAUDE.md TDD mandate — RED→GREEN per behavior:

- **Unit (service):** business-day util edge cases; window recompute; rating eligibility matrix (accept / auto-accept / rejected → allowed; refunded → blocked; duplicate → 409); vexatious 422; requestor-flag threshold (2 vs 3, aging past 12mo); each resolution outcome's escrow + status effect; revise-resubmit re-runs gate + fresh window + `revision_count`; drop-split (no split path remains); warning written on upheld; suspension trigger at 2/12mo; `report_published_eligible` per terminal; resolution-SLA due/overdue computation.
- **Integration (endpoint):** rating endpoint auth/dup/eligibility; dispute create with/without category + evidence; admin resolve per outcome (TOTP gate); `requestor_flagged` present on offer payload.
- **Beat tasks:** `escalate_attestation_disputes` retuned (flags overdue, no auto-resolve); auto-release still respects fresh windows and open disputes.
- **Migrations:** each slice `alembic upgrade head` + `downgrade -1` green. Migration-only tests run isolated (batch-isolation quirk from Module 4 noted).

Backend coverage ≥ 80% on touched modules.
