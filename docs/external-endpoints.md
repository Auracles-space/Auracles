# External endpoints — what to register in third-party consoles

Every URL that has to be typed into somebody else's dashboard for Auracles to
work, per environment, plus the stale ones to delete. Verified against the code
on 2026-09-04; `file:line` references are given so a future reader can confirm
rather than trust.

## The rule that decides the host

**Webhooks point at the API. OAuth redirects point at the FRONTEND.**

Webhooks are server-to-server: Stripe's servers call ours directly, so they
address the backend. OAuth redirects carry a browser, and the browser is
carrying auth cookies — which are *host-only*. A cookie set by
`api.auracles.space` is invisible to `auracles.space`. So the redirect must land
on the frontend, which proxies `/api/*` through to the backend
(`frontend/next.config.ts:11-18`) and keeps the whole exchange same-origin.

Getting this backwards produces a login that fails while every credential is
correct, and it reads as a Google misconfiguration rather than a host mistake.
`app/modules/auth/router.py:89` encodes the frontend path as the fallback.

## Environment hosts

| | Staging | Production |
| --- | --- | --- |
| API | `https://api.staging.auracles.space` | `https://api.auracles.space` *(not built yet)* |
| Frontend | `https://staging.auracles.space` | `https://auracles.space` |

> The staging custom domain went live on 2026-09-04, so every URL below is
> final — nothing here will need re-registering. Amplify still answers on
> `main.d1hsumq9pfyik0.amplifyapp.com` as well, but do not register that
> hostname anywhere: Google matches redirect URIs exactly, and a second
> registered origin is a second thing to remember to remove.

## Register these

### Stripe — <https://dashboard.stripe.com/webhooks>

Two endpoints, not one. The app verifies against a comma-separated list of
signing secrets and tries each (`app/integrations/stripe.py:582`), which is what
makes the split possible.

| Endpoint | Staging URL | Events |
| --- | --- | --- |
| Payments | `https://api.staging.auracles.space/v1/webhooks/stripe` | `payment_intent.*`, `payout.*`, `transfer.*` |
| Connect | `https://api.staging.auracles.space/v1/webhooks/stripe` | `account.updated` |

Production later: `https://api.auracles.space/v1/webhooks/stripe`.

Put both signing secrets in `STRIPE_WEBHOOK_SECRET`, comma-separated, no spaces.
Staging's live values are already in Secrets Manager.

### Paystack — Dashboard → Settings → API Keys & Webhooks

| Setting | Staging URL |
| --- | --- |
| Webhook URL | `https://api.staging.auracles.space/v1/webhooks/paystack` |

Production later: `https://api.auracles.space/v1/webhooks/paystack`.

No separate webhook secret exists: Paystack signs with the secret key itself
(HMAC SHA-512), so `PAYSTACK_SECRET_KEY` is the verification key.

### Persona — Dashboard → Webhooks, and the inquiry template

Note the two rows point at **different hosts** — this is the easiest one to
get wrong.

| Setting | Staging URL |
| --- | --- |
| Webhook (server-to-server) | `https://api.staging.auracles.space/v1/webhooks/persona` |
| Redirect after completion (browser) | `https://staging.auracles.space/settings/kyc` |

Production later: `https://api.auracles.space/v1/webhooks/persona` and
`https://auracles.space/settings/kyc`.

The redirect is also held in `PERSONA_REDIRECT_URL`
(`infra/envs/staging/main.tf`), and the template id in
`PERSONA_INQUIRY_TEMPLATE_ID` — both plain env vars, since neither is a
credential.

### Google Cloud — APIs & Services → Credentials → your OAuth 2.0 client

All three point at the **frontend**. Both callback paths are the frontend proxy
route, not the backend's own.

| Setting | Staging URL |
| --- | --- |
| Authorized JavaScript origin | `https://staging.auracles.space` |
| Authorized redirect URI (sign-in) | `https://staging.auracles.space/api/v1/auth/google/callback` |
| Authorized redirect URI (Drive connector) | `https://staging.auracles.space/api/v1/integrations/connectors/google-drive/callback` |

Production later: the same three paths on `https://auracles.space`.

Matching env vars on our side: `GOOGLE_REDIRECT_URI` and
`GOOGLE_DRIVE_REDIRECT_URI`. They must equal what Google holds, character for
character — Google compares exactly, including trailing slashes.

### Resend

No callback URL. What matters is the sending domain's DNS (SPF/DKIM/DMARC at
Namecheap, already live) and `RESEND_AUDIENCE_ID` for the waitlist collector.

## Not console settings — do not go looking

| Thing | Why not |
| --- | --- |
| Stripe `return_url` | Passed per transaction by the frontend (`app/modules/financials/service.py:2699`), never registered |
| Paystack `callback_url` | Optional per transaction; the app does not send one |
| Partner webhooks | *Outbound* — URLs supplied by partners, stored per partner, not configured anywhere by us |

## Stale entries to delete

The platform has left Render and Vercel. Anything still pointing there is at
best dead and at worst dangerous: a hostname nobody owns any more is one
somebody else can register and then receive real traffic on.

- [ ] **Stripe** — two **live-mode** endpoints left from Render. Toggle the
      dashboard to live mode to see them; test mode shows nothing.
- [ ] **Paystack** — check the webhook URL for an `onrender.com` host.
- [ ] **Persona** — same check.
- [ ] **Google Cloud** — remove `dev-auracles.vercel.app` redirect URIs and
      origins once the real ones are registered.
- [ ] **GitHub** — the `vercel` and `render` GitHub Apps are still installed on
      the org and no longer used (`gh api /orgs/Auracles-space/installations`).

Already handled in the repo (2026-09-04, commits `f2ac7e0d` and `a4feabed`):
`BACKEND_ORIGIN` defaulted to `auracles-api.onrender.com` in **two** places —
`frontend/next.config.ts` (the browser rewrite) and
`frontend/src/lib/api-base.ts` (server-side fetches). Both now fall back to
localhost, which cannot be taken over and fails visibly. The stale
`dev-auracles.vercel.app` entry is out of `backend/.env.prod.example`, where it
mattered twice over: `CORS_ALLOWED_ORIGINS` is not only an allowlist, its first
entry is the origin transactional email links are built from.

Still stale but harmless: test fixtures in
`backend/tests/integration/test_auth_google.py` (arbitrary strings), and the
historical design docs under `docs/superpowers/specs/`. One exception worth
retiring deliberately — `docs/dep-steps.md` is an *active* runbook that still
describes deploying to Render.
