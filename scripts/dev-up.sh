#!/usr/bin/env bash
#
# One-command local bootstrap for the Auracles backend stack.
#
# Brings up the datastores in Docker (Postgres, Redis, LocalStack — S3 dev
# buckets auto-created) and runs database migrations on the host. The API,
# Celery worker, and beat run on the host via uv (see `make api|worker|beat`),
# NOT in Docker: the repo's macOS `.venv` is bind-mounted over the image's
# Linux venv, so those containers can't exec their interpreter locally. The
# frontend also runs separately with `pnpm dev`.
set -euo pipefail

cd "$(dirname "$0")/.."

# Seed env files from the committed examples on first run. Secrets are not
# committed — fill them in before the stack will fully work. SECRET_KEY (backend)
# MUST equal SESSION_HINT_SECRET (frontend) or auth bounces to /login.
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "Created backend/.env from example — fill in secrets before using auth."
fi
if [ ! -f frontend/.env.local ]; then
  cp frontend/.env.local.example frontend/.env.local
  echo "Created frontend/.env.local from example."
fi

echo "Starting datastores (Postgres, Redis, LocalStack)..."
# ClamAV is excluded — its first-boot signature download takes minutes and is
# not needed for most local work. Start it with: docker compose up -d clamav
docker compose up -d postgres redis localstack

echo "Waiting for Postgres..."
until docker compose exec -T postgres pg_isready -U auracles -d auracles >/dev/null 2>&1; do
  sleep 1
done

echo "Running database migrations (host, via uv)..."
(cd backend && uv run alembic upgrade head)

# Dedicated test database — isolated from the dev DB so the suite's destructive
# fixtures (delete Users/audit/etc.) never wipe seeded dev data. Created if
# missing, then migrated. The suite points at it via tests/conftest.py.
echo "Ensuring test database (auracles_test)..."
docker compose exec -T postgres psql -U auracles -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='auracles_test'" | grep -q 1 \
  || docker compose exec -T postgres psql -U auracles -d postgres \
       -c "CREATE DATABASE auracles_test OWNER auracles;"
(cd backend && DATABASE_URL='postgresql+asyncpg://auracles:secret@localhost:5432/auracles_test' uv run alembic upgrade head)

cat <<'EOF'

Datastores ready:
  Postgres   localhost:5432
  Redis      localhost:6379
  S3         localhost:4566               (LocalStack — dev buckets auto-created)

Now run the backend processes on the host (each in its own terminal):
  make api       FastAPI on http://localhost:8000  (autoreload)
  make worker    Celery worker                      (autoreload, shows email links)
  make beat      Celery beat scheduler              (autoreload)

Frontend (separate process):
  make frontend  ->  http://localhost:3000

Stop datastores:  make down
EOF
