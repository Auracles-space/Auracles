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

## Slice 2 — Rarity Gate Context From Reviews

**Maps to:** BR-FWK-006, FR-FWK-014, FR-EXP-006.

### Product behavior

- Low rarity remains a publish gate because it detects similarity/plagiarism
  risk, not market quality.
- Once Framework reviews exist, the rarity warning should show context about the
  nearest published match:
  - nearest Framework title
  - internal rarity / similarity score
  - average review score and review count for the nearest match
- Low review score on the similar published Framework does not bypass the gate.
  It can support a Contributor differentiation note, but the platform still
  records the similarity and acknowledgement.
- Contributor acknowledgement should require a short differentiation statement
  when the nearest match has public review data.

### Backend scope

- Extend rarity failure metadata to include nearest-match review aggregate when
  available.
- Extend `acknowledge_soft_fail` payload with optional differentiation note.
- Persist differentiation note in audit metadata.
- Keep current publishing behavior: soft-fail acknowledgement can unblock allowed
  rarity failures; unresolved PII/virus/processing failures still block.

### Frontend scope

- Framework pipeline panel shows nearest-match review context beside the rarity
  warning.
- Acknowledgement form includes a concise differentiation field.
- Copy must make clear that low-rated similar content may still be protected
  content and cannot simply be copied.

### Tests

- Low-rarity framework with nearest match includes review aggregate in failure
  metadata.
- Low nearest-match rating does not auto-pass rarity.
- Acknowledgement persists differentiation note and unblocks only allowed
  rarity failures.

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
