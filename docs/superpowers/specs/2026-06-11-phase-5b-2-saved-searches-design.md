# Phase 5b-2 — Saved Searches + Alerts (design spec)

## Context

Operators save an Explore search (filters + keywords) under a name, optionally
enable email alerts for newly-published matching Frameworks, and manage them from
Settings (FRD §FR-SRCH-001..003). Second half of Phase 5b "Discovery polish";
Collections (FR-COL) is the separate 5b-1 spec. Small, self-contained.

Reuses the Explore filter/query builder (`app/modules/explore/service.py`,
`app/modules/explore/schemas.py`), the notifications module + Resend email task
(`app/workers/tasks/notifications.py`), Beat scaffolding, audit. No saved-search
tables exist yet. Naming follows the FRD/TDD entity: `user_id`, `filters`, and
`alert_enabled`.

## Locked decisions

| # | Decision | Value |
|---|---|---|
| 1 | Alert mechanism | **Beat digest with cursor + delivery dedupe** (daily default, configurable). A periodic task scans each alert-enabled saved search for newly-published matching Frameworks after the saved cursor, sends one digest (email + in-app notification), records delivered Framework ids, and advances the cursor. No per-publish fanout. |
| 2 | Filter storage | JSONB blob mirroring the Explore filter/query (`q`, `category`, `sector`, `industry`, `function`, `jurisdiction`, `complexity`, `org_size`, `lifecycle_stage`, `license_type`, `price_min`, `price_max`, `attestation_status`, `sort`). Validated at save time by reusing the live Explore filter schema, so a stored search can always be re-run. |
| 3 | Delivery channels | Email digest (Resend) **and** in-app notification listing the new matches with links. |
| 4 | Empty digests | If no new matches since the cursor, send nothing and leave the cursor unchanged. A quiet period must not skip a later match. |
| 5 | Currency/scope | Operator role only; managed from Settings. |

## Schema

- **`saved_searches`** — id UUID PK, user_id FK, name TEXT, filters JSONB
  NOT NULL, filter_version INT NOT NULL DEFAULT 1, alert_enabled BOOL NOT NULL
  DEFAULT false, last_alerted_at TIMESTAMPTZ NULL,
  last_alerted_framework_id UUID NULL, created_at, updated_at. INDEX (user_id);
  partial INDEX `idx_saved_searches_alerts` on `(user_id) WHERE alert_enabled =
  true` (matches TDD). UNIQUE (user_id, name) prevents duplicate names per user.
- **`saved_search_alert_deliveries`** — id UUID PK, saved_search_id FK,
  framework_id FK, delivered_at TIMESTAMPTZ NOT NULL, created_at. UNIQUE
  (saved_search_id, framework_id). This table is the retry/idempotency guard; the
  cursor is a fast scan boundary, not the only duplicate-prevention mechanism.
- **Framework index** — add `idx_frameworks_status_published_at` on
  `(status, published_at)` if it is still missing when this slice starts.
- **Notification enum** — extend `notification_type_enum` with
  `saved_search_alert` before the worker can persist in-app digests.

`platform_config` row: `saved_search_alert_cadence_hours` (24). Admin-tunable,
validated to a sane range such as 1-168 hours.

## Filter model

`filters` stores exactly the fields the Explore list endpoint accepts (minus
pagination): keyword `q` + the faceted filters + sort. On save, parse it through
the **same Pydantic filter model** Explore uses; reject unknown keys / invalid
values (422). The public API key remains `function`, but the backend query maps it
to `Framework.business_function` because the ORM property is not named
`function`.

The alert matcher and the "run this search" action both rebuild the Explore query
from this blob via a shared `build_explore_query(filters)` helper extracted from
`explore/service.py` (small refactor: factor the existing `_apply_filters` /
`_search_match` into a reusable entry point). This guarantees saved searches and
live Explore never diverge. If Explore filters evolve later, `filter_version`
supports tolerant read/migration instead of breaking old saved searches.

## Alert flow (FR-SRCH-002)

Beat `dispatch_saved_search_alerts` (every `saved_search_alert_cadence_hours`):
1. Select saved searches where `alert_enabled = true` and the owning user is
   active. Operator role is enforced on CRUD; the worker also skips users who no
   longer have the Operator role.
2. For each search, build the Explore query from `filters`, add
   `Framework.status = 'published'`, and scan after the cursor
   `(last_alerted_at, last_alerted_framework_id)` ordered by
   `(published_at ASC, id ASC)`. If no cursor exists, start at `created_at`.
3. Exclude rows already present in `saved_search_alert_deliveries`; fetch a capped
   batch such as 50. Oldest-first ordering prevents a broad search from skipping
   older matches when the cap is hit.
4. If matches exist, enqueue one in-app notification with type
   `saved_search_alert` and a deterministic dedupe key, plus one Resend digest
   email listing title + link per match. Email is only queued for verified,
   active users; notification preferences must be respected once the Settings
   preference model exists.
5. After both delivery jobs are queued, insert delivery rows and advance
   `last_alerted_at` / `last_alerted_framework_id` to the final Framework in the
   batch inside one DB transaction.
6. If no matches, send nothing and leave the cursor unchanged.

Idempotency is enforced by both the notification dedupe key and
`saved_search_alert_deliveries`. The cursor is a performance boundary and a
resume point; it is not trusted as the only duplicate guard.

## Module layout

```
backend/app/modules/saved_searches/
├── router.py     # /v1/saved-searches CRUD + toggle + run
├── service.py    # CRUD + filter validation (reuse Explore filter model)
├── models.py
└── schemas.py
backend/app/workers/tasks/saved_searches_beat.py # dispatch_saved_search_alerts
backend/app/modules/explore/service.py            # extract build_explore_query(filters)
```

## API surface

| Verb | Path | Auth |
|---|---|---|
| POST | /v1/saved-searches | operator |
| GET | /v1/saved-searches | operator (own) |
| PATCH | /v1/saved-searches/{id} | owner (name/filters/alert toggle) |
| DELETE | /v1/saved-searches/{id} | owner |
| GET | /v1/saved-searches/{id}/run | owner → executes filters, accepts page/page_size, returns Explore results |

## Security

- Operator role; all rows owner-scoped (cross-user access → 404).
- Limit saved searches per user (recommend 25) and validate name length to reduce
  alert abuse and accidental broad scans.
- Filters validated against the Explore filter model on write — no arbitrary
  JSON / injection into the query builder; the builder only consumes typed fields.
- Email/in-app dispatch reuses existing idempotent tasks. Do not log email
  addresses, full filter blobs, or digest links; log saved_search_id and counts.
  Audit:
  `saved_search_created`, `saved_search_updated`, `saved_search_deleted`,
  `saved_search_alert_sent`.
- All writes in `async with db.begin()`.

## Slice plan (~4)

1. Schema + CRUD — `saved_searches` and `saved_search_alert_deliveries` tables +
   ORM + migration; add Framework `(status, published_at)` index if missing; add
   `saved_search_alert` notification enum value; create/list/edit/delete/toggle
   endpoints; filters validated via the Explore filter model. Tests: save valid/
   invalid filters, duplicate name, max-per-user, owner isolation.
2. Explore query reuse + run endpoint — extract `build_explore_query(filters)`
   from `explore/service.py`, preserve Explore parity, add `/run` endpoint with
   page/page_size. Tests: saved search run returns the same ids as Explore for
   the same filters, including `function -> business_function` mapping.
3. Alert Beat — `dispatch_saved_search_alerts` (cursor match, delivery dedupe,
   digest email + in-app, advance-after-queue only) + `beat_schedule` entry +
   config cadence. Tests (`.apply()`): match since cursor → digest + cursor
   advance; no match → no send; cap resumes on the next run; second run → no
   duplicate; inactive/unverified email users skipped correctly.
4. OpenAPI sync + FE — Settings saved-search list (edit/delete/toggle alerts) +
   "Save this search" action on Explore that captures current filters. Mobile-first.
5. E2E — save a search from Explore → publish a matching framework → run Beat →
   assert digest email + in-app notification → re-run Beat → no duplicate.

## Risk flags

- **Filters/Explore drift:** saved blobs must always re-run; enforce by sharing
  one filter model + `build_explore_query`. If Explore filters change, a migration
  or tolerant parsing must keep old blobs runnable (validate-on-read, drop unknown).
- **Cursor correctness:** advance only after alert jobs are queued and delivery
  rows are inserted; use `(published_at, id)` ordering so equal timestamps and
  capped batches do not skip matches.
- **Delivery retry duplicates:** rely on deterministic notification dedupe keys
  and `saved_search_alert_deliveries`, not only `last_alerted_at`.
- **Digest volume:** cap matches per digest (e.g. 50) with a "view all" link; a
  brand-new broad search shouldn't email hundreds.
- **Timezone/`published_at`:** ensure frameworks set `published_at` on publish and
  it's indexed for the matcher.
- **Broad saved filters:** cap searches per user and add worker batch limits so a
  single Operator cannot create unbounded Beat work.

## Verification (after slice 5)

1. Backend: `uv run pytest --cov=app/modules/saved_searches --cov=app/workers/tasks/saved_searches_beat` ≥ 80%. Cover filter validation, owner isolation, run endpoint parity with Explore, Beat match/no-match/no-duplicate, cursor advance-after-queue, capped batch resume.
2. Frontend: `corepack pnpm --dir frontend test` + `corepack pnpm --dir frontend exec playwright test tests/e2e/saved-searches.spec.ts`.
3. Manual smoke: save an Explore search with filters + keyword; toggle alerts on; publish a matching framework; run `dispatch_saved_search_alerts`; receive one digest email + in-app notification; run again → no duplicate; edit filters so it no longer matches → no alert.

## Out of scope (later)

- Real-time/event-driven instant alerts (digest only here).
- Per-search custom cadence (single global cadence config now).
- Saved searches for Collections or other entity types (frameworks only).
- Shared/team saved searches.
- Push/SMS channels.
