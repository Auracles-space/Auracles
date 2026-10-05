# Production Stack Implementation Plan

> **For agentic workers:** steps use checkbox (`- [ ]`) syntax for tracking. Every
> `terraform apply` in this plan is run by the human, never the agent.

**Goal:** stand up `infra/envs/production` and its persistent shared entries, so
the `git tag v*` release path that already exists in `.github/workflows/release.yml`
has a production to deploy to.

**Architecture:** production reuses every module staging uses, unchanged except
for flag values. The split is the one already encoded in the modules' own
variable docs — ephemeral staging is permissive, production is protected. Nothing
new is designed here; what is new is a second environment stack, a second
delegated DNS branch, a second set of secret shells, and a second Amplify app.

**Region:** `eu-west-2` (London), same as staging and shared. Non-negotiable — the
ACM certificate must sit in the ALB's own region.

---

## Decisions (made 2026-10-04, do not re-open)

| Decision | Choice | Why |
| --- | --- | --- |
| RDS availability | Single-AZ, `db.t4g.micro` | A standby only earns its cost if the api is also multi-task across AZs. It is not, so an AZ loss would leave a surviving database with nothing to talk to. |
| api `desired_count` | 1 | Keeps `alembic upgrade head` in the container command, which is the model staging has run all along. Two tasks race the same migration. Revisit with real traffic. |
| worker capacity | Fargate Spot | A reclaimed worker re-queues an idempotent Celery job. Cost: ~3 min of clamd/freshclam warmup before it can scan again. |
| beat capacity | Fargate on-demand | Beat is the only clock and there is no queue behind it. A reclaim silently skips a payout sweep or an escrow auto-release. ~$6/mo to remove that failure mode. |
| Backup retention | 14 days | A data bug is often noticed days after it lands; 7 days can already be gone. Storage past the DB size is cents at 20 GB. |
| DNS | Delegate `api.auracles.space` to Route 53 | Same pattern staging already uses, so `infra/` has one pattern rather than two. The apex, `www` and the Google Workspace mail records stay at Namecheap and never move. |
| `deletion_protection` | `true` | Module doc: "True in production." |
| `skip_final_snapshot` | `false` | Module doc: "the final snapshot is the last line against a mistaken destroy." |
| S3 `force_destroy` | `false` | Module doc: "a destroy that would lose user artifacts must fail instead." |
| `apply_immediately` (RDS) | `false` | Already keyed off `environment == "production"` in `modules/rds/main.tf`. |
| ALB deletion protection | `true` | Already keyed off `environment == "production"` in `modules/alb/main.tf`. |

### Settled 2026-10-05 — how the frontend ships

**Both apps build `main`; production's auto-build is off and `release.yml`
starts its build.** Neither of the options originally offered here — a separate
`production` branch, or accepting continuous deploys — was taken. The human
pointed out that inverting the branch names changes nothing, which is correct:
Amplify builds on push to its branch, merges are frequent and tags are rare, so
the mismatch is auto-build, not the branch name. Turning auto-build off removes
it without a new branch, without changing how anyone merges, and without the
`contents: write` permission the branch plan would have needed. `release.yml`
starts the build after the ECS roll succeeds, pinned with `--commit-id` to the
tagged commit so a merge landing mid-release cannot ship a frontend ahead of
its backend.

---

## Global Constraints

- Work on a branch; merge only on the human's explicit word.
- The human runs every `terraform apply`. The agent may run `init`, `validate`,
  `fmt`, `plan`, and read-only AWS calls.
- Never display a production secret value. Secret shells are created by
  Terraform; values are entered by the human with `aws secretsmanager put-secret-value`.
- `terraform fmt` and `terraform validate` pass before any commit (CI runs both
  via `infra-checks.yml`).
- Production secret values must be **newly generated**, not copied from staging.
  If a staging key leaks, production data must stay safe.
- There is deliberately **no `make prod-down`**. Production is not ephemeral.
- Commit messages end with the session's attribution trailer.

---

## File Structure

**Module changes (small, both needed by production)**

- `infra/modules/ecs/variables.tf` — replace `use_spot` with `worker_use_spot`
  and `beat_use_spot` (both defaulting `true`, so staging is unaffected).
- `infra/modules/ecs/main.tf` — `local.spot_strategy` becomes two locals, one per
  service.
- `infra/modules/ecs/services.tf` — worker and beat read their own local.

**Shared stack additions** (persistent; survives any environment destroy)

- `infra/shared/main.tf` — `aws_route53_zone.api`, `aws_acm_certificate.api`,
  its validation records, and a `production_dns_delegation_complete` gate,
  mirroring the staging block exactly.
- `infra/shared/secrets.tf` — a second `for_each` over the same 16 names at
  `auracles/production/*`.
- `infra/shared/amplify.tf` — `module "production_frontend"`.
- `infra/shared/variables.tf` — `api_subdomain` (default `api`),
  `production_dns_delegation_complete`, `production_frontend_custom_domain`.
- `infra/shared/outputs.tf` — `production_api_zone_id`,
  `production_api_certificate_arn`, `production_secret_arns`,
  `namecheap_api_ns_records`, `production_frontend_url`.

**New environment stack** — `infra/envs/production/`

- `versions.tf` — same pins as staging, `Lifecycle = "permanent"` default tag.
- `backend.tf` / `backend.hcl` / `backend.hcl.example` — state key
  `envs/production/terraform.tfstate`. Separate file from staging (CLAUDE.md rule).
- `variables.tf` — `aws_region`, `vpc_cidr` (default `10.1.0.0/16`), `state_bucket`.
- `production.tfvars` — `state_bucket` only, as staging does.
- `main.tf` — the seven modules with production flags, composed `DATABASE_URL`
  and `REDIS_URL` secrets, and the `api.auracles.space` A-alias record.
- `outputs.tf` — same shape as staging's.

**Makefile**

- `prod-plan`, `prod-up`, `prod-status`, `prod-logs`, `prod-run`,
  `prod-bootstrap-admin`, `prod-promote-image`. No `prod-down`.

---

## Task 1 — Split the Spot flag per service — DONE (`b3f4c7cf`)

**This one had to happen before `make staging-down`.** Its verification is a
`terraform plan` that reports no changes; against a destroyed staging the
state is empty, the plan says "create 60 resources", and it proves nothing.

- [x] `infra/modules/ecs/variables.tf`: `use_spot` replaced by
      `worker_use_spot` and `beat_use_spot` (both default `true`), each
      documenting what a reclamation costs that service.
- [x] `infra/modules/ecs/main.tf`: `local.spot_strategy` replaced by
      `local.worker_strategy` and `local.beat_strategy`. The api stays absent
      from both, its on-demand strategy written inline in `services.tf` so no
      variable can move the user-facing service onto Spot.
- [x] `infra/modules/ecs/services.tf`: each service's dynamic block reads its
      own local.
- [x] Stale `use_spot` reference in `modules/ecs/tasks.tf` updated.
- [x] `terraform fmt -recursive -check` and `terraform validate` clean.
- [x] `terraform plan` against live staging: **"No changes. Your
      infrastructure matches the configuration."**

## Task 2 — Delegate `api.auracles.space` — DONE 2026-10-05 (`c4270cd5`, `39701208`)

- [x] Add the zone, certificate, validation records and
      `production_dns_delegation_complete` gate to `infra/shared/main.tf`,
      copying the staging block's structure and its comments' reasoning.
- [x] Certificate covers `api.auracles.space` and `*.api.auracles.space`.
- [x] Add the `namecheap_api_ns_records` output.
- [x] **Human:** `terraform apply` in `infra/shared` (pass one — gate still false).
- [x] **Human:** add the four NS records at Namecheap, on host `api` of
      `auracles.space`. Change nothing else there — the apex ALIAS, the `www`
      CNAME, `MX → smtp.google.com` and the SPF TXT all stay.
- [x] Confirm with `dig NS api.auracles.space` returning the Route 53 set.
- [x] Set `production_dns_delegation_complete = true` in `shared.auto.tfvars`.
- [x] **Human:** `terraform apply` in `infra/shared` (pass two — certificate
      validates, typically minutes).

## Task 3 — Production secret shells — DONE 2026-10-05 (`a6e09488`)

- [x] `infra/shared/secrets.tf`: the name list is now one shared
      `local.secret_names` feeding both environments, so a new secret cannot
      land in one and be forgotten in the other. Production shells at
      `auracles/production/${each.key}`, `recovery_window_in_days = 7`.
- [x] Output `production_secret_arns`.
- [x] Plan: 14 to add, 0 to change, 0 to destroy.
- [x] **Human:** `terraform apply` in `infra/shared`.
- [x] **Human:** fill all 14 values with `aws secretsmanager put-secret-value`.
      Freshly generated, never copied from staging:
      - `SECRET_KEY`, `TOTP_ENCRYPTION_KEY`, `PAYOUT_ACCOUNT_ENCRYPTION_KEY`,
        `PARTNER_WEBHOOK_ENCRYPTION_KEY`, `CONNECTOR_TOKEN_ENCRYPTION_KEY`
      - `RESEND_API_KEY`
      - `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` — **live** keys
      - `PAYSTACK_SECRET_KEY` — **live** key
      - `PERSONA_API_KEY`, `PERSONA_WEBHOOK_SECRET` — placeholders are fine;
        `KYC_PROVIDER` defaults to `manual` and Persona is shelved
      - `GOOGLE_CLIENT_SECRET` — from the new production OAuth client (Task 6)
      - `BRAVE_SEARCH_API_KEY`
      - `ADMIN_PASSWORD` — strong and unique; consumed by `scripts.bootstrap_admin`
- [x] Verify none is empty. There are 14 hand-entered shells; `DATABASE_URL`
      and `REDIS_URL` make 16 per environment but Terraform composes those in
      the environment stack from the live RDS and Redis.
- [x] `app/core/config.py` has validators that refuse to
      boot production on a placeholder for the five keys and the provider
      secrets — a missing value is a `ResourceInitializationError` naming the
      secret, which is loud, not subtle.

## Task 4 — Production Amplify app — DONE 2026-10-05 (`ef3b3e22`)

> Blocked on the open decision above (which branch it builds).

- [x] `module "production_frontend"` in `infra/shared/amplify.tf`:
      `app_name = "auracles-production"`, `stage = "PRODUCTION"`, the
      repository's own `amplify.yml`, `AMPLIFY_MONOREPO_APP_ROOT = frontend`,
      `AMPLIFY_DIFF_DEPLOY = false`.
- [x] Branch env: `BACKEND_ORIGIN = https://api.auracles.space`,
      `NEXT_PUBLIC_API_URL = /api`, `NEXT_PUBLIC_WS_URL = wss://api.auracles.space`,
      `NEXT_PUBLIC_WAITLIST_MODE = false`, `NEXT_PUBLIC_PLATFORM_CURRENCY = NGN`,
      live `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`, and `SESSION_HINT_SECRET` read
      from the **production** `SECRET_KEY` secret.
- [x] `custom_domain = null` for the first apply. The apex is not in Route 53, so
      attaching it needs records at Namecheap — that is the launch switch
      (Task 9), not part of standing the app up.
- [x] **Human:** `terraform apply` in `infra/shared`, then confirm the app builds
      and serves on its own `amplifyapp.com` URL.

## Task 5 — The production environment stack — DONE 2026-10-05 (`cca69c54`)

- [x] Write `infra/envs/production/` per the file structure above.
- [x] `vpc_cidr = "10.1.0.0/16"` — the range staging's variable doc already
      reserves for production, so the two VPCs could be peered without renumbering.
- [x] RDS module: `multi_az = false`, `instance_class = "db.t4g.micro"`,
      `backup_retention_days = 14`, `deletion_protection = true`,
      `skip_final_snapshot = false`.
- [x] S3 module: `force_destroy = false`, `cors_allowed_origins = ["https://auracles.space", "https://www.auracles.space"]`.
- [x] ECS module: `backend_image = "<ecr>:production"`, `worker_use_spot = true`,
      `beat_use_spot = false`.
- [x] ECS env vars, differing from staging: `ENVIRONMENT = "production"`,
      `CORS_ALLOWED_ORIGINS = "https://auracles.space,https://www.auracles.space"`,
      `TRUST_PROXY_HEADERS = "true"` (without it every per-IP rate limit
      collapses into one bucket keyed on the ALB), `EMAIL_SEND_ENABLED = "true"`,
      `PLATFORM_CURRENCY = "NGN"`, `ADMIN_EMAIL`, the production Google OAuth
      client id and its two redirect URIs on `https://auracles.space`. No
      `PERSONA_*` config.
- [x] Monitoring module: same wiring as staging — api excluded from the
      log-crash filter (FastAPI prints a traceback for any unhandled 500, so that
      filter would fire on ordinary bugs), every service included in the
      not-running alarm, ALB 5xx and unhealthy-target alarms on. Publishes to the
      existing shared SNS topic, already confirmed, so no new email click.
- [x] `aws_route53_record.api`: A-alias at the `api.auracles.space` zone apex
      pointing at the ALB.
- [x] `terraform fmt`, `validate`, and `init` with the production backend config.
- [x] **Human:** `make prod-plan` and read it. Expect ~60 resources, zero
      destroys, zero changes to anything named `staging`.

## Task 6 — Human prerequisites outside Terraform

- [x] Google OAuth. The staging client is reused rather than given a twin
      (human decision 2026-10-05): one client holds several redirect URIs, so
      localhost, staging and production coexist. The accepted cost is that a
      misconfiguration on that client reaches real sign-ins.
      `https://auracles.space/api/v1/auth/google/callback` added to its
      authorized redirect URIs, and the secret copied into the production
      shell.
- [x] ~~Stripe live webhook endpoint.~~ **Descoped 2026-10-05.** Stripe carries
      no pilot traffic: `PLATFORM_CURRENCY` is NGN and `select_provider` sends
      every NGN transaction to Paystack. The two Stripe secrets hold
      non-placeholder dummies purely to satisfy
      `production_provider_secrets_are_not_placeholders`, which refuses to boot
      without them. A stray Stripe webhook would fail signature verification and
      be rejected with a 400 plus an audit row, which is the correct outcome for
      a provider that is not in use. Create the real endpoint if Stripe ever
      comes into scope, and replace both dummies at the same time.
- [ ] Paystack live webhook URL → `https://api.auracles.space/v1/webhooks/paystack`.
      Paystack allows one URL per mode; set the live one. This is the rail that
      actually matters.
- [ ] Paystack: confirm **transfer OTP is disabled** on the live account.
      OTP-held transfers are abandoned after about an hour with no webhook,
      which strands a beneficiary's balance.
- [ ] Resend: confirm `auracles.space` is a verified sending domain for live
      traffic.
- [ ] Apply for AWS Activate Founders credits if still unapplied — at this burn
      it is roughly eight months of runway.

### Found while doing Task 6, not yet fixed

`config.py`'s `production_provider_secrets_are_not_placeholders` checks the two
**Stripe** secrets and not Paystack, and its docstring still says "Phase 3 runs
Stripe-only after the 2026-06-09 payment-scope decision". That is backwards for
a Nigeria pilot: production would boot happily with an empty
`PAYSTACK_SECRET_KEY` and fail at the first real charge instead of at startup.
Small fix, needs a human yes because it is a boot-blocking validator.

## Task 7 — First image, then first apply

The ECS task definitions pull `:production`, and that tag does not exist yet.
Applying before it does means three services crash-looping on image pull.

- [ ] Pick the commit to launch: on `main`, with a completed "Backend build" run.
- [ ] `make prod-promote-image COMMIT=<sha>` — copies the `sha-<commit>` manifest
      to the `production` tag inside ECR via `batch-get-image` + `put-image`. No
      bytes leave the registry and the multi-arch manifest survives. This burns
      no version number; `release.yml` handles every promotion after this one.
- [ ] `prod-up` guards on the tag existing, the same way `staging-up` guards on
      `:staging`.
- [ ] **Human:** `make prod-up`. RDS is the slow piece, ~10 minutes.
- [ ] Verify `https://api.auracles.space/v1/health` returns 200.
- [ ] Check `rolloutState` on all three services, and read the worker log for a
      clean clamd start. ECS reporting `ACTIVE 1/1` is not proof of health.
- [ ] Confirm the api log shows `alembic upgrade head` reaching the current head.

## Task 8 — Bootstrap and verify before any traffic

- [ ] **Human:** `make prod-bootstrap-admin` (idempotent; reads `ADMIN_EMAIL`
      from the task definition and `ADMIN_PASSWORD` from Secrets Manager, so
      neither value passes through a command line or CloudTrail).
- [ ] Do **not** run a seed. `scripts.seed_user` exists for QA; production starts
      with one admin and nothing else.
- [ ] Sign in to `/admin` on the Amplify URL and confirm the console loads.
- [ ] Fire one real registration against the production API and confirm the
      verification email arrives.
- [ ] Confirm a Stripe test event and a Paystack test event each reach their
      webhook and pass signature verification.

## Task 9 — Launch switch (the human's call, reversible)

- [ ] At Namecheap: repoint the apex ALIAS and the `www` CNAME from the waitlist
      app's CloudFront address to the production Amplify app's.
- [ ] Set `production_frontend_custom_domain = true` and apply `infra/shared` so
      Amplify serves the apex.
- [ ] **Rollback is the same edit backwards.** The eu-north-1 waitlist app
      (`Auracles`, `d34ih8666gpdu1`) stays untouched and keeps working
      throughout. Delete it only once comfortable post-launch.

## Task 10 — After launch

- [ ] Run one point-in-time restore into a throwaway instance. The design doc has
      carried "RDS restore has never been exercised" as an open risk since the
      Neon era. An untested backup is not a backup.
- [ ] Prove the alert path with `aws cloudwatch set-alarm-state` on a production
      alarm and confirm the mail arrives.
- [ ] Update `CLAUDE.md`'s tech-stack table and this plan's parent design doc
      (`docs/superpowers/specs/2026-08-24-aws-hybrid-infra-design.md` §8 still
      describes the Render cutover, which is history).

---

## Optional, needs a yes

**Deployment circuit breaker on the api service.** Worker and beat have one;
`modules/ecs/services.tf` gives api none, though the design doc's §5 says the api
should. Today a bad api deploy stalls rather than breaking anything — min-healthy
100% means the old task serves until the new one is healthy — but it stalls
silently until someone notices. A breaker reverts it automatically. It is four
lines, and it would apply to staging too. Not in the plan above because it is a
change to a service that is currently working.

---

## Cost

Production, monthly, `eu-west-2`. Verify in the calculator before applying.

| Item | Size | ~$/mo |
| --- | --- | --- |
| ALB | 1, low LCU | 20 |
| api task | 0.5 vCPU / 1 GB, on-demand | 18 |
| worker task (incl. clamd) | 1 vCPU / 4 GB, Spot | 13 |
| beat task | 0.25 vCPU / 0.5 GB, on-demand | 9 |
| RDS Postgres | `db.t4g.micro`, 20 GB gp3, single-AZ, 14-day backups | 14 |
| ElastiCache Redis | `cache.t4g.micro`, single node | 13 |
| Amplify Hosting | low traffic | 1–10 |
| Secrets Manager | 16 secrets at $0.40 (14 hand-entered + 2 composed) | 6.40 |
| Route 53 | second hosted zone | 0.50 |
| CloudWatch logs, ECR, data transfer, ALB access logs | | 8–12 |
| **Total** | | **≈ 105–135** |

Two notes against the design doc's §7 estimate. It costed "1 JSON secret" at ~$1;
the implementation uses sixteen separate secrets per environment, so that row is
$6.40 each — about $13/mo across both environments, worth knowing but not worth
restructuring. And Resend sits outside this table on its own plan.

Staging adds ~$2–3/day only while it is up, which is only during a QA cycle.
