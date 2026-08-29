# AWS Hybrid Infrastructure Design (Phase 1.5)

**Date:** 2026-08-24
**Status:** Approved (human decision, 2026-08-24)
**Supersedes:** `2026-06-07-pre-scale-infra-design.md` (Render hosting) — its Neon and Resend sections still apply. Its Upstash section does **not**: Redis moved to ElastiCache on 2026-08-29 (§1).
**Relation to TDD:** Overrides TDD Section 3 (infrastructure) until the Phase 2 upgrade triggers below fire.

---

## 1. Context and decision

Vercel and Render are being abandoned. Full TDD Phase 2 (ECS + RDS + ElastiCache + NAT + ALB, staging + production) costs ~$250–300/mo — roughly one month of the current budget (a few hundred USD). The approved path is a **hybrid**: AWS takes over *compute only*; the serverless data plane stays where it is cheap.

| Decision | Choice | Rejected alternatives |
| --- | --- | --- |
| Backend hosting | ECS Fargate (api, worker, beat, clamav) | Single EC2 + compose (throwaway); full Phase 2 now (burns budget) |
| Frontend hosting | AWS Amplify Hosting | Fargate container (+$18/mo, manual scaling); OpenNext/Lambda (tooling risk) |
| Database | **Neon stays** | RDS (+$14/mo + forces NAT) |
| Redis | **ElastiCache** (revised 2026-08-29 — Upstash free tier exhausted) | Upstash paid (per-command billing against an always-connected Celery broker); self-hosted on ECS (owns persistence/failover for a queue holding payouts) |
| Email | **Resend stays** | SES (no reason to move yet) |
| NAT Gateway | **None** — tasks in public subnets with public IPs, locked security groups | NAT (+$35/mo fixed) |

**Correction to this table's earlier reasoning (2026-08-29).** The rejected-alternatives column previously claimed ElastiCache and RDS each "force NAT". That is wrong, and it overstated the cost of the option now chosen. NAT exists to give *outbound internet* to instances without public IPs. Reaching an in-VPC service is a different path entirely: an ElastiCache node has a private address inside the VPC CIDR, which matches the VPC's `local` route, so a Fargate task talks to it directly regardless of which subnet either sits in. Tasks keep their public IPs and their IGW route for Stripe, Paystack, Persona, and Resend exactly as before. The only requirement is a security group rule. ElastiCache therefore costs ~$12–15/mo, not ~$47/mo. NAT would only become necessary if tasks were *moved into private subnets*, which is a separate choice this design is not making.
| Staging | **Ephemeral** — `terraform apply` before a release QA pass, `terraform destroy` after | Always-on parity (~2× cost) |
| Savings Plan | **No commitment** until load is known | 1-yr Compute SP (~20% off Fargate only; doesn't touch ALB) |

Phase 2 upgrade trigger (unchanged in spirit from the pre-scale doc): sustained load Neon's low tier cannot hold, or AWS Activate credits landing — then RDS and private subnets for the tasks slot in as new Terraform modules and env-var swaps. No code changes. ElastiCache is no longer part of that upgrade, having been pulled forward to Phase 1.

**Environment parity rule adaptation:** staging uses the *same Terraform modules* as production with smaller sizes, but exists only during release testing. Parity of architecture is kept; parity of uptime is deliberately dropped for budget.

---

## 2. Target architecture

```
                        ┌─────────────────────────────┐
  users ──────────────► │ Amplify Hosting (Next.js 15) │  auracles.space
                        │ CloudFront + Lambda, managed │
                        └──────────────┬──────────────┘
                                       │ NEXT_PUBLIC_API_URL
                                       ▼
                        ┌──────────────────────────────┐
  api.auracles.space ─► │ ALB (HTTPS, ACM cert)         │
                        └──────────────┬───────────────┘
                                       ▼
        ┌─────────────────── ECS Fargate cluster ───────────────────┐
        │  api      0.5 vCPU / 1 GB   desired=1  (alembic on boot)  │
        │  worker   1 vCPU / 4 GB     desired=1  (+ clamav sidecar) │
        │  beat     0.25 vCPU / 0.5GB desired=1  (singleton)        │
        └───────────┬───────────────────┬───────────────────────────┘
                    │                   │
          Neon (Postgres)      ElastiCache (Redis broker+cache, in-VPC)
          Resend (email)       S3 (artifacts/avatars/reports/thumbnails)
          Stripe / Paystack / Persona (webhooks → ALB → api)
```

### ClamAV placement (sub-decision, recommendation pending sign-off)

Render runs clamd as a separate private service (`auracles-clamav`, 2 GB, worker streams via INSTREAM on :3310). On ECS there are two placements:

1. **Sidecar container in the worker task (recommended).** Same task, `CLAMAV_HOST=localhost`. No service discovery, no extra service, one fewer moving part. Cost is folded into the worker task size (worker 1 GB + clamd 2 GB + headroom → 1 vCPU / 4 GB task).
2. **Separate ECS service + Service Connect.** Mirrors Render exactly; scan capacity scales independently of workers. Adds ~$16–27/mo and service-discovery config. Right answer when there are multiple workers — not yet.

Sidecar is the plan unless the human objects. Switching later is task-definition-only.

---

## 3. Terraform layout

Remote state in S3 + DynamoDB locking from day one (per CLAUDE.md — never local state). Staging and production state fully separate.

```
infra/
├── modules/
│   ├── networking/   # VPC, 2 public subnets (ALB needs 2 AZs), IGW, security groups. No NAT.
│   ├── ecr/          # One repo: auracles-backend
│   ├── ecs/          # Cluster, task definitions, services (api, worker+clamav, beat), CloudWatch log groups
│   ├── alb/          # ALB, target group (health check GET /health), HTTPS listener, ACM cert
│   ├── amplify/      # aws_amplify_app + branch (monorepo appRoot=frontend), domain association
│   ├── secrets/      # Secrets Manager entries + IAM policy for task execution role
│   └── s3/           # Import/manage the four existing buckets + lifecycle + CORS
├── envs/
│   ├── production/   # main.tf, variables.tf, backend.tf (state key: production/terraform.tfstate)
│   └── staging/      # same modules, smaller sizes; applied only during release QA, then destroyed
└── (no root main.tf — envs are the entry points)
```

Security groups (deny by default):

| SG | Inbound | Notes |
| --- | --- | --- |
| `alb` | 443 from 0.0.0.0/0 (+ 80 → 301 redirect) | Public edge |
| `api-task` | 8000 from `alb` SG only | Public IP exists but nothing can reach it directly |
| `worker-task` | none | Outbound only (Neon, S3, providers); clamd is localhost |
| `beat-task` | none | Outbound only |
| `redis` | 6379 from `api-task`, `worker-task`, `beat-task` SGs only | ElastiCache. Never from a CIDR — Redis has no authentication worth the name, so the SG *is* the access control |

No NAT means tasks get public IPs for outbound internet (Neon/Stripe/Paystack/Persona/Resend). All inbound is blocked by SGs except ALB→api. Redis traffic never touches that path: ElastiCache holds a private address inside the VPC CIDR, so it is reached over the VPC `local` route and never leaves AWS. Add an S3 **gateway VPC endpoint** (free) so artifact traffic to S3 doesn't either.

ElastiCache needs a subnet group. Put it in **private** subnets — it requires no outbound internet, so private subnets with no NAT cost nothing and keep the node off the public internet entirely.

Enable **encryption in transit** on the cluster and set `REDIS_URL` to `rediss://`. The application already handles that scheme (`app/core/config.py::cache_redis_url` passes `ssl_cert_reqs` through), so it costs nothing in code. Without it, refresh tokens and rate-limit state cross the VPC in clear text.

No code change is otherwise required by this move. The app shares one Redis database between Celery and application keys, which began as an Upstash constraint; ElastiCache supports numbered databases but the arrangement is kept, since the key prefixes already make collision impossible.

### Beat singleton guarantee

`desired_count = 1`, `deployment_minimum_healthy_percent = 0`, `deployment_maximum_percent = 100` — ECS stops the old beat before starting the new one, so two schedulers never overlap during deploys. Beat's `celerybeat-schedule` file is ephemeral container state; all entries are fixed intervals, so losing it on redeploy is harmless (worst case: a periodic task runs once early).

### Migrations

The Dockerfile runs `alembic upgrade head` on API boot. Safe while `api desired_count = 1`. **Before ever scaling the API past 1**, migrations move to a dedicated `aws ecs run-task` step in the deploy workflow (one-off task, then update services). Recorded here so scaling doesn't silently create a migration race.

---

## 4. Secrets and configuration

All secrets in **AWS Secrets Manager**, injected via task-definition `secrets` (execution role reads them; they never appear in the task def in plaintext). ~$0.40/secret/mo → store as **one JSON secret per environment** (`auracles/production/app`) with key-per-variable to keep cost at ~$0.40 + rotation freedom.

Secret keys (from `app/core/config.py`): `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `TOTP_ENCRYPTION_KEY`, `PAYOUT_ACCOUNT_ENCRYPTION_KEY`, `PARTNER_WEBHOOK_ENCRYPTION_KEY`, `CONNECTOR_TOKEN_ENCRYPTION_KEY`, `RESEND_API_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `PAYSTACK_SECRET_KEY`, `PAYSTACK_WEBHOOK_SECRET`, `PERSONA_API_KEY`, `PERSONA_WEBHOOK_SECRET`, `GOOGLE_CLIENT_SECRET`, `BRAVE_SEARCH_API_KEY`.

Plain env vars on the task definition: `ENVIRONMENT=production`, `LOG_FORMAT=json`, `CORS_ALLOWED_ORIGINS=https://auracles.space`, `AWS_DEFAULT_REGION`, the four `S3_*_BUCKET` names, `CLAMAV_HOST=localhost`, `CLAMAV_PORT=3310`, Persona/Google IDs and redirect URIs, `PLATFORM_CURRENCY`, invoice seller fields, **`TRUST_PROXY_HEADERS=true`**.

`TRUST_PROXY_HEADERS` defaults to **off** and must be turned on here. Behind the ALB the TCP peer is the load balancer, so with it off every per-IP auth rate limiter keys on one address and the whole internet shares a single bucket — the limiter still "works" and protects nothing. `client_ip` (`app/core/network.py`) reads the **right-most** `X-Forwarded-For` entry, because an ALB *appends* the peer it saw rather than replacing the header: everything to the left is caller-supplied and forgeable. That is correct for **exactly one** trusted hop. Putting CloudFront or any CDN in front of the ALB adds a hop and moves the real client one position left — change the function, not the edge config, if that ever happens.

**IAM instead of keys:** on Fargate, drop `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` entirely — the **task role** grants S3 access (boto3 picks up the role automatically; `Settings` fields are `None`-defaulted so nothing breaks). One fewer long-lived credential in existence.

Amplify env vars: `NEXT_PUBLIC_API_URL=https://api.auracles.space`, `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_PLATFORM_CURRENCY`, `NEXT_PUBLIC_WAITLIST_MODE`.

### Runtime limits to set before first deploy

Both limits below are now enforced in code with conservative defaults, so an unconfigured deploy is already safe. What remains here is per-service tuning: each service runs its own process with its own pool, so the values differ by service and are set as environment variables in the task definitions.

**Connection pool.** Bounded by `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` (`app/core/database.py::create_database_engine`, and `app/workers/schedules.py::create_beat_engine` for Beat's separate sync engine). Defaults are 5 + 5. Left implicit, as they were until these helpers existed, SQLAlchemy allows 5 + 10 **per process**, up to 45 across api + worker + beat against a Neon tier that caps connections. Also point `DATABASE_URL` at Neon's **pooled** endpoint rather than the direct one: the driver pool and the Neon pooler are different layers and both need sizing. Per-service starting point, to revisit under real load:

| Service | `DB_POOL_SIZE` | `DB_MAX_OVERFLOW` | Rationale |
| --- | --- | --- | --- |
| api | 5 | 5 | Request-scoped sessions, short-lived |
| worker | 3 | 2 | Few concurrent tasks at `desired_count=1` |
| beat | 1 | 1 | Dispatches only; does almost no querying |

**WebSocket caps.** Bounded by `WS_MAX_CONNECTIONS_PER_USER` (5), `WS_MAX_MESSAGES_PER_SECOND` (10), and `WS_MAX_SUBSCRIPTIONS_PER_SOCKET` (50), landed in commit `70f35505`. The gateway opens a DB session per inbound message against the pool above, so before the caps existed a reconnect loop — a bug or a malicious client — could exhaust the pool and take the HTTP API down with it. All three are counted **per API process**, which is the scope that matters because the pool being defended is itself per process; running more than one api task therefore multiplies the effective per-user ceiling, which is bounded but worth knowing when sizing `desired_count`. Defaults are safe as shipped; override only if real usage shows false positives.

---

## 5. CI/CD

`checks.yml` is unchanged (it already gates everything). `deploy.yml` is rewritten:

```
on: workflow_run [Checks] success on main
jobs:
  deploy:
    - aws-actions/configure-aws-credentials  (GitHub OIDC role — NO long-lived AWS keys in GH secrets)
    - docker build backend → push to ECR (tag = git SHA)
    - aws ecs update-service --force-new-deployment  (api, worker, beat — new task-def revision pinned to the SHA tag)
    - wait for services-stable on api (rollback signal: deployment circuit breaker enabled)
```

- **GitHub OIDC** (`aws_iam_openid_connect_provider` + a deploy role scoped to ECR push + ECS deploy) replaces stored AWS keys — Terraform creates it.
- ECS **deployment circuit breaker** with rollback on: a task that can't pass `/health` auto-rolls back to the previous revision.
- Frontend deploys via **Amplify's own git integration** (push to `main` → build) — outside GitHub Actions, mirroring how Vercel worked. The Render deploy-hook secrets get deleted.
- E2E (Playwright) is still not in CI — tracked separately; the ephemeral-staging QA pass is where it runs for now.

---

## 6. Ephemeral staging workflow

```
make staging-up      # terraform -chdir=infra/envs/staging apply  (≈5–10 min incl. ACM DNS validation reuse)
make staging-seed    # alembic upgrade + seed script against the Neon `develop` branch
# ... QA / E2E pass against staging.auracles.space ...
make staging-down    # terraform destroy — idle cost returns to ~$0
```

- Staging DB = Neon `develop` branch (already exists per pre-scale doc) and is **not** created or destroyed by Terraform. Staging Redis now *is* a Terraform resource, since ElastiCache is in-VPC — it comes up and goes down with the rest of the ephemeral stack. That is an improvement on the Upstash arrangement: staging starts with an empty broker every cycle instead of inheriting whatever a previous run left in a shared instance.
- ACM certs + Route 53 zone live in a tiny **persistent** shared stack (cert validation takes too long to recreate each time); staging apply only attaches to them.
- Fargate Spot for all staging services (~70% off the already-small window).

---

## 7. Cost estimate (production, monthly, us-east-1 — verify in AWS calculator before apply)

| Item | Size | ~$/mo |
| --- | --- | --- |
| ALB | 1, low LCU | 20 |
| api task | 0.5 vCPU / 1 GB | 18 |
| worker task (incl. clamd sidecar) | 1 vCPU / 4 GB | 42 |
| beat task | 0.25 vCPU / 0.5 GB | 9 |
| Amplify Hosting | low traffic | 1–10 |
| Secrets Manager (1 JSON secret) + KMS default | | 1 |
| CloudWatch logs + ECR + data transfer | | 8–12 |
| Route 53 hosted zone | | 0.50 |
| ElastiCache Redis | `cache.t4g.micro`, single node | 12–15 |
| Neon / Resend | current tiers | 0–20 |
| **Total** | | **≈ 112–145** |

Honest correction vs. the earlier estimate ($75–90): the ClamAV daemon's 2 GB requirement was not priced in. It is now. Budget survives ~2.5–3 months at this burn; **AWS Activate Founders ($1,000 credits) should be applied for immediately** — it roughly doubles runway or funds the Phase 2 upgrade.

Cheapest lever if burn must drop: fold worker to 0.5 vCPU / 3 GB (~$31) and accept slower artifact processing.

---

## 8. Cutover order

1. **Human:** create/verify AWS account, enable MFA on root, create the Terraform state bucket + DynamoDB table (one-time, manual by design), apply for Activate credits.
2. Terraform bootstrap: networking, ECR, secrets (values entered by human, never committed), IAM/OIDC.
3. Build + push backend image to ECR manually once; stand up ECS cluster + services with `desired_count=0→1`; confirm `/health` green through the ALB.
4. Set the runtime limits from §4 in each task definition — per-service `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`, the `WS_MAX_*` caps, `TRUST_PROXY_HEADERS=true`. The caps are enforced in code with safe defaults, so this step is tuning rather than a gate; `TRUST_PROXY_HEADERS` is not, and must be set **before** the next step makes the API reachable.
5. Point **api.auracles.space** DNS at the ALB (ACM cert validated first). Old Render URL keeps working in parallel — this is the rollback path.
6. Update webhook endpoints at Stripe, Paystack, Persona to the new API host. (Paystack: single URL per mode — swap test URL first, verify, then live.)
7. Amplify app connected to the GitHub repo (`appRoot=frontend`), env vars set, deploy, attach **auracles.space** domain.
8. Rewrite `deploy.yml` (ECR + ECS via OIDC), delete Render hook secrets. One full push-to-main → auto-deploy verified.
9. Run one ephemeral-staging cycle end-to-end to prove the QA workflow.
10. Decommission Render services; delete `render.yaml` in a follow-up PR; update CLAUDE.md tech-stack table.

Rollback at any step ≤ 8: DNS back to Render, webhooks back to old URLs. Nothing is destroyed until step 10.

---

## 9. Risks

| Risk | Mitigation |
| --- | --- |
| Public-IP tasks (no NAT) widen exposure surface | SGs allow zero inbound except ALB→api:8000; this is standard "public subnet + SG" posture. Revisit when private subnets arrive with Phase 2. |
| Neon egress: traffic now crosses AWS↔Neon | Pick the Neon region matching the AWS region; Neon doesn't bill egress on current tiers, latency is the only cost. |
| Amplify build quirks vs. Vercel (monorepo, Next 15) | Prove the Amplify build in step 6 **before** DNS cutover; Render/old URL remains live. |
| clamd cold start (freshclam signature download, ~3 min) | Container healthcheck + ECS grace period 300 s, mirroring compose's `start_period: 180s`. |
| Migration race if api scales >1 | Locked in §3: move migrations to `ecs run-task` before any scale-out. |
| Beat double-run during deploy | min-healthy 0 / max 100 deployment config (§3). |
| Ephemeral staging drift (“works on prod modules only”) | Staging uses identical modules — only tfvars differ; CI runs `terraform fmt`/`validate` on every infra PR. |
| Default DB pool (5+10 × 3 services) exhausts Neon's connection cap | Explicit `pool_size`/`max_overflow` per service and Neon's pooled endpoint, set when `DATABASE_URL` is wired (§4). |
| Unbounded WebSocket sockets exhaust the DB pool and take the API down with them | Per-user connection cap + per-socket rate limit landed before step 4 exposes the ALB (§4). |
| `TRUST_PROXY_HEADERS` left off silently collapses every per-IP rate limit into one bucket | Set it on the task definition (§4); the limiter keys on the ALB address otherwise and protects nothing. |
| No error tracking or metrics — production failures surface via users | Accepted for the pilot. Sentry (or equivalent) is the first addition once traffic is real; CloudWatch logs alone will not surface a 500 spike. |
| Neon restore has never been exercised | Run one PITR restore against the `develop` branch during an ephemeral-staging cycle (§6). An untested restore is not a backup. |
