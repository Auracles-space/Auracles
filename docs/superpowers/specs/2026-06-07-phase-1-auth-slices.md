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
| FR-AUTH-002 | OAuth Google + LinkedIn | **DEFERRED — approved Phase 1 deviation** (post-Phase 1, target Phase 2.5) |
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

## Approved FRD deviations (Phase 1)

| FRD ref | FRD says | Plan does | Reason | Approved |
|---------|----------|-----------|--------|----------|
| FR-AUTH-002 | OAuth Google + LinkedIn at registration | Email/password only; `oauth_accounts` table shipped schema-only for future use | Scope control — OAuth is its own integration surface | Human, 2026-06-07 |
| FR-AUTH-001 (duplicate handling) | `409 Conflict` on duplicate email register | `200` + generic "if email is new, verification sent" | Prevents email enumeration; security > literal spec | Human, 2026-06-07 |
| FR-AUTH-009 / BR-AUTH-002 (KYC scope) | Contributor KYC for payout + framework publish | **Additionally**: Operator KYC required before downloading purchased artifacts (Contributor side unchanged: still gates framework + artifact upload/publish + payout) | Trust floor for marketplace; flag to legal/UX before Phase 2 | Human, 2026-06-07 |
| TDD §8 (refresh token in JSON) | Login returns `{ access, refresh }` in JSON | Browser flows: refresh travels via HttpOnly cookie only; JSON returns access only. Mobile/API flows via `X-Client-Type` header reserved for later. | Browser-side XSS protection | Human, 2026-06-07 |

---

## Architectural decisions captured this session

| Decision | Value | Note |
|----------|-------|------|
| OAuth (Google/LinkedIn) | **Defer — approved deviation from FR-AUTH-002** | Email/password only in Phase 1. Re-opens Phase 2.5. Human-approved 2026-06-07. |
| KYC scope | **Contributor KYC** gates framework + artifact publish/upload **and** payout. **Operator KYC** gates download of purchased artifacts. | **Approved expansion** beyond FR-AUTH-009 / BR-AUTH-002 (which only cover Contributor publish + payout). Adds Operator-side gate on downloads. Human approved 2026-06-07 — heavier UX friction accepted. Trust floor for marketplace. |
| Duplicate registration | **No-enumeration: 200 + generic message** | **Approved deviation from FR-AUTH-001 / FRD §409 response** — security > literal FRD compliance. Human approved 2026-06-07. |
| Browser refresh contract | **HttpOnly cookie only — JSON never carries refresh token for browser clients** | Backend sets `Set-Cookie: refresh_token=...; HttpOnly; Secure; SameSite=<env-driven>; Path=/v1/auth` on login/refresh/2fa-verify-login; clears on logout. JSON returns `LoginResponse { access_token, token_type, expires_in }` only. TDD §8 refresh-in-JSON pattern reserved for future non-browser clients (mobile/API) gated by `X-Client-Type` header. |
| Cookie SameSite | **`Strict` only when API + frontend share an eTLD+1** (e.g. `auracles.space` + `api.auracles.space`). **Fallback `None`** when API stays on `*.onrender.com` while FE is on a Vercel domain — Render `onrender.com` is a different site → `Strict` blocks the cookie. | Driven by env var `COOKIE_SAMESITE` (`strict` \| `none`) read in `app/core/cookies.py`. Default `strict` in prod once `api.auracles.space` DNS exists; `none` until then. `None` always paired with `Secure` (browser requirement) **and** strict `CORS_ALLOWED_ORIGINS` allowlist (no `*`). |
| Domain plan | **Preferred:** `api.auracles.space` (Render custom domain) + `auracles.space` (Vercel). **Fallback:** `*.onrender.com` API + Vercel FE w/ `SameSite=None`. | Pre-Slice-4 deploy task: provision Render custom domain + DNS. If delayed → use fallback, file follow-up to flip to `Strict` once custom domain live. |
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
| CORS | FastAPI `CORSMiddleware` allowlist `CORS_ALLOWED_ORIGINS` (new backend setting in `app/core/config.py`; comma-separated; e.g. `http://localhost:3000` dev, `https://auracles.space` prod) only, `credentials: true` for refresh cookie | Slice 4. |
| Audit log | New DB table `audit_logs` lands in **Slice 1**; written directly from Slice 3 onward | Loguru structured logs continue alongside; DB table = queryable security trail. |

---

## Cross-cutting concerns (apply to every slice)

These rules apply across all slices — call them out in each slice's tests rather than assuming.

1. **Pydantic schemas** on every input. No raw dict.
2. **Loguru bound context** (`module`, `action`, `user_id` if known, `request_id` from middleware) on every log line.
3. **Audit DB write** for every event in CLAUDE.md logging table (login_success, login_failure, access_denied, password_reset, role change, 2fa_enabled/disabled, kyc_status_change). Table `audit_logs` lands in Slice 1; helper `audit.write(db, actor_id, action, target_id, metadata, ip, ua)` lands in Slice 2; every later slice writes directly — no conditional, no no-op.
4. **No secret in logs.** Never log tokens, passwords, TOTP codes, S3 presigned URLs.
5. **Idempotency.** Verify-email, reset-password, refresh, logout all safe to retry.
6. **Transactions.** Any write touching 2+ tables uses `async with db.begin()`.

---

## Slice plan

Each slice ends green: `ruff` + `mypy --strict` + `pytest --cov` (100% on touched modules) + Alembic `upgrade head` and `downgrade -1` both succeed. **One commit per slice.** Human reviews + commits before next slice starts.

---

### Slice 1 — Schema foundation
> **Repo state note:** `backend/alembic.ini` + `backend/migrations/env.py` + `backend/migrations/versions/` already exist (Phase 0). Slice 1 only **adds** migration files under `backend/migrations/versions/` — no env.py rewrite.

**Add:**
- Migration `backend/migrations/versions/2026_06_07_initial_users_and_roles.py`:
  - Enums: `role_enum` (contributor, operator, attestor, admin), `kyc_status_enum` (unverified, pending, verified, rejected)
  - `users` table per TDD §3 + `users.deactivated_at` (FR-SET-010 prep)
  - `user_roles` table per TDD §3
  - `oauth_accounts` table (schema-only; no endpoints this phase — supports future FR-AUTH-002)
  - **`audit_logs`** table: `id`, `actor_id` (nullable for system/unauth), `action` (varchar), `target_type`, `target_id` (nullable), `metadata` (jsonb), `ip_address` (inet), `user_agent` (text), `created_at`. Indexed on (actor_id, created_at) + (action, created_at).
- SQLAlchemy ORM: `app/modules/auth/models.py` (User, UserRole, OAuthAccount), `app/shared/models/audit_log.py` (AuditLog)
- `app/shared/models/base.py` extension if needed for `TimestampMixin`
- **Bootstrap script** `backend/scripts/bootstrap_admin.py` — idempotent CLI (`uv run python -m scripts.bootstrap_admin`) reading `ADMIN_EMAIL` + `ADMIN_PASSWORD` env vars, hashes via `app.core.security.hash_password`, inserts admin user + admin role row if not present. **Not a migration** — keeps env-dependent data out of schema versioning (per agent finding #7). Documented in `backend/README.md` as required first-run step.

**Test (`tests/unit/test_migrations.py` + `tests/unit/test_bootstrap_admin.py`):**
- `upgrade head` → assert all tables + indexes + enums exist
- `downgrade -1` → assert clean
- Bootstrap with env set → admin user + admin role inserted; without env → exits non-zero with message; idempotent re-run → no duplicate

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
> **Browser contract:** access token returned in JSON; refresh token returned **only** as HttpOnly `Set-Cookie`. No `refresh_token` field in browser JSON responses. (Agent finding #5.)

**Add:**
- `app/main.py`: `CORSMiddleware` allowlist `CORS_ALLOWED_ORIGINS` (new backend setting in `app/core/config.py`; comma-separated; e.g. `http://localhost:3000` dev, `https://auracles.space` prod), `allow_credentials=True`
- `app/modules/auth/schemas.py`:
  - `LoginRequest`
  - `LoginResponse { access_token, token_type: "bearer", expires_in }` (browser path — refresh travels via cookie)
  - `RefreshRequest` (empty body — server reads cookie)
  - Internal `RefreshTokenRecord` Pydantic (Redis value shape)
- **Cookie helpers** (`app/core/cookies.py`): `set_refresh_cookie(response, token)` writes `Set-Cookie: refresh_token=<token>; HttpOnly; Secure; SameSite=<settings.COOKIE_SAMESITE>; Path=/v1/auth; Max-Age=2592000`; `clear_refresh_cookie(response)`. `COOKIE_SAMESITE` env var in `app/core/config.py` Settings (`Literal["strict", "none"]`, default `"strict"`). When `"none"` → assert `Secure` always set (FastAPI dep check at startup). Validates at startup that if `COOKIE_SAMESITE=none`, `CORS_ALLOWED_ORIGINS` does not contain `*`.
- **`contracts/openapi.yaml` updated this slice** (per agent finding #8) — every endpoint added in slices 3–8 updates the contract in the same slice. Slice 9 only ships FE codegen + utilities.
- `app/modules/auth/service.py`:
  - `login(email, password, ip, ua)`:
    - Rate-limit IP (20/min) + email (5 failures/15min) — lockout key in Redis
    - Verify password; failures → audit `login_failure`, increment lockout counter
    - Check `email_verified`; if false → 403 (no token issued)
    - Check `users.deactivated_at`; if set → 403
    - Compute device fingerprint hook (filled in Slice 7); placeholder no-op here
    - Issue access (15m) + refresh (sliding 30d TTL); store refresh in Redis as `refresh:{sha256(token)} -> { user_id, family_id, issued_at, ip, user_agent, last_seen }`; **set refresh cookie** via helper; JSON returns access only; audit `login_success`
  - `refresh(cookie_token, ip, ua)`:
    - Read cookie; if missing → 401
    - Lookup Redis; if missing → 401
    - **Rotate**: issue new access + new refresh; delete old; reset Redis TTL to 30d (sliding) per BR-AUTH-003; set new cookie
    - If reused old token detected (same family but already deleted) → revoke entire family (token-theft signal); clear cookie; audit `refresh_token_reuse_detected`
    - Audit `token_refresh`
  - `logout(cookie_token)`: delete refresh from Redis; clear cookie; access token remains valid until exp (documented limitation); audit `logout`
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
  - TOTP secret encrypt/decrypt via Fernet keyed off **separate** `TOTP_ENCRYPTION_KEY` env var (urlsafe base64-encoded 32-byte key — Fernet format). Added to `app/core/config.py` Settings + `.env.example`. Generation note in `backend/README.md`: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Not derived from `SECRET_KEY` — separate rotation, separate blast radius.
  - `generate_backup_codes(n=10) -> list[str]` (single-use, format `xxxx-xxxx`); hash each (sha256) for storage
- Migration: `user_backup_codes` table (`id`, `user_id`, `code_hash`, `used_at`)
- `app/modules/auth/service.py`: `setup_totp`, `verify_totp_enable`, `disable_totp`, `verify_totp_login`, `consume_backup_code`
- `POST /v1/auth/2fa/setup` (returns provisioning URI + QR PNG b64 + 10 backup codes **shown once**), `POST /v1/auth/2fa/verify`, `POST /v1/auth/2fa/disable`
- Login change: if `users.totp_enabled`, `/login` returns `{ challenge_token, requires_2fa: true }` (no tokens, no cookie); `POST /v1/auth/2fa/verify-login` trades challenge + code (or backup code) for `LoginResponse` (access token in JSON) + sets HttpOnly refresh cookie + `session_hint` cookie — same browser contract as `/login` success path. No `TokenPair` JSON.
- Access token carries `totp_verified` claim per TDD §8
- Rate-limit verify endpoints: 5 wrong codes per 5-min per user → 429
- Clock skew: TOTP window ±1 step (30s before, 30s after)

**Edge cases tested:**
- Setup → user gets secret + QR + codes; verify w/ valid code enables; wrong code 422
- Login w/ 2FA enabled returns challenge, not tokens; challenge single-use (5-min TTL)
- verify-login: valid code → `LoginResponse` + refresh cookie + session_hint cookie set; expired challenge → 410; wrong code → 422; backup code single-use; reuse → 422
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

### Slice 8 — KYC submission (Contributor: gates upload + publish + payout; Operator: gates artifact download)
**Add:**
- Migration: `kyc_documents` table (`id`, `user_id`, `doc_type` (enum: `passport|drivers_license|national_id|proof_of_address`), `s3_key`, `mime_type`, `file_size`, `status` (enum: `pending|verified|rejected`), `reviewed_by`, `reviewed_at`, `notes`)
- `app/modules/auth/service.py`: `request_kyc_upload_url(...)` (returns presigned POST target + max size 10MB; mime whitelist `image/jpeg|image/png|application/pdf`), `confirm_kyc_upload(...)` (called after FE finishes POST), `get_kyc_status(...)`
- `POST /v1/settings/kyc/upload-url`, `POST /v1/settings/kyc/submit`, `GET /v1/settings/kyc`
- `PATCH /v1/admin/users/{id}/kyc` — admin verify/reject (`status` update); audit `kyc_status_change`
- `app/core/dependencies.py`: `require_kyc_verified()` dep — Phase 2 Contributor paths (framework + artifact upload/publish), Phase 2 Operator path (purchased artifact download), Phase 3 financials (payout). Same dep, different consumers.

**Edge cases tested:**
- Upload-url w/ disallowed mime → 415; file > 10MB → 413 (server signs constraints into URL conditions)
- Submit before upload → 409
- Admin verify → `users.kyc_status = verified`, audit row
- `require_kyc_verified` raises 403 when `kyc_status != verified`
- S3 mocked via `moto`

**Deps added:** `boto3`, `moto` (dev).

---

### Slice 9 — FE auth client + middleware guard prep
> **Contract sync moved.** Per agent finding #8, `contracts/openapi.yaml` is updated **in each backend slice** (3–8 + 11). Slice 9 only ships the FE side.

**Add:**
- Regenerate `frontend/src/lib/generated/` via existing `hey-api` script against the now-complete `contracts/openapi.yaml`
- `frontend/src/lib/auth/token-store.ts`: in-memory Zustand store for **access token** + `{ userId, roles, totpVerified, expiresAt }` derived from JWT payload
- `frontend/src/lib/auth/refresh-client.ts`: silent refresh helper — calls `POST /v1/auth/refresh` w/ `credentials: 'include'`, updates store on 200, clears on 401
- `frontend/src/lib/auth/session-hint-cookie.ts`: server-side helper reading a **non-HttpOnly `session_hint` cookie** (set by backend alongside refresh cookie, contains `{ userId, roles, exp }` signed payload — NO secrets). Used by Next.js middleware **for routing only**. **Backend authorization never trusts `session_hint`** — every protected API call re-validates the JWT and re-reads roles from DB. Role grants/revocations and admin actions (Slice 5 + Slice 8 admin endpoints) must re-issue both refresh and `session_hint` cookies so stale roles cannot route the user incorrectly; if re-issue is not practical (e.g., admin demotes another user mid-session), the next `/refresh` call refreshes the hint.
- **Backend addition:** alongside HttpOnly refresh cookie, set `session_hint` cookie (HttpOnly=false, `SameSite=<settings.COOKIE_SAMESITE>` matching refresh cookie, `Secure`, signed w/ `SECRET_KEY` HMAC, 30d Max-Age) carrying `{ user_id, roles, totp_verified, exp }`. Cleared on logout. Middleware verifies signature server-side before trusting.
- Add `openapi-spec-validator` CI step (lints contract on every PR touching `contracts/`)

**Test:**
- CI: `openapi-spec-validator` passes
- FE: type-check generated client; vitest on token-store (set/get/clear/expiry); vitest on session-hint signature verify (good sig → parsed; tampered → rejected)
- Backend integration: cookie attributes asserted for both `refresh_token` (HttpOnly) and `session_hint` (signed, readable)

**Deps added:** `zustand` (frontend), `openapi-spec-validator` (backend dev).

---

### Slice 10 — Frontend auth pages + middleware guard
**Add (mobile-first per Brand Book §11–13):**
- `frontend/src/app/(public)/register/page.tsx`, `login/page.tsx`, `verify-email/page.tsx`, `forgot-password/page.tsx`, `reset-password/page.tsx`
- `frontend/src/app/(auth)/2fa-setup/page.tsx`, `2fa-challenge/page.tsx`, `settings/kyc/page.tsx`
- `frontend/src/components/modules/auth/*`: `RegisterForm`, `LoginForm`, `TotpInput`, `BackupCodeInput`, `KycUpload`
- `frontend/middleware.ts`: reads + verifies `session_hint` cookie (from Slice 9), redirects per role on login (contributor → dashboard, operator → explore, attestor → assignments, admin → admin), gates `(auth)/*`. **Does not** trust the access token (lives in memory only, invisible to middleware — agent finding #6). Backend remains source of truth on every protected API call.
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
- **`SECRET_KEY` rotation** invalidates all JWTs + session-hint signatures. Document for ops.
- **`TOTP_ENCRYPTION_KEY` rotation** = lost 2FA secrets for every existing user → all must re-enroll. Separate from `SECRET_KEY` so JWT rotation does not break 2FA. Phase 2 migrates to AWS KMS envelope encryption.
- **Audit log volume**: every login + 403 + role change writes a row. Index strategy must hold. Consider partitioning by month if volume warrants in Phase 6.
- **No enumeration leak** on register/forgot — UX cost: users can't tell "is this email new?" until they receive (or don't receive) email. Accepted trade-off.
- **Access-token-after-logout** valid until 15m exp (JWT design). Document; revisit if compliance demands shorter window or jti deny-list.
- **Cross-site cookies (Render + Vercel)**: until `api.auracles.space` DNS is provisioned, `COOKIE_SAMESITE=none` is in effect. `None` accepts third-party cookie contexts → defense relies on strict `CORS_ALLOWED_ORIGINS` + `Secure` flag + signed `session_hint`. Flip to `strict` post-DNS. Track as deploy follow-up.

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
