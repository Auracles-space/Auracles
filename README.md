# Auracles

A knowledge marketplace. Contributors package professional expertise into
licensed **Frameworks**; Operators purchase and implement them; Attestors verify
their quality. The platform manages provenance, trust, transactions, and value
exchange.

See `docs/auracles-prd.md` for the product overview and `CLAUDE.md` for the
engineering conventions.

## Stack

| Layer    | Tech                                            |
| -------- | ----------------------------------------------- |
| Frontend | Next.js 15 (App Router) + Tailwind              |
| Backend  | FastAPI (Python 3.13), SQLAlchemy async, Alembic |
| Async    | Celery + Redis                                  |
| Data     | PostgreSQL 16, Redis, S3 (LocalStack in dev)    |
| Payments | Stripe + Paystack                               |
| Email    | Resend                                          |

## Local setup

**Prerequisites:** Docker + Docker Compose, Node 20+ with `pnpm`,
[`uv`](https://docs.astral.sh/uv/) (only for running backend tooling outside Docker).

### One command (backend stack)

```bash
make dev
```

This runs `scripts/dev-up.sh`, which:

1. Seeds `backend/.env` and `frontend/.env.local` from the committed examples on
   first run (you must fill in the secrets — see below).
2. Starts Postgres, Redis, LocalStack (S3 — dev buckets auto-created), and the
   API / worker / beat containers.
3. Runs database migrations (`alembic upgrade head`).

Then start the frontend (it is **not** dockerised):

```bash
make frontend          # or: cd frontend && pnpm install && pnpm dev
```

| Service  | URL / port                                   |
| -------- | -------------------------------------------- |
| API      | http://localhost:8000 (OpenAPI docs `/docs`) |
| Frontend | http://localhost:3000                        |
| Postgres | localhost:5432                               |
| Redis    | localhost:6379                               |
| S3       | localhost:4566 (LocalStack)                  |

### Secrets (required)

`.env` files are gitignored — each developer fills their own from the examples
(`backend/.env.example`, `backend/.env.prod.example`, `frontend/.env.local.example`).

> **Critical:** the backend `SECRET_KEY` and the frontend `SESSION_HINT_SECRET`
> **must be identical** — the backend signs the `session_hint` cookie and the
> frontend verifies it. If they differ, every authenticated route bounces to
> `/login`. The same pairing must hold in production (Render `SECRET_KEY` =
> Vercel `SESSION_HINT_SECRET`).

For local email testing, set `EMAIL_SEND_ENABLED=false` (default in the example):
verification/reset emails are logged (with a clickable link) instead of sent
through Resend, so you never burn the Resend daily quota.

### Common commands

```bash
make dev        # bring up backend stack + migrate
make frontend   # run the Next.js dev server
make worker     # run the Celery worker in the foreground (shows email links)
make migrate    # apply migrations against the running stack
make logs       # tail API + worker logs
make down       # stop the stack
```

ClamAV (virus scanning) is started on demand — `docker compose up -d clamav` —
because its first-boot signature download takes several minutes.

## Tests

```bash
# Backend
cd backend && uv run pytest

# Frontend
cd frontend && pnpm vitest run        # unit/component
cd frontend && pnpm test:e2e          # Playwright (see package.json)
```

## Repository layout

```
auracles/
├── frontend/          # Next.js app
├── backend/           # FastAPI + Celery
│   └── app/modules/   # auth | explore | frameworks | projects | attestation | financials | settings
├── infra/             # Terraform (Phase 2 AWS)
├── contracts/         # openapi.yaml (frontend client is generated from this)
├── scripts/           # dev-up.sh, localstack init, ...
└── docs/              # PRD, FRD, TDD, infra design
```
