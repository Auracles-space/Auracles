.PHONY: dev datastores api worker beat migrate test-db down logs frontend

# One-command local bootstrap: datastores in Docker + migrations on the host.
# After this, run the backend processes locally: `make api`, `make worker`,
# `make beat` (each in its own terminal). They run on the host via uv, not in
# Docker — the macOS .venv shadows the image's Linux venv inside the container.
dev:
	./scripts/dev-up.sh

# Start only the datastores (Postgres, Redis, LocalStack) in Docker.
datastores:
	docker compose up -d postgres redis localstack

# Run the FastAPI app on the host with autoreload.
api:
	cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run the Celery worker on the host with autoreload (restarts on app/**.py
# changes). Local email links (verification, password reset) are logged here.
worker:
	cd backend && uv run watchmedo auto-restart --directory=app --pattern='*.py' --recursive --signal SIGTERM -- celery -A app.workers.celery_app worker --loglevel=info

# Run the Celery beat scheduler on the host with autoreload.
beat:
	cd backend && uv run watchmedo auto-restart --directory=app --pattern='*.py' --recursive --signal SIGTERM -- celery -A app.workers.celery_app beat --loglevel=info

# Apply database migrations on the host.
migrate:
	cd backend && uv run alembic upgrade head

# Create (if missing) and migrate the isolated test database. The suite points
# at auracles_test via tests/conftest.py so its destructive fixtures never touch
# the dev DB. `make dev` runs this automatically; use this to repair it.
test-db:
	docker compose exec -T postgres psql -U auracles -d postgres -tAc \
	  "SELECT 1 FROM pg_database WHERE datname='auracles_test'" | grep -q 1 \
	  || docker compose exec -T postgres psql -U auracles -d postgres \
	       -c "CREATE DATABASE auracles_test OWNER auracles;"
	cd backend && DATABASE_URL='postgresql+asyncpg://auracles:secret@localhost:5432/auracles_test' uv run alembic upgrade head

# Stop and remove the datastores (keeps named volumes).
down:
	docker compose down

# Tail the datastore logs (api/worker/beat run locally in their own terminals).
logs:
	docker compose logs -f postgres redis localstack

# Start the Next.js dev server (frontend is not dockerised).
frontend:
	cd frontend && pnpm install && pnpm dev
