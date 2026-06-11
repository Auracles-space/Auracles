# Phase 5c — GDPR & Data Rights (design spec)

## Context

Phase 5c implements user data rights (FRD §FR-GDPR-001..004): data export,
account deletion, and a consent log. It is cross-cutting — user personal data
lives across auth, frameworks, financials, projects, attestation, workspace,
notifications, reputation, and developer modules (8+ FK-to-users tables). No GDPR
code exists today. Pre-launch compliance work; one of the Phase 5 sub-phases.

Reuses: S3 + presigned-URL pattern (Phase 2 artifacts), Celery + Beat
scaffolding, 2FA `verify_totp_for_sensitive_action` (`app/modules/auth/service.py`),
audit log, notifications module, Fernet (for any encrypted-at-rest references).

Current repo alignment, verified on 2026-06-11:
- `users` has `deactivated_at`, not `deleted_at`; GDPR anonymisation should set
  `deactivated_at` and use `account_deletion_requests.completed_at` as the
  durable erasure/tombstone marker unless a later slice explicitly adds a
  `gdpr_erased_at` column.
- The TDD sketched a combined `gdpr_requests` table, but this design intentionally
  uses separate export/deletion tables because their state machines, retention,
  and security rules differ.
- Use table name `consent_logs` and document types
  `terms_of_service|privacy_policy` to match the TDD naming.
- Routers use module-local prefixes (`/gdpr`) and are mounted in
  `backend/app/main.py` with `prefix="/v1"`.
- Frontend commands should use `corepack pnpm --dir frontend ...`, not bare
  `pnpm`, to match this environment.

## Locked decisions

| # | Decision | Value |
|---|---|---|
| 1 | Deletion strategy | **Anonymise-in-place + tombstone** (FR-GDPR-003): scrub PII fields, replace identity with a "Deleted user" marker, keep the user row + downstream records (transactions, escrow, licenses, reviews, published frameworks, attestations, project history) intact but de-identified. No cascade delete. |
| 2 | Deletion flow | Fresh account confirmation to initiate (password confirmation for password accounts; signed email/OAuth re-auth for passwordless accounts; plus TOTP when enabled) → **block** (409 + reasons) if unsettled obligations exist (held escrow, pending/processing payout, open/under-review dispute, in-progress project, active attestation assignment) → on accept, cancellable **cooling-off window** (default 14d, config) → Beat anonymises. |
| 3 | Export scope | **Comprehensive** — all user-linked data across modules, JSON bundle per category, with secrets and counterparty PII redacted. |
| 4 | Export delivery | Async Celery `generate_data_export` → JSON → private S3 → short-lived presigned link + notification. 30-day SLA (FR-GDPR-002; realistically minutes). One active request per user; expiry Beat cleans bundles. |
| 5 | Consent log | Append-only `consent_logs` (user_id, document_type terms_of_service|privacy_policy, version, accepted_at, ip, user_agent) captured at registration; a re-accept gate forces consent on document version bumps (FR-GDPR-004). |
| 6 | Irreversibility | Anonymisation is irreversible once the cooling-off window elapses; before then the request is cancellable. |

## Schema (new tables)

- **`data_export_requests`** — id, user_id FK, status `data_export_status_enum`
  (pending|processing|ready|failed|expired), bundle_key TEXT NULL, expires_at NULL,
  failure_reason TEXT NULL, requested_at, completed_at NULL. INDEX (user_id,
  status). Partial UNIQUE (user_id) WHERE status IN ('pending','processing')
  (one active generation). A ready export is downloadable until `expires_at`, but
  does not block a later new request unless product chooses stricter throttling.
- **`account_deletion_requests`** — id, user_id FK, status
  `account_deletion_status_enum` (pending|scheduled|blocked|cancelled|completed),
  blocked_reasons JSONB NULL, scheduled_for TIMESTAMPTZ NULL (cooling-off end),
  requested_at, completed_at NULL. Partial UNIQUE (user_id) WHERE status IN
  ('pending','scheduled'). INDEX (status, scheduled_for).
- **`consent_logs`** — id, user_id FK, document_type `consent_document_enum`
  (terms_of_service|privacy_policy), version TEXT, accepted_at TIMESTAMPTZ,
  ip INET NULL, user_agent TEXT NULL. Append-only. INDEX (user_id,
  document_type, accepted_at DESC).

`platform_config` rows: `consent_version_terms_of_service`,
`consent_version_privacy_policy` (current versions),
`account_deletion_grace_days` (14), `data_export_expiry_days` (7). Admin-tunable.
Admin config validation must enforce integer ranges: deletion grace 1-30 days,
export expiry 1-30 days, non-empty consent version strings.

## Export contents (comprehensive, redacted)

One JSON object keyed by category. Include:
- **profile** — public + private profile fields, roles, kyc_status (status only,
  not raw documents), created_at, consent_logs entries.
- **financial** — purchases, licenses, transactions, payouts, payout_accounts
  (masked refs only — never decrypted provider account ids), partner_commissions.
- **reviews** — reviews authored.
- **frameworks** — frameworks authored (metadata; not other users' data).
- **projects** — projects, proposals, milestones, deliverables they own; workspace
  **messages they sent** only.
- **attestation** — attestations as requestor or attestor; attestor application;
  credentials they own.
- **developer** — developer account, api_keys **metadata only** (name, prefix,
  scopes, created_at — never key_hash), partner webhooks (url + events, never
  the secret), partner payouts.
- **reputation** — their reputation scores + component labels.
- **security_audit** — audit events where they are the actor or target, with
  metadata redacted to remove secrets, raw URLs, email addresses, tokens, provider
  account IDs, and counterparty PII.

**Hard redactions (never exported):** password_hash, TOTP secret, API key hashes,
webhook secrets, raw KYC document bytes, decrypted payout provider ids, other
users' PII appearing in shared records (counterparty profiles, the other party's
workspace messages, dispute counterparty details).

Binary files are out of the JSON bundle for this phase. Do not include raw KYC
documents, framework artifacts, attestation evidence/report files, workspace
attachments, thumbnails, or payout-account provider documents. Export only safe
metadata and S3 key presence where the key itself is not sensitive. A future legal
review can decide whether to add a separate binary archive.

Collectors are deny-by-default: every collector returns an explicit allow-list of
fields, and test fixtures must include forbidden-looking fields to prove they do
not leak. Modules that do not exist yet in the current branch, such as developer
or reputation, get no-op collectors until those modules land.

## Anonymisation (deletion) — what changes

On the scheduled Beat run for a `scheduled` request past `scheduled_for`:
- **Scrub `users` PII:** email → `deleted+{user_id}@tombstone.invalid`,
  password_hash → unusable random, display_name → "Deleted user", avatar_url,
  bio, location, website → NULL; set `deactivated_at = now()`, keep the row.
  Do not reference `deleted_at` unless a slice adds that column.
- **KYC:** delete stored KYC document objects from S3, delete `kyc_documents`
  rows where legally allowed, and set `users.kyc_status` to `unverified` or a
  documented tombstone-compatible value supported by the existing enum.
- **Credentials:** revoke + delete refresh tokens (Redis), revoke all API keys,
  delete OAuth accounts, delete/disable backup codes, remove TOTP secret, and
  invalidate sessions.
- **Payout accounts:** do not hard-delete rows that may be referenced by payouts.
  Soft-delete them (`deleted_at=now()`), set `is_default=false`, and overwrite
  encrypted provider IDs / lookup hashes with irreversible tombstone values that
  still satisfy NOT NULL and uniqueness constraints.
- **Audit metadata:** retain audit rows for integrity, but scrub known PII-bearing
  metadata keys such as email, ip, provider refs, raw URLs, uploaded filenames,
  and free-text notes when they identify the deleted user.
- **Retain, de-identified:** transactions, escrow, licenses (financial
  compliance — FR-GDPR-003), reviews (author shown "Deleted user"), published
  frameworks (others hold licenses — author de-identified), attestations,
  project/proposal/milestone history, workspace messages (sender de-identified).
- **Marketplace behavior:** deactivated/tombstoned Contributors keep published
  Frameworks visible for existing licensees and provenance, but new purchases are
  suspended per BR-SET-002.
- Audit `account_deletion_completed`. Notification cannot be delivered (email
  scrubbed) — send the final confirmation just before scrubbing the email, or to
  a captured pre-deletion address per policy.

Referential integrity preserved (no FK breakage); the tombstoned user row anchors
all retained rows. Freed email becomes reusable for a future registration.

## Module layout

```
backend/app/modules/gdpr/
├── router.py            # /gdpr/* (export request/status/download, deletion request/cancel, consent)
├── export_service.py    # build comprehensive bundle (per-category collectors + redaction)
├── deletion_service.py  # request + obligation checks + schedule/cancel
├── anonymise.py         # the scrub engine (pure-ish, well-tested)
├── consent_service.py   # record + current-version gate
├── models.py
├── schemas.py
└── dependencies.py
backend/app/workers/tasks/
└── gdpr_beat.py         # generate_data_export, process_account_deletions, expire_data_exports
```

## API surface

| Verb | Path | Auth |
|---|---|---|
| POST | /v1/gdpr/exports | self (rate-limited, one active) |
| GET | /v1/gdpr/exports/{id} | self (status) |
| GET | /v1/gdpr/exports/{id}/download | self → 302 presigned (if ready) |
| POST | /v1/gdpr/account-deletion | self + fresh account confirmation (+ TOTP when enabled) |
| GET | /v1/gdpr/account-deletion | self (status + blocked_reasons + scheduled_for) |
| POST | /v1/gdpr/account-deletion/cancel | self |
| POST | /v1/gdpr/consent | self (record acceptance of current versions) |
| GET | /v1/gdpr/consent | self (history) |

## Celery / Beat

| Task | Trigger | Action |
|---|---|---|
| `generate_data_export(request_id)` | on request | Aggregate all categories, redact, write JSON to private S3 (`gdpr-exports/{user}/{request}.json`), set ready + expires_at, notify. Idempotent. |
| `expire_data_exports` | daily | Mark past-expiry requests `expired`, delete S3 bundle. |
| `process_account_deletions` | hourly | For each `scheduled` request past `scheduled_for` with no active obligations (re-checked), run `anonymise`, mark completed. Idempotent. |

## Security

- Export bundle in **private** S3; download via short-lived presigned URL only,
  owner-checked; never proxied. Redaction list enforced in `export_service`
  (deny-by-default: collectors return only whitelisted fields).
- Presigned export URLs should expire quickly (10 minutes), use download
  `Content-Disposition`, and must never be written to logs or audit metadata.
- Export generation and download endpoints are rate-limited per user in addition
  to the one-active-generation DB guard.
- Deletion initiation requires fresh account confirmation. Reuse
  `verify_totp_for_sensitive_action` only when TOTP is enabled; passwordless
  users need an email/OAuth re-auth confirmation flow before scheduling deletion.
- Obligation re-check at both request time and Beat execution (state can change
  during cooling-off) — never anonymise a user with live escrow/payout/dispute.
- All writes in `async with db.begin()`. Audit: `gdpr_export_requested`,
  `gdpr_export_ready`, `account_deletion_requested`, `account_deletion_blocked`,
  `account_deletion_cancelled`, `account_deletion_completed`, `consent_recorded`.
- Consent gate: a middleware/dependency blocks privileged actions until the user
  has accepted the current `consent_version_*` (configurable; non-blocking for
  read-only public browsing). It must not block GDPR endpoints, auth/logout,
  password reset, account-deletion cancellation, or security recovery flows.

## Slice plan (~8)

1. Schema foundation — 3 tables + enums + `platform_config` consent/grace seeds + ORM + migration up/down smoke.
2. Consent log — record endpoint + capture at registration + current-version gate dependency + history endpoint.
3. Data export — request endpoint (one-active guard) + `generate_data_export` Celery (per-category collectors + redaction) + S3 write + status endpoint.
4. Export download + expiry — secure presigned download (owner-checked, ready-only) + `expire_data_exports` Beat.
5. Deletion request — `POST /account-deletion` (fresh account confirmation + TOTP when enabled) + obligation checks (held escrow / pending payout / open dispute / in-progress project / active attestation) → blocked 409 + reasons; schedule cooling-off; cancel endpoint; status endpoint.
6. Anonymisation engine — `anonymise.py` scrub (PII + creds/keys/TOTP/payout + KYC docs) with financial/marketplace retention + de-identification; `process_account_deletions` Beat (re-check obligations, idempotent).
7. OpenAPI sync + FE settings — export (request/download), delete-account flow (fresh account confirmation + blocked-reasons display + cooling-off + cancel), consent history. Mobile-first.
8. E2E — request export→ready→download JSON (assert no secrets/counterparty PII); request deletion with active obligation→blocked; settle→schedule→cancel; re-request→cooling-off elapse (clock)→anonymised (PII gone, transactions retained de-identified).

## Risk flags

- **Export leakage:** comprehensive collectors must whitelist fields and exclude
  secrets + counterparty PII. Highest risk — test the bundle for forbidden keys.
- **Anonymisation integrity:** must not break FKs or financial records; retained
  rows must remain queryable with a tombstoned author. Test against every
  FK-to-users table.
- **Obligation completeness:** missing one obligation type can strand money/a
  counterparty. Enumerate against all of escrow/payout/dispute/project/attestation
  and re-check at Beat time.
- **Financial legal-hold:** transactions retained for compliance per FR-GDPR-003;
  document the retention basis. Erasure scrubs PII, not the financial ledger.
- **Email reuse:** scrubbed email frees the address for re-registration — ensure
  the tombstone email is unique and the unique constraint allows reuse.
- **Notification after scrub:** deliver the deletion-complete notice before the
  email is scrubbed (or to a captured address), else it cannot be sent.

## Verification (after slice 8)

1. Backend: `uv run pytest --cov=app/modules/gdpr --cov=app/workers/tasks/gdpr_beat` ≥ 80%. Assert export bundle contains no forbidden keys (password_hash, *_secret, key_hash, totp, decrypted provider ids, counterparty PII). Assert anonymisation scrubs every PII field and retains transactions/licenses de-identified, with all FKs intact.
2. Frontend: `corepack pnpm --dir frontend test` + `corepack pnpm --dir frontend exec playwright test tests/e2e/gdpr.spec.ts`.
3. Manual smoke: request export → ready → download → inspect JSON (all categories present, secrets absent). Request deletion while holding active escrow → blocked with reason. Settle → schedule (14d) → cancel → re-request → fast-forward clock → `process_account_deletions` → user PII gone, login impossible, transactions still present de-identified, others' licenses to that user's frameworks still valid. Bump consent version → next privileged action forces re-accept → `consent_logs` row written.

## Out of scope (later)

- Self-serve data rectification/correction beyond existing profile edit.
- Automated DPA/processor records, RoPA tooling.
- Per-field consent granularity / marketing preferences.
- Legal-hold override workflow for litigation (manual/admin for now).
- Cross-region data residency.
