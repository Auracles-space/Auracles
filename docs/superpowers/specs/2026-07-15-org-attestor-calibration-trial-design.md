# Org Attestor Calibration Trial (Module 4) — Design

**Date:** 2026-07-15
**Status:** Approved for planning
**Module:** Attestation / Organizations (Org-as-Attestor onboarding gate)

## Problem

An organization becoming an Attestor must pass a **calibration trial**: a nominated
org member reviews a known test framework and their judgement is checked against a
known-good answer key. Today only a stub exists — `AttestorTrial` is created by the
admin, decided by manually flipping the DB `status`, with no seeded framework, no
nominee surface, and no grading. The nominee, when notified, is sent to an
owner/admin-only page and sees "Failed to load application" (403).

This design builds the real trial: curated fixture frameworks with answer keys, a
member-scoped trial workspace where the nominee submits rubric scores, an auto-score
engine that suggests pass/fail, and an admin confirm/override step that feeds the
application's `trial_passed` gate.

## Decisions (locked)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Test framework source | **Curated calibration fixtures** — platform-maintained `Framework` rows flagged `is_calibration`, each with an answer key. Admin picks one at start-trial. Never appear in the marketplace. |
| 2 | Grading | **Auto-score + admin confirm** — nominee's rubric scored vs the key → threshold suggestion → admin confirms or overrides. |
| 3 | Nominee submission | **Rubric scores + comments only** — 1–5 per rubric dimension with an optional comment per dimension. No narrative report, no annotations/clarifications. |
| 4 | Representation | **Trial-scoped tables (Approach A)** — new tables keyed to `attestor_trials.id`; the `attestations`/escrow tables are untouched. Reuse the shared `AttestationRubricDimension` definitions. |
| 5 | Pass threshold | Weighted agreement **≥ 80%**, a named tunable constant. |
| 6 | Attempts | Existing cap of 2 (`ck_attestor_trials_attempt_range`) unchanged. |

## Architecture

The trial reuses the platform's **rubric definitions** (`AttestationRubricDimension`,
seeded per `review_type`, weighted, versioned) and the **presigned-artifact** delivery
pattern, but stores the nominee's work in **trial-scoped tables** rather than the
escrow-funded `attestations` table. Grading is a pure, dependency-free module mirroring
the style of `app/modules/attestation/scoring.py` (which is AMM matching only — no
grading engine exists today).

A fixture is a normal `Framework` row (with artifacts) flagged `is_calibration=true`
and carrying a `review_type` that selects which seeded rubric applies. The answer key is
stored **per fixture** (expected score + tolerance per rubric dimension) and reused
across every trial run on that fixture.

### Isolation (units)

- **`trial_scoring.py`** — pure grading. Input: nominee scores + key + dimension weights. Output: `score_pct` + `auto_result`. No I/O, no ORM.
- **Trial workspace service** — nominee-facing: load fixture + rubric + draft, submit scores. Member-scoped RBAC; 404 hides existence from non-nominees.
- **Trial grading/decide service** — admin-facing: start-trial with fixture, load grade view, confirm/override.
- **Fixture curation service** — admin CRUD over calibration frameworks + answer keys.

Each has one responsibility and a well-defined interface; the scoring unit is fully
testable in isolation.

## Data Model

### Migration — additive

**`frameworks`**
- Add `is_calibration BOOLEAN NOT NULL DEFAULT false`.
- All Explore / search / matching / attestation-target queries filter `is_calibration = false` so fixtures never leak to the marketplace.

**`attestor_trials`** (existing table, additive columns)
- `seeded_framework_id` — already present (FK → `frameworks.id`); now actually set at start-trial.
- Add `submitted_at TIMESTAMPTZ NULL`.
- Add `score_pct NUMERIC(5,2) NULL` — computed weighted agreement.
- Add `auto_result TEXT NULL` — `pass` | `fail` suggestion (enum-checked).
- `status` enum `ATTESTOR_TRIAL_STATUS_ENUM` gains **`submitted`** between `assigned` and `passed`/`failed`.
- `decided_by` / `decided_at` / `feedback` — already present; used by admin confirm.

**New table `attestor_trial_answer_keys`**
```
id              UUID PK
framework_id    UUID FK → frameworks.id (CASCADE)
dimension_id    UUID FK → attestation_rubric_dimensions.id
expected_score  INT  CHECK (1..5)
tolerance       INT  NOT NULL DEFAULT 0  CHECK (0..4)
UNIQUE (framework_id, dimension_id)
```

**New table `attestor_trial_rubric_scores`**
```
id            UUID PK
trial_id      UUID FK → attestor_trials.id (CASCADE)
dimension_id  UUID FK → attestation_rubric_dimensions.id
score         INT  CHECK (1..5)
comment       TEXT NULL
UNIQUE (trial_id, dimension_id)
```

Migration is backwards-compatible: new nullable columns + new tables + one enum value.
`alembic upgrade head` and `downgrade -1` must both succeed.

## Grading — `trial_scoring.py`

```
agreement(n, e, t):
    d = abs(n - e)
    if d <= t: return 1.0
    return max(0.0, 1.0 - (d - t) / 4.0)   # 4 = span of the 1..5 scale

score_pct = 100 * sum(weight_d * agreement(n_d, e_d, t_d)) / sum(weight_d)
auto_result = "pass" if score_pct >= PASS_THRESHOLD_PCT else "fail"
```

- `PASS_THRESHOLD_PCT = 80.0` — named constant.
- Pure function: `(nominee_scores, answer_key, dimension_weights) -> (score_pct, auto_result)`.
- Every rubric dimension for the fixture's `review_type`/version must have both a nominee score and a key entry; the service guarantees this before calling.

## Flows

```
admin start-trial(fixture framework_id)
  validate fixture is_calibration + has a key for every rubric dimension (else 422)
  set seeded_framework_id, status=assigned, attempt (existing cap/retry logic)
  notify nominee → link /dashboard/organizations/{org_id}/attestor-trial

nominee opens trial page (member-scoped)
  GET fixture metadata + presigned artifacts + rubric dimensions + saved draft

nominee submits rubric (POST submit)
  require a score for every dimension (else 422)
  require status == assigned (else 409)
  persist scores, compute score_pct + auto_result, status=submitted, submitted_at

admin grade view
  GET submission vs answer key, score_pct, auto_result suggestion

admin decide (POST trial/decide {result, feedback})
  require status == submitted (else 409)
  set status=passed|failed, decided_by/decided_at/feedback
  passed → _trial_passed gate flips true → approve unblocks

failed + attempt < 2 → admin start-trial again (attempt++), new fixture allowed
```

## API (OpenAPI first)

**Nominee (member-scoped RBAC)**
- `GET /v1/organizations/{org_id}/attestor-trial` — current trial for the calling member: fixture + presigned artifacts + rubric dimensions + saved scores. 404 if none or caller is not the nominee.
- `POST /v1/organizations/{org_id}/attestor-trial/submit` — body: list of `{dimension_id, score, comment?}` for every dimension. 422 incomplete/out-of-range, 409 if not `assigned`.

**Admin (platform admin gate)**
- Extend `POST /v1/.../{application_id}/start-trial` — accept `framework_id` (fixture). Validates fixture + key completeness.
- `GET /v1/.../{application_id}/trial` — grade view: nominee scores + comments, answer key, `score_pct`, `auto_result`.
- `POST /v1/.../{application_id}/trial/decide` — body `{result: pass|fail, feedback?}`. Sets terminal status. Replaces manual DB flip. 409 if not `submitted`.

**Admin fixture curation**
- Create/list calibration frameworks (reuse framework creation flagged `is_calibration`).
- Answer-key CRUD per fixture: `POST` / `PUT` / `DELETE` under the admin module, keyed by `framework_id` + `dimension_id`.

## Security & RBAC

- **Nominee dependency** — resolve the org member for `application.trial_member_id`; require `caller.user.id == member.user_id`. Deny → 403 + WARNING audit (`user_id`, attempted action). 404 (not 403) when no trial exists, to hide existence.
- **Admin endpoints** — existing platform-admin gate.
- **Fixture leak guard** — `is_calibration = false` enforced on every buyer-facing query (Explore, search, matching, attestation-target). Regression-tested.
- **Presigned artifacts only** — fixture artifacts delivered via presigned URL, never proxied.
- **Audit** — start-trial, submit, decide (pass/fail), nominee-access-denied all written to the audit log.
- Answer keys and expected scores are **admin-only**; never exposed on nominee endpoints.

## Surfaces (frontend)

- **Nominee page** — new member-accessible route `/dashboard/organizations/{org_id}/attestor-trial`. Fixture summary + artifact links, a rubric form (1–5 selector + comment per dimension), submit (gated until all scored), read-only "under review" state after submit, terminal pass/fail + feedback. **This resolves the original 403/dead-link bug** — the assignment notification repoints here.
- **Admin review panel** — start-trial gains a fixture picker; a new grade state shows the nominee submission beside the answer key, the `score_pct` + suggestion, and Pass/Fail confirm with override + feedback.
- Mobile-first, 44px touch targets, tested at 375px.

## Edge Cases

| Case | Handling |
|---|---|
| Submit missing a dimension | 422 (all dimensions required) |
| Score out of 1–5 | 422 (Pydantic) + DB CHECK |
| Submit when not `assigned` | 409 |
| Nominee ≠ trial member | 403 + audit |
| Decide when not `submitted` | 409 |
| Fixture missing a key for any rubric dimension | start-trial 422 (ungradeable) |
| Nominee removed mid-trial (`member_id` SET NULL) | nominee 404; admin re-nominates + re-starts |
| Retry after fail, cap 2 spent | 422 (existing cap guard) |
| Application already decided | existing 409 guard unchanged |
| Fixture leaks to marketplace | `is_calibration=false` filter; regression test |

## Testing (TDD RED→GREEN)

**Unit — `trial_scoring.py`**
- Exact match → 100%; within tolerance → full credit; large deviation → decayed; weighting correct; threshold boundary (79.9 → fail, 80.0 → pass).

**Unit — services**
- Submit persists scores, computes `score_pct`/`auto_result`, flips to `submitted`.
- Decide sets passed/failed + `_trial_passed` gate; wrong state → 409.
- Start-trial rejects a fixture with an incomplete key (422).
- Nominee-only guard (non-nominee denied).

**Integration — endpoints**
- Nominee submit happy → 200; missing dimension → 422; re-submit → 409; non-nominee → 403.
- Admin decide happy → gate flips; decide wrong state → 409.
- **Full gate walk extended:** verify-kyb → start-trial(fixture) → nominee submit → admin decide pass → approve.

**Regression — leak guard**
- Calibration framework absent from Explore, search, matching, attestation-target lists.

**Frontend**
- Nominee rubric form (submit gating, read-only post-submit); admin grade view (suggestion + override). vitest + tsc + eslint clean.

## Build Order (backend → OpenAPI → frontend)

1. Migration: `frameworks.is_calibration` + `attestor_trials` columns + `submitted` enum value + two new tables.
2. `trial_scoring.py` (pure) + unit tests.
3. Answer-key + trial-score models; fixture leak-guard filters + regression tests.
4. Nominee trial workspace service + endpoints (GET / submit).
5. Admin start-trial fixture picker + grade view + decide endpoint.
6. Admin fixture curation (calibration framework + answer-key CRUD).
7. `contracts/openapi.yaml` + regenerate client.
8. Frontend nominee trial page.
9. Frontend admin grade view + start-trial fixture picker.

## Out of Scope

- Narrative report artifact, annotations, clarifications on trials.
- Fully automated (no-admin) decisioning.
- Rubric authoring UI (dimensions remain seeded).
- Reusing the paid-attestation workspace for trials.
