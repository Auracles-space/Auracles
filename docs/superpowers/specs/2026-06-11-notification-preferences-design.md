# Notification Preferences (FR-SET-008) — design spec

## Context

The notification *delivery* system shipped in Phase 4a (`app/modules/notifications/`
+ `dispatch_project_notification`: in-app DB row + WS push + email). Product
notifications currently fire every supported channel for every event
unconditionally — FR-SET-008 ("configure notification preferences by channel
(email, in-app) and by event type") was never built. Several Phase 5 specs
(notably 5b-2 saved searches) already assume a preference check exists. This spec
closes that gap. Small, Settings-module-scoped.

Reuses: the existing notifications dispatch path (`app/workers/tasks/
project_notifications.py`), transactional email tasks that must remain ungated
(`app/workers/tasks/notifications.py`), the settings module
(`app/modules/settings/*`, which already hosts KYC + sessions),
`notification_type_enum`, audit.

## Locked decisions

| # | Decision | Value |
|---|---|---|
| 1 | Model | `notification_preferences` table keyed (user_id, notification_type, channel) → enabled bool. Notification types map to user-facing **categories** only for grouping in the Settings UI; storage and enforcement stay event-type based to satisfy FR-SET-008. |
| 2 | Default | **Opt-out**: a missing row means enabled. No backfill; preferences are created lazily on first toggle. |
| 3 | Critical always-on | A fixed set of notification types bypasses preferences entirely (non-toggleable, enforced server-side): payout, escrow, account-deletion, dispute resolution, and other legally/financially required platform events. Auth/security emails such as verification, password reset, 2FA, and new-device login are not product notifications and bypass this system entirely. |
| 4 | In-app suppression | Disabling the `in_app` channel for an event type **skips the DB row + WS push** for that event (nothing in the bell). Disabling `email` skips the email only. Category toggles, if exposed, expand into per-event updates server-side. |
| 5 | Enforcement | A single `should_deliver(user_id, notification_type, channel)` gate, called in **every** product-notification dispatch path before each channel's side effect. |
| 6 | Out of scope | Transactional/security emails (verification, password reset, 2FA, new-device) are NOT notifications — always sent, never gated. |

## Categories + mapping

`notification_category_enum`: `project | attestation | financial | discovery |
account`. A code constant `NOTIFICATION_TYPE_CATEGORY: dict[str, Category]` maps
every `notification_type` to one category for display. **Critical** types sit in a
`CRITICAL_NOTIFICATION_TYPES` set checked before preferences.

- Unmapped new type → **fail-open to enabled** + a default category (`account`),
  and a test asserts every enum value has a mapping (so a new type cannot
  silently slip the map in normal development).
- Critical examples: payout/escrow completion and failure events, dispute
  resolution events, account-deletion completion/failure events, and admin/legal
  notices once those notification types exist. Critical types always deliver on
  every channel supported by the dispatch path. Do not invent in-app rows for
  auth-only transactional emails.
- `saved_search_alert` from Phase 5b-2 maps to `discovery` and is user-toggleable.

## Schema

- **`notification_preferences`** — id UUID PK, user_id FK, notification_type
  `notification_type_enum`, category `notification_category_enum`, channel
  `notification_channel_enum` (email|in_app), enabled BOOL NOT NULL, created_at,
  updated_at. UNIQUE (user_id, notification_type, channel). INDEX (user_id,
  notification_type). Absent row ⇒ enabled (opt-out default).
- `category` is denormalized from `NOTIFICATION_TYPE_CATEGORY` for easier Settings
  reads and grouped updates. Service code must validate that stored category
  matches the mapping during writes; migrations can repair category values if the
  mapping changes.

No change to `notifications`. `notification_type_enum` changes only when another
phase adds a new product notification type such as `saved_search_alert`; this
preference spec must include that new type in the mapping when present.

## Enforcement

Add `should_deliver(db, user_id, notification_type, channel) -> bool`:
- if `notification_type` is critical → return True (bypass).
- else look up the `(user_id, notification_type, channel)` row; missing → True;
  else its `enabled`.

Wire into the dispatch impl (`_dispatch_project_notification_impl`):
- resolve `category` from the notification type.
- **in_app:** create the DB row + `publish_to_channel` only if
  `should_deliver(..., notification_type, 'in_app')`.
- **email:** `send_project_notification_email.delay(...)` only if
  `should_deliver(..., notification_type, 'email')`.
- If both channels are disabled, return `{"status": "suppressed"}` without
  creating a DB row, publishing WS, or queueing email.
- If `in_app` is disabled but email is enabled, send the email without creating a
  durable notification row. The task result should reflect `in_app_suppressed` so
  tests and logs can distinguish this from duplicates.
- Apply the same gate in the saved-search alert sender (5b-2) and any other path
  that emails/creates product notifications. Direct calls to
  `notification_service.create_notification` should remain internal to gated
  dispatchers; tests should grep/inspect call sites so future direct use fails
  review.

Note: dispatch is a Celery task → `should_deliver` runs in the task's own DB
session.

## API (Settings)

| Verb | Path | Auth |
|---|---|---|
| GET | /v1/settings/notification-preferences | self |
| PATCH | /v1/settings/notification-preferences | self |

- **GET** returns the full effective matrix grouped by category: every
  `(notification_type × channel)` with its effective `enabled` (default true
  where no row), display labels, descriptions, and `locked: true` for critical
  types (UI shows them on + disabled).
- **PATCH** body: list of `{notification_type, channel, enabled}` → upsert rows.
  Reject attempts to disable a critical notification type (422). Owner-only.
- Optional grouped toggle: the backend may accept `{category, channel, enabled}`
  only as a convenience that expands server-side to all non-critical event types
  in that category. The persisted rows remain per-event-type.

## Module layout

```
backend/app/modules/notifications/
├── preferences.py    # category map, CRITICAL set, should_deliver(), matrix builder
├── models.py         # + NotificationPreference
└── schemas.py        # + preference request/response
backend/app/modules/settings/router.py   # + 2 endpoints (delegate to notifications.preferences)
backend/app/workers/tasks/project_notifications.py  # wire should_deliver into dispatch
backend/app/workers/tasks/notifications.py          # transactional emails stay ungated
```

## Security

- Preferences owner-scoped; no cross-user access.
- Critical-always enforced **server-side** in `should_deliver` — UI locking is
  cosmetic; the gate never lets a critical notification be suppressed.
- Transactional/security emails bypass this system entirely (separate senders).
- Do not log preference matrices or email addresses; log user_id, changed counts,
  and notification_type/channel keys only.
- Audit `notification_preferences_updated`.

## Slice plan (~4)

1. Schema + mapping — `notification_preferences` table +
   `notification_channel_enum` + `notification_category_enum` + ORM + migration;
   `preferences.py` with the type→category map, `CRITICAL_NOTIFICATION_TYPES`,
   labels/descriptions, and `should_deliver`. Test: every
   `notification_type_enum` value is mapped; critical bypass; missing-row default.
2. Preferences API — GET (effective matrix + locked flags) + PATCH (upsert, reject
   disabling critical event types) in the settings module. Owner-scoped tests.
3. Enforcement — wire `should_deliver` into `_dispatch_project_notification_impl`
   (per-channel in-app + email gating) and the saved-search alert sender; critical
   bypass. Tests: disabled email → no email task; disabled in-app → no DB row/WS
   but email still sends if enabled; both disabled → suppressed; critical → all
   supported channels regardless.
4. OpenAPI sync + FE — Settings → Notifications preference matrix (toggles, locked
   critical rows, grouped by category) + E2E (toggle off email for
   `saved_search_alert`, trigger a saved-search alert → in-app present, no email).

## Risk flags

- **Gate coverage:** every path that creates a notification or sends a
  notification email must call `should_deliver`. Enumerate call sites; add a test
  that fails if a new dispatch path skips the gate.
- **Unmapped types:** fail-open to enabled + assert-all-mapped test prevents a
  new type from being silently ungated or dropped.
- **Critical bypass server-side:** never trust the client; `should_deliver`
  returns True for critical before any preference lookup.
- **Don't gate transactional emails:** verification/reset/2FA are not routed
  through this system.
- **FRD granularity:** storage is per event type. Categories are display/grouping
  only; do not regress to category-only persistence.

## Verification (after slice 4)

1. Backend: `uv run pytest --cov=app/modules/notifications --cov=app/modules/settings` ≥ 80%. Cover: all-types-mapped, missing-row default-enabled, PATCH reject critical-disable, dispatch gating per channel, both-channel suppression, critical bypass.
2. Frontend: `corepack pnpm --dir frontend test` + `corepack pnpm --dir frontend exec playwright test tests/e2e/notification-preferences.spec.ts`.
3. Manual smoke: open Settings → Notifications (critical rows shown locked-on); disable email for `saved_search_alert`; trigger a saved-search alert → in-app notification appears, no email sent; disable in-app for a project event → no bell entry but email still sends if enabled; verify a payout/escrow critical notification ignores all toggles.

## Out of scope (later)

- Per-role default templates or organization-wide preference policies.
- Quiet hours / digest batching of in-app notifications.
- Push/SMS channels.
- Per-saved-search alert frequency (lives in 5b-2).
