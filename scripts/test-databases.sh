#!/usr/bin/env bash
#
# Create the databases the backend suite runs against.
#
# The suite is I/O-bound on a single Postgres, so it runs under pytest-xdist.
# Every worker truncates whole tables, which means workers cannot share a
# database. `tests/conftest.py` derives its database name from the worker id
# xdist exports, so this script creates one database per worker ahead of the
# run.
#
# `auracles_test` is migrated once and then cloned with CREATE DATABASE ...
# TEMPLATE, so the 123 migrations are paid once rather than once per worker.
# Keep TEST_WORKERS in step with the -n passed to pytest: a worker whose
# database was never created fails on connect rather than silently sharing one.
#
# Environment:
#   TEST_WORKERS      Number of worker databases to create (default 4).
#   USE_DOCKER_PSQL   1 to reach Postgres through docker compose (the local
#                     default), 0 to use a psql on PATH (CI).
set -euo pipefail

WORKERS="${TEST_WORKERS:-4}"
TEMPLATE_DB="auracles_test"
DB_USER="${POSTGRES_USER:-auracles}"
DB_PASSWORD="${POSTGRES_PASSWORD:-secret}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
USE_DOCKER_PSQL="${USE_DOCKER_PSQL:-1}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Run one psql command against the `postgres` maintenance database. CREATE and
# DROP DATABASE cannot run from inside the database being altered.
psql_admin() {
  if [ "$USE_DOCKER_PSQL" = "1" ]; then
    docker compose exec -T postgres psql -U "$DB_USER" -d postgres "$@"
  else
    PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" \
      -U "$DB_USER" -d postgres "$@"
  fi
}

database_exists() {
  psql_admin -tAc "SELECT 1 FROM pg_database WHERE datname='$1'" | grep -q 1
}

# The template must exist and be at head before anything is cloned from it.
if ! database_exists "$TEMPLATE_DB"; then
  psql_admin -c "CREATE DATABASE \"$TEMPLATE_DB\" OWNER \"$DB_USER\";"
fi
(
  cd "$REPO_ROOT/backend"
  DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${TEMPLATE_DB}" \
    uv run alembic upgrade head
)

for index in $(seq 0 $((WORKERS - 1))); do
  worker_db="${TEMPLATE_DB}_gw${index}"
  # Always rebuild from the template. A worker database carries whatever the
  # last run left in it, and starting from a clone is both cheaper and more
  # predictable than reasoning about that. FORCE terminates connections a
  # crashed run left open, which would otherwise block the drop.
  if database_exists "$worker_db"; then
    psql_admin -c "DROP DATABASE \"$worker_db\" WITH (FORCE);"
  fi
  psql_admin -c \
    "CREATE DATABASE \"$worker_db\" TEMPLATE \"$TEMPLATE_DB\" OWNER \"$DB_USER\";"
done

echo "Ready: $TEMPLATE_DB + $WORKERS worker databases (${TEMPLATE_DB}_gw0..gw$((WORKERS - 1)))."
