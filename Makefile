.PHONY: dev datastores api worker beat migrate test-db down logs frontend \
        staging-plan staging-up staging-down staging-status staging-logs \
        staging-bootstrap-admin staging-frontend-build staging-frontend-logs \
        staging-run staging-seed

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

# Rebuild and redeploy the staging frontend. Needed after ANY change to its
# environment variables: Next.js bakes them into the bundle at build time, so
# `terraform apply` alone changes what the next build will use and nothing
# about what is currently served. Also the way to deploy frontend code without
# waiting for a push.
staging-frontend-build:
	@app=$$(aws amplify list-apps --region $(AWS_REGION) \
	  --query "apps[?name=='auracles-staging'].appId | [0]" --output text); \
	if [ -z "$$app" ] || [ "$$app" = "None" ]; then \
	  echo "no auracles-staging Amplify app found — apply infra/shared first"; exit 1; \
	fi; \
	job=$$(aws amplify start-job --region $(AWS_REGION) --app-id "$$app" \
	  --branch-name main --job-type RELEASE --query 'jobSummary.jobId' --output text); \
	echo "build $$job started on app $$app; watching..."; \
	while :; do \
	  st=$$(aws amplify get-job --region $(AWS_REGION) --app-id "$$app" \
	    --branch-name main --job-id "$$job" --query 'job.summary.status' --output text); \
	  case "$$st" in \
	    SUCCEED) echo "build SUCCEEDED → https://main.$$app.amplifyapp.com"; break;; \
	    FAILED|CANCELLED) echo "build $$st — logs: make staging-frontend-logs"; exit 1;; \
	  esac; \
	  sleep 20; \
	done

# Print the URL of the most recent staging frontend build log.
staging-frontend-logs:
	@app=$$(aws amplify list-apps --region $(AWS_REGION) \
	  --query "apps[?name=='auracles-staging'].appId | [0]" --output text); \
	job=$$(aws amplify list-jobs --region $(AWS_REGION) --app-id "$$app" \
	  --branch-name main --max-items 1 --query 'jobSummaries[0].jobId' --output text); \
	aws amplify get-job --region $(AWS_REGION) --app-id "$$app" --branch-name main \
	  --job-id "$$job" --query 'job.steps[].logUrl' --output text

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

# Run one Python statement inside a throwaway staging task, for QA work the UI
# cannot reach — chiefly firing a Celery Beat task on demand (§24 of
# docs/auracles-ui-full-test-scenarios.md) instead of waiting for its schedule:
#
#   make staging-run CMD="from app.workers.tasks.projects_beat import \
#     auto_approve_deliverables; auto_approve_deliverables.apply()"
#
# `.apply()` executes the task in-process, so this needs no worker and the api
# task definition (same image, same env) serves. CMD travels via the environment
# rather than the shell so quotes and semicolons inside it survive intact.
staging-run:
	@set -e; \
	test -n "$(CMD)" || { echo 'usage: make staging-run CMD="<python statements>"'; exit 1; }; \
	net=$$(aws ecs describe-services --region $(AWS_REGION) --cluster auracles-staging \
	  --services api --query 'services[0].networkConfiguration.awsvpcConfiguration' --output json); \
	if [ "$$net" = "null" ] || [ -z "$$net" ]; then \
	  echo "staging is not running — bring it up first with: make staging-up"; exit 1; \
	fi; \
	subnets=$$(echo "$$net" | python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)["subnets"]))'); \
	sgs=$$(echo "$$net" | python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)["securityGroups"]))'); \
	overrides=$$(CMD="$(CMD)" python3 -c 'import json,os; print(json.dumps({"containerOverrides":[{"name":"api","command":["python","-c",os.environ["CMD"]]}]}))'); \
	arn=$$(aws ecs run-task --region $(AWS_REGION) --cluster auracles-staging \
	  --task-definition auracles-staging-api --launch-type FARGATE \
	  --network-configuration "awsvpcConfiguration={subnets=[$$subnets],securityGroups=[$$sgs],assignPublicIp=ENABLED}" \
	  --overrides "$$overrides" --query 'tasks[0].taskArn' --output text); \
	echo "task: $$arn"; \
	aws ecs wait tasks-stopped --region $(AWS_REGION) --cluster auracles-staging --tasks "$$arn"; \
	code=$$(aws ecs describe-tasks --region $(AWS_REGION) --cluster auracles-staging --tasks "$$arn" \
	  --query 'tasks[0].containers[0].exitCode' --output text); \
	echo "exit code: $$code"; \
	aws logs tail /ecs/auracles-staging/api --region $(AWS_REGION) --since 5m 2>/dev/null | tail -30; \
	[ "$$code" = "0" ]

# Create a pre-verified staging test account, so a QA pass does not need a live
# inbox per account. Registration and email verification themselves are covered
# by AU-1/AU-4 with a real address; every other account in the bank can start
# here:
#
#   make staging-seed EMAIL=auracles.qa+operator@gmail.com \
#     PASSWORD=Operator-Pass-2026 ROLES=operator
#
# ROLES is a comma-separated subset of contributor,operator,attestor,admin.
# The password is visible in CloudTrail as a task-override parameter — fine for
# throwaway staging accounts, never for real credentials, which is why the admin
# password comes from Secrets Manager via staging-bootstrap-admin instead.
staging-seed:
	@set -e; \
	test -n "$(EMAIL)" -a -n "$(PASSWORD)" -a -n "$(ROLES)" || { \
	  echo 'usage: make staging-seed EMAIL=... PASSWORD=... ROLES=contributor,operator'; exit 1; }; \
	net=$$(aws ecs describe-services --region $(AWS_REGION) --cluster auracles-staging \
	  --services api --query 'services[0].networkConfiguration.awsvpcConfiguration' --output json); \
	if [ "$$net" = "null" ] || [ -z "$$net" ]; then \
	  echo "staging is not running — bring it up first with: make staging-up"; exit 1; \
	fi; \
	subnets=$$(echo "$$net" | python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)["subnets"]))'); \
	sgs=$$(echo "$$net" | python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)["securityGroups"]))'); \
	overrides=$$(SEED_EMAIL="$(EMAIL)" SEED_PASSWORD="$(PASSWORD)" SEED_ROLES="$(ROLES)" \
	  python3 -c 'import json,os; print(json.dumps({"containerOverrides":[{"name":"api","command":["python","-m","scripts.seed_user"],"environment":[{"name":k,"value":os.environ[k]} for k in ("SEED_EMAIL","SEED_PASSWORD","SEED_ROLES")]}]}))'); \
	arn=$$(aws ecs run-task --region $(AWS_REGION) --cluster auracles-staging \
	  --task-definition auracles-staging-api --launch-type FARGATE \
	  --network-configuration "awsvpcConfiguration={subnets=[$$subnets],securityGroups=[$$sgs],assignPublicIp=ENABLED}" \
	  --overrides "$$overrides" --query 'tasks[0].taskArn' --output text); \
	echo "seed task: $$arn"; \
	aws ecs wait tasks-stopped --region $(AWS_REGION) --cluster auracles-staging --tasks "$$arn"; \
	code=$$(aws ecs describe-tasks --region $(AWS_REGION) --cluster auracles-staging --tasks "$$arn" \
	  --query 'tasks[0].containers[0].exitCode' --output text); \
	echo "exit code: $$code"; \
	[ "$$code" = "0" ]
