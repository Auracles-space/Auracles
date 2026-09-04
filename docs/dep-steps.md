# Deployment — Environment Collection Steps

Collect every value below, then paste into Render / Vercel / GitHub (see "Where each goes"). Work top to bottom. Companion to `superpowers/specs/2026-06-14-phase6-g4-g5-deploy-runbook.md`.

> Secrets shown once (AWS secret key, Stripe keys) — copy immediately. Store all generated secrets in a password manager too.

---

## 1. Neon → `DATABASE_URL`

- Use the default **`production`** branch (skip creating extra branches now — staging deferred).
- Copy its connection string. **Change the prefix to `postgresql+asyncpg://`**, keep `?sslmode=require`.

```
DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host>/<db>?sslmode=require
```

## 2. Upstash → `REDIS_URL`

- Use the **TCP** connection string, NOT the REST URL/token.
- Force TLS: scheme must be `rediss://` (double s).

```
REDIS_URL=rediss://default:<PASSWORD>@firm-bulldog-148696.upstash.io:6379
```

- App appends `/0` (Celery broker) and `/1` (cache) itself — give the base string only.
- Verify: `redis-cli --tls -u "rediss://default:<PASSWORD>@firm-bulldog-148696.upstash.io:6379" ping` → `PONG`.

## 3. AWS S3 → 7 values  (do the setup as **root**, app uses a dedicated user)

Sign in as **root** for setup (root is not used by the app afterwards).

### 3a. Create the 4 buckets
S3 console → **Create bucket** (×4). Same region each. Globally-unique names (add `-prod` suffix). Leave **Block all public access ON**. Defaults otherwise.

### 3b. Create the IAM policy
IAM console → **Policies** → **Create policy** → **JSON** tab → paste the JSON below (swap in your real bucket names) → Next → name it `auracles-s3-rw` → **Create policy**.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BucketList",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::auracles-artifacts-prod",
        "arn:aws:s3:::auracles-avatars-prod",
        "arn:aws:s3:::auracles-reports-prod",
        "arn:aws:s3:::auracles-thumbnails-prod"
      ]
    },
    {
      "Sid": "ObjectRW",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": [
        "arn:aws:s3:::auracles-artifacts-prod/*",
        "arn:aws:s3:::auracles-avatars-prod/*",
        "arn:aws:s3:::auracles-reports-prod/*",
        "arn:aws:s3:::auracles-thumbnails-prod/*"
      ]
    }
  ]
}
```

### 3c. Create the app user + attach the policy
IAM console → **Users** → **Create user**:
1. User name: `auracles-app`.
2. **Do NOT** check "Provide user access to the AWS Management Console" (programmatic only).
3. Next → Permissions → **Attach policies directly** → search `auracles-s3-rw` → tick it.
4. Next → **Create user**.

### 3d. Create the access key
Open the `auracles-app` user → **Security credentials** tab → **Create access key** → use case **"Application running outside AWS"** → Next → **Create access key**.
Copy both now (secret shown only once):

```
AWS_ACCESS_KEY_ID=<auracles-app key id>
AWS_SECRET_ACCESS_KEY=<shown once>
AWS_DEFAULT_REGION=us-east-1
S3_ARTIFACTS_BUCKET=auracles-artifacts-prod
S3_AVATARS_BUCKET=auracles-avatars-prod
S3_REPORTS_BUCKET=auracles-reports-prod
S3_THUMBNAILS_BUCKET=auracles-thumbnails-prod
```

- Verify: `aws s3 ls s3://auracles-artifacts-prod --region us-east-1` → empty, no error.
- Buckets are created by root; the `auracles-app` user never manages buckets, only objects.

## 4. Resend → 2 values

- Verify domain `auracles.space` (add SPF `include:_spf.resend.com`, DKIM CNAME, DMARC).
- Create API key.

```
RESEND_API_KEY=<key>
RESEND_FROM_ADDRESS=noreply@auracles.space
```

## 5. Stripe → 3 values

- Live secret key now.
- Webhook secret AFTER Render gives you the API URL — add endpoint `https://<render-api>/v1/webhooks/stripe`, then copy its signing secret.

```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...                 # after creating the webhook endpoint
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_live_...  # → Vercel, not Render
```

## 6. Brave → 1 value

```
BRAVE_SEARCH_API_KEY=<key>
```

## 7. Generate yourself (run locally) → 4 values

`cryptography` is in the backend venv (not system python). Run from `backend/`:

```bash
cd backend
echo "SECRET_KEY=$(openssl rand -hex 32)"
echo "TOTP_ENCRYPTION_KEY=$(.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
echo "PAYOUT_ACCOUNT_ENCRYPTION_KEY=$(.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
echo "PARTNER_WEBHOOK_ENCRYPTION_KEY=$(.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
```

(`uv run python -c "..."` works too. System `python3` lacks `cryptography`.)

| Var | Protects |
|---|---|
| `SECRET_KEY` | Signs JWT access tokens **and** the `session_hint` cookie. |
| `TOTP_ENCRYPTION_KEY` | Encrypts 2FA seeds at rest. |
| `PAYOUT_ACCOUNT_ENCRYPTION_KEY` | Encrypts payout account details at rest. |
| `PARTNER_WEBHOOK_ENCRYPTION_KEY` | Encrypts partner webhook signing secrets at rest. |

⚠️ Generate once, store safely, **never rotate after prod has data** — changing a Fernet key makes already-encrypted rows permanently undecryptable. Prod boot fails if any are left as placeholders.

## 8. Choose yourself → 3 values

```
ADMIN_EMAIL=dev@auracles.space
ADMIN_PASSWORD=<strong password>
CORS_ALLOWED_ORIGINS=https://<your-prod-vercel-domain>   # no '*'
```

---

## Where each goes

### Render — Environment Group `auracles-secrets`
All of §1–8 (every `sync: false` key in `render.yaml`), EXCEPT the frontend-only `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`.
`ENVIRONMENT`, `LOG_FORMAT`, `TRUST_PROXY_HEADERS`, `COOKIE_SAMESITE` are already set inline in `render.yaml` — don't add them.

### Vercel — Project Environment Variables (frontend)
```
NEXT_PUBLIC_API_URL=https://<render-api-url>
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_live_...
SESSION_HINT_SECRET=<same value as backend SECRET_KEY>
```
The frontend verifies the session-hint cookie the backend signed with `SECRET_KEY`, so `SESSION_HINT_SECRET` here **must equal** the backend's `SECRET_KEY`. (`SECRET_KEY` / `AUTH_SECRET` are accepted fallbacks for the same purpose — only one is needed.)

### GitHub — repo secrets (after first Render deploy)
Copy each Render service's Deploy Hook URL:
```
RENDER_DEPLOY_HOOK_API
RENDER_DEPLOY_HOOK_WORKER
RENDER_DEPLOY_HOOK_BEAT
```

---

## Render — step by step

The repo already has `render.yaml` at the root (Blueprint). Render reads it and creates all 3 services (api / worker / beat).

### R1. Connect the repo as a Blueprint
1. Render dashboard → **New +** → **Blueprint**.
2. Connect your GitHub → pick repo **`Auracles-space/Auracles`**, branch `main`.
3. Render detects `render.yaml` → shows the 3 services + the `auracles-secrets` env group. **Apply** / Create.
4. First build will likely **fail or wait** because secrets aren't set yet — that's fine, fill them next.

### R2. Fill the secret group
1. Render dashboard → **Env Groups** → **`auracles-secrets`**.
2. Add every value from §1–8 (the `sync: false` keys). Do NOT add `ENVIRONMENT` / `LOG_FORMAT` / `TRUST_PROXY_HEADERS` / `COOKIE_SAMESITE` — those are inline in `render.yaml` already.
3. Save. The group is shared by all 3 services automatically.

### R3. First deploy + get the API URL
1. Open the **`auracles-api`** service → **Manual Deploy** → Deploy latest commit.
2. Wait for live. Copy its URL, e.g. `https://auracles-api.onrender.com` → this is `NEXT_PUBLIC_API_URL` for Vercel and the base for the Stripe webhook.
3. Check `https://<api-url>/v1/health` → `200`. Check the `auracles-worker` and `auracles-beat` logs show "ready".

### R4. Copy the 3 deploy-hook URLs
For **each** service (api, worker, beat): open it → **Settings** → **Deploy Hook** → copy the URL. These become the GitHub repo secrets below.

> If you don't see a "Blueprint" option: it's under **New +**. If Render created the services but no env group, create the group manually (Env Groups → New) named exactly `auracles-secrets` and link it to all 3 services.

---

## Order gotcha

Stripe webhook secret (§5) needs the Render API URL → deploy Render first (R3), then create the Stripe webhook endpoint, then fill `STRIPE_WEBHOOK_SECRET` and redeploy.

## Then

Push to `main` → **Checks** workflow runs → on success **Deploy** fires the 3 hooks → Render builds, runs `alembic upgrade head` on API boot. Vercel auto-deploys the frontend on the same push.
