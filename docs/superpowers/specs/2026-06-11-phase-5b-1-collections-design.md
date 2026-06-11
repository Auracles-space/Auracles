# Phase 5b-1 — Collections (design spec)

## Context

Collections let a Contributor bundle ≥2 of their own published Frameworks at a
discounted price; an Operator buys the bundle and gains access to all members
(FRD §FR-COL-001..004, BR-COL-001..003). First half of Phase 5b "Discovery
polish"; Saved searches (FR-SRCH) is a separate spec (5b-2). This is a money-path
feature — purchase, licensing, earnings allocation, refund.

Reuses Phase 3 purchase / PaymentIntent / webhook / License / refund and the
existing per-framework artifact-access path (`app/modules/financials/*`,
`app/modules/frameworks/*`), Explore catalog (`app/modules/explore/*`), audit,
notifications. No collection tables exist yet.

Current repo alignment, verified on 2026-06-11:
- TDD names the tables `framework_collections` and `collection_frameworks`; use
  those names instead of introducing parallel `collections` / `collection_members`
  names.
- `transactions.ref_type` is a `String(50)`, not an enum, so supporting
  `ref_type='collection'` needs service/OpenAPI handling but no enum migration.
- Routers use module-local prefixes and are mounted in `backend/app/main.py` with
  `prefix="/v1"`. Collection CRUD lives under `/collections`; collection checkout
  should live under `/financials/collections/{collection_id}/purchase` to match
  the existing financial purchase routes.
- Stripe metadata values are strings with practical size limits. Do not store
  member framework ID arrays in PaymentIntent metadata; store the member snapshot
  in the database before creating the PaymentIntent.
- Frontend commands should use `corepack pnpm --dir frontend ...`, not bare
  `pnpm`, to match this environment.

## Locked decisions

| # | Decision | Value |
|---|---|---|
| 1 | Licensing model | Purchase **mints one normal framework License per member**, members **snapshotted at purchase in DB** (license tag `source='collection'` + `collection_id`), sharing one collection-purchase transaction. Artifact access / presigned download logic stays unchanged. Later membership edits do not affect past buyers. |
| 2 | Already-owned members | Skip members the Operator already licenses (respect `UNIQUE(framework_id, operator_id)`); mint the rest; charge the **full bundle price**. UI discloses "includes N you already own." |
| 3 | Refund | **All-or-nothing**: eligible only if within `refund_window_hours` (48h) AND no artifact downloaded across ANY minted member. Reverses the whole bundle transaction (Stripe refund) and revokes all minted licenses. |
| 4 | Earnings pro-rate (FR-COL-004) | Bundle price allocated across the **minted** members by their individual list-price ratio; recorded per-framework in `collection_earning_allocations`. Rounding remainder assigned to the highest-priced member so allocations sum exactly to the bundle price. (Single contributor per BR-COL-002 → this is per-framework attribution/analytics, not multi-payee split.) |
| 5 | Explore | Collections appear in the Explore catalog alongside frameworks (FR-COL-003) as a distinct item type. Keep existing `/v1/explore/frameworks` backward-compatible; add a mixed catalog surface for the UI/SEO route. |
| 6 | Validation | BR-COL-001 ≥2 members; BR-COL-002 all members published + owned by the same contributor; BR-COL-003 bundle price < sum of member list prices. Revalidated at **publish** and again at **purchase** (member prices/status can drift). |
| 7 | Currency | USD only. |

## Schema

- **`framework_collections`** — id UUID PK, contributor_id FK, title, description, bundle_price
  NUMERIC(12,2) CHECK > 0, currency CHAR(3) DEFAULT 'USD' CHECK 'USD',
  status `collection_status_enum` (draft|published|unpublished), created_at,
  updated_at. INDEX (contributor_id, status).
- **`collection_frameworks`** — collection_id FK, framework_id FK, PRIMARY KEY
  (collection_id, framework_id). INDEX (framework_id).
- **`collection_purchase_snapshots`** — id, transaction_id FK, one row per
  transaction/member, collection_id FK, framework_id FK, list_price_at_purchase
  NUMERIC(12,2), license_type `license_type_enum`, already_owned BOOL DEFAULT
  false, created_at. UNIQUE (transaction_id, framework_id). This is the webhook
  source of truth for which members were present/missing at checkout time.
- **`collection_earning_allocations`** — id, transaction_id FK, collection_id FK,
  framework_id FK, allocated_amount NUMERIC(12,2), created_at. INDEX
  (transaction_id). Records the per-framework split of a bundle purchase.
- **Extend `licenses`** — add `source` `license_source_enum` (individual|collection)
  NOT NULL DEFAULT 'individual', `collection_id` UUID NULL FK
  `framework_collections(id)`.
  The existing `UNIQUE(framework_id, operator_id)` is preserved (skip-owned at mint).
- **`transactions.ref_type`** — use string value `collection` for the bundle
  purchase row; no enum migration required in the current schema.

## Collection lifecycle

- **Create/edit (draft):** contributor sets title/description/bundle_price, adds/
  removes member frameworks. No validation gate while draft.
- **Publish:** validate ≥2 members (BR-COL-001); every member `status='published'`,
  `deleted_at IS NULL`, and `contributor_id == collection.contributor_id`
  (BR-COL-002); `bundle_price < SUM(member.price)` (BR-COL-003). On pass →
  `status='published'`, appears in Explore.
- **Unpublish:** hide from Explore; existing buyers keep their minted licenses.
- Editing members/price while published: require unpublish→edit→republish (so the
  validated invariant always holds for a published collection).

## Purchase flow (FR-COL-002)

1. `POST /v1/financials/collections/{collection_id}/purchase` (operator role) → load
   published collection + members → revalidate BR-COL-003 against current member
   prices and current member status/deleted state (reject 422 if no longer valid)
   → reject self-purchase when the Operator is the collection contributor →
   validate the selected `license_type` is supported by every **missing** member
   framework → compute **missing** members (those the operator doesn't already
   actively license) → if zero missing → 409 "already own all members" → create
   `transactions(type=purchase, ref_type=collection,
   ref_id=collection_id, status=pending, amount=bundle_price,
   payee_id=collection.contributor_id, platform_commission/net_amount using the
   same commission calculation as a normal framework purchase)` +
   `collection_purchase_snapshots` rows for every checkout member, marking
   `already_owned=true` for members the Operator already held. Then create a
   Stripe PaymentIntent (`metadata={kind:"collection", transaction_id,
   collection_id}` only) → return `{transaction_id, client_secret}`.
2. **Extend the Phase 3 `payment_intent.succeeded` handler** for `ref_type=
   collection`: inside the txn, load `collection_purchase_snapshots` for the
   transaction. The snapshot is the source of truth; later collection edits or
   unpublishing do not change what this buyer paid for. For each snapshot row
   with `already_owned=false` and still unowned, mint `License(framework_id,
   operator_id, transaction_id, source='collection', collection_id,
   license_type=snapshot.license_type, version_at_grant=framework.version,
   status='active')`; compute pro-rate allocations over the minted set and insert
   `collection_earning_allocations`; mark the parent transaction `completed`;
   audit `collection_purchased`. Idempotent on replay (skip already-minted, do
   not duplicate allocations). If a snapshot framework has been hard-deleted or
   suspended before the webhook, fail loudly, audit
   `collection_purchase_needs_refund`, and refund/ops-handle rather than silently
   granting a partial bundle.
3. Explore adds collection card/detail schemas with `item_type='collection'`,
   member summaries, `bundle_price`, `member_price_sum`, `savings_amount`, and
   `savings_percent`. `GET /v1/explore/collections/{id}` includes, for an
   authenticated operator, an `already_owned_member_ids` hint so the UI can show
   "includes N you already own."

## Refund (all-or-nothing)

`POST /v1/financials/purchases/{transaction_id}/refund` extended for collection
txns: eligible iff `now - created_at < refund_window_hours` AND
`COUNT(artifact_downloads for any minted license of this txn) == 0`. On pass:
Stripe refund (idempotency_key `refund:{transaction_id}`), mark txn refunded,
revoke all minted licenses (`status='revoked'`), audit `collection_refunded`.
Ineligible → 422 with reason. Earnings allocations reverse with the txn.

Implementation detail: add a collection refund helper instead of overloading the
existing single-license `_load_refundable_purchase` return shape. It must lock the
collection `Transaction` and every active minted `License` with
`with_for_update()`, verify all licenses have `source='collection'` and the same
`collection_id`, call Stripe with the existing idempotency key pattern, then
re-check downloads across all locked licenses after the provider call before
flipping local state. If that post-provider recheck detects a race, log
`collection_refund_download_race_after_provider_refund` at CRITICAL and return a
409/manual-reconciliation response, matching the Phase 3 refund discipline.

`collection_earning_allocations` are analytics/allocation rows only. Contributor
earnings and payout balance continue to read the parent completed purchase
`Transaction`; do not double-count allocations as separate earnings rows. When
the parent transaction becomes `refunded`, allocations remain for audit but are
excluded by transaction status.

## Module layout

```
backend/app/modules/collections/
├── router.py        # /collections/* (CRUD, publish/unpublish, owner reads)
├── service.py       # CRUD + publish validation + purchase initiate
├── purchase.py      # mint + pro-rate (called by webhook handler)
├── models.py
├── schemas.py
└── dependencies.py
```
Purchase initiation is exposed from `financials.router` for route consistency but
delegates collection-specific validation/snapshotting to `collections.service`.
Purchase confirmation lives in the existing webhook handler (extend), not here;
`collections/purchase.py` exposes the mint+allocate function it calls.

## API surface

| Verb | Path | Auth |
|---|---|---|
| POST | /v1/collections | contributor |
| GET | /v1/collections/mine | contributor |
| PATCH | /v1/collections/{id} | owner, draft only |
| POST | /v1/collections/{id}/members, DELETE .../{framework_id} | owner, draft only |
| POST | /v1/collections/{id}/publish · /unpublish | owner |
| GET | /v1/explore/catalog | public mixed framework/collection catalog |
| GET | /v1/explore/collections, /v1/explore/collections/{id} | public collection list/detail |
| POST | /v1/financials/collections/{id}/purchase | operator |
| (extended) | /v1/financials/purchases/{txn}/refund | operator (owner) |

## Security

- Collection CRUD owner-only; members must be the owner's own published frameworks
  (re-checked at publish). Bundle<sum enforced at publish + purchase.
- Purchase mints licenses only inside the webhook txn (never the initiate
  endpoint); idempotent; skip-owned respects `UNIQUE(framework_id, operator_id)`.
- Refund eligibility checked across all minted members; local revocation happens
  in one DB transaction after provider refund succeeds and the post-provider
  download recheck still passes.
- Collection refunds must not use the existing single-license loader without
  changing its return shape; use a dedicated multi-license path.
- All multi-row writes in `async with db.begin()`. Audit: `collection_created`,
  `collection_published`, `collection_unpublished`, `collection_purchased`,
  `collection_refunded`.

## Slice plan (~8)

1. Schema — `framework_collections`, `collection_frameworks`, `collection_purchase_snapshots`, `collection_earning_allocations`, `licenses.source/collection_id`, `transactions.ref_type='collection'` support + ORM + migration up/down smoke.
2. Collection CRUD + publish — create/edit/add-remove members (draft), publish validation (≥2, same-contributor, all-published, bundle<sum), unpublish. Owner RBAC + audit.
3. Explore catalog — list/detail collections publicly (member framework summaries, bundle price, savings vs sum) and add a mixed `/explore/catalog` read model so collections render alongside framework cards without breaking existing `/explore/frameworks`.
4. Purchase initiate — `POST /financials/collections/{id}/purchase`, revalidate bundle<sum, compute missing members, persist DB snapshot, full-price PaymentIntent; `already_owned_member_ids` hint on detail.
5. Purchase confirm — extend webhook for `ref_type=collection`: mint missing licenses (source=collection) + pro-rate allocations (rounding remainder), idempotent + audit.
6. Refund — extend refund endpoint for collection txns (all-or-nothing eligibility, revoke all minted, reverse allocations).
7. OpenAPI sync + FE — contributor collection builder, Explore collection card/detail (savings badge), operator purchase + "already own N", Library shows collection-sourced licenses. Mobile-first.
8. E2E — create→add 3 members→publish (reject bundle≥sum)→operator buys (owns 1 already → mints 2, full price)→library shows members→refund in-window (no downloads)→licenses revoked; download then refund→422.

## Risk flags

- **Price/status drift:** a member's price can change or it can be unpublished/
  suspended after the collection publishes. Revalidate bundle<sum and member
  visibility at purchase; persist the DB snapshot before charging. After checkout
  initiation, the snapshot determines what the buyer receives unless a member is
  hard-deleted/suspended before webhook confirmation, which requires refund/manual
  handling rather than silent partial fulfillment.
- **Pro-rate rounding:** allocations must sum exactly to bundle price — assign the
  remainder deterministically (highest-priced member). Test with prices that don't
  divide evenly.
- **Skip-owned correctness:** never mint a duplicate license (UNIQUE); if all
  members already owned → 409 before charging.
- **Refund scope:** download check must span every minted member; use the same
  provider-call + post-provider recheck + local transaction discipline as Phase 3
  refund.
- **Same-contributor invariant:** enforce at publish; a framework can't be added
  from another contributor.

## Verification (after slice 8)

1. Backend: `uv run pytest --cov=app/modules/collections` ≥ 80%. Cover: publish validation (each BR), missing-member computation, mint idempotency, pro-rate sum-exactness + rounding, all-or-nothing refund (eligible + each ineligible reason).
2. Frontend: `corepack pnpm --dir frontend test` + `corepack pnpm --dir frontend exec playwright test tests/e2e/collections.spec.ts`.
3. Manual smoke (Stripe test mode): contributor creates a 3-framework collection, publishes (reject when bundle ≥ sum), operator who already owns 1 buys it → 2 licenses minted, charged full bundle price, library lists all 3 (1 prior + 2 new), earnings allocations sum to bundle price; refund within 48h with no downloads → all minted revoked + Stripe refund; download one then attempt refund → 422.

## Out of scope (later / 5b-2)

- Saved searches + email alerts (FR-SRCH — separate 5b-2 spec).
- Multi-contributor collections.
- Collection-level reviews/reputation (members carry their own).
- Discount/promo codes on bundles.
- Per-member partial refunds.
- Non-USD bundles.
