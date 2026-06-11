# Post-Phase-4 — Marketplace Polish Backlog

## Context

Phase 2 created the `reviews` table as schema-only because Framework reviews
require real Licenses. Phase 3 shipped purchase and License creation, but
explicitly deferred review wiring to keep the financial slice focused. Phase 4a
and 4b cover Projects and Attestation, not customer reviews.

This backlog keeps the deferred marketplace polish work visible after Phase 4b
so Explore trust signals do not stay permanently shimmed.

## Slice 1 — Licensed Operator Framework Reviews

**Maps to:** FR-FWK-014, BR-FWK-004, BR-FWK-005, FR-EXP-006, FR-FWK-010.

**Status:** Implemented in backlog Slice 1. Backend review writes enforce active
License ownership, one review per Operator, no self-review, 30-day edit window,
and audit rows. Public Explore now returns average review score/count and
`top-rated` uses real review aggregates. Operator Library exposes the licensed
review form, and Contributor analytics reads the real review aggregate.

### Product behavior

- Operators can submit a 1-5 score plus optional body for a Framework they
  actively license.
- One Operator can have only one review per Framework.
- The Operator can edit their own review for 30 days after creation.
- Contributors cannot review their own Frameworks, even if they somehow hold a
  License.
- Suspended/unpublished Frameworks do not accept new public reviews, but existing
  reviews remain available to licensees/admin and can still feed historical
  analytics.
- Public Explore cards/detail show average score and review count.
- `top-rated` Explore sorting stops using the current zero-value shim once the
  review aggregate exists.
- Contributor analytics replaces the current `avg_review = 0` shim with real
  average score and count.

### Backend scope

- Add schemas for create/update review requests and review responses.
- Add endpoints:
  - `POST /v1/frameworks/{framework_id}/reviews`
  - `PATCH /v1/frameworks/{framework_id}/reviews/me`
  - `GET /v1/frameworks/{framework_id}/reviews`
- Enforce active License ownership with row-level checks before insert/update.
- Enforce one-review-per-Operator with the existing
  `uq_reviews_framework_operator` constraint.
- Enforce 30-day edit window in service logic.
- Write audit rows:
  - `framework_review_created`
  - `framework_review_updated`
- Update Explore list/detail queries to return aggregate review score/count.
- Update Contributor analytics to use real review aggregates.
- Keep all multi-table writes in `async with db.begin()`.

### Frontend scope

- Operator Library/Framework detail: review form for licensed Operators.
- Explore card/detail: average rating and review count.
- Contributor dashboard analytics: real average review metric.
- Empty states: no reviews yet, already reviewed, edit window closed.

### Tests

- Licensed Operator can create one review.
- Unlicensed Operator gets 403/404 and no row is written.
- Contributor cannot self-review own Framework.
- Second create returns 409; edit endpoint updates within 30 days.
- Edit after 30 days returns 409.
- Explore detail/list include average score and count.
- `top-rated` sort orders by aggregate score with created-at fallback.
- Contributor analytics uses real review aggregates.

### Out of scope

- Review disputes/moderation queue.
- Weighted reputation scoring from reviews.
- Review helpfulness/upvotes.
- Organization-level reviews.

## Slice 2 — Rarity Gate Reframe + Notice-Band Review Context

**Maps to:** BR-FWK-006 (semantics change — see below), FR-FWK-014, FR-EXP-006.

### Problem with the current gate

Internal rarity = `1.0 − max_jaccard`, where `max_jaccard` is the MinHash-Jaccard
overlap of an artifact's text shingles against every published Framework
(`workers/tasks/processing/rarity_internal.py:104`). The publish gate blocks at
`internal_rarity < 0.30`, i.e. **`jaccard > 0.70`** (`frameworks/pipeline_gate.py:85`).

MinHash-Jaccard measures **shared vocabulary / topic overlap, not copying**.
Consequences:
- Two independent Frameworks solving the **same problem** share heavy domain
  vocabulary → high Jaccard → hard-blocked. Same problem ≠ plagiarism.
- The signal has **no notion of "better."** A more thorough Framework on the same
  topic has *more* shared terminology → *more* likely to trip the gate.
- **First-mover lock-in:** whoever publishes first claims the shingle space; a
  later, superior entrant is hard-blocked.
- 0.70 is a weak plagiarism bar — real copy-paste sits ~0.90+.

**Intent correction:** the gate must block *near-duplication / copying*, not
*topical similarity*. Quality and originality-of-approach are decided by reviews
and Attestation, never by a similarity threshold.

### Decision — three bands (recalibrate, don't rebuild)

```
jaccard ≥ NEAR_DUP (≈0.90, calibrated)   → HARD block "near-duplicate / likely copy"
NOTICE (≈0.70) ≤ jaccard < NEAR_DUP      → NON-BLOCKING "similar to X" notice
jaccard < NOTICE                          → clear, no flag
```

- **Hard band** stays a `pipeline_failed` reason (`internal_rarity`), but only for
  near-duplicates. **Admin override** path added (reuse the escrow-style admin +
  audit pattern) so legitimate edge cases — same author republishing, licensed
  reuse, new version — are not dead-ended.
- **Notice band** does **not** block. Framework publishes; system records the
  nearest match for context. This is where review context + differentiation note
  live (informational, audited, never gating).
- This **changes BR-FWK-006 semantics**: update the FRD wording and the rarity
  docstrings to say the gate targets *near-duplication*, not *rarity*, so the
  behavior is not silently "restored" later.

### Sub-step ordering

- **2.0 — Threshold calibration (prereq, offline).** Run the internal scorer over
  a labelled sample (known copies vs known same-topic-distinct Frameworks). Pick
  `NEAR_DUP` at the valley between the two clusters; pick `NOTICE` floor likewise.
  0.90 / 0.70 are starting guesses, not final. Document the chosen cutoffs.
- **2.1 — Gate reframe (independent of reviews; can ship first).** `pipeline_gate.py`
  bands + `INTERNAL_RARITY_NEAR_DUP_THRESHOLD` / `INTERNAL_RARITY_NOTICE_THRESHOLD`
  constants (the old `0.30` hard threshold moves to `1 − NEAR_DUP ≈ 0.10`). Notice
  band writes a non-blocking `similarity_notice` (nearest title + jaccard) onto the
  framework/artifact instead of a failure reason. Admin override endpoint on the
  hard block. Reuses already-persisted `nearest_match_id` + `internal_jaccard`
  (`rarity_internal.py`) — no recompute.
- **2.2 — Notice-band review context (depends on Slice 1 reviews).** Enrich the
  `similarity_notice` with the nearest match's review aggregate (avg score +
  count) via `nearest_match_id` → artifact → `framework_id` → reviews. Add an
  optional differentiation note to the contributor acknowledgement of a notice
  (persisted in audit metadata — no new column); require it only when the nearest
  match has public review data. Low review score on the similar Framework never
  bypasses or weakens anything — notice is non-blocking regardless.

### Backend scope

- `pipeline_gate.py`: replace the single internal-rarity hard fail with the
  three-band logic; emit `similarity_notice` for the notice band.
- New admin override on the hard band (admin role + audit `rarity_block_overridden`).
- Extend the notice/acknowledgement payload with optional `differentiation_note`;
  persist in `write_audit` metadata.
- Notice/aggregate read path: `nearest_match_id` → nearest Framework → review
  aggregate (after Slice 1).
- Keep PII/virus/processing as hard blocks unchanged.
- All multi-table writes in `async with db.begin()`.

### Frontend scope

- Pipeline panel: near-duplicate hard fail (with admin-only override affordance)
  vs non-blocking "similar to X" notice — visually distinct.
- Notice shows nearest-match title + (after Slice 1) review aggregate; optional
  differentiation field.
- Copy makes clear: same-problem Frameworks are welcome; only near-duplicates are
  blocked; similar low-rated content may still be protected and cannot be copied.

### Tests

- `jaccard ≥ NEAR_DUP` → hard `pipeline_failed`; admin override unblocks + audits.
- `NOTICE ≤ jaccard < NEAR_DUP` → publishes, `similarity_notice` recorded, no block.
- `jaccard < NOTICE` → no flag.
- Same-problem distinct Framework (notice band) is no longer blocked (regression
  guard for the reported bug).
- Notice review aggregate populated when nearest match has reviews (post Slice 1).
- Differentiation note persisted in audit; required only when nearest has review
  data; never bypasses the hard band.

## Slice 3 — Public Contributor Profiles With Attestation Badges

**Maps to:** FR-ATT-011, FR-ATT-008, FR-EXP-006.

### Product behavior

- Public Explore exposes a Contributor profile page at
  `/explore/contributors/{id}`.
- Framework cards and Framework detail pages link the Contributor name to that
  profile when `contributor_id` and `contributor_name` are available.
- The profile shows only public identity/profile fields, published Frameworks,
  and public trust signals. It must not expose email, KYC status, private role
  metadata, payout state, or private evidence files.
- Contributor-target Attestations show as the same public badge pattern used by
  Framework badges:
  - `report_submitted` → `pending_acceptance`
  - `closed` → `attested`
- Public report links remain labelled `pending_acceptance` until the Attestation
  closes, so the UI does not overstate trust before release/closure.

### Backend scope

- Add `GET /v1/explore/contributors/{contributor_id}`.
- Response includes:
  - `id`
  - `display_name`
  - `avatar_url`
  - `bio`
  - `location`
  - `website`
  - `attestation_badge`
  - `published_framework_count`
  - `published_frameworks`
- Extend Explore Framework card/detail responses with `contributor_id` and
  `contributor_name`.
- Reuse the existing public badge criteria:
  - `target_type = "contributor"`
  - `outcome IS NOT NULL`
  - `report_key IS NOT NULL`
  - `status IN ("report_submitted", "closed")`
- Return only published Frameworks on the profile.
- Keep this as a public read endpoint; no KYC/profile gate.

### Frontend scope

- Add public route `/explore/contributors/[id]`.
- Render public identity fields, Contributor Attestation badge, and published
  Framework cards.
- Link contributor name from Framework cards and detail pages to the profile.
- Reuse the existing `AttestationBadge` component and Explore card pattern.
- Do not redesign the existing Explore layout in this slice.

### Tests

- Public contributor profile returns public fields, badge, and only published
  Frameworks.
- Response does not include email, KYC status, payout details, or private
  evidence keys.
- Contributor badge maps `report_submitted` to `pending_acceptance` and `closed`
  to `attested`.
- Framework card/detail responses include contributor id/name.
- Frontend profile page renders badge and published Frameworks.
- Framework cards/detail link to `/explore/contributors/{id}`.

### Out of scope

- Private profile editing.
- Contributor reputation scoring.
- Organization membership/affiliation display.
- Public credential gallery beyond attested credential badges.
