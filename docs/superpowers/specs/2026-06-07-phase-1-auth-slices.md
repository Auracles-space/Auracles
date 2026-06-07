# Phase 1 — Auth & Identity: Sliced Build Plan

**Status:** Draft — awaiting human approval before Slice 1 starts.
**Maps to:** FR-AUTH-001..011, BR-AUTH-001..004, FR-SET-004/005/009/010, BR-SET-001, TDD §3, TDD §8.

---

## Context

Phase 0 (FastAPI scaffold, health module, Celery scaffold, Tailwind / Brand Book design system) is shipped. Phase 1 builds the auth surface — accounts, JWT sessions, RBAC, 2FA, email verification, password reset, sessions, account email change, deactivation, KYC, and the audit log table that every later phase depends on. Sliced into **11 small, independently reviewable adds** so the human can keep pace and commit between slices.

---

## Coverage matrix

| ID | Title | Slice |
|----|-------|------|
| FR-AUTH-001 | Email/password registration | 3 |
| FR-AUTH-002 | OAuth Google + LinkedIn | **DEFERRED** (post-Phase 1) |
| FR-AUTH-003 | Role selection at registration | 3 |
| FR-AUTH-004 | Email verification gate | 3 |
| FR-AUTH-005 | Add role post-registration | 5 |
| FR-AUTH-006 | TOTP 2FA | 6 |
| FR-AUTH-007 | Scoped access token w/ roles | 2 + 4 |
| FR-AUTH-008 | RBAC on protected resources | 5 |
| FR-AUTH-009 | KYC submission | 8 |
| FR-AUTH-010 | New-device login notification | 7 |
| FR-AUTH-011 | Password reset (15m link) | 7 |
| BR-AUTH-001 | Attestor needs Admin approval | 3 + 5 |
| BR-AUTH-002 | Framework publish gated by KYC | 8 (dep only; enforced Phase 2) |
| BR-AUTH-003 | 30d inactivity session expiry (sliding TTL) | 4 |
| BR-AUTH-004 | 2FA required for email change (Phase 1 surface) | 11 |
| FR-SET-004 | View KYC status | 8 |
| FR-SET-005 | Enable / disable 2FA | 6 |
| FR-SET-009 | View sessions + revoke | 11 |
| FR-SET-010 | Account deactivate | 11 |
| BR-SET-001 | Email change re-verify + 2FA | 11 |

---

## Architectural decisions captured this session

| Decision | Value | Note |
|----------|-------|------|
| OAuth (Google/LinkedIn) | Defer | FR-AUTH-002 → Phase 2.5+. |
| KYC scope | **Gates artifact upload AND download** (not just payouts) | Extends BR-FWK-002. Operators need verified KYC before downloading purchased artifacts. Confirm before Phase 2. |
| Password hashing | argon2 (`argon2-cffi`) | Memory-hard. |
| JWT lib | `python-jose[cryptography]` | HS256 per TDD §8. |
| TOTP | `pyotp` + `qrcode[pil]` | RFC 6238, ±1-step (30s) skew window. |
| Email | Resend via Celery task | Per CLAUDE.md tech stack. |
| Refresh token store | Redis, opaque, **sliding 30d TTL** (refresh on use → BR-AUTH-003) | Per TDD §8. |
| Refresh token rotation | New refresh issued on every `/refresh`; old revoked | Best-practice against replay. |
| Email verify token | Redis, opaque, 24h TTL | Not in TDD — proposed. |
| Password reset token | Redis, opaque, 15m TTL, single-use | Per FR-AUTH-011. |
| 2FA backup codes | 10 single-use codes, sha256-hashed at rest | Standard recovery. |
| Email enumeration policy | `/register` returns 200 + generic "if email is new, verification sent"; **never** 409. `/forgot-password` always 200. | No leak. |
| Password strength | min 12 chars, must include letter + digit, max 128 | Pydantic validator. |
| Login lockout | 5 failed attempts → 15-min Redis lockout per email + per IP | Brute-force guard. |
| TOTP verify rate-limit | 5 wrong codes per 5-min window → temp lock | Replay/brute guard. |
| Rate limiting | Redis fixed-window per IP on `/register`, `/login`, `/forgot-password`, `/resend-verification`, `/2fa/verify-login`, `/reset-password` | Hand-rolled, no `slowapi`. |
| CORS | FastAPI `CORSMiddleware` allowlist `NEXT_PUBLIC_APP_URL` only, `credentials: true` for refresh cookie | Slice 4. |
| Audit log | New DB table `audit_logs` (Slice 11 schema, retroactively written from Slice 3 onward) | Loguru structured logs continue alongside; DB table for queryable security trail. |

---

## Cross-cutting concerns (apply to every slice)

These rules apply across all slices — call them out in each slice's tests rather than assuming.

1. **Pydantic schemas** on every input. No raw dict.
2. **Loguru bound context** (`module`, `action`, `user_id` if known, `request_id` from middleware) on every log line.
3. **Audit DB write** for every event in CLAUDE.md logging table (login_success, login_failure, access_denied, password_reset, role change, 2fa_enabled/disabled, kyc_status_change). Helper `audit.write(actor_id, action, target_id, metadata)` lands in Slice 2; table lands in Slice 11; write is a no-op until Slice 11 then enabled (or write goes through repo with conditional check on table existence — pick: land table in Slice 1 instead — see Slice 1 update below).
4. **No secret in logs.** Never log tokens, passwords, TOTP codes, S3 presigned URLs.
5. **Idempotency.** Verify-email, reset-password, refresh, logout all safe to retry.
6. **Transactions.** Any write touching 2+ tables uses `async with db.begin()`.

> **Decision refinement:** push `audit_logs` table into **Slice 1** (foundation migration) so all subsequent slices can write to it directly. Slice 11 then only adds the read endpoint for sessions/audit if surfaced in UI.

---

## Slice plan

Each slice ends green: `ruff` + `mypy --strict` + `pytest --cov` (100% on touched modules) + Alembic `upgrade head` and `downgrade -1` both succeed. **One commit per slice.** Human reviews + commits before next slice starts.

---

### Slice 1 — Schema foundation
**Add:**
- `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/`
- Migration `2026_06_07_initial_users_and_roles.py`:
  - Enums: `role_enum` (contributor, operator, attestor, admin), `kyc_status_enum` (unverified, pending, verified, rejected)
  - `users` table per TDD §3 + `users.deactivated_at` (FR-SET-010 prep)
  - `user_roles` table per TDD §3
  - `oauth_accounts` table (schema-only; no endpoints this phase)
  - **`audit_logs`** table: `id`, `actor_id` (nullable for system/unauth), `action` (varchar), `target_type`, `target_id` (nullable), `metadata` (jsonb), `ip_address` (inet), `user_agent` (text), `created_at`. Indexed on (actor_id, created_at) + (action, created_at).
- SQLAlchemy ORM: `app/modules/auth/models.py` (User, UserRole, OAuthAccount), `app/shared/models/audit_log.py` (AuditLog)
- `app/shared/models/base.py` extension if needed for `TimestampMixin`
- **Seed migration `2026_06_07_seed_initial_admin.py`** — creates one admin user from env vars `ADMIN_EMAIL` + `ADMIN_PASSWORD_HASH` (or no-op if unset). Idempotent.

**Test (`tests/unit/test_migrations.py`):**
- `upgrade head` → assert all tables + indexes + enums exist
- `downgrade -1` → assert clean
- Seed migration with admin env set → admin user + admin role inserted; without env → no rows

**Deps added:** none (alembic already in pyproject).

---

### Slice 2 — Security primitives + audit helper (no endpoints)
**Add:**
- `app/core/security.py`:
  - `hash_password(plain) -> str`, `verify_password(plain, hash) -> bool` (argon2)
  - `create_access_token(user_id, roles, totp_verified=False) -> str` (JWT HS256, 15m exp, jti uuid, roles claim per FR-AUTH-007)
  - `decode_access_token(token) -> TokenPayload` (raises on invalid/expired)
  - `generate_opaque_token() -> str` (32-byte urlsafe; reused for refresh, email-verify, reset, challenge tokens)
  - `hash_token(token) -> str` (sha256; Redis key derivation)
  - **Password strength validator** (Pydantic `field_validator`) reusable in register + reset
- `app/core/redis.py`: async Redis client singleton via `get_redis()` dep
- `app/core/audit.py`: `write_audit(db, actor_id, action, target_type=None, target_id=None, metadata=None, ip=None, ua=None)` helper
- `app/core/rate_limit.py`: `RateLimiter` fixed-window on Redis. `RateLimiter("login_ip", limit=20, window=60).check(key)` raises 429.
- `app/shared/schemas/token.py`: `TokenPayload` Pydantic

**Test:** unit tests on each — round-trip JWT, tamper, expiry (freezegun), wrong secret, argon2 verify, password validator accept/reject cases, rate-limiter window roll-over, audit row inserted.

**Deps added:** `argon2-cffi`, `python-jose[cryptography]`, `freezegun` (dev).

---

### Slice 3 — Register + email verification
**Add:**
- `app/modules/auth/schemas.py`:
  - `RegisterRequest`: `email: EmailStr`, `password: SecretStr` (validator), `display_name: str`, `roles: list[Literal["contributor","operator","attestor"]]` (FR-AUTH-003, `min_length=1`)
  - `RegisterResponse`: `{ "message": "If email is new, verification sent." }` (no-enum policy)
  - `VerifyEmailRequest`, `ResendVerificationRequest`
- `app/modules/auth/service.py`:
  - `register_user(...)`:
    - Normalize email (lowercase + strip)
    - Hash password
    - Insert user; on `IntegrityError` (dup email) → still return success (no enumeration), log `register_duplicate_attempt` audit
    - For each role: insert `user_roles`; attestor row left with `approved_at = NULL` (BR-AUTH-001)
    - Generate email-verify token (24h Redis TTL); dispatch `send_verification_email`
    - Audit write `register_success`
  - `verify_email(token)`: looks up Redis, marks `email_verified=true`, deletes token, audit `email_verified`
  - `resend_verification(email)`: rate-limited to 3 per hour per email (Redis); always 200
- `app/modules/auth/router.py`: `POST /v1/auth/register`, `POST /v1/auth/verify-email`, `POST /v1/auth/resend-verification`
- `app/workers/tasks/notifications.py`: `send_verification_email` Celery task using Resend SDK; idempotent (re-send safe), retried with `self.retry(countdown=60)` on transient
- `app/integrations/resend.py`: thin Resend wrapper w/ verify-email + password-reset + new-device + email-change templates (templates added later slices)
- Wire router into `app/main.py`

**Edge cases tested:**
- Register: duplicate email → 200 (no leak); weak password → 422; missing role → 422; attestor selected → role row created but `approved_at=NULL`
- Verify-email: valid → 200; invalid → 400; expired → 410; reused → 410
- Resend: rate limit hit → 429; unknown email → 200 (no leak)
- Race: two concurrent registers same email → one succeeds, one returns generic success; only one user row

**Deps added:** `resend`, `respx` (dev).

---

### Slice 4 — Login + refresh (rotating, sliding) + logout + `get_current_user` + CORS
**Add:**
- `app/main.py`: `CORSMiddleware` allowlist `NEXT_PUBLIC_APP_URL`, `allow_credentials=True`
- `app/modules/auth/schemas.py`: `LoginRequest`, `TokenPair { access_token, refresh_token, token_type, expires_in }`, `RefreshRequest`
- `app/modules/auth/service.py`:
  - `login(email, password, ip, ua)`:
    - Rate-limit IP (20/min) + email (5 failures/15min) — lockout key in Redis
    - Verify password; failures → audit `login_failure`, increment lockout counter
    - Check `email_verified`; if false → 403 (no token issued)
    - Check `users.deactivated_at`; if set → 403
    - Compute device fingerprint hook (filled in Slice 7); placeholder no-op here
    - Issue access (15m) + refresh (sliding 30d TTL); store refresh in Redis as `refresh:{sha256(token)} -> { user_id, family_id, issued_at }`; audit `login_success`
  - `refresh(token, ip, ua)`:
    - Lookup Redis; if missing → 401
    - **Rotate**: issue new access + new refresh; delete old refresh; reset Redis TTL to 30d (sliding) per BR-AUTH-003
    - If reused old token detected (same family but already deleted) → revoke entire family (token-theft signal); audit `refresh_token_reuse_detected`
    - Audit `token_refresh`
  - `logout(refresh_token)`: delete refresh from Redis; access token remains valid until exp (documented); audit `logout`
  - `logout_all(user_id)`: scan + delete all refresh tokens for user; audit `logout_all`
- `POST /v1/auth/login`, `POST /v1/auth/refresh`, `POST /v1/auth/logout`
- `app/core/dependencies.py`: `get_current_user(token) -> User` dep (loads roles; checks `deactivated_at`)
- `GET /v1/auth/me` — protected echo for testing the dep

**Edge cases tested:**
- Wrong password → 401; lockout after 5 → 429; unverified email → 403; deactivated account → 403
- Refresh: valid → new pair, old revoked; reusing rotated token → all family revoked; logged-out → 401
- Sliding TTL: refresh after 29 days → still works, TTL extended; after 31d idle → 401
- /me without token → 401; with valid → 200; expired token → 401
- CORS preflight from allowed origin → 200; disallowed origin → blocked

---

### Slice 5 — RBAC dep + role assignment
**Add:**
- `app/core/dependencies.py`: `require_role(*roles)` factory dep; emits audit `access_denied` on 403
- `app/modules/auth/router.py`: `POST /v1/auth/roles` — self-add Contributor or Operator (Attestor blocked → 403 per BR-AUTH-001)
- `app/modules/admin/router.py` + `service.py`: `PATCH /v1/admin/users/{id}/roles` (assigns/approves Attestor; only `admin` role can call); audit `role_assigned` / `attestor_approved`
- Protected sample endpoints to test 401/403/200 paths

**Edge cases tested:**
- Self-add Contributor → 200; self-add Attestor → 403; duplicate role → 409
- Admin approves Attestor → `approved_at` + `approved_by` set
- Non-admin calls admin endpoint → 403 + audit row
- Token w/o role claim → 403

---

### Slice 6 — TOTP 2FA (setup / verify / disable + login challenge + backup codes)
**Add:**
- `app/core/security.py`:
  - TOTP secret encrypt/decrypt via Fernet keyed off `SECRET_KEY`
  - `generate_backup_codes(n=10) -> list[str]` (single-use, format `xxxx-xxxx`); hash each (sha256) for storage
- Migration: `user_backup_codes` table (`id`, `user_id`, `code_hash`, `used_at`)
- `app/modules/auth/service.py`: `setup_totp`, `verify_totp_enable`, `disable_totp`, `verify_totp_login`, `consume_backup_code`
- `POST /v1/auth/2fa/setup` (returns provisioning URI + QR PNG b64 + 10 backup codes **shown once**), `POST /v1/auth/2fa/verify`, `POST /v1/auth/2fa/disable`
- Login change: if `users.totp_enabled`, `/login` returns `{ challenge_token, requires_2fa: true }` (no token pair); `POST /v1/auth/2fa/verify-login` trades challenge + code (or backup code) for `TokenPair`
- Access token carries `totp_verified` claim per TDD §8
- Rate-limit verify endpoints: 5 wrong codes per 5-min per user → 429
- Clock skew: TOTP window ±1 step (30s before, 30s after)

**Edge cases tested:**
- Setup → user gets secret + QR + codes; verify w/ valid code enables; wrong code 422
- Login w/ 2FA enabled returns challenge, not tokens; challenge single-use (5-min TTL)
- verify-login: valid code → tokens; expired challenge → 410; wrong code → 422; backup code single-use; reuse → 422
- Disable requires current TOTP code; audit `2fa_disabled`
- 6 wrong codes in 5min → 429 lockout

**Deps added:** `pyotp`, `qrcode[pil]`.

---

### Slice 7 — Password reset + new-device login notification
**Add:**
- `POST /v1/auth/forgot-password`:
  - Rate-limit IP (10/hour) + email (3/hour)
  - Always 200 response (no enumeration)
  - If email exists: generate reset token (15m Redis TTL, single-use), dispatch `send_password_reset_email`
- `POST /v1/auth/reset-password`:
  - Validate token + new password (validator)
  - On success: update `password_hash`, **invalidate all refresh tokens** for user, delete token, audit `password_reset`
- Login (extend Slice 4):
  - Compute device fingerprint = sha256(IP `/24` prefix + User-Agent)
  - Lookup Redis set `known_devices:{user_id}` (sliding 30d per device)
  - New device → dispatch `send_new_device_email` (FR-AUTH-010); audit `new_device_login`
  - Add to set
- `send_password_reset_email` + `send_new_device_email` Celery tasks

**Edge cases tested:**
- Forgot for unknown email → 200; rate limit hit → 429
- Reset valid → 200 + all sessions killed; reused token → 410; expired → 410; weak new password → 422
- Known device → no notification; new device → 1 notification; rotating UA on same IP/24 → still treated new (acceptable)
- Race: 2 concurrent resets w/ same token → one 200, one 410

---

### Slice 8 — KYC submission (gates artifact upload + download)
**Add:**
- Migration: `kyc_documents` table (`id`, `user_id`, `doc_type` (enum: `passport|drivers_license|national_id|proof_of_address`), `s3_key`, `mime_type`, `file_size`, `status` (enum: `pending|verified|rejected`), `reviewed_by`, `reviewed_at`, `notes`)
- `app/modules/auth/service.py`: `request_kyc_upload_url(...)` (returns presigned PUT URL + max size 10MB; mime whitelist `image/jpeg|image/png|application/pdf`), `confirm_kyc_upload(...)` (called after FE finishes PUT), `get_kyc_status(...)`
- `POST /v1/settings/kyc/upload-url`, `POST /v1/settings/kyc/submit`, `GET /v1/settings/kyc`
- `PATCH /v1/admin/users/{id}/kyc` — admin verify/reject (`status` update); audit `kyc_status_change`
- `app/core/dependencies.py`: `require_kyc_verified()` dep — used by Phase 2 frameworks router + Phase 3 financials + artifact upload/download (per session decision)

**Edge cases tested:**
- Upload-url w/ disallowed mime → 415; file > 10MB → 413 (server signs constraints into URL conditions)
- Submit before upload → 409
- Admin verify → `users.kyc_status = verified`, audit row
- `require_kyc_verified` raises 403 when `kyc_status != verified`
- S3 mocked via `moto`

**Deps added:** `boto3`, `moto` (dev).

---

### Slice 9 — OpenAPI contract sync + FE auth client
**Add:**
- Update `contracts/openapi.yaml` with all `/v1/auth/*` + `/v1/admin/users/*` + `/v1/settings/kyc/*` + `/v1/settings/sessions/*` + `/v1/settings/account/*` schemas + responses
- Regenerate `frontend/src/lib/generated/` via existing `hey-api` script
- `frontend/src/lib/auth/token-store.ts`: in-memory access token store (Zustand)
- `frontend/src/lib/auth/refresh-client.ts`: silent refresh helper (calls `/refresh`, updates store; refresh token is HttpOnly cookie set by backend)
- Backend: set refresh token via `Set-Cookie: refresh_token=<...>; HttpOnly; Secure; SameSite=Strict; Path=/v1/auth` on `/login`, `/refresh`, `/2fa/verify-login`; clear on `/logout`

**Test:**
- CI: `openapi-spec-validator` on contract
- FE: type-check generated client; vitest unit on token-store (set/get/clear/expiry)
- Cookie attributes verified in backend integration test

**Deps added:** `zustand` (frontend), `openapi-spec-validator` (backend dev).

---

### Slice 10 — Frontend auth pages + middleware guard
**Add (mobile-first per Brand Book §11–13):**
- `frontend/src/app/(public)/register/page.tsx`, `login/page.tsx`, `verify-email/page.tsx`, `forgot-password/page.tsx`, `reset-password/page.tsx`
- `frontend/src/app/(auth)/2fa-setup/page.tsx`, `2fa-challenge/page.tsx`, `settings/kyc/page.tsx`
- `frontend/src/components/modules/auth/*`: `RegisterForm`, `LoginForm`, `TotpInput`, `BackupCodeInput`, `KycUpload`
- `frontend/middleware.ts`: checks token + role, redirects per role on login (contributor → dashboard, operator → explore, attestor → assignments, admin → admin), gates `(auth)/*`
- Inter Rounded + Poppins via `next/font/google`
- Primary `Button` UI primitive (Brand Blue `#0025CC`) ships here — first consumer is auth forms

**Test:**
- vitest component: form validation, TOTP input format, error states
- playwright e2e `auth.spec.ts`: register → verify (catch token via test endpoint) → login → role-based redirect (FR-AUTH-001/004/007); login → 2FA challenge → tokens; password reset full loop

---

### Slice 11 — Sessions + account email change + deactivation + audit read
**Add:**
- `app/modules/settings/router.py` + `service.py`:
  - `GET /v1/settings/sessions` — list active refresh tokens for user (Redis scan, return `{ id (jti), ip, user_agent, last_seen, created_at, current: bool }`) → FR-SET-009
  - `DELETE /v1/settings/sessions/{id}` — revoke specific refresh; `DELETE /v1/settings/sessions` — revoke all except current → FR-SET-009
  - `POST /v1/settings/account/email-change` — body `{ new_email, totp_code }`. Verify TOTP (BR-AUTH-004), generate verify-new-email token (24h), dispatch `send_email_change_verification` to new address; old email stays until new confirmed (BR-SET-001)
  - `POST /v1/settings/account/email-change/confirm` — body `{ token }` from new email → swap `users.email`, invalidate all sessions, audit `email_changed`
  - `POST /v1/settings/account/deactivate` — body `{ password, totp_code? }`. Set `users.deactivated_at`, revoke all sessions, audit `account_deactivated` (FR-SET-010). Published frameworks remain visible per BR-SET-002 (enforced in Phase 2 read path).
- Refresh tokens stored w/ richer metadata to power session list (extend Slice 4 Redis schema with `ip`, `user_agent`, `last_seen`; update on every `/refresh`)
- FE: `frontend/src/app/(auth)/settings/sessions/page.tsx`, `settings/account/page.tsx` (email + deactivate)

**Edge cases tested:**
- Session list: only own sessions; current marked correctly
- Revoke current session → 200 + immediate 401 on next call
- Email change w/o TOTP when enabled → 403; w/ wrong TOTP → 422; new email already exists → 409 (only here is enumeration acceptable — authenticated path)
- Confirm token: valid → swap + all sessions killed; expired → 410; reused → 410
- Deactivate w/ wrong password → 401; success → `deactivated_at` set, all sessions gone; login attempt → 403

---

## Per-slice working agreement

After each slice the agent will:
1. Open with one-line summary + FR/BR mapping
2. List files to be created/modified before writing
3. Write failing test first per `tdd` skill
4. Implement minimum to pass
5. Run `uv run ruff check && uv run mypy app && uv run pytest --cov` (backend) or `pnpm test` (frontend)
6. **Stop.** Wait for human review + commit. No autonomous next slice.

---

## Risk flags

- **KYC-on-download**: heavier UX friction than FRD says. Operators need verified KYC before downloading purchased artifacts. Confirm before Phase 2.
- **Email deliverability**: `auracles.space` needs SPF/DKIM/DMARC before Slice 3 in any non-local env. Local dev uses Resend test mode.
- **`SECRET_KEY` rotation** invalidates all JWTs + TOTP-secret decryption fails. Document for ops.
- **TOTP secret encryption** re-uses `SECRET_KEY` via Fernet — acceptable Phase 1; switch to AWS KMS in Phase 2.
- **Audit log volume**: every login + 403 + role change writes a row. Index strategy must hold. Consider partitioning by month if volume warrants in Phase 6.
- **No enumeration leak** on register/forgot — UX cost: users can't tell "is this email new?" until they receive (or don't receive) email. Accepted trade-off.
- **Access-token-after-logout** valid until 15m exp (JWT design). Document; revisit if compliance demands shorter window or jti deny-list.

---

## Verification (end-to-end after Slice 11)

1. `docker compose up` (api, db, redis, beat, worker, frontend)
2. Backend: `uv run pytest --cov=app` → ≥ 80% line coverage on `app/modules/auth/**` and `app/modules/settings/**`
3. Frontend: `pnpm test` + `pnpm exec playwright test tests/e2e/auth.spec.ts`
4. Manual smoke:
   register william+test@auracles.space → verify email → login → enable 2FA + save backup codes → logout → login → 2FA challenge → use backup code once → settings → upload KYC docs → admin approve → change email + verify new → list sessions + revoke one → deactivate → confirm login blocked.

---

## Out of scope (later phases)

- OAuth providers (Google, LinkedIn) — FR-AUTH-002 → Phase 2.5
- Notification preferences (FR-SET-008) — Phase 5
- GDPR export/delete (FR-GDPR-*) — Phase 5
- Profile fields beyond email/display_name (FR-SET-001..003) — Phase 5 settings polish
- Payment method / payout account (FR-SET-006/007) — Phase 3 financials
- Admin commission rate / feature flags (FR-SET-011 partial) — Phase 5 admin module
- Rate limiting at Render edge — Phase 6 hardening
