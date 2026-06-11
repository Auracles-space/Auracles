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

**Status:** Implemented in backlog Slice 2. Internal MinHash-Jaccard now uses
explicit near-duplicate and notice bands. Near-duplicate matches hard-block until
admin override writes durable audit state; notice-band matches reach
`pipeline_passed`, publish remains Contributor-controlled, and
`ArtifactResponse` exposes typed similarity notice context with review aggregate
data. Contributors can acknowledge notices with a differentiation note that is
audited but never gating.

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
jaccard ≥ NEAR_DUPLICATE_JACCARD_THRESHOLD (provisional 0.90)
  → HARD block "near-duplicate / likely copy"
SIMILARITY_NOTICE_JACCARD_THRESHOLD (provisional 0.70) ≤ jaccard < NEAR_DUPLICATE_JACCARD_THRESHOLD
  → NON-BLOCKING "similar to X" notice
jaccard < SIMILARITY_NOTICE_JACCARD_THRESHOLD
  → clear, no flag
```

- **Hard band** stays a `pipeline_failed` reason (`internal_rarity`), but only for
  near-duplicates. **Admin override** path added (reuse the escrow-style admin +
  audit pattern) so legitimate edge cases — same author republishing, licensed
  reuse, new version — are not dead-ended. Override state must be durable, not
  audit-only, so future gate re-evaluations remain deterministic.
- **Notice band** does **not** block. The Framework can reach `pipeline_passed`,
  and the normal Contributor-controlled publish action remains enabled. The
  system records the nearest match for context. This is where review context +
  an optional differentiation note live (informational, audited, never gating).
- This **changes BR-FWK-006 semantics**: update the FRD wording and the rarity
  docstrings to say the gate targets *near-duplication*, not *rarity*, so the
  behavior is not silently "restored" later.

### Sub-step ordering

- **2.0 — Threshold calibration (data-gated, not launch-blocking).** Ship
  provisional defaults first:
  `NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.90` and
  `SIMILARITY_NOTICE_JACCARD_THRESHOLD = 0.70`, ideally configurable through
  backend settings. Once there is a labelled sample (known copies vs known
  same-topic-distinct Frameworks), run the internal scorer and recalibrate at the
  valley between the clusters. Document any changed cutoffs.
- **2.1 — Gate reframe (independent of reviews; can ship first).** `pipeline_gate.py`
  bands + explicit Jaccard constants, not inverted rarity constants:
  `NEAR_DUPLICATE_JACCARD_THRESHOLD` and
  `SIMILARITY_NOTICE_JACCARD_THRESHOLD`. The old `0.30` rarity hard threshold
  moves to a near-duplicate Jaccard comparison (`internal_jaccard >= 0.90`, or
  equivalently `internal_rarity <= 0.10` only at the implementation boundary).
  Notice band writes a non-blocking `similarity_notice` (nearest title + jaccard)
  to `Artifact.metadata_vector["similarity_notice"]` and exposes it through
  `ArtifactResponse`, not `framework.pipeline_failure_reasons`. Admin override
  endpoint on the hard block writes both durable override state and audit.
  Reuses already-persisted `nearest_match_id` + `internal_jaccard`
  (`rarity_internal.py`) — no recompute.
- **2.2 — Notice-band review context (depends on Slice 1 reviews).** Enrich the
  `similarity_notice` with the nearest match's review aggregate (avg score +
  count) via `nearest_match_id` → artifact → `framework_id` → reviews. Add an
  optional differentiation note to the contributor acknowledgement of a notice
  (persisted in audit metadata). A note is required only if the Contributor
  chooses to acknowledge/dismiss the notice in the UI, never as a condition for
  `pipeline_passed` or publish. Low review score on the similar Framework never
  bypasses or weakens anything — notice is non-blocking regardless.

### Backend scope

- `pipeline_gate.py`: replace the single internal-rarity hard fail with the
  three-band logic; emit `similarity_notice` for the notice band.
- New admin override on the hard band (admin role + durable override state +
  audit `rarity_block_overridden`).
- Add explicit durable override columns to `artifact_rarity_audit`
  (`near_duplicate_overridden_at`, `near_duplicate_overridden_by`,
  `near_duplicate_override_reason`) so pipeline re-evaluation does not depend on
  audit-log queries.
- Store notice-band context in `Artifact.metadata_vector["similarity_notice"]`
  and expose it via `ArtifactResponse`.
- Extend the notice acknowledgement payload with optional
  `differentiation_note`; persist in `write_audit` metadata.
- Notice/aggregate read path: `nearest_match_id` → nearest Framework → review
  aggregate (after Slice 1).
- Keep PII/virus/processing as hard blocks unchanged.
- All multi-table writes in `async with db.begin()`.

### Frontend scope

- Pipeline panel: near-duplicate hard fail (with admin-only override affordance)
  vs non-blocking "similar to X" notice — visually distinct.
- Notice shows nearest-match title + (after Slice 1) review aggregate; optional
  differentiation field. That field is required only when the Contributor
  explicitly acknowledges/dismisses the notice; it must not disable publish.
- Copy makes clear: same-problem Frameworks are welcome; only near-duplicates are
  blocked; similar low-rated content may still be protected and cannot be copied.

### Tests

- `jaccard ≥ NEAR_DUPLICATE_JACCARD_THRESHOLD` → hard `pipeline_failed`; admin
  override writes durable state, unblocks re-evaluation, and audits.
- `SIMILARITY_NOTICE_JACCARD_THRESHOLD ≤ jaccard < NEAR_DUPLICATE_JACCARD_THRESHOLD`
  → `pipeline_passed`, `similarity_notice` recorded, no block.
- `jaccard < SIMILARITY_NOTICE_JACCARD_THRESHOLD` → no flag.
- Same-problem distinct Framework (notice band) is no longer blocked (regression
  guard for the reported bug).
- Notice review aggregate populated when nearest match has reviews (post Slice 1).
- Differentiation note persisted in audit when the Contributor acknowledges or
  dismisses a notice; never required for publish and never bypasses the hard band.

## Slice 3 — Public Contributor Profiles With Attestation Badges

**Maps to:** FR-ATT-011, FR-ATT-008, FR-EXP-006.

**Status:** Implemented in backlog Slice 3. Explore now exposes public
Contributor profile detail pages, links Contributor names from Framework cards
and detail pages, returns safe public profile fields with a capped newest
Framework list, and uses outcome-driven public Attestation badges with
`conditionally_attested`, report counts, and rejected-report suppression.

### Product behavior

- Public Explore exposes a Contributor profile page at
  `/explore/contributors/{id}`.
- Framework cards and Framework detail pages link the Contributor name to that
  profile when `contributor_id` and `contributor_name` are available.
- The profile shows only public identity/profile fields, published Frameworks,
  and public trust signals. It must not expose email, KYC status, private role
  metadata, payout state, or private evidence files.
- Contributor-target Attestations show the public badge. The badge label is
  derived from **outcome**, not status alone (see Finding 1 below):
  - `outcome = approved` + `status = closed` → `attested`
  - `outcome = conditional` + `status = closed` → `conditionally_attested`
  - `outcome = rejected` → **no positive badge** (suppress, or show a neutral
    "reviewed — did not pass"; never `attested`). This rejection rule has
    precedence over status, so `outcome = rejected` + `status = report_submitted`
    is also not `pending_acceptance`.
  - `status = report_submitted` (any non-rejected outcome) → `pending_acceptance`
- Public report links remain labelled `pending_acceptance` until the Attestation
  closes, so the UI does not overstate trust before release/closure.
- **Multiple attestations per target (BR-ATT-004):** do not blindly show the
  latest. Pick the **best public outcome** in deterministic order:
  `closed approved` > `closed conditional` > `report_submitted approved` >
  `report_submitted conditional` > none. Surface a count ("N attestations") so a
  newer rejected/conditional report does not hide an older approved report.
- No public contributor **directory/listing** page exists today; this slice ships
  the detail page only, reachable via contributor-name links on Framework cards.
  A browsable directory is a separate decision (see Discovery note).
- Deactivated Contributors are a limited public-profile case, not a 404, when
  they still have published Frameworks. This matches BR-SET-002: their published
  Frameworks remain visible in Explore, but new purchases are suspended. The
  public profile should show safe public identity, published Frameworks, and a
  read-only/deactivated marker; it must not expose private account state.

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
  - `attestation_count`
  - `is_deactivated`
  - `published_framework_count`
  - `published_frameworks` capped to the first 12 newest published Frameworks
- Extend Explore Framework card/detail responses with `contributor_id` and
  `contributor_name` (public `display_name` only — never email/handle).
- Badge query: the existing `_framework_attestation_badges` hardcodes
  `target_type == "framework"` and returns only a single latest badge, so this
  needs a **parameterized shared helper** that works for Framework and Contributor
  targets. Criteria:
  - `target_type = "framework" | "contributor"`
  - `report_key IS NOT NULL`
  - `status IN ("report_submitted", "closed")`
  - **label derived from `outcome`** (approved/conditional/rejected) per the badge
    rules above — `outcome IS NOT NULL` alone is insufficient (Finding 1).
- **Enumeration guard:** `GET /v1/explore/contributors/{id}` must return **404
  unless the target is a Contributor with ≥1 published Framework**. A public,
  unauthenticated endpoint must not confirm the existence of arbitrary user ids
  (operators, attestors, admins, or contributors with no published Frameworks).
  Do **not** 404 solely because the Contributor is deactivated if they still have
  published Frameworks; return the limited read-only public profile instead.
  Admin-driven user suspension/banning is deferred to Phase 5 user management
  (`FR-ADMIN-004`) because no separate `suspended_at`/ban state exists yet.
- Return only published (not suspended/unpublished) Frameworks on the profile.
- Keep this as a public read endpoint; no KYC/profile gate.

### Live 4b bug to fix alongside (or before) this slice

**Finding 1 already ships in production framework badges.** `_public_attestation_status`
(`explore/service.py:255`) maps `closed → attested` on **status only**, and
`_framework_attestation_badges` accepts `outcome IS NOT NULL`. A **rejected**
framework attestation (which still gets paid, closed, and has a `report_key`)
therefore renders as `attested` on Explore cards/detail today. Fix the shared
badge mapper to derive the label from `outcome` — this corrects both the existing
framework badge and the new contributor badge in one place.

Required schema/API adjustment: `ExploreAttestationBadge.status` and the
`attestation_status` filter must support `conditionally_attested` in addition to
`pending_acceptance`, `attested`, and `none`. `attestation_count` should be
returned beside the selected badge so public UI can say "N attestations" without
exposing private report details.

### Frontend scope

- Add public route `/explore/contributors/[id]`.
- Render public identity fields, Contributor Attestation badge, and published
  Framework cards.
- Link contributor name from Framework cards and detail pages to the profile.
- Reuse the existing `AttestationBadge` component and Explore card pattern.
- Render `conditionally_attested` distinctly from `attested`, and never render a
  rejected report as a positive badge.
- Render only the first 12 newest published Frameworks on the profile in this
  slice. Full contributor-profile pagination is deferred unless product asks for
  it.
- For deactivated Contributors with published Frameworks, render a neutral
  read-only marker and do not expose private deactivation metadata.
- Do not redesign the existing Explore layout in this slice.

### Tests

- Public contributor profile returns public fields, badge, and only published
  Frameworks.
- Response does not include email, KYC status, payout details, or private
  evidence keys.
- Badge label is outcome-driven: `approved`→`attested`, `conditional`→
  `conditionally_attested`, `rejected`→ no positive badge; `report_submitted`→
  `pending_acceptance` only for non-rejected outcomes.
- **Rejected attestation never renders `attested`** (regression guard for
  Finding 1 — assert for both framework and contributor badges).
- Multiple attestations on one target: best public outcome wins; a newer
  rejected/conditional does not hide an older approved; count surfaced.
- `GET /v1/explore/contributors/{id}` returns 404 for a non-contributor id and a
  contributor with zero published Frameworks (enumeration guard). Suspended or
  banned account behavior is covered by Phase 5 user management once
  `FR-ADMIN-004` adds a distinct admin suspension state.
- Deactivated Contributor with published Frameworks returns 200 with a limited
  read-only public profile and no private account metadata.
- Contributor profile returns at most 12 newest published Frameworks while
  `published_framework_count` reports the total published count.
- Framework card/detail responses include contributor id/name.
- Frontend profile page renders badge and published Frameworks.
- Framework cards/detail link to `/explore/contributors/{id}`.

### Discovery (open decision)

No contributor directory/listing exists. This slice ships the detail page only;
contributors are reachable solely via name links on Framework cards. A browsable
`/explore/contributors` directory (search/filter by specialization, attestation,
framework count) is **deferred pending a product decision** — pull into its own
slice if contributor discovery is wanted.

### Out of scope

- Private profile editing.
- Contributor reputation scoring.
- Organization membership/affiliation display.
- Public credential gallery beyond attested credential badges.
- Browsable contributor directory/listing (see Discovery note — deferred, not
  designed here).
