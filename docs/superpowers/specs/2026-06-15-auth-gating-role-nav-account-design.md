# Auth Gating + Role-Based Nav + Account/Profile — Design

**Date:** 2026-06-15
**Status:** Approved (brainstorming)
**Area:** Frontend (Next.js). No backend changes.

## Problem

1. **Pages not locked by auth state.** The pure decision helper
   (`route-guards.ts`) and the signed `session_hint` cookie exist, but there is
   **no `frontend/src/middleware.ts`** wiring them — so the guard never runs and
   `(auth)` routes render regardless of auth state.
2. **All users see all nav, incl. Admin.** `AuthenticatedAppShell` hardcodes the
   full `appLinks` array (including `/admin/analytics`) for everyone; it receives
   no roles. Info disclosure + broken UX.
3. **No account/profile surface.** The sidebar profile widget and the "Sign out"
   button are dead (no handlers); there is no page to view your own identity,
   email-verification, or KYC status.

Framing: the backend already enforces RBAC (deny-by-default, `require_role`,
`require_kyc_verified`). Frontend gating is **UX + info-disclosure**, not the
security boundary. The real gate stays server-side.

## What already exists (reused, not rebuilt)

- `src/lib/auth/route-guards.ts` — `resolveAuthRouteDecision`,
  `getRoleLandingPath`, protected-prefix list (currently auth-gate only).
- `src/lib/auth/session-hint-cookie.ts` — `verifySessionHintCookie(value, secret)`
  (HMAC-SHA256, carries `roles`, `exp`).
- `src/lib/auth/token-store.ts` — zustand store with `roles`, `clearAuthToken()`.
- `AuthenticatedAppShell` — styled sidebar/header; needs a `roles` prop + filter.
- Public **contributor** profile: `GET /v1/explore/contributors/{id}` +
  `(public)/explore/contributors/[id]/page.tsx`. Operators intentionally have no
  public profile.
- Email verification: `users.email_verified`, register→`ev_` token (Redis, 24h),
  `verify_email`, resend, `/verify-email` page.
- KYC: `users.kyc_status` (`unverified`→`pending`→`verified`|`rejected`),
  `POST /v1/settings/kyc/upload-url`, `/kyc/submit`, `GET /kyc`; admin review via
  `PATCH /v1/admin/users/{id}/kyc`. Gate: `require_kyc_verified`.
- Admin creation: `scripts/bootstrap_admin.py` (first admin) + admin directory
  `PATCH /v1/admin/users/{id}/roles`. Registration cannot grant `admin`
  (`AssignableRole = contributor|operator|attestor`).

## Role model (locked)

`roles` is a **set** on the verified `session_hint`. operator + contributor can
coexist on one user; attestor is standalone; admin is standalone. `admin` is
never self-assignable (backend-enforced).

## Design

### 1. Middleware route-lock — role-gate (option A)

**New `frontend/src/middleware.ts`:**
- Read `session_hint` cookie; `hint = await verifySessionHintCookie(value,
  process.env.SESSION_HINT_SECRET)`.
- Call `resolveAuthRouteDecision({ hint, pathname })`; apply `next` or
  `NextResponse.redirect`.
- `config.matcher` covers protected prefixes and the auth pages that redirect
  when already logged in; excludes `/explore`, `/`, static assets, `_next`, API.

**Extend `route-guards.ts`** to role-gate (today it only auth-gates):
- Add a path→required-roles map:
  ```
  /admin                    -> ["admin"]
  /attestor                 -> ["attestor"]
  /attestations             -> ["attestor"]
  /dashboard                -> ["contributor"]
  /library                  -> ["operator"]
  /checkout                 -> ["operator"]
  /projects                 -> ["operator", "contributor"]   # any of
  /settings                 -> any logged-in
  /2fa-setup                -> any logged-in
  ```
- Decision order in `resolveAuthRouteDecision`:
  1. `/2fa-challenge`, `/settings/onboarding` → `next` (unchanged).
  2. logged-in on `/login`|`/register` → redirect `getRoleLandingPath(roles)`.
  3. not logged-in on protected prefix → redirect `/login?next=<pathname>`.
  4. logged-in on protected prefix whose required-roles set is non-empty and the
     user holds **none** of them → redirect `getRoleLandingPath(roles)`.
  5. else → `next`.
- **Fix `getRoleLandingPath`:** attestor → `/attestor/assignments` (route that
  exists; not `/assignments`); admin → `/admin`; operator → `/explore`;
  contributor (fallback) → `/dashboard`.

**Env:** `SESSION_HINT_SECRET` (= backend `SECRET_KEY`) must be set in Vercel and
local `.env` for the frontend; middleware verification fails closed without it
(treats hint as null → redirects to login). Already consumed by
`explore/layout.tsx`.

### 2. Role-based nav

- `AuthenticatedAppShell` gains `roles: string[]` prop.
- Each `appLinks` entry gains `roles: string[] | null` (`null` = any logged-in):
  ```
  Explore        -> null
  Projects       -> ["operator","contributor"]
  Attestations   -> ["attestor"]
  Attestor       -> ["attestor"]
  Frameworks     -> ["contributor"]
  Collections    -> ["contributor"]
  Earnings       -> ["contributor"]
  Payouts        -> ["contributor"]
  Developer      -> ["contributor"]
  Library        -> ["operator"]
  Credentials    -> ["attestor"]            # verify intent during impl
  Consent        -> null
  Notifications  -> null
  Saved Searches -> null
  Admin          -> ["admin"]
  Settings       -> null
  ```
- Pure filter helper `visibleNavLinks(links, roles)` (unit-tested): keep links
  where `roles === null` or the user holds ≥1 listed role.
- Roles are supplied **server-side** to avoid a client flash of wrong links: a
  shared `(auth)` layout (`src/app/(auth)/layout.tsx`) verifies the hint once via
  `verifySessionHintCookie`, and passes `roles` into the shell. Per-section
  layouts that today render the shell on presence-only (`!!session_hint`) are
  consolidated to defer to this shared layout (or pass roles through). If no
  valid hint, the shared layout redirects to `/login` (middleware already does;
  this is defense-in-depth for direct RSC renders).

### 3. Account / profile (Scope A — private identity)

- **Sidebar account widget → dropdown** (client component using `token-store`
  roles + a server-provided display name/email): shows name, email, active
  roles, theme toggle, and **Sign out**.
- **Sign out**: call the existing logout endpoint (revokes refresh token),
  `clearAuthToken()`, clear `session_hint` (server action / route handler since
  it is `HttpOnly`), redirect `/login`.
- **`/settings/profile` page** under `(auth)/settings`:
  - Identity: name, email, avatar, active roles.
  - **Email verification**: show `email_verified`; if false, a "Resend
    verification email" action (existing resend endpoint).
  - **KYC**: show `kyc_status`; link to the existing settings KYC upload/submit
    flow to start/continue verification; show `pending`/`rejected` states.
  - Editable fields only where the backend already allows (name/avatar via
    existing settings endpoints). No new backend.
- Public contributor profile stays as-is; no operator public profile.

### 4. Admin creation (documentation only, no code)

- First admin: `scripts/bootstrap_admin.py` (server-run, idempotent).
- Further admins: existing admin promotes via the admin user directory
  (`PATCH /v1/admin/users/{id}/roles`).
- Confirm the **register form** lists only `contributor`/`operator`/`attestor`
  (no `admin` option). Backend already rejects `admin` at registration.

## Testing

- **Unit (vitest):**
  - `resolveAuthRouteDecision`: for each role and each protected prefix —
    logged-out→`/login?next=`; wrong-role→`getRoleLandingPath`; right-role→`next`;
    operator+contributor sees both `/projects` and own areas; `/explore` always
    `next`; logged-in on `/login`→landing.
  - `getRoleLandingPath`: admin→`/admin`, attestor→`/attestor/assignments`,
    operator→`/explore`, contributor→`/dashboard`.
  - `visibleNavLinks`: admin-only link hidden for non-admin; operator+contributor
    union; `null` links always present.
- **E2E (`auth.spec.ts` extended):**
  - Logged-out visiting `/library` → redirected to `/login`.
  - Operator visiting `/admin` → redirected to landing; Admin link absent from
    nav.
  - Admin sees Admin link and reaches `/admin`.
  - Sign-out clears session and returns to `/login`; protected route then
    redirects.
- Mobile-first check at 375px for the account dropdown and `/settings/profile`
  (per project standard; `frontend-design` skill invoked at implementation).

## Slice plan (~6)

1. Extend `route-guards.ts` with path→roles map + role-gate decision + landing
   fixes; unit tests (red→green).
2. Add `frontend/src/middleware.ts` wiring verify + decision; `matcher` config.
3. Role-filter nav: `visibleNavLinks` helper + `roles` prop on shell + per-link
   roles; unit test.
4. Shared `(auth)/layout.tsx` verifying hint server-side and passing `roles`;
   consolidate per-section presence-only layouts.
5. Account dropdown + Sign out (logout + clear token + clear session_hint +
   redirect).
6. `/settings/profile` page (identity + email-verify + KYC status/links); extend
   `auth.spec.ts` E2E; verify register form role options.

## Risks / notes

- **`SESSION_HINT_SECRET` parity:** must equal backend `SECRET_KEY` in every
  environment or middleware fails closed (everyone treated as logged-out). Add to
  Vercel + `.env`/`.env.prod`.
- **Fail-closed posture:** verification errors or missing secret → null hint →
  redirect to login. Acceptable and safe.
- **`/attestations` = attestor-only (locked).** If requestors (operators/
  contributors) later need to view attestation requests they raised, revisit this
  row — backend `attestation` router already distinguishes `requestor|attestor`.
- **Hint freshness:** roles in the hint reflect last login/refresh. A role
  granted by an admin mid-session appears after the next token refresh; backend
  RBAC is authoritative regardless. Acceptable.
- Frontend gating never replaces backend RBAC; it only hides/redirects.

## Out of scope

- Public operator profile (intentionally none).
- Public contributor profile changes (already built).
- Any backend change (all required endpoints already exist).
- External KYC provider (review stays manual via admin).
