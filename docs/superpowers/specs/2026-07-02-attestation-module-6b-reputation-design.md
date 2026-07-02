# Attestation Module 6b — Reputation — Design

**Date:** 2026-07-02
**Build priority:** 6 (Settlement & Payout), sub-module **b** of 4.
**Status:** Approved for planning.

## 0. Module 6 decomposition (context)

Module 6 (Settlement & Payout, workflow §6.1–6.5) is four independent
sub-modules, each its own spec → plan → implement cycle, built in order:

| Sub-module | Scope | Workflow |
| ---------- | ----- | -------- |
| 6a Settlement | Escrow settles attestation at 90/10; attestor earnings clear immediately into the payout balance. | §6.1, §6.2 |
| **6b Reputation** (this doc) | Attestor becomes a reputation subject; M5 star ratings → 0-100 score via the existing engine → feeds AMM matching; Certified Attestor (L5) awarded on merit. | §6.4 |
| 6c Badge & Provenance | Version-locked attestation badge on framework page + attestor public "Completed Attestations" + provenance record. | §6.3 |
| 6d Invoicing | Attestation tax invoice (requestor) + earnings statement (attestor) + annual summaries. | §6.5 |

## 1. Overview

6b closes the **trust** side of the attestation loop. When a requestor rates a
stood attestation report (1–5 stars, captured in Module 5), that rating is
processed into the Attestor's reputation score. The score is a first-class
0-100 reputation, computed by the **existing reputation engine** used for
frameworks, contributors, and operators — the Attestor simply becomes a fourth
subject type. The score then feeds every subsequent AMM match run, and
crossing a merit threshold awards **Auracles Certified Attestor** status.

**Deliberately minimal.** No new scoring engine. 6b reuses `combine_factors`
(weight → shrinkage-toward-prior → 0-100), the `reputation_scores` table, and
the daily recompute Beat task. The only genuinely new scoring surface is one
factor aggregator plus config values, all human-reviewable.

## 2. Scope boundary

**In scope:**
- `attestor` added as a reputation subject type (engine, table constraint,
  config, read paths, recompute).
- New `attestor_factors` aggregator: rating average + reliability penalty.
- Certified Attestor (L5) merit award, sticky.
- Recompute triggers: on rating submission (targeted) + daily Beat (sweep).
- AMM matching consumes the attestor's real reputation (was a hardcoded 0.5).
- Attestor reputation score + certified flag surfaced on the read paths /
  directory (backend).

**Out of scope (other sub-modules / already done):**
- Escrow settlement + payout — 6a.
- Attestation badge publish, provenance, public "Completed Attestations" — 6c.
- Invoicing — 6d.
- Rating capture (`AttestationRating`) — done in Module 5.
- Frontend (directory UI, profile badge display) — 6b is backend-only.

## 3. What already exists (reused unchanged)

- **Reputation engine:** `reputation/service.py::combine_factors` weights
  normalized factors, shrinks toward a neutral prior by evidence volume, and
  emits a 0-100 `ScoreResult` with a provisional flag. `upsert_score` /
  `get_score` / `read_reputation` / `summaries_for_subjects` persist and read.
- **Config loader:** `reputation/weights.py::load_config` reads
  `platform_config` with code defaults per subject type (`_DEFAULT_WEIGHTS`,
  `_DEFAULT_MIN_ACTIVITY`) and validates weight maps sum to 1.
- **Recompute:** `workers/tasks/reputation.py` — `recompute_subject`
  (single, idempotent, own transaction; reused by admin trigger and
  `recompute_subject_task`) and `recompute_reputation` (daily Beat sweep via
  `_recompute_all_impl`).
- **Rating input:** `AttestationRating` (1–5 `stars`, one immutable row per
  stood attestation, `attestation_id` FK). Populated in Module 5.
- **Reliability inputs:** `AttestorWarning` (one row per upheld dispute) and
  `AttestorProfile.late_submission_count`.
- **AMM matching:** `attestation/matching_service.py::_rank_eligible_attestors`
  scores candidates via `attestation/scoring.py::compute_match_score`;
  `scoring.reputation_score()` is currently a hardcoded `0.5` swap point with
  weight `0.10`.
- **Attestor profile:** `AttestorProfile.verification_level` (int, default 1) —
  onboarding **vetting** tier. **Untouched by 6b.**

## 4. Locked decisions

### 4.1 L5 storage — separate merit flag

`verification_level` remains onboarding vetting. Certified Attestor status is a
**new** `attestor_profiles.certified_attestor_at TIMESTAMPTZ NULL`. Vetting and
merit are distinct concepts; overloading `verification_level` would conflate
them and make demotion ambiguous. Public display shows an "Auracles Certified"
badge when `certified_attestor_at IS NOT NULL`.

### 4.2 Score factors — rating primary + reliability penalty

Two factors combined by the existing engine:

| Factor | Normalized value (0..1) | Evidence count |
| ------ | ----------------------- | -------------- |
| `rating` | `(avg_stars − 1) / 4` over ratings on the attestor's stood attestations; `0` when no ratings | number of ratings |
| `reliability` | `max(0, 1 − penalty · (warnings + late_submission_count))` | number of stood attestations |

Rationale: §6.4 makes the star rating the driver; the reliability penalty
mirrors the dispute-penalty pattern already used for framework/operator
factors, and folds M5 warnings/late-submissions into the score without a
separate mechanism.

### 4.3 Certification — sticky merit award

Evaluated inside `recompute_subject` (attestor branch), in the same
transaction as the score upsert. If `certified_attestor_at IS NULL` **and**
stood-attestation count ≥ `attestor_certification_min_attestations` **and**
average rating ≥ `attestor_certification_min_avg_rating`, set
`certified_attestor_at = now()` and write audit `attestor_certified`.

**Never cleared by recompute** — certification is earned once and stays.
A lapse in standing is handled by the M5 suspension-review / admin path, not
by silent decertification (avoids boundary flip-flop at the 4.5 threshold).

### 4.4 Update triggers — targeted + daily

- **On rating submit:** `rating_service.submit_rating`, after its commit,
  enqueues `recompute_subject_task("attestor", <attestor_id>)` so the score and
  certification reflect the new rating immediately.
- **Daily Beat:** `_recompute_all_impl` enumerates active attestor profiles and
  recomputes each (catch-all for reliability drift and missed enqueues).

### 4.5 AMM cold-start — neutral for unscored attestors

An attestor with no stored score, or a provisional one, contributes the neutral
`0.5` reputation swap point to the match score — new attestors are neither
rewarded nor penalized until they have enough rated evidence.

## 5. Definitions

- **Stood attestation:** `Attestation.status == "closed"` **and**
  `report_published_eligible == True` (set in M5 on accept / auto-accept /
  dispute-rejected). Refunded and CoI-upheld outcomes are **not** stood.
- **Certification count:** number of the attestor's stood attestations.
- **Certification average:** mean `stars` over `AttestationRating` rows joined
  to the attestor's stood attestations (the rated subset — a stood attestation
  may be unrated; rating is optional and already requires a stood report).

## 6. Configuration (code defaults, no seed migration)

Follows the 6a pattern: config-overridable at runtime, in-code default,
**no seed migration**.

| Key | Default | Meaning |
| --- | ------- | ------- |
| `reputation_weights_attestor` | `{"rating":"0.75","reliability":"0.25"}` | attestor factor weights (must sum to 1) |
| `reputation_min_activity_attestor` | `3` | ratings/evidence below which the score reads provisional |
| `attestor_reliability_penalty` | `0.10` | penalty per (warning + late submission) event |
| `attestor_certification_min_attestations` | `10` | stood attestations for L5 eligibility |
| `attestor_certification_min_avg_rating` | `4.5` | average rating for L5 eligibility |

Reuses the generic `reputation_prior` (0.5) and `reputation_prior_strength_k`
(5) already loaded by `load_config`.

## 7. Code changes (blast radius)

- **Migration (Alembic, additive):**
  1. Alter `reputation_scores` CHECK constraint `ck_reputation_subject_type` to
     include `'attestor'`.
  2. Add `attestor_profiles.certified_attestor_at` (nullable timestamptz).
  - Backwards-compatible; `upgrade`/`downgrade` both clean. Human review noted
    (constraint change), but no column drop.
- **`attestation/models.py`:** add `certified_attestor_at` to `AttestorProfile`.
- **`reputation/weights.py`:** add `attestor` to `_DEFAULT_WEIGHTS`,
  `_DEFAULT_MIN_ACTIVITY`; load the new certification/penalty config keys.
- **`reputation/factors.py`:** new `attestor_factors(db, user_id, cfg)`.
- **`reputation/service.py`:** add `attestor` to `VALID_SUBJECT_TYPES`,
  `subject_exists`, `_public_subject_exists` (active profile).
- **`workers/tasks/reputation.py`:** add `attestor` to `_FACTOR_FN`; enumerate
  active attestor profiles in `_recompute_all_impl`; certification-evaluation
  step in `recompute_subject` for the attestor branch.
- **`attestation/rating_service.py`:** enqueue targeted recompute after commit.
- **`attestation/matching_service.py`:** batch-load candidate reputation scores;
  pass normalized value into `scoring.reputation_score`.
- **`attestation/scoring.py`:** `reputation_score(normalized: float = 0.5)`.
- **`attestation/directory_service.py`:** surface score + certified flag.

## 8. Error handling & edge cases

- **No ratings / no stood attestations:** `rating` value `0`, evidence `0`;
  score reads provisional; AMM uses neutral `0.5`. No division by zero
  (guard on empty rating set).
- **Attestor with warnings but no ratings:** reliability penalty applies, but
  low total evidence keeps the score provisional until `min_activity` ratings
  exist — a brand-new attestor is never dragged negative into AMM.
- **Reliability floor:** `max(0, …)` prevents a heavily-penalized attestor from
  contributing a negative factor.
- **Certification idempotency:** guarded by `certified_attestor_at IS NULL`;
  re-running recompute never re-stamps or re-audits an already-certified
  attestor. Safe under retries and the double (rating-submit + daily) triggers.
- **Recompute-on-rating enqueue failure:** the daily Beat sweep is the
  catch-all; a dropped enqueue delays freshness at most ~24h, never loses it.
- **Deactivated attestor:** excluded from `_public_subject_exists`; the daily
  sweep enumerates only `active` profiles.

## 9. Security

- No new endpoint, no money movement, no escrow-path change.
- Certification write is a server-side merit evaluation inside the recompute
  transaction; not user-triggerable except by earning ratings. Audited.
- Reputation reads honor existing public-visibility rules; sub-values and
  weights are never exposed (only labels), unchanged from the current engine.
- Config values (thresholds, weights, penalty) are non-secret `platform_config`
  rows; never logged as sensitive.

## 10. Testing (TDD, RED → GREEN per behavior)

**Unit — `attestor_factors`:**
1. Attestor with N ratings averaging R → `rating` factor `(R−1)/4`,
   evidence `N`.
2. No ratings → `rating` value `0`, evidence `0` (no ZeroDivisionError).
3. Reliability: `w` warnings + `l` late → value `max(0, 1 − 0.10·(w+l))`,
   evidence = stood count; floors at 0 for heavy penalties.

**Unit — certification (`recompute_subject` attestor branch):**
4. 10 stood + avg 4.6 & not yet certified → `certified_attestor_at` set + audit.
5. 9 stood (below threshold) → not certified.
6. Already certified + avg later 4.0 → stays certified (sticky), no re-audit.
7. Idempotent: two recomputes of an eligible attestor stamp/audit once.

**Unit — AMM cold-start (`scoring` + `matching_service`):**
8. `reputation_score(0.8)` returns `0.8`; default arg returns `0.5`.
9. Ranking uses stored non-provisional score/100; provisional/absent → `0.5`.

**Integration — triggers & reads:**
10. `submit_rating` enqueues `recompute_subject_task("attestor", id)`.
11. Daily `recompute_reputation` includes active attestors in its counts.
12. `read_reputation(subject_type="attestor", …)` returns a payload for an
    existing attestor and `None`/404 for a non-attestor.
13. Migration: `upgrade`→ constraint allows `attestor` + column exists;
    `downgrade` reverses cleanly.

## 11. Build slices (for the plan)

1. Migration (CHECK constraint + `certified_attestor_at`) + model field.
2. `weights.py` attestor defaults + certification/penalty config loading.
3. `attestor_factors` aggregator.
4. Service + recompute wiring (`VALID_SUBJECT_TYPES`, existence checks,
   `_FACTOR_FN`, `_recompute_all_impl` enumeration).
5. Certification evaluation (sticky) in `recompute_subject` + audit.
6. Rating-submit targeted recompute hook.
7. AMM cold-start wiring (`scoring.reputation_score` param + matching batch load).
8. Directory read exposure (score + certified flag).

Each slice is independently testable, TDD RED → GREEN.
