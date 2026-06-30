# Attestation Module 3 — AMM Matching Engine — Design Spec

**Date:** 2026-06-30
**Module:** Attestation / Module 3 (AMM Matching Engine)
**Source of truth:** `docs/Auracles Attestation — Product Development Workflow.md` §3.1–§3.4 (+ §1.4)
**Status:** Approved — ready for implementation plan

## Purpose

Module 3 is the algorithmic core that selects which Attestors are offered an
Attestation request. Today selection is a naive FIFO query:
`_matching_attestor_ids` filters active profiles by specialization/jurisdiction
array-overlap and orders by `approved_at`. This spec replaces that with the
spec'd weighted AMM score, adds conflict and availability screening, and adds
the annual Conflict-of-Interest (CoI) re-sign enforcement layer.

### What is already built (do not rebuild)

Most of §3.3 (Notification Dispatch) and §3.4 (First-Accept-Wins) shipped in
Modules 2a/2b and are **out of scope** here:

| Workflow item | Status | Where |
| ------------- | ------ | ----- |
| Simultaneous cohort dispatch (top-N) | ✅ built | `matching_service.offer_next_cohort` |
| In-app + email notification on offer | ✅ built | `notifications.py` |
| First-accept-wins assignment | ✅ built | `matching_service.accept_attestation_offer` |
| Decline → advance cohort | ✅ built | `matching_service.decline_attestation_offer` |
| Offer expiry → next cohort / refund | ✅ built | `matching_service.expire_stale_offers` |
| Preview revoked / full unlocked on accept | ✅ built | `access_service` (derived entitlement) |
| Already-offered exclusion across cohorts | ✅ built | `offer_next_cohort` `excluded_ids` |

### What this module adds

1. **§3.2 AMM Scoring** — weighted formula replaces FIFO ordering.
2. **§3.1 Conflict Screening** — CoI cross-reference beyond requestor/owner.
3. **Availability cap** — at-cap Attestors excluded from the pool entirely.
4. **§3.1 / §1.4 CoI re-sign** — enforcement (expired CoI excluded) + a daily
   reminder Beat task.

## Locked decisions

| # | Decision | Choice | Rationale |
| - | -------- | ------ | --------- |
| 1 | Missing-data factors | **Full 5-factor formula, constants for missing inputs** | Reputation does not exist (Module 6 §6.4 builds it); Credential relevance has no matchable data. Both become flat `0.5` swap-points. Weights and structure stay identical to the source doc — one function swap each when the data lands. No premature schema, no re-tuning. |
| 2 | Conflict screening surface | **Structured `subject_id` screening; free-text name matching out of scope** | `coi_declarations` is name-based today. Extend the existing `CoiEntry` with optional `subject_id`/`subject_kind` so an Attestor links a declaration to a known platform entity. Screen on exact id match. No brittle/untestable string matching; no org entities exist yet. |
| 3 | Availability cap | **Config-driven, live count, offers excluded from count** | Cap via the existing `_platform_int_config` helper (default 5). "Active assignment" = an Attestation the candidate holds in `{accepted, report_submitted, disputed}` (the same `FULL_ACCESS_STATUSES` — an Attestor holding content is a live workload). Outstanding `offered` rows do **not** count: first-accept-wins means most evaporate, and counting them would starve cohorts. |
| 4 | Compute location | **Two-stage: SQL hard-filters the eligible pool, Python scores + ranks** | The per-factor math (credential, availability count, future reputation) is awkward and untestable in SQL. The eligible pool for one request is small, so in-memory scoring is cheap, readable, unit-testable per factor, and isolates the reputation/credential swap-points. |
| 5 | Score persistence | **Persist `match_score` + `score_breakdown` on each `AttestationOffer`** | A trust-layer matching engine must be able to answer "why was this Attestor picked?". One column + one JSONB on a row we already write. Ephemeral scoring would make every match decision unexplainable after the fact. |
| 6 | CoI expiry effect | **Exclude from matching only; do not deactivate the profile** | Re-signing (the existing `sign_coi` endpoint) restores eligibility instantly. Matching-exclusion is the right blast radius; profile deactivation is heavier and admin-reversible-only. |
| 7 | CoI reminder cadence | **Daily Beat task: 30-days-before + on-lapse, deduped** | Mirrors the existing scheduled attestation tasks. A `coi_reminder_sent_at` timestamp dedupes so a daily run does not spam. Enforcement itself is the eligibility filter; the job only nudges. |

## Architecture

The change is surgical. `offer_next_cohort` already assembles `excluded_ids`
(requestor + target owner + every Attestor already offered across prior
cohorts) and calls one helper to pick the next cohort. Only that helper changes;
the cohort lifecycle, audit, and first-accept-wins flow around it are untouched.

| Concern | Before | After |
| ------- | ------ | ----- |
| Candidate selection | `_matching_attestor_ids(...) -> list[UUID]` (FIFO) | `_rank_eligible_attestors(...) -> list[ScoredCandidate]` (scored) |
| Eligibility | active + spec/jurisdiction overlap + not-excluded | + CoI valid + not CoI-conflicted + not at-cap |
| Ordering | `approved_at` ASC | score DESC, then `approved_at` ASC, then `user_id` |
| Offer rows | created without scores | created with `match_score` + `score_breakdown` |

`offer_next_cohort` slices the top `cohort_size` `ScoredCandidate`s and writes
their score onto the offers it already creates. The `attestation_offered` audit
metadata gains the per-Attestor scores.

## Components

### 1. Scoring engine — `app/modules/attestation/scoring.py` (new)

A pure, dependency-light module holding the formula and per-factor functions so
each is unit-testable in isolation and the two constant swap-points are obvious.

```python
WEIGHTS = {
    "sector": 0.30,
    "category": 0.25,
    "credential": 0.20,
    "availability": 0.15,
    "reputation": 0.10,
}

CREDENTIAL_RELEVANCE_BASELINE = 0.5  # swap-point: real relevance needs credential tagging
REPUTATION_BASELINE = 0.5            # swap-point: Module 6 §6.4 builds reputation
```

Factor functions (each returns a `float` in `[0.0, 1.0]`):

- `sector_alignment(requested_specializations, profile_sectors, profile_specializations)`
  — `|requested ∩ (sectors ∪ specializations)| / |requested|`. Empty `requested`
  → `1.0` (an unconstrained request is not penalized).
- `category_match(framework_category, profile_specializations, profile_sectors)`
  — `1.0` if `framework_category` ∈ `specializations ∪ sectors`, else `0.0`.
  `framework_category is None` (non-framework target: credential / contributor /
  operator) → `1.0` (factor not applicable, do not penalize).
- `availability_score(active_count, cap)` — `max(0.0, (cap - active_count) / cap)`.
  Caller has already excluded `active_count >= cap`, so this is `> 0.0` here.
- `credential_relevance()` → `CREDENTIAL_RELEVANCE_BASELINE`.
- `reputation_score()` → `REPUTATION_BASELINE`.

`compute_match_score(factors: dict[str, float]) -> tuple[float, dict]` returns
the weighted sum rounded to 3 decimals and the factor breakdown dict (the value
persisted to `score_breakdown`).

### 2. Eligibility + ranking — `matching_service._rank_eligible_attestors` (replaces `_matching_attestor_ids`)

Signature:

```python
@dataclass(frozen=True)
class ScoredCandidate:
    user_id: UUID
    score: float
    breakdown: dict[str, float]

async def _rank_eligible_attestors(
    db: AsyncSession,
    *,
    attestation: Attestation,
    excluded_ids: set[UUID],
    limit: int,
    now: datetime,
) -> list[ScoredCandidate]:
    ...
```

**Stage 1 — SQL hard filter (exclude entirely):** select `AttestorProfile`
rows where:

- `active IS TRUE`
- `specializations && requested_specializations` AND `jurisdictions && requested_jurisdictions` (existing overlap)
- `user_id NOT IN excluded_ids`
- `coi_signed_at IS NOT NULL AND coi_expires_at > now` (CoI enforcement)

No `LIMIT` at this stage — the pool must be fully scored before ranking.

**Stage 2 — Python screening + scoring** over the returned profiles:

- **CoI conflict screen:** load each candidate's `coi_declarations`; exclude the
  candidate if any entry's `subject_id` ∈ `{attestation.target_id, owner_id,
  attestation.requestor_id}`. Malformed entries (missing/invalid `subject_id`)
  are skipped, logged at WARNING, and never cause exclusion.
- **Availability cap:** count the candidate's Attestations in
  `{accepted, report_submitted, disputed}`; exclude if `count >= cap`; else feed
  `count` to `availability_score`.
- Resolve `framework_category` once per request (one `Framework` lookup if
  `target_type == "framework"`, else `None`).
- Compute each factor, `compute_match_score`, build a `ScoredCandidate`.

**Stage 3 — rank:** sort by `score` DESC, then `approved_at` ASC, then `user_id`
(deterministic; preserves FIFO fairness on ties). Return the first `limit`.

Owner resolution and the `excluded_ids` set are produced by the existing
`_target_owner_id` / `_excluded_attestor_ids` helpers — unchanged.

### 3. `offer_next_cohort` wiring (`matching_service`)

Replace the `_matching_attestor_ids(...)` call with `_rank_eligible_attestors(...)`.
When building `AttestationOffer` rows, set `match_score=candidate.score` and
`score_breakdown=candidate.breakdown`. Add the scores to the existing
`attestation_offered` audit metadata. Empty result → existing `needs_admin`
path, unchanged.

### 4. CoI conflict-link schema — `schemas.CoiEntry` (extend)

Add two optional fields to the existing `CoiEntry`:

```python
class CoiEntry(BaseModel):
    entity: str
    entity_type: Literal["firm", "fund", "individual"]
    relationship: Literal["financial", "advisory", "employment"]
    within_24mo: bool
    subject_id: UUID | None = None
    subject_kind: Literal["user", "framework"] | None = None
```

`coi_declarations` is JSONB — no DB migration. Existing entries have no
`subject_id` and therefore never conflict-match (correct: they are unlinked
external parties). `within_24mo` does not gate screening — a declared tie to the
exact linked entity is disqualifying regardless of age.

### 5. Availability cap config

`_platform_int_config(db, key="attestation_concurrency_cap", default=5, minimum=1)`
— same pattern as `attestation_cohort_size`.

### 6. CoI re-sign reminder Beat task — `app/workers/tasks/`

A daily scheduled task (alongside the existing attestation scheduled tasks):

- For each active `AttestorProfile` with `coi_expires_at` not null:
  - **30-day window:** `now >= coi_expires_at - 30d AND now < coi_expires_at`
    AND not already reminded for this cycle → send "CoI expiring" email + in-app
    notification, set `coi_reminder_sent_at = now`.
  - **Lapsed:** `now >= coi_expires_at` AND not already reminded for this cycle →
    send "CoI lapsed — re-sign to resume receiving requests" notice, set
    `coi_reminder_sent_at = now`.
- **Dedup:** `coi_reminder_sent_at` guards against repeat sends within a window.
  Re-signing resets `coi_signed_at`/`coi_expires_at` (existing `sign_coi`); the
  task clears/ignores `coi_reminder_sent_at` for the new cycle (a reminder is
  only re-sent when `coi_reminder_sent_at < coi_expires_at - 30d`, i.e. it
  predates the current cycle).
- Idempotent — safe to run repeatedly the same day; the dedup guard makes a
  second run a no-op.

Enforcement of expiry is the Stage-1 SQL filter (§2), not this task. The task
only nudges.

### 7. Migration — `2026_06_30_0047_amm_matching_scores.py`

One migration (`down_revision = "2026_06_30_0046"`; bump the sequence number if a
later head has landed by build time):

- `attestation_offers`: add `match_score NUMERIC(4,3) NULL`,
  `score_breakdown JSONB NULL`.
- `attestor_profiles`: add `coi_reminder_sent_at TIMESTAMPTZ NULL`.

All nullable, backwards-compatible, no backfill. Downgrade drops the three
columns.

## Data flow

```
escrow confirmed -> Attestation.status = matching
  -> offer_next_cohort
       excluded_ids = {requestor, owner, already-offered}            (existing)
       _rank_eligible_attestors:
         SQL filter: active + spec/jurisdiction overlap + not-excluded
                     + coi_signed_at not null + coi_expires_at > now
         Python: drop CoI-conflicted (subject_id match)
                 drop at-cap (active_count >= cap)
                 score survivors, sort score DESC / approved_at / user_id
                 take top cohort_size
       create offers WITH match_score + score_breakdown               (new fields)
       status -> offered, audit attestation_offered (+ scores)        (existing + scores)
  -> first-accept-wins / decline / expiry                             (existing, unchanged)

daily Beat:
  coi_reminder task -> 30-day + lapsed reminders, deduped by coi_reminder_sent_at
  (expiry enforcement is automatic via the matching filter)
```

## Error handling / edge cases

| Case | Handling |
| ---- | -------- |
| Empty eligible pool (all filtered/conflicted/at-cap) | existing `needs_admin` path + audit `matching_cohorts_exhausted` |
| Malformed CoI entry (no/invalid `subject_id`) | skipped, logged WARNING, candidate **not** excluded (deny-by-default applies to conflicts, not to data noise) |
| All candidates tie on score | deterministic tie-break (`approved_at`, `user_id`) — stable cohort |
| Framework target deleted / category null | `category_match` → `1.0` (N/A), no crash |
| Re-run of cohort (offered status, active offer exists) | existing early-return guard, unchanged |
| Beat task double-run same day | dedup guard → no-op (idempotent) |

## Security / audit

- Scores persisted for auditability; `score_breakdown` is non-PII (numeric
  factors only).
- `attestation_offered` audit gains per-Attestor scores — IDs + numbers only,
  no PII.
- CoI conflict screening is exact-id, deny-by-default for genuine conflicts;
  data noise never silently excludes (logged instead).
- Reminder emails: no secrets, no brief contents — Attestor + expiry date only.
- No new endpoints; no new auth surface. Matching runs server-side only.

## Testing (TDD)

**Unit — `scoring.py`:**
- `sector_alignment`: full overlap → 1.0; partial → fraction; empty request → 1.0; no overlap → 0.0
- `category_match`: in-set → 1.0; not-in-set → 0.0; `None` category → 1.0
- `availability_score`: 0 active → 1.0; (cap-1) active → `1/cap`; boundary
- `compute_match_score`: known factor dict → expected weighted sum (3dp), breakdown returned
- constants present and wired (credential + reputation = 0.5)

**Unit — `_rank_eligible_attestors`:**
- expired CoI excluded; valid CoI included
- `subject_id` matching target/owner/requestor excluded; non-matching included
- malformed CoI entry → not excluded, WARNING logged
- at-cap excluded; below-cap included with correct availability factor
- ranking order: higher score first; tie → `approved_at` then `user_id`
- top-`limit` slice respected

**Unit — CoI reminder task:**
- 30-day-before → reminder sent, `coi_reminder_sent_at` set
- lapsed → lapsed notice sent
- already reminded this cycle → no-op
- re-run same day → idempotent no-op
- re-signed (new expiry) → eligible again, fresh reminder only at new 30-day mark

**Integration — `offer_next_cohort`:**
- cohort ordered by score; `match_score` + `score_breakdown` persisted on offers
- audit `attestation_offered` carries scores
- empty eligible pool → `needs_admin`

## Scope / file summary

~5 areas: 1 new `scoring.py`, 1 helper swap in `matching_service.py` (+ offer
wiring), 1 schema extension (`CoiEntry`), 1 Beat task + schedule entry, 1
migration (3 columns). No new endpoints.

## Out of scope (flagged)

- **Firm/org-name conflict matching** — no org entities are modeled; only exact
  `subject_id` screening today (decision 2).
- **Real reputation scoring** — Module 6 §6.4; flat `0.5` swap-point until then
  (decision 1).
- **Real credential relevance** — needs credential tagging/specialization data;
  flat `0.5` swap-point until then (decision 1).
- **Sector field on requests** — derived from `requested_specializations` against
  profile `sectors ∪ specializations` until a dedicated request sector tag lands.
- All of §3.3/§3.4 dispatch + first-accept-wins — already built in Modules 2a/2b.
