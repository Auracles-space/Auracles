# Credential Verification (manual, Admin-driven) — Design

**Date:** 2026-06-15
**Status:** Approved (brainstorming)
**Area:** Backend (FastAPI). One Alembic migration. Minor public-profile response extensions.

## Problem

Today `Credential` (`app/modules/attestation/models.py`) is only a record +
evidence store: `title`, `issuer` (free text), `issued_date`, `expires_date`,
`evidence_file_keys`. Any logged-in user owns credentials; there is **no
verification**. The FRD Credential entity specifies `type`, `verification_url`,
and `verified`; the full spec describes a Credential Registry that "stores
verified credentials", a Credential Record that displays "Verification Status",
and a "Credential Verified" trust badge. None of that exists yet.

The CEO wants credentials = certificates from Institutions / Organisations /
Government / Associations, verified by calling the issuer's API to cross-check,
**or manually**. This spec builds the **manual** path only.

Maps to: FR-ATT-003 (credential remains an attestation target — unchanged),
FR-SET-002 (verified credentials display on contributor profile), FRD Credential
entity, full-spec Credential Registry + Trust & Attestation taxonomy
("Credential Verified").

## Locked decisions

| # | Decision | Value |
|---|---|---|
| 1 | Scope | **Personal** professional credentials (CPA/PMP/ISO/license) for **Contributors + Attestors**. Operator business verification is a separate later feature. |
| 2 | Verifier | **Admin/staff queue** — free, manual. Separate from the paid Attestor/Attestation flow. "Credential Verified" badge = platform confirmed authenticity. |
| 3 | API path | **Manual only, no API seam.** No issuer-API integration, no adapter abstraction. Issuer-API cross-check is a wholly separate future feature. |
| 4 | Lifecycle | `unverified → pending → verified \| rejected`; resubmit `rejected → pending`. Editing a material field while `pending\|verified` resets to `unverified`. No `revoked` state. |
| 5 | Expiry | `expired` is **derived** (`expires_date < today`), not a stored status. |
| 6 | Fields | Add `credential_type`, `verification_url`, `reference_number`, `issuer_type` (taxonomy), plus verification/review fields. |
| 7 | CRUD access | Credential CRUD stays open to any logged-in user (roles coexist; harmless). Verification badge surfaces only on Contributor public profile + Attestor context. |

## Out of scope (separate features)

- **Operator business verification** (Business Identity / Company Registration /
  Compliance / Procurement Authority — full-spec "Operator Verification").
- **Issuer-API cross-check** (automated verification against issuer registries).
- **Reputation scoring** (Phase 5e) — verified credentials feed contributor
  reputation later; no reputation work here.
- **Paid Attestation on credentials** — already exists (`credential` is an
  `attestation_target_enum` value); unchanged and independent of this badge.
- `revoked` state — not built; revisit if issuer-disavowal/fraud handling needed.

## Data model — extend `Credential` (one migration)

New Postgres enums:

- `credential_verification_status_enum`: `unverified | pending | verified | rejected`
- `credential_issuer_type_enum`: `institution | organisation | government | association`

Add columns to `credentials`:

| Column | Type | Null | Default | Notes |
|--------|------|------|---------|-------|
| `verification_status` | `credential_verification_status_enum` | not null | `unverified` | lifecycle state |
| `credential_type` | text | null | — | FRD `type`, e.g. "PMP" |
| `verification_url` | text | null | — | issuer public verify link (admin checks) |
| `reference_number` | text | null | — | cert/license number (admin cross-checks) |
| `issuer_type` | `credential_issuer_type_enum` | null | — | CEO taxonomy |
| `submitted_at` | timestamptz | null | — | set on submit |
| `verified_at` | timestamptz | null | — | set on approve |
| `reviewed_by` | uuid FK `users.id` | null | — | admin who acted |
| `rejection_reason` | text | null | — | set on reject |

- Index `idx_credentials_verification_status` on `(verification_status)` for the
  admin queue scan.
- `expired` is never stored — computed from `expires_date` at read time.
- Migration must round-trip: `alembic upgrade head` then `downgrade -1` both
  succeed (downgrade drops columns + both enums).

## Lifecycle & service rules

State logic lives in `app/modules/attestation/credential_service.py`. Invalid
transitions raise `HTTPException(422)`. RBAC is enforced at the dependency layer,
never inside the service.

```
unverified ──submit──> pending ──admin verify──> verified
     ▲                    │
     │                    └──admin reject──> rejected ──resubmit──> pending
     │
     └── edit material field (title / issuer / issued_date / reference_number)
         while pending|verified  →  reset to unverified (clear review fields)
```

- **`submit_credential(owner)`** — `unverified|rejected → pending`; set
  `submitted_at`. Reject submit with 422 unless at least one of
  {`evidence_file_keys` non-empty, `verification_url`, `reference_number`} is
  present — admin needs something to check. Audit `credential_submitted`.
- **`verify_credential(admin)`** — `pending → verified`; set `verified_at` +
  `reviewed_by`; clear `rejection_reason`. Notify owner. Audit
  `credential_verified`.
- **`reject_credential(admin, reason)`** — `pending → rejected`; set
  `rejection_reason` (required, non-empty) + `reviewed_by`. Notify owner. Audit
  `credential_rejected`.
- **Edit-reset** — in `update_credential`, if `verification_status` is
  `pending` or `verified` and any of `title` / `issuer` / `issued_date` /
  `reference_number` changes, force `verification_status = unverified` and clear
  `submitted_at` / `verified_at` / `reviewed_by` / `rejection_reason`. Audit
  `credential_verification_reset`. Prevents badge bait-and-switch.
- Invalid transitions (e.g. verify a non-`pending` credential, submit an already
  `verified` one) → 422.

## API surface

### User (owner-gated, existing CRUD plus)

- `POST /v1/attestation/credentials/{id}/submit` — owner only; `unverified|rejected → pending`.

(Existing: `POST/GET/PATCH/DELETE /v1/attestation/credentials`, evidence upload
session — unchanged except `update_credential` gains the edit-reset rule and the
new optional fields are accepted on create/update.)

### Admin (`require_role("admin")`, mirrors existing admin/kyc review wiring)

- `GET /v1/admin/credentials?status=pending` — paginated review queue (default
  `pending`; `status` filter optional). PII-safe: includes evidence keys +
  reference number **for admins only**, since they need them to verify.
- `POST /v1/admin/credentials/{id}/verify`
- `POST /v1/admin/credentials/{id}/reject` — body `{ "reason": str }` (required).

No 2FA gate — not a money operation; CLAUDE.md reserves 2FA for payout / email /
payment-method changes. All admin actions audit-logged.

### Public display

- Extend `GET /v1/explore/contributors/{id}` to include credentials with
  `verification_status == verified` **only**. Response exposes
  `title`, `issuer`, `credential_type`, `issued_date`, `expires_date`, and the
  derived `expired` flag. **Never** exposes `evidence_file_keys`,
  `verification_url`, `reference_number`, `reviewed_by`, or any
  pending/rejected/unverified credential.
- Attestor profile context surfaces verified credentials the same way.

## Security

- Admin endpoints deny-by-default via `require_role("admin")`; non-admin → 403
  (logged WARNING with user_id + action). Owner-only on submit + edit + delete.
- Public responses expose **only** verified credentials and **only** the
  non-sensitive subset above — anti-gaming + no PII (evidence, issuer reference,
  verify URL stay private to owner + admin).
- Every state change (`submit`, `verify`, `reject`, `verification_reset`) writes
  an audit row. Owner notified on `verify` / `reject` via the existing
  notification system.
- Logging per standards: `module="attestation"`, snake_case `action`,
  `user_id`, credential id; admin actions logged INFO, RBAC denials WARNING.

## Testing

**Unit (service):**
- Each transition: `submit` from `unverified`/`rejected` ok; from
  `pending`/`verified` → 422.
- `submit` blocked (422) when no evidence file AND no `verification_url` AND no
  `reference_number`; allowed when any one present.
- `verify` only from `pending`; sets `verified_at`/`reviewed_by`; else 422.
- `reject` only from `pending`; requires non-empty reason; sets fields; else 422.
- Edit-reset: changing `title`/`issuer`/`issued_date`/`reference_number` while
  `pending`/`verified` resets to `unverified` and clears review fields; changing
  a non-material field (e.g. `expires_date`) does **not** reset.
- `expired` derivation: `expires_date` in past → `expired = true`.

**Integration (endpoints):**
- Admin verify/reject: non-admin → 403; admin → 2xx; owner cannot self-verify.
- Submit: non-owner → 404/403; owner happy path → `pending`.
- Public contributor endpoint: returns verified credential without sensitive
  fields; a pending/rejected credential is absent; evidence keys / verify URL /
  reference number never present in the public payload.

**Migration:** `alembic upgrade head` + `downgrade -1` both succeed.

Coverage ≥ 80% on touched `app/modules/**`.

## Module layout

```
app/modules/attestation/
├── credential_service.py   # + submit / verify / reject / edit-reset state logic
├── schemas.py              # + new fields on create/update; submit/verify/reject
│                           #   request+response; admin queue + public schemas
├── models.py               # + columns + 2 enums on Credential
└── router.py               # + owner submit endpoint
app/modules/admin/router.py # + 3 admin credential endpoints (delegate to service)
app/modules/explore/...     # contributor profile response includes verified creds
backend/migrations/versions/2026_06_15_credential_verification.py
```

## Risks / notes

- **Manual review load:** admin queue scales with credential volume; acceptable
  pre-scale. Issuer-API automation (future) reduces it.
- **Trust of a manual badge:** "Credential Verified" means platform-staff
  confirmed authenticity from evidence/URL/reference — not a cryptographic
  proof. Acceptable; the deeper paid Attestation remains available separately.
- **Edit-reset friction:** a verified user editing a typo in `title` loses the
  badge until re-review. Intended — integrity over convenience. Non-material
  fields (avatar/bio/`expires_date`) do not reset.
- **Forward-compat:** when issuer-API arrives, `verification_status` +
  `verification_url` + `issuer_type` already exist; the API path can set
  `verified` automatically without a schema change.
```
