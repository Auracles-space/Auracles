# Pre-Scale Infrastructure Design

**Date:** 2026-06-07  
**Status:** Approved  
**Phase:** 1 (pre-scale) — replaces AWS compute/DB until scale demands it

---

## 1. Context

The agreed target architecture (TDD Section 3) uses AWS ECS Fargate, RDS, ElastiCache, Lambda, and SES. That stack is correct at scale but over-provisioned and expensive for an early-stage product.

This document defines Phase 1 infrastructure: same Docker images, same code, different hosts. Migration to full AWS is an env-var swap + Terraform apply — no code changes required.

---

## 2. Two-Phase Architecture

```
Phase 1 (pre-scale)                    Phase 2 (AWS — when ready)
──────────────────────────────         ──────────────────────────────────
Next.js   →  Vercel                    Next.js   →  Vercel (stays)
FastAPI   →  Render Web Service        FastAPI   →  ECS Fargate
Celery W  →  Render Background Worker  Celery W  →  ECS Fargate
Beat      →  Render Background Worker  Beat      →  ECS Fargate (singleton)
Postgres  →  Neon (serverless PG)      Postgres  →  AWS RDS Postgres 16
Redis     →  Upstash (serverless)      Redis     →  AWS ElastiCache
Email     →  Resend                    Email     →  AWS SES (optional swap)
Files     →  AWS S3 (both phases)      Files     →  AWS S3 (stays)
Virus     →  Celery task + ClamAV      Virus     →  AWS Lambda (S3 trigger)
Payments  →  Stripe + Paystack         Payments  →  Stripe + Paystack (stays)
```

**Migration trigger:** when any single Render service sustains >70% CPU/RAM for >2 weeks, or monthly Render cost exceeds AWS equivalent.

---

## 3. Service Configuration

### 3.1 Render (`render.yaml`)

Three services, one Dockerfile (`backend/Dockerfile`), one environment group.

```yaml
services:
  - type: web
    name: auracles-api
    runtime: docker
    dockerfilePath: ./backend/Dockerfile
    startCommand: sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"
    plan: starter
    envVars:
      - fromGroup: auracles-secrets

  - type: worker
    name: auracles-worker
    runtime: docker
    dockerfilePath: ./backend/Dockerfile
    startCommand: celery -A app.workers.celery_app worker --loglevel=info --concurrency=4
    plan: starter
    envVars:
      - fromGroup: auracles-secrets

  - type: worker
    name: auracles-beat
    runtime: docker
    dockerfilePath: ./backend/Dockerfile
    startCommand: celery -A app.workers.celery_app beat --loglevel=info --scheduler=celery.beat.PersistentScheduler
    plan: starter
    envVars:
      - fromGroup: auracles-secrets
```

Notes:
- `alembic upgrade head` runs only on the API container — workers skip migrations
- Beat runs as a singleton background worker — Render guarantees single instance
- All three share the same `auracles-secrets` environment group

### 3.2 Neon (Postgres)

- Two Neon branches: `main` (production) and `develop` (staging)
- Connection string format: `postgresql://user:pass@host/auracles?sslmode=require`
- Injected as `DATABASE_URL` in both Render and local `.env`
- Alembic `alembic.ini` reads `DATABASE_URL` from environment — no hardcoded URL

### 3.3 Upstash (Redis)

- One Redis instance, two databases: `db=0` (broker/Celery), `db=1` (cache/rate limiting)
- Injected as `REDIS_URL`
- `CELERY_BROKER_URL = REDIS_URL + "/0"`
- `CELERY_RESULT_BACKEND = REDIS_URL + "/0"`
- App cache: `REDIS_URL + "/1"`

### 3.4 Resend (Email)

- Domain: `auracles.space` (existing Zoho domain — DNS additions only, no conflict)
- Sender: `noreply@auracles.space`
- Injected as `RESEND_API_KEY`
- DNS changes required:

| Record | Type | Action |
|--------|------|--------|
| MX | — | No change — Zoho stays |
| SPF (TXT) | `v=spf1` | Add `include:_spf.resend.com` alongside existing Zoho entry |
| DKIM | CNAME | Add Resend's CNAME (provided in Resend dashboard) |
| DMARC | TXT | Add if missing |

### 3.5 AWS S3 (Phase 1 + 2)

- Stays across both phases — no migration needed
- Buckets: `auracles-artifacts`, `auracles-avatars`, `auracles-reports`
- Access via presigned URLs (15-min expiry) — unchanged
- AWS credentials injected as `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`

### 3.6 Virus Scanning (Phase 1)

Phase 1 replaces the Lambda S3-trigger with a Celery task:

```
Artifact upload to S3 completes
        ↓
POST /v1/artifacts/{id}/process  (called by frontend after upload)
        ↓
FastAPI dispatches process_artifact.delay(artifact_id)
        ↓
Celery worker: scan with ClamAV → extract text → PII → fingerprint → rarity → thumbnail → index
```

ClamAV installed in the Celery worker Docker image. API image does not include ClamAV.

Phase 2: remove ClamAV from worker image, add Lambda with S3 trigger (per TDD Section 12).

---

## 4. Secrets Management

Three locations. Each owns its layer. No secrets in code or `render.yaml`.

| Layer | Tool | Keys |
|-------|------|------|
| Render | Environment Group `auracles-secrets` | `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `PAYSTACK_SECRET_KEY`, `PAYSTACK_WEBHOOK_SECRET`, `RESEND_API_KEY` |
| Vercel | Project Environment Variables | `NEXT_PUBLIC_API_URL` (others added during frontend implementation) |
| GitHub | Repository Secrets | `GHCR_TOKEN`, `RENDER_DEPLOY_HOOK_API`, `RENDER_DEPLOY_HOOK_WORKER`, `RENDER_DEPLOY_HOOK_BEAT` |

Local development: `.env` file only, gitignored. `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` derived from `REDIS_URL` in app config — not stored separately.

---

## 5. CI/CD Pipeline

### 5.1 Flow

```
Push to main or develop
        ↓
GitHub Actions: pytest (≥80% coverage) + vitest (≥70% coverage)
        ↓ tests pass
Build Docker image → push to GHCR (ghcr.io/auracles/backend:<sha>)
        ↓
Trigger Render deploy hooks (API + worker + beat)   |   Vercel auto-deploys frontend
        ↓
Render pulls new image → rolling restart
        ↓
alembic upgrade head runs on API container start
```

### 5.2 Branch → Environment Mapping

| Branch | Backend | Frontend | Database |
|--------|---------|----------|----------|
| `main` | Render prod (3 services) | Vercel prod | Neon `main` |
| `develop` | Render staging (3 services) | Vercel preview | Neon `develop` |
| Feature branches | — | Vercel preview | — |

### 5.3 GitHub Actions Workflow

```yaml
# .github/workflows/deploy.yml
name: Test, Build, Deploy

on:
  push:
    branches: [main, develop]

jobs:
  test-backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: test
      redis:
        image: redis:7
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install -r backend/requirements.txt
      - run: pytest backend/tests/ --cov=app --cov-fail-under=80

  test-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: cd frontend && npm ci && npm run test -- --coverage

  build:
    needs: [test-backend, test-frontend]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GHCR_TOKEN }}
      - run: |
          docker build backend/ -t ghcr.io/auracles/backend:${{ github.sha }}
          docker push ghcr.io/auracles/backend:${{ github.sha }}

  deploy:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - run: curl -X POST ${{ secrets.RENDER_DEPLOY_HOOK_API }}
      - run: curl -X POST ${{ secrets.RENDER_DEPLOY_HOOK_WORKER }}
      - run: curl -X POST ${{ secrets.RENDER_DEPLOY_HOOK_BEAT }}
```

### 5.4 Phase 2 Migration Diff

Only these lines change in the workflow:

```diff
- docker push ghcr.io/auracles/backend:${{ github.sha }}
+ docker push ${{ secrets.ECR_REGISTRY }}/auracles-backend:${{ github.sha }}

- curl -X POST ${{ secrets.RENDER_DEPLOY_HOOK_API }}
- curl -X POST ${{ secrets.RENDER_DEPLOY_HOOK_WORKER }}
- curl -X POST ${{ secrets.RENDER_DEPLOY_HOOK_BEAT }}
+ aws ecs update-service --cluster auracles --service auracles-api --force-new-deployment
+ aws ecs update-service --cluster auracles --service auracles-worker --force-new-deployment
+ aws ecs update-service --cluster auracles --service auracles-beat --force-new-deployment
```

Same Dockerfile. Same tests. Same image. Different deploy target.

---

## 6. Migration Path to AWS (Phase 2)

Ordered steps — no ambiguity:

### Step 1 — Provision AWS via Terraform
```bash
cd infra/envs/production
terraform apply
# Creates: VPC, RDS, ElastiCache, ECS cluster, ECR, ALB, S3 (already exists)
```

### Step 2 — Postgres: Neon → RDS
```bash
pg_dump $NEON_DATABASE_URL | pg_restore -d $RDS_DATABASE_URL
# On RDS: alembic upgrade head
# Verify: SELECT COUNT(*) on key tables — must match Neon
```

### Step 3 — Redis: Upstash → ElastiCache
No data migration. Redis is ephemeral (broker + cache only).
Update `REDIS_URL` in ECS task definitions → ElastiCache endpoint.

### Step 4 — Switch image registry: GHCR → ECR
Update GitHub Actions (diff in Section 5.4).
ECS task definitions reference ECR image ARN.

### Step 5 — Deploy to ECS
Update GitHub Actions deploy step (diff in Section 5.4).
Confirm ECS services healthy: `aws ecs describe-services`.

### Step 6 — DNS cutover
```
api.auracles.space CNAME → ALB DNS name
```
Render services remain live until DNS propagates, then decommission.

### Step 7 — Email: Resend → SES (optional)
Resend can stay indefinitely. Swap only if cost justifies it.
If switching: verify `auracles.space` in SES, update `RESEND_API_KEY` → SES SMTP config.

### Step 8 — Add Lambda (virus scan isolation)
Deploy `backend/lambda/virus_scan.py` to Lambda.
Wire S3 event trigger on `auracles-artifacts` bucket.
Remove ClamAV from Celery worker Dockerfile.

---

## 7. Cost Estimates

### Phase 1 Monthly
| Service | Plan | Cost |
|---------|------|------|
| Render (3 services) | Starter × 3 | $21/mo |
| Neon | Free → Pro | $0–$19/mo |
| Upstash | Free → Pay-per-use | $0–$10/mo |
| Resend | Free (3k emails/mo) | $0 |
| AWS S3 | Usage-based (~$0.023/GB) | ~$1–3/mo |
| Vercel | Hobby/Pro | $0–$20/mo |
| **Total** | | **~$22–75/mo** |

### Phase 2 (indicative AWS)
ECS Fargate + RDS + ElastiCache + ALB: ~$150–300/mo depending on instance sizes.

---

## 8. What This Changes in Existing Docs

The TDD (`2026-06-06-auracles-tdd.md`) describes the Phase 2 AWS target and remains unchanged as the authoritative technical spec. This document is the Phase 1 overlay — it does not replace the TDD.

CLAUDE.md tech stack table will be updated to reflect the two-phase approach.
