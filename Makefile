.PHONY: dev down logs migrate worker frontend

# One-command local backend bootstrap: containers up + migrations.
dev:
	./scripts/dev-up.sh

# Stop and remove the local stack (keeps named volumes).
down:
	docker compose down

# Tail the API + worker logs.
logs:
	docker compose logs -f api worker

# Apply database migrations against the running stack.
migrate:
	docker compose exec -T api alembic upgrade head

# Run the Celery worker in the foreground (logs verification links, etc.).
worker:
	docker compose up worker

# Start the Next.js dev server (frontend is not dockerised).
frontend:
	cd frontend && pnpm install && pnpm dev
