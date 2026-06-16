.PHONY: dev dev-logs down logs migrate worker frontend

# One-command local backend bootstrap: containers up (detached) + migrations.
dev:
	./scripts/dev-up.sh

# Same as `dev`, then stream api/worker/beat logs in this terminal.
# Ctrl+C stops watching; containers keep running (use `make down` to stop them).
dev-logs:
	./scripts/dev-up.sh
	docker compose logs -f api worker beat

# Stop and remove the local stack (keeps named volumes).
down:
	docker compose down

# Tail the API + worker + beat logs.
logs:
	docker compose logs -f api worker beat

# Apply database migrations against the running stack.
migrate:
	docker compose exec -T api alembic upgrade head

# Run the Celery worker in the foreground (logs verification links, etc.).
worker:
	docker compose up worker

# Start the Next.js dev server (frontend is not dockerised).
frontend:
	cd frontend && pnpm install && pnpm dev
