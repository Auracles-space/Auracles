# Phase 6 · G4 (prod infra) + G5 (deploy CI/CD) — Provisioning Runbook

> **Status:** Config authored by agent. **Provisioning + deploy = human** (CLAUDE.md: agent cannot deploy to Render/Vercel/AWS or create accounts).
> **Date:** 2026-06-14
> **Stack:** Render (api/worker/beat) · Neon (Postgres) · Upstash (Redis) · Resend (email) · AWS S3 (files) · Vercel (frontend) · Stripe (payments).
> Grounded in `2026-06-07-pre-scale-infra-design.md`. This runbook reconciles that doc with the *actual* code (env vars, uv build, 4 S3 buckets, 3 Fernet keys).

---

## What the agent produced

| File | Purpose | Gate |
|---|---|---|
| `render.yaml` | Render blueprint: 3 services + `auracles-secrets` group (all `sync: false`), `autoDeploy: false`, healthcheck `/v1/health` | G4 |
| `.github/workflows/deploy.yml` | `workflow_run` on **Checks** success → curl 3 Render deploy hooks | G5 |
| `frontend/.env.example` | Frontend env template (Vercel mirror) | G4 |
| `.github/workflows/checks.yml` | (already existed) test+build CI gate — deploy depends on it | G5 |

**Deploy is CI-gated:** `autoDeploy: false` + deploy.yml only fires when Checks passes → broken commits never ship.

---

## G4 — Human provisioning checklist

Do in order. Nothing here the agent can do.

### 1. Neon (Postgres 16)
- [ ] Create project. Two branches: `main` (prod), `develop` (staging).
- [ ] Copy pooled connection string; convert driver prefix to **`postgresql+asyncpg://`** and keep `?sslmode=require`.
- [ ] Holds `DATABASE_URL`.

### 2. Upstash (Redis)
- [ ] Create Redis DB (TLS — `rediss://`). Region near Render.
- [ ] App derives broker = `URL/0`, cache = `URL/1` — provide the base `REDIS_URL`.

### 3. AWS S3
- [ ] Create 4 private buckets: `auracles-artifacts`, `auracles-avatars`, `auracles-reports`, `auracles-thumbnails`.
- [ ] Block all public access; access only via presigned URLs.
- [ ] IAM user, least-privilege policy (Get/Put/Delete on those 4 buckets only) → `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, region → `AWS_DEFAULT_REGION`.

### 4. Resend (email)
- [ ] Verify domain `auracles.space` (add SPF `include:_spf.resend.com`, DKIM CNAME, DMARC — see infra doc §3.4).
- [ ] API key → `RESEND_API_KEY`. Sender `noreply@auracles.space` → `RESEND_FROM_ADDRESS`.

### 5. Stripe
- [ ] Live secret key → `STRIPE_SECRET_KEY`.
- [ ] Add webhook endpoint `https://<api-host>/v1/webhooks/stripe` → signing secret → `STRIPE_WEBHOOK_SECRET`.
- [ ] Frontend publishable key → Vercel `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`.

### 6. Generate the crypto secrets (do NOT reuse dev values — prod boot fails on placeholders)
```bash
openssl rand -hex 32                                                   # SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # TOTP_ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # PAYOUT_ACCOUNT_ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # PARTNER_WEBHOOK_ENCRYPTION_KEY
```

### 7. Render
- [ ] New Blueprint from repo → Render reads `render.yaml`, creates api/worker/beat.
- [ ] Open Environment Group `auracles-secrets`, fill every `sync: false` key (table below).
- [ ] Set `CORS_ALLOWED_ORIGINS` to the prod Vercel origin (no `*`).
- [ ] Copy each service's **Deploy Hook URL** → GitHub repo secrets (G5).
- [ ] First deploy manual; confirm `/v1/health` is 200 and beat/worker logs show ready.

### 8. Vercel (frontend)
- [ ] Import repo, root = `frontend/`. Connect prod → `main`, preview → `develop`.
- [ ] Set env vars (see frontend table). `NEXT_PUBLIC_API_URL` = the Render API URL.

---

## G5 — Deploy wiring

- [ ] GitHub repo secrets:
  - `RENDER_DEPLOY_HOOK_API`
  - `RENDER_DEPLOY_HOOK_WORKER`
  - `RENDER_DEPLOY_HOOK_BEAT`
- [ ] Push to `main` → **Checks** runs → on success **Deploy** fires the 3 hooks → Render rebuilds, API runs `alembic upgrade head` on boot.
- [ ] Vercel auto-deploys frontend on the same push (its own git integration — not in deploy.yml).
- [ ] Verify: failed Checks ⇒ no deploy (test by pushing a deliberately failing branch to `develop`, optional).

---

## Backend env var inventory (Render `auracles-secrets` + inline)

| Var | Secret? | Source | Notes |
|---|---|---|---|
| `DATABASE_URL` | secret | Neon | `postgresql+asyncpg://…?sslmode=require` |
| `REDIS_URL` | secret | Upstash | `rediss://…`; app derives `/0` broker, `/1` cache |
| `SECRET_KEY` | secret | generated | JWT signing; prod-mandatory non-placeholder |
| `TOTP_ENCRYPTION_KEY` | secret | generated (Fernet) | prod boot fails if placeholder |
| `PAYOUT_ACCOUNT_ENCRYPTION_KEY` | secret | generated (Fernet) | prod boot fails if placeholder |
| `PARTNER_WEBHOOK_ENCRYPTION_KEY` | secret | generated (Fernet) | prod boot fails if placeholder |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | secret | chosen | bootstrap admin account |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | secret | AWS IAM | least-privilege |
| `AWS_DEFAULT_REGION` | secret | AWS | e.g. `us-east-1` |
| `S3_ARTIFACTS_BUCKET` / `S3_AVATARS_BUCKET` / `S3_REPORTS_BUCKET` / `S3_THUMBNAILS_BUCKET` | secret | AWS | 4 private buckets |
| `RESEND_API_KEY` / `RESEND_FROM_ADDRESS` | secret | Resend | `noreply@auracles.space` |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | secret | Stripe | webhook secret per endpoint |
| `BRAVE_SEARCH_API_KEY` | secret | Brave | plagiarism/search integration |
| `CORS_ALLOWED_ORIGINS` | secret | chosen | prod Vercel origin, no `*` |
| `ENVIRONMENT` | inline | render.yaml | `production` |
| `LOG_FORMAT` | inline | render.yaml | `json` (Render log drain) |
| `TRUST_PROXY_HEADERS` | inline | render.yaml (api) | `true` behind Render proxy |
| `COOKIE_SAMESITE` | inline | render.yaml (api) | `none` (cross-site Vercel↔Render) |

Optional / deferred: `PAYSTACK_SECRET_KEY`, `PAYSTACK_WEBHOOK_SECRET` (Nigeria rails — config-optional, Stripe-only at launch). `OCR_*`, `PLATFORM_COMMISSION_RATE` have safe defaults; override only if needed.

## Frontend env var inventory (Vercel)

| Var | Scope | Notes |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | public | Render API base URL |
| `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` | public | Stripe pk_live |
| `SECRET_KEY` | server | must match backend `SECRET_KEY` |
| `SESSION_HINT_SECRET` | server | must match backend session-hint secret |
| `AUTH_SECRET` | server | `openssl rand -hex 32` |

---

## Open decisions (human)

1. **Render region** — `render.yaml` omits region (Render default Oregon). Set explicitly if you want EU/closer to Neon+Upstash to cut latency.
2. **Staging blueprint** — render.yaml is the prod (`main`) blueprint. Decide: second blueprint on `develop`, or Render preview environments. deploy.yml already triggers on both branches once staging hooks exist.
3. **Plan sizing** — all 3 services `starter`. Beat is light; could drop to a smaller plan.

---

## Reconciliation notes (vs infra design doc)

- **Build:** Dockerfile uses **uv** (`uv sync --frozen`), not pip/requirements.txt. CI (`checks.yml`) already uses uv — the infra doc's pip snippet is stale; ignore it.
- **Image registry:** Phase 1 Render builds from `backend/Dockerfile` directly — **no GHCR push** needed. GHCR/ECR is Phase 2 (ECS) only.
- **S3 buckets:** code uses **4** buckets (incl. thumbnails), not the doc's 3 + single `S3_BUCKET`.
- **Secrets:** code requires **3 Fernet keys** + `SECRET_KEY` as prod-mandatory; doc's list omitted them.
- **ClamAV:** single Dockerfile already includes ClamAV (worker needs it; API carries it too) — matches the "one image" decision.

---

## G6 — Performance (<3s on /explore + /explore/[id])

Measured locally 2026-06-14: prod build (`pnpm build`), `next start` on :3100, backend on :8000 against docker Postgres/Redis, 12 seeded published frameworks.

| Route | Warm SSR TTFB (6 samples) | HTML size | First-load JS |
|---|---|---|---|
| `/explore` | ~48–50 ms | 254 KB | 116 KB |
| `/explore/[id]` | ~32–34 ms | 104 KB | 105 KB |

Backend `/v1/explore/frameworks?limit=12` = 325 ms cold / faster warm. Both pages **far under the 3s gate** — ~50× headroom on server render.

**Caveat:** local, single-host, light data (12 rows), warm Next prod server. Authoritative G6 sign-off = re-measure on **staging** with prod-like data volume + real Vercel↔Render↔Neon network RTT (Neon serverless cold-start can add 100s of ms) + Lighthouse LCP. Local result establishes the app is not the bottleneck; network/data scale is the remaining risk to confirm post-provisioning.

**Status:** ✅ passes locally; confirm on staging.

## Next

G4+G5 close once the human completes the checklists and a `main` push deploys green. G6 confirmed locally; re-run on staging with prod-like data. That is the last Phase 6 gate.
