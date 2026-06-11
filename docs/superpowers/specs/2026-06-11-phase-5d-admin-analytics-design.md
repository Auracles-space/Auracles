# Phase 5d — Admin + Analytics (design spec)

## Context

Phase 5d completes the Admin module (FRD §FR-ADMIN-001..004): an analytics
dashboard, CSV export, a content-moderation queue, and user suspension. The admin
module already exists with config, role assignment, KYC review, framework
suspend, rarity-block override, license grant, escrow release/refund, and dispute
resolution (`app/modules/admin/router.py`). 5d extends it — no new module needed.
Final Phase 5 sub-phase.

Reuses: existing `AdminUser = require_role("admin")` + 2FA pattern, audit log,
Beat scaffolding, the current moderation signals on `artifact_rarity_audit`,
`artifacts`, and Framework pipeline metadata (`flagged_for_review`,
near-duplicate rarity state, `pii_review_needed`), Explore query exclusions,
Redis refresh-token revocation, and API key revoke once Phase 5a developer keys
exist.

## Locked decisions

| # | Decision | Value |
|---|---|---|
| 1 | Analytics compute | **On-demand aggregates** for current-state metrics + a **daily snapshot table** (Beat) for trend/history/CSV. No heavy materialization. |
| 2 | Suspend user | **Block access + freeze marketplace presence**, reversible. Suspended user can't authenticate (login/refresh/TOTP/realtime/API keys blocked; all authed requests → 403); their published frameworks/collections become unpurchasable + hidden from Explore. Existing buyers keep access to already-licensed artifacts; existing escrow/in-flight obligations are retained and can be resolved by admin if the suspended party cannot act. `unsuspend` restores marketplace visibility. Data retained. |
| 3 | Active-users metric | Derived from **distinct `audit_logs.actor_id` within the window** (no new per-request write). If audit coverage proves insufficient, a follow-up adds `users.last_active_at`; flagged for the coder. |
| 4 | GMV | Sum of **completed, non-refunded** USD gross marketplace transactions in the window. Include Framework purchases, released Project milestone transactions, Attestation fees, and future Collection purchases; exclude failed/refunded rows and refund rows. Dashboard also returns a by-source breakdown so product can separate marketplace lines. |
| 5 | CSV export | Synchronous streaming response of snapshot history + current totals (small dataset); no async/S3 job. |
| 6 | Suspend gate | Admin role + 2FA (sensitive, mirrors escrow override). |

## Schema

- **`analytics_daily_snapshots`** — `snapshot_date` DATE PRIMARY KEY,
  gmv_total NUMERIC(14,2), gmv_by_source JSONB NOT NULL DEFAULT `'{}'::jsonb`,
  active_users INT, new_registrations INT, frameworks_published INT,
  attestations_issued INT, disputes_open INT, computed_at TIMESTAMPTZ. One row
  per day (upsert). `gmv_by_source` keys start as `framework_purchase`,
  `project_milestone`, `attestation_fee`, and later `collection_purchase`.
- **Extend `users`** — add `suspended_at` TIMESTAMPTZ NULL, `suspended_by` UUID
  NULL FK users(id), `suspension_reason` TEXT NULL. INDEX (suspended_at) WHERE
  suspended_at IS NOT NULL. Suspension is separate from `deactivated_at`; a user
  can be active-but-suspended or self-deactivated without blurring audit reasons.

## Dashboard metrics (FR-ADMIN-001)

`GET /v1/admin/analytics/dashboard` returns current-state + a short trend series:
- **GMV** for today / last 7d / last 30d (completed non-refunded USD gross
  marketplace transactions) with by-source breakdown.
- **active_users** — distinct non-null `audit_logs.actor_id` in last 24h / 7d /
  30d.
- **new_registrations** — users created in window.
- **frameworks_published** — frameworks with `status='published'` (total + new in window).
- **attestations_issued** — attestations `status IN ('report_submitted','closed')` with non-null outcome in window.
- **disputes_open** — project + attestation disputes `status IN ('open','under_review')` (current count, plus optional by-source counts).
- **trend** — last 30 `analytics_daily_snapshots` rows (gmv + counts) for charts.

All read-only aggregates; admin-only. Money amounts are returned as strings or
minor-unit integers in API schemas to avoid float drift.

## Daily snapshot (Beat)

`snapshot_daily_analytics` (daily, just after midnight UTC): compute the prior
UTC day's GMV + counts and `INSERT ... ON CONFLICT (snapshot_date) DO UPDATE`
(idempotent; safe to re-run). Active_users for the day = distinct non-null audit
actors that day. Frozen history makes CSV + trend cheap and stable.

GMV query rules:
- Include `transactions.currency = 'USD'`, `status = 'completed'`, and
  `type IN ('purchase', 'milestone', 'attestation_fee')` at current code level.
  Add `collection_purchase` if Phase 5b-1 introduces a distinct transaction type;
  otherwise collection purchases remain `type='purchase'` with `ref_type`
  identifying the source.
- Exclude `type='refund'`, `status IN ('failed', 'refunded')`, and any original
  transaction flipped to `refunded`.
- For partial escrow splits, count only the completed release-side transaction
  amount. Do not count the original refunded funding row.

## Moderation queue (FR-ADMIN-003)

`GET /v1/admin/moderation/queue?type=&page=` aggregates existing flags into one
paginated view:
- Artifact rarity audit rows with `artifact_rarity_audit.flagged_for_review =
  true` (low-rarity / originality review queue).
- Frameworks hard-blocked or notice-flagged by near-duplicate rarity from current
  Framework metadata (`pipeline_failure_reasons.internal_rarity` and
  `pipeline_metadata.near_duplicate_blocked`) plus the linked Artifact rarity
  audit context.
- Artifacts with `artifacts.pii_review_needed = true`.
Each row carries the context needed to act, and the existing endpoints
(`suspend_framework`, `override_rarity_block`, Contributor PII resolve /
accept-redaction flow) are the actions — no new mutation endpoints here, just the
unified read + links. If reviewers need an admin-only "dismiss PII flag" action,
that becomes a later mutation slice; do not silently clear PII from this queue.

## Suspend / unsuspend (FR-ADMIN-004)

- `POST /v1/admin/users/{user_id}/suspend` (admin + 2FA, body `{reason}`): set
  `suspended_at/by/reason`; revoke all refresh tokens (Redis) + API keys
  (`api_keys.status='revoked'`); audit `user_suspended`.
- **Enforcement:** the auth dependency (`get_current_user`) rejects a user with
  `suspended_at IS NOT NULL` → 403 on every authenticated request; login,
  refresh-token rotation, TOTP completion, realtime auth, and settings session
  endpoints must also reject suspended accounts. The `X-API-Key` dependency
  likewise rejects keys of a suspended developer after Phase 5a. Explore catalog,
  contributor profile/detail pages, saved-search alert matching, and purchase
  initiation exclude frameworks/collections whose contributor is suspended.
- `POST /v1/admin/users/{user_id}/unsuspend` (admin + 2FA): clear suspension;
  marketplace presence restored; user can re-authenticate (must log in fresh —
  tokens were revoked). Audit `user_unsuspended`.
- Data fully retained; suspension is reversible and distinct from GDPR deletion.
- Guardrails: admin cannot suspend themselves; suspending the final active admin
  is blocked; repeated suspend/unsuspend is idempotent and audited without
  corrupting the original suspension metadata.

## API surface

| Verb | Path | Auth |
|---|---|---|
| GET | /v1/admin/analytics/dashboard | admin |
| GET | /v1/admin/analytics/export?from=&to= | admin (CSV stream) |
| GET | /v1/admin/moderation/queue | admin |
| POST | /v1/admin/users/{id}/suspend · /unsuspend | admin + 2FA |

## Security

- All endpoints `require_role("admin")`; suspend/unsuspend add 2FA.
- Suspend enforcement must cover **every** authenticated entry point: JWT auth
  dependency + login/refresh/TOTP + realtime + `X-API-Key` dependency +
  Explore/purchase visibility. A missed path = a suspended user still acting.
  Test each.
- Analytics expose aggregates only — no per-user PII beyond counts; CSV contains
  metrics, not personal records.
- CSV export accepts a bounded date range (recommend max 366 days) to avoid
  accidental large responses.
- Audit: `user_suspended`, `user_unsuspended`, `analytics_exported`,
  `moderation_queue_viewed`.
- Snapshot Beat + dashboard read-only; no money movement.

## Slice plan (~7)

1. Schema — `analytics_daily_snapshots` + `users.suspended_at/by/reason` + ORM
   + migration up/down smoke. Include indexes and a model docstring explaining
   UTC snapshot semantics.
2. Dashboard analytics — `GET /analytics/dashboard` on-demand aggregates
   (GMV/active/registrations/published/attestations/disputes) + shared aggregate
   helpers. Tests cover money source inclusion/exclusion and decimal-safe output.
3. Daily snapshot Beat — `snapshot_daily_analytics` idempotent upsert +
   `beat_schedule` entry + trend from snapshots. Tests cover UTC boundary,
   rerun idempotency, and partial escrow split GMV.
4. CSV export — `GET /analytics/export?from=&to=` streaming CSV of bounded
   snapshot history + current totals; audit export without logging CSV contents.
5. Moderation queue — `GET /moderation/queue` aggregating Artifact rarity audit
   flags + near-duplicate Framework flags + PII flags, paginated, with action
   links and no mutation side effects.
6. Suspend/unsuspend — endpoints (2FA) + `users.suspended_at` enforcement in JWT
   auth dep, login/refresh/TOTP/realtime, Phase 5a X-API-Key dep if present,
   Explore/contributor-profile/saved-search/purchase exclusion, token/key
   revocation; reversible.
7. OpenAPI sync + FE — admin dashboard (metrics + trend charts), moderation
   queue, user suspend/unsuspend control + E2E.

## Risk flags

- **Active-users signal:** depends on audit coverage of meaningful actions; if
  thin, add `users.last_active_at` (cheap middleware touch) — coder decides after
  checking audit volume.
- **Suspend enforcement completeness:** every auth path (JWT, login, refresh,
  TOTP, realtime, API key) + Explore visibility must honor suspension, and
  unsuspend must fully reverse. Highest risk — a missed path defeats the feature.
  Test exhaustively.
- **GMV definition:** exclude refunded/failed; include Framework purchases,
  released Project milestone transactions, Attestation fees, and future
  Collection purchases; USD only. Keep by-source breakdown so finance can audit
  what was counted.
- **Snapshot idempotency:** upsert on `snapshot_date`; re-running a day must not
  double count.
- **Timezone:** define the day boundary (UTC) consistently for snapshots + GMV
  buckets.
- **API key dependency:** Phase 5d may land before Phase 5a is implemented. If no
  developer API key table exists yet, leave a no-op integration seam and add a
  Phase 5a test when keys are introduced.
- **Moderation source drift:** queue must query the actual current tables:
  `artifact_rarity_audit.flagged_for_review`, Framework pipeline metadata, and
  `artifacts.pii_review_needed`; do not invent a `frameworks.flagged_for_review`
  column.

## Verification (after slice 7)

1. Backend: `uv run pytest --cov=app/modules/admin --cov=app/workers/tasks` (admin analytics + suspend) ≥ 80%. Cover GMV excludes refunds/failed rows and counts split releases correctly, snapshot upsert idempotency, moderation queue aggregates each real flag source, suspended user → 403 on JWT/login/refresh/realtime/API-key paths + hidden in Explore/profile/purchase, unsuspend restores.
2. Frontend: `corepack pnpm --dir frontend test` + `corepack pnpm --dir frontend exec playwright test tests/e2e/admin-analytics.spec.ts`.
3. Manual smoke: seed purchases/refunds → dashboard GMV matches non-refunded sum; run snapshot Beat twice → one row/day; export CSV → opens with metrics; flag a framework + a PII artifact → both appear in the queue; suspend a contributor → their login 403s, their API key 401s if Phase 5a keys exist, their frameworks vanish from Explore, existing buyers still access; unsuspend → restored.

## Out of scope (later)

- Real-time/streaming dashboards (daily snapshot + on-demand only).
- Cohort/funnel/retention analytics beyond the named metrics.
- Admin role granularity / sub-admin permissions.
- Bulk moderation actions.
- Scheduled/emailed analytics reports.
