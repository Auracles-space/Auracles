# Phase 5a — Developer Platform (design spec)

## Context

Phase 5a builds the Developer Platform / Partner API (FRD §FR-DEV-001..032,
BR-DEV-001..010): third parties register as Developers, generate scoped API keys,
read the marketplace catalog, drive purchases on behalf of buyers, earn
attributed commissions, receive signed outbound webhooks, and withdraw cleared
commissions. It is the first Phase 5 sub-phase brainstormed as a single spec on
explicit request, but internally decomposes into five build-ordered clusters.

Reuses heavily: the attestor application→profile→role pattern
(`app/modules/attestation/application_service.py`), Phase 3 purchase / escrow /
license / payout rails (`app/modules/financials/*`), Explore query surface
(`app/modules/explore/service.py`), inbound-webhook HMAC verification pattern
(`app/modules/webhooks/service.py`) adapted for **outbound** signing, Fernet
secret encryption stored as text (Phase 3 payout-account pattern), audit log, Beat scaffolding,
`platform_config` + admin-config UI.

No developer / api-key / partner tables exist yet. The current `role_enum` does
**not** include `developer`, so Slice 1 must extend the PostgreSQL enum before
admin approval can create `UserRole(role="developer")`. Financial payout accounts
can be reused, but the current `payouts` table is contributor-shaped
(`contributor_id` is required), so partner commission withdrawals need a separate
`partner_payouts` table while reusing provider adapters, 2FA checks, payout
accounts, and transfer processing helpers.

Current repo alignment, verified on 2026-06-11:
- Routers use module-local prefixes (`/developer`, `/partner`) and are mounted in
  `backend/app/main.py` with `prefix="/v1"`.
- Auth roles currently are `contributor`, `operator`, `attestor`, `admin`; add
  `developer` via Alembic enum migration.
- Payment provider scope is Stripe-only for this phase. Paystack references in
  the base TDD are historical and not part of this Phase 5a implementation.
- Frontend commands should use `corepack pnpm --dir frontend ...`, not bare
  `pnpm`, to match this environment.

## Locked decisions

| # | Decision | Value |
|---|---|---|
| 1 | Buyer identity | Partner-driven purchase grants the License to an **Auracles operator** (find-or-invite by email). Full reuse of License / presigned-artifact / refund. Commission attributed to the partner's API key. |
| 2 | Payout model | Separate `partner_commissions` ledger + cleared-commission balance, distinct from contributor earnings; withdrawals use a new `partner_payouts` table and reuse Phase 3 payout accounts, Stripe Connect provider adapter, 2FA, and transfer execution helpers. Do not overload the contributor-only `payouts` table. |
| 3 | Developer onboarding | Mirror attestor: `developer_applications` (company, website, use-case, status, admin_feedback) → admin review → `developer_accounts` + `developer` role (`UserRole.approved_at`). Slice 1 must add `developer` to `role_enum`. |
| 4 | API key storage | SHA-256 hash + prefix stored; **raw shown once** at creation (BR-DEV-001/002); scopes TEXT[]; optional expiry; revoke → instant 401 (BR-DEV-009). Auth via `X-API-Key` header dependency (hash lookup). |
| 5 | Commission economics | Deducted from **platform margin**, never the contributor's earnings (BR-DEV-003). Contributor always receives full net. Partner tier rate must be ≤ platform `commission_rate` (validated). Tiers 5/8/12% configurable (BR-DEV-004); rate **locked at sale** (BR-DEV-005); `pending → cleared` after 48h (BR-DEV-006); voided if the sale is refunded in-window. |
| 6 | Rate limiting | Redis (Upstash) sliding-window per key, default 60/min (FR-DEV-008), `429 + Retry-After`; notify at 80% threshold (FR-DEV-010). |
| 7 | Outbound webhooks | Per-partner HMAC-SHA256 secret (Fernet-encrypted at rest); events `purchase.confirmed`, `commission.cleared`, `framework.updated`; exponential backoff, max 5 attempts (FR-DEV-025); dead-letter + manual retry. |
| 8 | Tiers | Monthly Beat recompute from prior-30d attributed sales count → tier (BR-DEV-004). Thresholds/rates in `platform_config`, admin-tunable. |
| 9 | Currency | USD only (matches Phase 3/4 lock). |

## Schema (new tables)

- **`developer_applications`** — id, user_id FK, company_name, website, use_case
  TEXT, status `developer_application_status_enum` (pending|approved|rejected|
  withdrawn), admin_feedback TEXT NULL, reviewed_by FK NULL, reviewed_at NULL,
  created_at. Partial UNIQUE (user_id) WHERE status='pending'.
- **`developer_accounts`** — id, user_id FK UNIQUE, status (active|suspended),
  application_id FK UNIQUE, company_name, commission_tier SMALLINT DEFAULT 1
  CHECK IN (1,2,3), tier_rate NUMERIC(5,4), tier_sales_count INT DEFAULT 0,
  tier_recalculated_at NULL, approved_at, created_at, updated_at.
- **`api_keys`** — id, developer_account_id FK, name TEXT, key_prefix VARCHAR(12),
  key_hash VARCHAR(64) UNIQUE (sha256), scopes TEXT[], rate_limit_per_min INT
  NOT NULL DEFAULT 60, status (active|revoked), expires_at NULL, revoked_at NULL, last_used_at NULL,
  created_at. INDEX (developer_account_id), (key_hash).
- **`api_request_logs`** — id, api_key_id FK, endpoint TEXT, method VARCHAR(8),
  status_code INT, response_ms INT, ip INET NULL, created_at. INDEX
  (api_key_id, created_at DESC). High-volume → time-based retention/partition
  flagged (out of scope to partition now; add a prune Beat or retention policy).
- **`partner_commissions`** — id, api_key_id FK, developer_account_id FK,
  transaction_id FK (the purchase txn), framework_id FK, sale_amount
  NUMERIC(12,2), currency CHAR(3) DEFAULT 'USD', tier_at_sale SMALLINT,
  tier_rate NUMERIC(5,4), commission_amount NUMERIC(12,2),
  status `partner_commission_status_enum` (pending|cleared|paid|voided),
  cleared_at NULL, payout_id FK NULL to `partner_payouts.id`, created_at.
  UNIQUE (transaction_id). INDEX (developer_account_id, status), (status,
  created_at). Create the nullable `payout_id` FK after both tables exist if the
  migration order needs it.
- **`partner_payouts`** — id, developer_account_id FK, payout_account_id FK,
  amount NUMERIC(12,2), currency CHAR(3) DEFAULT 'USD', status
  `payout_status_enum` (pending|processing|completed|failed), provider_ref NULL,
  initiated_at, completed_at NULL, created_at. INDEX (developer_account_id,
  status), (payout_account_id).
- **`partner_webhooks`** — id, developer_account_id FK, url TEXT, secret_encrypted
  TEXT (Fernet), events TEXT[], active BOOL, created_at. INDEX (developer_account_id).
- **`partner_webhook_deliveries`** — id, partner_webhook_id FK, event_type,
  payload JSONB, status `webhook_delivery_status_enum` (pending|delivered|failed|
  dead), attempts INT DEFAULT 0, response_code INT NULL, last_attempt_at NULL,
  next_attempt_at NULL, created_at. INDEX (status, next_attempt_at).

**`platform_config` rows:** `partner_tier_thresholds` (JSON: tier→{min,max,rate}),
admin-tunable; `partner_min_payout_usd` (50); `partner_api_log_retention_days`
(90). Validate tier rates ≤ `commission_rate`, tier keys exactly `1|2|3`, ranges
non-overlapping, and rates non-negative.

**Migration note:** adding `developer` to the existing PostgreSQL `role_enum`
uses `ALTER TYPE role_enum ADD VALUE IF NOT EXISTS 'developer'`. Downgrade must
succeed for local test discipline by dropping the new developer tables/config
rows, but it may intentionally leave the enum value in place because removing a
Postgres enum value requires a table-rewrite migration and is unsafe once any
environment has seen the role. Document this in the migration docstring.

## Commission economics (worked)

Platform commission today = 15% (BR-FIN-001), taken from contributor gross at
payout; contributor nets 85%. On a partner-attributed sale, the partner's tier
rate (5/8/12%) is carved **out of the platform's 15%**, not added and not from
the contributor. Example, $100 sale, tier 2 (8%): contributor nets $85
(unchanged), partner earns $8, platform keeps $7. Validation: reject any tier
rate > current `commission_rate` (can't pay a partner more than the margin).
`partner_commissions.commission_amount = sale_amount × tier_rate` snapshotted at
sale. Cleared after 48h; voided if the sale refunds in-window.

## Partner purchase flow (FR-DEV-017..021)

1. `POST /v1/partner/frameworks/{framework_id}/purchase` (scope
   `purchase:write`, body `{buyer_email, license_type}`) → find-or-invite
   operator (existing user by email
   or create an invited operator account) → create `transactions(type=purchase,
   status=pending)` + Stripe PaymentIntent with `metadata={kind:"purchase",
   transaction_id, api_key_id, tier_rate:<locked>}` → return `{transaction_id,
   client_secret}` for the partner to complete on their platform.
2. Partner completes payment; Phase 3 webhook `payment_intent.succeeded` fires.
   **Extend the existing purchase-succeeded handler**: after the License is
   created, if the txn metadata carries `api_key_id`, insert a
   `partner_commissions` row (status=pending, amounts from the locked tier_rate).
3. `GET /v1/partner/purchases/{transaction_id}` status endpoint for polling. The
   endpoint only returns transactions attributed to the same API key/developer.
4. Refund within 48h (existing self-serve refund) → void the linked commission.
5. Invited buyers receive an email invitation/receipt. Artifact access still
   requires the buyer to verify email, authenticate as that operator account, and
   pass the existing license download path; the partner never receives licensed
   artifact URLs on behalf of the buyer.

Invited-operator creation must respect the current `users` constraints:
`password_hash` may be NULL, but `display_name` is required. Create a clearly
invited, email-unverified user with an approved `operator` role, send the invite,
and require normal email verification / password setup before any authenticated
library or artifact-download action.

## Module layout

```
backend/app/modules/developer/
├── router.py            # /developer/* (account, keys, earnings, tiers, webhooks, analytics, payouts)
├── partner_router.py    # /partner/* (X-API-Key auth: catalog, detail, preview, attestations, purchase)
├── application_service.py # apply/withdraw + admin review → account + role
├── keys_service.py      # generate/list/label/revoke, hash, prefix
├── auth.py              # X-API-Key dependency: hash lookup, revoked/expiry, scope, rate limit
├── partner_service.py   # catalog reads (reuse explore), purchase initiate + find-or-invite
├── commission_service.py# attribution, clearing, tier compute, payout (separate balance, shared rails)
├── webhooks_service.py  # register + sign + enqueue + deliver + retry
├── analytics_service.py # usage (api_request_logs) + sales (partner_commissions)
├── models.py
├── schemas.py
└── dependencies.py
backend/app/workers/tasks/
├── partner_webhooks.py  # deliver_partner_webhook (HMAC, retry backoff, dead-letter)
└── developer_beat.py    # clear_partner_commissions (48h), recompute_partner_tiers (monthly), prune_api_request_logs
```

## API surface (summary)

| Verb | Path | Auth |
|---|---|---|
| POST | /v1/developer/applications | any auth user |
| GET | /v1/developer/applications/mine | self |
| GET/POST | /v1/admin/developer/applications, .../{id}/review | admin + 2FA |
| POST/GET/DELETE | /v1/developer/api-keys (+ /{id}) | developer |
| GET | /v1/developer/earnings, /tiers, /payouts, /analytics/usage, /analytics/sales | developer |
| POST | /v1/developer/payouts | developer + 2FA |
| POST/GET/DELETE | /v1/developer/webhooks (+ /{id}), .../{delivery_id}/retry | developer |
| GET | /v1/partner/catalog, /catalog/{id}, /catalog/{id}/preview, /catalog/{id}/attestations | X-API-Key (read scopes) |
| POST | /v1/partner/frameworks/{framework_id}/purchase | X-API-Key (purchase:write) |
| GET | /v1/partner/purchases/{txn_id} | X-API-Key (purchase:write) |

## Celery / Beat

| Task | Cadence | Action |
|---|---|---|
| `clear_partner_commissions` | hourly | pending → cleared past 48h with non-refunded sale; void if refunded. |
| `recompute_partner_tiers` | monthly | prior-30d attributed sales count → tier per developer (BR-DEV-004). |
| `deliver_partner_webhook` | on event + retry | HMAC-sign, POST, exp backoff, max 5 → dead. |
| `prune_api_request_logs` | daily | retention trim (configurable horizon). |
| `notify_rate_limit_threshold` | inline/Celery once per key per window (on 80%) | FR-DEV-010 notification with Redis throttle to prevent notification spam. |

## Security

- `X-API-Key` dependency: SHA-256 hash lookup; **revoked → 401 immediately**
  (BR-DEV-009); expired → 401; scope check per endpoint; rate-limit (Redis
  sliding window) → 429 + Retry-After. Raw key never stored; shown once.
- Partner artifact access still goes through the licensed presigned-URL path —
  unlicensed download via partner → **403** (BR-DEV-008). No bypass.
- Webhook secrets Fernet-encrypted; outbound payloads HMAC-SHA256 signed
  with `X-Auracles-Timestamp` + `X-Auracles-Signature`, where the signature is
  computed over `{timestamp}.{raw_body}`. Partners reject stale timestamps
  (recommended 5-minute tolerance) before processing (BR-DEV-010).
- Payout 2FA + $50 min (BR-DEV-007). Admin application review 2FA.
- Partner payout balance is computed from `partner_commissions.status='cleared'`
  minus commissions already attached to non-failed `partner_payouts`. Use row
  locks or serializable transaction boundaries around payout creation so two
  concurrent requests cannot overdraw cleared commission.
- Every write in `async with db.begin()`; `with_for_update()` on commission /
  payout rows. Audit: developer_application_*, api_key_created/revoked,
  partner_purchase_initiated, partner_commission_created/cleared/voided,
  partner_tier_recalculated, partner_payout_requested, partner_webhook_*.
- `api_request_logs` records endpoint/status/latency/ip per FR-DEV-009 (no secrets/raw key). Invalid-key attempts that cannot be linked to an `api_key_id` are written to the security audit log instead of this table.
- Outbound webhook URL validation must allow only `https://` in staging/prod and
  block localhost, loopback, private RFC1918, link-local, and metadata IP ranges
  after DNS resolution. Re-check the resolved IP at delivery time, not only at
  registration.

## Slice plan (~14)

1. Schema foundation — all 8 developer/partner tables + enums + `role_enum` value `developer` + `platform_config` tier seeds + ORM + migration up/down smoke.
2. Developer application + admin review — apply/withdraw/mine, admin approve(→account+`developer` role)/reject+feedback, 2FA. Mirror attestor.
3. API key lifecycle — generate (raw-once, prefix, sha256 hash), list/label, revoke; scopes validated against the known set.
4. `X-API-Key` auth dependency + scope enforcement + Redis rate limit + `api_request_logs` middleware + 80% threshold notify.
5. Partner API read — catalog/detail/preview/attestations reusing Explore queries. Preview returns only the contributor-designated preview artifact; it never returns full licensed artifacts. Attestations return public report metadata/status only, never private evidence files, escrow data, or internal dispute notes.
6. Partner purchase initiate — `POST /v1/partner/frameworks/{framework_id}/purchase`, find-or-invite operator, PaymentIntent with api_key + tier_rate attribution; status endpoint.
7. Purchase webhook confirm + commission attribution — extend Phase 3 `payment_intent.succeeded` handler to create `partner_commissions` (pending) when txn carries key attribution; refund-in-window voids it.
8. Commission clearing Beat — `clear_partner_commissions` (48h, refund-void), idempotent.
9. Commission tiers — `recompute_partner_tiers` monthly Beat + rate-at-sale lock + tier display/progress.
10. Partner payout — separate cleared-commission balance + `POST /v1/developer/payouts` (2FA, $50, reuse payout_accounts + provider transfer helper, write `partner_payouts`) + history.
11. Outbound webhooks — register (encrypted secret) + `deliver_partner_webhook` Celery (HMAC, exp backoff max 5, dead-letter) + manual retry.
12. Analytics — usage (api_request_logs aggregates) + sales (partner_commissions aggregates).
13. OpenAPI sync + FE developer portal — apply, keys, earnings/tiers, webhooks, analytics, payout (mobile-first).
14. E2E — apply→approve→key→catalog read→partner purchase→commission pending→clear→payout; webhook delivery + signature verify.

## Risk flags

- **Commission vs platform margin:** validate tier rate ≤ `commission_rate` at sale and on tier/config change; never let partner commission exceed margin or touch contributor net. Highest money-risk — test explicitly (mirror the 4a/4b earnings discipline).
- **Find-or-invite operator:** invited-but-unactivated operator may own a license, but must not receive artifact access until email verification + authenticated operator session. The partner only receives purchase status, never licensed artifact URLs.
- **`api_request_logs` volume:** can grow fast; ship with a retention prune; partition later if needed.
- **Outbound webhook SSRF:** partners supply the URL — validate scheme/host, block internal/loopback ranges before delivery.
- **Rate-limit accuracy under concurrency:** Redis sliding-window must be atomic (Lua / INCR+EXPIRE) to avoid races.
- **Key attribution integrity:** tier_rate snapshot must travel in PaymentIntent metadata and be re-validated server-side at commission creation, not trusted from the client.
- **Partner read leakage:** partner detail/preview/attestation endpoints must reuse the public Explore visibility rules plus explicit artifact/report gating. Only published Frameworks are returned; private evidence and non-preview artifacts are never exposed through Partner API reads.

## Verification (after slice 14)

1. Backend: `uv run pytest --cov=app/modules/developer --cov=app/workers/tasks/partner_webhooks --cov=app/workers/tasks/developer_beat` ≥ 80%.
2. Frontend: `corepack pnpm --dir frontend test` + `corepack pnpm --dir frontend exec playwright test tests/e2e/developer.spec.ts`.
3. Manual smoke (Stripe test mode): apply→admin approve→generate key (raw shown once; second view shows prefix only)→catalog read with scope (wrong scope→403; revoked key→401; >60/min→429)→partner purchase (buyer operator invited, license granted)→commission pending→fast-forward 48h→`clear_partner_commissions`→cleared→request payout (2FA, ≥$50)→Stripe transfer. Register webhook→trigger purchase.confirmed→partner endpoint receives signed payload→verify HMAC; force failures→retries→dead-letter→manual retry. Refund a sale in-window→commission voided. Run monthly tier recompute→tier rate updates for future sales only.

## Out of scope (later)

- Non-USD partner sales.
- Partner-side white-label catalog UI.
- Per-framework partner allow/deny lists.
- Real-time streaming usage analytics (batch/aggregate only here).
- Reputation-driven partner ranking.
