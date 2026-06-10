# Phase 3 — Transactions & Financials (Sliced)

**Date:** 2026-06-09
**Phase:** 3 (Transactions & Financials)
**Maps to:** FR-FIN-001..014, BR-FIN-001..005, TDD §3 (transactions/licenses/escrows/payouts/payout_accounts), TDD §9 (webhooks, payout Celery), CLAUDE.md Phase 3 build sequence
**Cross-cuts:** extends the Phase 2 `licenses` foundation into paid purchases; provides EscrowService consumed by Phase 4 Projects/Attestation.

---

## 1. Goals

Turn purchase intent into real money. Ship:

- Stripe integration for checkout, refunds, Connect onboarding, and payouts.
- Purchase flow (PaymentIntent → webhook → License grant).
- Self-serve refund within 48 hours, gated by zero downloads.
- Contributor payout pipeline: provider-hosted onboarding → request with KYC + 2FA → Celery transfer → webhook completion.
- Earnings dashboard with refund-safe `available` balance.
- Escrow infrastructure (hold/release/refund + admin override) consumed by Phase 4.
- Invoice PDF generation via WeasyPrint in a Celery task.
- Webhook idempotency via `webhook_events` table.
- Admin config endpoints for commission rate, payout thresholds, refund window.

---

## 2. Architectural decisions (locked)

| Decision                          | Value                                                                                                                                                                | Rationale                                                                                                                                                                           |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `license_type_enum`               | Keep existing `single_user, team, enterprise`; add `organizational` additively                                                                                       | Avoids breaking Phase 2 licenses/admin grants/library downloads while expanding the commercial model. `white_label` is deferred until custom contract/resale-rights support exists. |
| Invoice format                    | WeasyPrint PDF in a Celery task, stored in S3, served via presigned URL                                                                                              | Real PDF without external service. Cairo/Pango added to worker image only.                                                                                                          |
| Payout onboarding                 | Provider-hosted — Stripe Connect Express                                                                                                                             | Stripe runs hosted onboarding/KYC. We store `provider_ref` only; no bank-detail forms.                                                                                             |
| Refund trigger                    | Self-serve Operator button, eligibility-checked                                                                                                                      | `< 48h` AND `artifact_downloads == 0`. Provider refund API called inline.                                                                                                           |
| Reviews wiring (FR-FWK-014)       | Defer — Phase 2 schema stays dormant                                                                                                                                 | Reduces Phase 3 scope; closes in a later polish phase.                                                                                                                              |
| Escrow scope                      | Migration + `EscrowService.hold/release/refund` + admin override endpoints + tests                                                                                   | Phase 4 calls the service. Webhook routes funding events tagged `metadata.kind == "escrow"`.                                                                                        |
| Webhook idempotency               | Dedicated `webhook_events` table, UNIQUE `(provider, provider_event_id)`, status `received/processed/failed`                                                         | Durable audit + dedupe. Replays return 200, no side effects.                                                                                                                        |
| `available` balance formula       | `sum(completed purchases where created_at < now() - refund_window_hours) − commission(15%) − sum(paid out)`                                                          | Refund-safe; no clawback path needed. Pending balance = sales inside the window.                                                                                                    |
| Currency                          | USD only for Phase 3 MVP                                                                                                                                              | Team decision on 2026-06-09: Stripe-only for MVP. NGN/Paystack is deferred, so no FX conversion is implemented.                                                                     |
| Partner API / Developer Platform  | Deferred to Phase 5                                                                                                                                                  | Per CLAUDE.md phase plan.                                                                                                                                                           |
| Self-serve checkout license types | `single_user`, `team`, `organizational`                                                                                                                              | `enterprise` remains admin/custom-grant for now. `white_label` remains out of scope.                                                                                                |
| KYC gate                          | Required for: payout onboarding, payout request, escrow funding (Phase 4 consumers), artifact download (Phase 1 deviation). **Not** required for purchase or refund. |
| 2FA gate                          | Required for: payout request, payout-account changes (BR-FIN-005), admin escrow override, admin config change.                                                       |
| Commission                        | Deducted at payout, not at sale (BR-FIN-001). Default 15%, in `platform_config`.                                                                                     |
| Minimum payout                    | $50 USD — configurable in `platform_config`.                                                                                                                         |

---

## 3. New & extended schema (Slice 1)

**New tables**

- `transactions(id, payer_id, payee_id?, amount, currency, platform_commission, net_amount, type, status, provider, provider_ref, ref_id?, ref_type?, created_at, updated_at)`
- `escrows(id, ref_id, ref_type, amount, currency, status, release_conditions JSONB, transaction_id, held_at, released_at?, released_by?)`
- `payouts(id, contributor_id, payout_account_id, amount, currency, commission_deducted, net_amount, status, provider_ref, initiated_at, completed_at?)`
- `payout_accounts(id, user_id, provider, provider_account_id, type, is_default, verified_at?, created_at, deleted_at?)` — `provider_account_id` encrypted at rest
- `webhook_events(id, provider, provider_event_id, event_type, status, payload_hash, received_at, processed_at?, error?)` — UNIQUE `(provider, provider_event_id)`

**Extended tables**

- `users` — add `stripe_customer_id` (nullable, indexed) — created on first Operator card-add.
- `licenses` — existing Phase 2 table remains in `frameworks.models`; add FK to `transactions(id)` when purchase flow lands, keep `transaction_id` nullable for existing/admin grants, and expand `license_type_enum` additively with `organizational`.
- `platform_config` — seed rows: `commission_rate=0.15`, `min_payout_usd=50`, `min_payout_ngn=20000`, `refund_window_hours=48`.

**New enums:** `transaction_type_enum`, `transaction_status_enum`, `payment_provider_enum`, `escrow_status_enum`, `payout_status_enum`, `webhook_event_status_enum`.

**Existing enum extensions:** `license_type_enum` add value `organizational`. Do not rename `single_user`, do not recreate `license_type_enum`, and do not add `white_label` in Phase 3.

---

## 4. Module layout

```
backend/app/
├── modules/
│   ├── financials/
│   │   ├── router.py
│   │   ├── service.py            # purchase, payment-methods, payout-accounts, earnings, payouts, refunds
│   │   ├── escrow_service.py     # hold / release / refund (slice 9)
│   │   ├── models.py             # Transaction, Escrow, Payout, PayoutAccount
│   │   └── schemas.py
│   └── webhooks/
│       ├── router.py             # /v1/webhooks/stripe
│       ├── service.py            # dedupe via webhook_events, dispatch by event type
│       ├── handlers/             # one file per event type
│       │   ├── stripe_payment_intent.py
│       │   ├── stripe_account.py
│       │   └── stripe_transfer.py
│       ├── models.py             # WebhookEvent
│       └── schemas.py
└── integrations/
    └── stripe.py                 # create_customer, create_payment_intent, create_refund, create_express_account, create_account_link, create_transfer, verify_webhook
```

---

## 5. Slice plan (14 slices)

Working agreement per slice (unchanged from Phase 1/2): one-line summary → file list → failing test → minimum impl → `ruff` + `mypy --strict` + `pytest --cov` green + Alembic up/down green → stop for human review/commit.

### Slice 1 — Schema foundation + platform_config seed

Migrations (new financial enums/tables, additive `license_type_enum` value `organizational`, existing `licenses.transaction_id` FK to `transactions`, `users.stripe_customer_id`, seed rows). ORM models. Empty module dirs. Migration up/down test + seed assertion. `License` stays in `frameworks.models`; financials imports/updates it.

### Slice 2 — Provider integration layer (no endpoints)

`stripe.py`. Production validator rejects placeholder Stripe secrets. Unit tests via `respx` + signature verify matrix.

### Slice 3 — Payment methods (Operator)

`POST/GET/DELETE /v1/financials/payment-methods`. Creates Stripe Customer on first add and returns a Stripe SetupIntent so the browser can attach a provider-held payment method. No PAN ever stored. RBAC: Operator role. Audit `payment_method_added/removed`.

### Slice 4 — Payout accounts (Contributor) + onboarding

`POST /v1/financials/payout-accounts/onboard` (KYC-required) → Stripe Express account link creation. `GET` list. `DELETE` (2FA-required) soft-deletes. Audit each transition.

### Slice 5 — Purchase flow

`POST /v1/financials/purchase/{framework_id}` validates selected self-serve license type (`single_user`, `team`, `organizational`), creates `transactions(status=pending)`, calls provider `create_payment_intent` with `metadata={transaction_id, kind:"purchase"}`. Returns `{transaction_id, client_secret, provider}`. License **only** created in Slice 6 webhook handler. `enterprise` remains admin/custom-grant and is not exposed in checkout.

### Slice 6 — Webhooks (Stripe)

`POST /v1/webhooks/stripe`. Signature verify before any DB write. Insert `webhook_events(status=received)`. Dispatch by `event_type`. Replay returns 200, no side effects. Handlers wrapped in `async with db.begin()`. Escrow funding branch stubs into `EscrowService.hold` (full impl in Slice 9).

### Slice 7 — Self-serve refund

`POST /v1/financials/purchases/{transaction_id}/refund`. Eligibility: txn `completed`, type `purchase`, owner, `now − created_at < refund_window_hours`, `artifact_downloads.count == 0`. On pass: provider refund call + mark `refunded` + license `revoked` + audit. Stripe `charge.refunded` webhook becomes idempotent ack.

### Slice 8 — Purchase history + invoice PDF

`GET /v1/financials/purchases` (paginated). `GET /v1/financials/purchases/{id}/invoice` (302 to presigned S3, 202 if not yet generated). Celery task `generate_invoice_pdf` renders Jinja2 → WeasyPrint → S3. Worker image adds Cairo + Pango + GDK-PixBuf.

### Slice 9 — Escrow service + admin override

`EscrowService.hold/release/refund`, idempotent. Admin endpoints `POST /v1/admin/escrows/{id}/release` and `…/refund` (admin role + 2FA + reason). Webhook handler now calls real `hold(...)`. Audit `escrow_*` events; mismatches CRITICAL.

### Slice 10 — Earnings dashboard + payout request + Celery payout

`GET /v1/financials/earnings` (computed via SQL against `refund_window_hours`). `POST /v1/financials/payouts` (KYC + 2FA, ≥ min). `GET /v1/financials/payouts`. Celery `process_payout` calls provider transfer; webhook flips to `completed`/`failed`. Beat job `clear_expired_licenses` daily.

### Slice 11 — Admin config + dispute polish

`GET /v1/admin/config`, `PATCH /v1/admin/config` (admin + 2FA + reason; whitelist of keys + ranges). Audit each change. Wire admin escrow endpoints into FE admin shell if it exists; else backend-only.

### Slice 12 — OpenAPI sync + FE codegen + helpers

Update `contracts/openapi.yaml` for all new paths. Regenerate `frontend/src/lib/generated/`. FE helper `stripe-client.ts` (publishable key from env).

### Slice 13 — FE Operator (mobile-first)

Pages: `checkout/[framework_id]`, `library`, `settings/payment-methods`. Components: `CheckoutForm` (self-serve license choices: `single_user`, `team`, `organizational`), `PurchaseHistoryTable`, `RefundButton`, `PaymentMethodList`. E2E `purchase.spec.ts` per CLAUDE.md Phase 6 critical flow.

### Slice 14 — FE Contributor (mobile-first)

Pages: `dashboard/earnings`, `dashboard/payouts`, `settings/payout-accounts`. Components: `EarningsSummary`, `PayoutRequestModal` (TOTP challenge), `PayoutAccountConnect`, `PayoutHistoryTable`. E2E `financials.spec.ts` per AGENT.md Phase 6 critical flow.

---

## 6. Webhook event matrix

| Provider | Event                           | Handler effect                                                                                                                                                           |
| -------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Stripe   | `payment_intent.succeeded`      | If `metadata.kind == "purchase"` → mark txn completed + create License; if `kind == "escrow"` → `EscrowService.hold(...)`. Audit `purchase_completed` / `escrow_funded`. |
| Stripe   | `payment_intent.payment_failed` | Mark txn failed. Audit `purchase_failed`.                                                                                                                                |
| Stripe   | `charge.refunded`               | Idempotent ack (refund already updated by Slice 7 inline call).                                                                                                          |
| Stripe   | `account.updated`               | If `charges_enabled && payouts_enabled`, flip `payout_accounts.verified_at`.                                                                                             |
| Stripe   | `transfer.paid`                 | Mark payout completed; audit `payout_completed`.                                                                                                                         |
| Stripe   | `transfer.failed`               | Mark payout failed; audit `payout_failed`.                                                                                                                               |

All other events: insert `webhook_events(status=received)` and return 200. Unknown event types audited at WARNING per CLAUDE.md logging table.

---

## 7. Security gates

- **Webhook signature verification** before any parse or DB write. Stripe via `Stripe-Signature`. Failure → 400 + audit.
- **DB transactions** wrap every multi-table write (purchase + license, refund + license-revoke, escrow hold/release, payout + txn pair).
- **No PAN** in our codebase; Stripe Elements tokenizes client-side.
- **Provider secrets** validated at startup (placeholder values rejected outside `environment=local`, mirroring `SECRET_KEY` and `TOTP_ENCRYPTION_KEY` validators from Phase 1).
- **2FA** required for payout request, payout-account delete, admin escrow override, admin config patch. Uses the Phase 1 `verify_totp_login` challenge pattern; challenge consumed once.
- **KYC** required for payout onboarding, payout request, and Phase 4 escrow funding. Not required for purchase or refund (per Phase 1 deviation table).
- **Provider refs** never logged in plaintext beyond last-4. Invoice URLs are presigned and short-lived (15 min).
- **Idempotency** keyed by `(provider, provider_event_id)` for webhooks, `transaction_id` for payouts, `escrow_id` for releases.

---

## 8. Risk flags

- **Stripe Connect Express vs Custom:** Express chosen; Stripe owns onboarding dashboard. Cheaper compliance.
- **Paystack/NGN rails deferred:** Team decision on 2026-06-09 is Stripe-only for Phase 3 MVP. Keep Paystack out of active checkout, webhook, and payout slices until a later regional-payments phase.
- **License enum migration:** add `organizational` only. Existing `single_user/team/enterprise` values stay valid to preserve Phase 2 grants, library access, and generated frontend contracts.
- **White-label licensing:** deferred because the app does not yet support resale/rebrand contract terms, approval workflow, or custom rights enforcement.
- **WeasyPrint image bloat:** worker image grows ~150 MB with Cairo + Pango. Acceptable for Render Background Worker tier.
- **48-hour refund + payout collision:** `available` formula excludes the window, so payouts can never include refundable sales. Regression-tested in Slice 10.
- **Currency rounding:** all amounts NUMERIC(12,2). Stripe expects integer minor units — provider wrappers normalise consistently.
- **2FA replay on payout:** payout endpoint requires fresh TOTP challenge token consumed once, like login 2FA.
- **PCI scope:** SAQ-A applicable; we never see PANs. Documented for ops.

---

## 9. Verification (end-to-end after Slice 14)

1. `docker compose up` (api, db, redis, worker, beat, frontend).
2. Backend: `uv run pytest --cov=app/modules/financials --cov=app/modules/webhooks --cov=app/integrations` → ≥ 80% line coverage on touched modules.
3. Frontend: `pnpm test` (vitest) + `pnpm exec playwright test tests/e2e/purchase.spec.ts tests/e2e/financials.spec.ts`.
4. Manual smoke (Stripe test mode):
   - Operator buys framework via Stripe (US card) → library entry → artifact download → invoice PDF.
   - Operator refunds inside 48 h → status `refunded`, license `revoked`.
   - Contributor onboards Stripe Connect Express test account → webhook flips `verified_at`.
   - Contributor requests payout with TOTP code → Celery transfer → webhook completes payout.
   - Admin patches `commission_rate = 0.12` → audit log captures change.
   - Admin releases held escrow with reason → audit log captures override.

---

## 10. Out of scope (later phases)

- Reviews submission flow (FR-FWK-014) — schema dormant, wired in `2026-06-10-post-phase-4-marketplace-polish-backlog.md`.
- White-label licensing — requires contract terms, resale/rebrand rights, admin approval/quote flow, and stronger rights audit.
- Partner / Developer Platform commissions & tier upgrades — Phase 5 (FR-DEV-017..030).
- Projects + Attestation modules — Phase 4 (consumes `EscrowService` shipped here).
- Tax compliance, 1099/W-9 — separate compliance phase.
- Multi-currency beyond USD.
- Paystack / NGN payment and payout rails.
- ACH / wire transfer rails outside provider rails.
- GDPR-driven payout-account export — Phase 5 GDPR slice.
