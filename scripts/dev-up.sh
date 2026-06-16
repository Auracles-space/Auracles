#!/usr/bin/env bash
#
# One-command local bootstrap for the Auracles backend stack.
#
# Brings up Postgres, Redis, LocalStack (S3, dev buckets auto-created), ClamAV,
# and the API/worker/beat containers, then runs database migrations. The
# frontend runs separately with `pnpm dev` (it is not dockerised).
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

echo "Starting Docker services..."
# ClamAV is excluded from the wait — its first-boot signature download takes
# minutes and is not needed for most local work. Start it with: docker compose up -d clamav
docker compose up -d postgres redis localstack api worker beat

echo "Waiting for Postgres..."
until docker compose exec -T postgres pg_isready -U auracles -d auracles >/dev/null 2>&1; do
  sleep 1
done

echo "Running database migrations..."
docker compose exec -T api alembic upgrade head

cat <<'EOF'

Backend stack ready:
  API        http://localhost:8000        (OpenAPI docs: /docs)
  Postgres   localhost:5432
  Redis      localhost:6379
  S3         localhost:4566               (LocalStack — dev buckets auto-created)

Frontend (separate process):
  cd frontend && pnpm install && pnpm dev  ->  http://localhost:3000

Logs:  make logs      Stop:  make down
EOF
