.PHONY: dev datastores api worker beat migrate test-db down logs frontend \
        staging-plan staging-up staging-down staging-status staging-logs \
        staging-bootstrap-admin

# Staging lives in eu-west-2 and is deliberately ephemeral: bring it up for a
# QA pass, tear it down after. See infra/README.md.
STAGING_DIR := infra/envs/staging
AWS_REGION  := eu-west-2
ECR_REPO    := auracles-backend

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

# ---------------------------------------------------------------------------
# Staging (AWS, eu-west-2). Roughly $2-3/day while up, $0 while down — so the
# habit these targets exist to support is: up, test, DOWN. `staging-status`
# answers "am I paying for it right now?".
#
# Nothing here can deploy to production: that needs a v* git tag, which goes
# through .github/workflows/release.yml.
# ---------------------------------------------------------------------------

# Review what a staging-up would build, without building it. Writes tfplan.
staging-plan:
	cd $(STAGING_DIR) && terraform init -backend-config=backend.hcl && \
	  terraform plan -var-file=staging.tfvars -out=tfplan

# Bring staging up (~10 min; RDS is the slow piece). Terraform shows the plan
# and waits for you to type `yes` — that prompt is the human gate on every
# apply, so this target never runs unattended.
#
# The image check is not paranoia: all three services pull the :staging tag,
# and if it is absent they crash-loop invisibly for ten minutes before anyone
# looks. CI pushes that tag on every merge to main touching backend/.
staging-up:
	@aws ecr describe-images --region $(AWS_REGION) --repository-name $(ECR_REPO) \
	  --image-ids imageTag=staging >/dev/null 2>&1 \
	  || { echo "ERROR: no :staging image in ECR. Merge to main (CI builds it), or run the Backend build workflow manually."; exit 1; }
	cd $(STAGING_DIR) && terraform init -backend-config=backend.hcl && \
	  terraform apply -var-file=staging.tfvars
	@echo
	@echo "Staging is up. Health: https://api.staging.auracles.space/v1/health"
	@echo "Remember: make staging-down when the QA pass is over."

# Tear staging down to $0. The hand-entered secrets survive: they live in
# the shared stack precisely so this cannot touch them. Only DATABASE_URL and
# REDIS_URL die, and the next staging-up regenerates them.
staging-down:
	cd $(STAGING_DIR) && terraform destroy -var-file=staging.tfvars

# "Is staging running, and what is it costing me?" Safe to run any time.
staging-status:
	@state=$$(aws ecs describe-clusters --region $(AWS_REGION) --clusters auracles-staging \
	    --query 'clusters[0].status' --output text 2>/dev/null); \
	if [ "$$state" = "ACTIVE" ]; then \
	  echo "STAGING IS UP (~\$$2-3/day) — services:"; \
	  aws ecs describe-services --region $(AWS_REGION) --cluster auracles-staging \
	    --services api worker beat \
	    --query 'services[].{name:serviceName,running:runningCount,desired:desiredCount}' \
	    --output table; \
	  echo "Health: https://api.staging.auracles.space/v1/health"; \
	else \
	  echo "staging is down (\$$0). Bring it up with: make staging-up"; \
	fi

# Tail the api service's logs. SERVICE=worker or SERVICE=beat for the others.
SERVICE ?= api
staging-logs:
	aws logs tail /ecs/auracles-staging/$(SERVICE) --region $(AWS_REGION) --follow

# Create the initial admin account on a fresh staging database. Idempotent —
# a second run just re-asserts the admin role, so it is safe after every
# staging-up. Reads ADMIN_EMAIL from the task definition and ADMIN_PASSWORD
# from Secrets Manager; neither value passes through this command line, which
# is why it runs as a task override rather than `docker run -e`.
#
# The network configuration is copied from the running api service instead of
# being hardcoded, so it cannot drift from what Terraform actually built.
staging-bootstrap-admin:
	@set -e; \
	net=$$(aws ecs describe-services --region $(AWS_REGION) --cluster auracles-staging \
	  --services api --query 'services[0].networkConfiguration.awsvpcConfiguration' --output json); \
	if [ "$$net" = "null" ] || [ -z "$$net" ]; then \
	  echo "staging is not running — bring it up first with: make staging-up"; exit 1; \
	fi; \
	subnets=$$(echo "$$net" | python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)["subnets"]))'); \
	sgs=$$(echo "$$net" | python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)["securityGroups"]))'); \
	arn=$$(aws ecs run-task --region $(AWS_REGION) --cluster auracles-staging \
	  --task-definition auracles-staging-api --launch-type FARGATE \
	  --network-configuration "awsvpcConfiguration={subnets=[$$subnets],securityGroups=[$$sgs],assignPublicIp=ENABLED}" \
	  --overrides '{"containerOverrides":[{"name":"api","command":["python","-m","scripts.bootstrap_admin"]}]}' \
	  --query 'tasks[0].taskArn' --output text); \
	echo "bootstrap task: $$arn"; \
	aws ecs wait tasks-stopped --region $(AWS_REGION) --cluster auracles-staging --tasks "$$arn"; \
	code=$$(aws ecs describe-tasks --region $(AWS_REGION) --cluster auracles-staging --tasks "$$arn" \
	  --query 'tasks[0].containers[0].exitCode' --output text); \
	echo "exit code: $$code"; \
	aws logs tail /ecs/auracles-staging/api --region $(AWS_REGION) --since 5m \
	  --filter-pattern 'admin_user' 2>/dev/null | tail -5; \
	[ "$$code" = "0" ]
