# Frontend API Proxy & Cross-Domain Auth

**Status:** active · **Last updated:** 2026-06-24

Why browser API traffic is proxied through the frontend origin, and the env
vars every Vercel project must set. Read this before changing the API base URL,
the auth cookies, or the Vercel project setup.

---

## The problem

The frontend (Vercel) and backend (Render) run on **different registrable
domains**:

- Frontend: `dev-auracles.vercel.app` and `auracles.space`
- Backend: `auracles-api.onrender.com`

`vercel.app` and `onrender.com` are both on the Public Suffix List, so they
cannot share a cookie domain.

The routing middleware (`src/middleware.ts`) gates `/settings/*`, `/admin/*`,
etc. by reading a signed **`session_hint`** cookie that the backend sets at
login. A cookie set by the Render origin is **host-only** — it is stored for
`auracles-api.onrender.com` and is **invisible to the Vercel domain**. So the
middleware always saw `hint = null` and bounced every protected route to
`/login` (the visible symptom was "Start KYC sends me to sign in").

In-memory Bearer auth still worked (that is why login and `/settings/onboarding`
— a whitelisted route — rendered), which made it look like only KYC was broken.

## The fix: same-origin proxy

Browser API traffic is proxied through the frontend origin so every auth cookie
is **first-party** to whatever domain served the page.

- `next.config.ts` rewrites `/api/:path*` → `${BACKEND_ORIGIN}/:path*`.
- `NEXT_PUBLIC_API_URL` is set to the relative path `/api`.
- `src/lib/api-base.ts` resolves the base URL:
  - **Browser** → returns `/api` (relative, same-origin → cookies land on the
    frontend domain).
  - **Server (SSR)** → a relative path cannot be fetched from Node, so it falls
    back to the absolute `BACKEND_ORIGIN`.
- WebSockets are **not** proxied (Vercel rewrites do not upgrade WS, and the WS
  handshake authenticates via a first message, not cookies), so
  `resolveWebsocketUrl()` connects straight to the backend via
  `NEXT_PUBLIC_WS_URL`.

Because the base is a relative path and the rewrite is per-deployment, this works
for **any** frontend domain or alias automatically — no per-domain code.

## Two halves of the bug

Both must hold or auth still bounces:

1. **Delivery** — the proxy puts `session_hint` on the frontend domain. (Code.)
2. **Verification** — the middleware verifies the cookie's HMAC with
   `SESSION_HINT_SECRET`; the backend signs it with `SECRET_KEY`. These two
   values **must be identical**, or the hint fails to verify and the user is
   bounced even though the cookie is present. (Env config.)

## Required Vercel env vars (per project)

Env vars are **per Vercel project**, not in the repo. There are two projects
feeding from the same repo and branch, so the code (rewrite + resolver) ships to
both, but **each project must set these in its own Vercel settings**:

| Var | Value | Notes |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `/api` | Relative → routes browser calls through the proxy. |
| `NEXT_PUBLIC_WS_URL` | `wss://auracles-api.onrender.com/v1/ws` | WS connects directly; not proxied. |
| `SESSION_HINT_SECRET` | **exact value of Render `SECRET_KEY`** | Must match the backend signer. |
| `BACKEND_ORIGIN` | `https://auracles-api.onrender.com` | Optional; defaults to this in code. Rewrite destination + SSR fallback. |

Backend (Render): no code change. The cookie is first-party now, so
`cookie_samesite=lax` is fine; just keep `cookie_secure=true` (HTTPS).

## Gotchas

- **Set `/api` in *both* projects.** If a project still has
  `NEXT_PUBLIC_API_URL` pointing at the absolute `onrender.com` URL, it skips the
  proxy and keeps bouncing on auth. Harmless while `auracles.space` is in
  waitlist mode (no login), but **flip it to `/api` before that project serves
  the authed app**.
- **`SESSION_HINT_SECRET` must equal `SECRET_KEY`.** If you later split
  staging/prod backends, give each Vercel project the secret matching the
  backend it talks to.
- **Local dev needs nothing.** `NEXT_PUBLIC_API_URL` is unset → defaults to the
  absolute `http://localhost:8000`, so the resolver and WS derivation work
  without the proxy (frontend and backend share `localhost`).

## How to verify in production

1. Log in on the frontend domain.
2. DevTools → Application → Cookies → the **frontend** domain. Confirm a
   `session_hint` cookie is present.
3. Click a protected action (e.g. Start KYC). It should navigate, not bounce to
   `/login`.
4. If the cookie is present but it still bounces → `SESSION_HINT_SECRET` ≠
   backend `SECRET_KEY`.

## Related code

- `frontend/next.config.ts` — the `/api` rewrite.
- `frontend/src/lib/api-base.ts` — base + WS resolution (`resolveApiBaseUrl`,
  `resolveWebsocketUrl`).
- `frontend/src/middleware.ts`, `frontend/src/lib/auth/route-guards.ts` —
  cookie-based route gating.
- `backend/app/core/cookies.py` — signs `session_hint` with `SECRET_KEY`.
- `frontend/tests/unit/lib/api-base.test.ts` — regression coverage.
