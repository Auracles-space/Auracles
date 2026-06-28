# Auracles

A knowledge marketplace. Contributors package professional expertise into
licensed **Frameworks**; Operators purchase and implement them; Attestors verify
their quality. The platform manages provenance, trust, transactions, and value
exchange.

See `docs/auracles-prd.md` for the product overview and `CLAUDE.md` for the
engineering conventions.

## License

Source-available under the **PolyForm Noncommercial License 1.0.0** — see
[`LICENSE`](./LICENSE). You may view, fork, modify, self-host, and share the
code for **noncommercial purposes only**. **Commercial use of any kind is not
permitted.** All commercial rights are reserved by the copyright holder.

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

### Bootstrap (datastores + migrations)

```bash
make dev
```

This runs `scripts/dev-up.sh`, which:

1. Seeds `backend/.env` and `frontend/.env.local` from the committed examples on
   first run (you must fill in the secrets — see below).
2. Starts **only the datastores** in Docker: Postgres, Redis, LocalStack (S3 —
   dev buckets auto-created).
3. Runs database migrations on the host (`uv run alembic upgrade head`).

The API, Celery worker, and beat run **on the host via uv**, each in its own
terminal — they are not run in Docker locally because the repo's macOS `.venv`
is bind-mounted over the image's Linux venv inside the container. All three
hot-reload on code changes (uvicorn `--reload`; worker/beat via `watchmedo`):

```bash
make api        # FastAPI on http://localhost:8000 (autoreload)
make worker     # Celery worker (autoreload; logs dev email/reset links)
make beat       # Celery beat scheduler (autoreload)
```

Then start the frontend (also **not** dockerised):

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
verification **and** password-reset emails are logged (with a clickable link)
instead of sent through Resend, so you never burn the Resend daily quota. These
emails are sent from Celery tasks, so the link appears in the **worker**
terminal (`make worker`), not the API logs.

### Common commands

```bash
make dev        # bootstrap: datastores in Docker + run migrations
make datastores # start only Postgres/Redis/LocalStack
make api        # run FastAPI on the host (autoreload)
make worker     # run the Celery worker on the host (autoreload; shows email links)
make beat       # run Celery beat on the host (autoreload)
make migrate    # apply migrations on the host
make frontend   # run the Next.js dev server
make logs       # tail datastore logs (Postgres/Redis/LocalStack)
make down       # stop the datastores
```

Typical day-to-day: `make dev` once, then `make api`, `make worker`, and
`make frontend` in separate terminals. The datastores have no restart policy,
so run `make dev` again after a reboot, after `make down`, or after quitting
Docker Desktop (check with `docker compose ps`). If they're already `Up`, skip
straight to `make api` / `make worker` / `make frontend`.

ClamAV (virus scanning) is started on demand — `docker compose up -d clamav` —
because its first-boot signature download takes several minutes.

## Tests

The backend suite runs against an **isolated** `auracles_test` database and Redis
db 1 — never the dev datastores — because integration fixtures delete Users and
other rows. `make dev` creates and migrates `auracles_test` automatically; run
`make test-db` to repair it if it's missing.

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
