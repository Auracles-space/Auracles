# Auracles infrastructure

Terraform for an all-AWS deployment (decision 2026-09-01): ECS Fargate compute,
RDS Postgres, ElastiCache Redis, S3, Amplify. Email stays on Resend.
Authoritative design: `docs/superpowers/specs/2026-08-24-aws-hybrid-infra-design.md`.

Region is **eu-west-2 (London)** for everything new (decision 2026-09-01,
revised same day from Stockholm when "closest to Nigeria" was made the
priority). London has the lowest practical latency from Lagos (~90–120ms —
West African submarine cables land in and near the UK) with full service
coverage. Cape Town looks closer on a map but has no Amplify Hosting, costs
20–30% more, and Lagos traffic often routes via Europe anyway. The co-location
rule stands: compute, database, cache, and buckets stay together, because the
worker streams every uploaded artifact out of S3 to scan it and the API
queries Postgres on every server-rendered page.

One deliberate exception: the **existing Amplify app in `eu-north-1` keeps
serving the waitlist** at auracles.space, untouched — it is static content
behind CloudFront (Lagos has an edge location), so its region is irrelevant. A
new Amplify app in `eu-west-2` carries the main application; launch day is
moving the domain from the old app to the new one, and rollback is moving it
back.

## Layout

```
infra/
├── shared/      Persistent. Applied once, never destroyed.
├── modules/     Reusable building blocks.
└── envs/
    ├── staging/     Ephemeral — apply for a QA pass, destroy after.
    └── production/  Long-lived.
```

`shared/` exists because two things are too slow to recreate on every staging
cycle: DNS delegation (nameserver propagation) and ACM certificate validation.
Destroying the hosted zone would assign new nameservers and force a manual
Namecheap edit each time, which is the exact toil the delegation removes. So the
zone and certificate persist; only the records inside them come and go.

## DNS

`auracles.space` stays at **Namecheap**, which remains authoritative for the
domain. Email lives there — MX, SPF, DKIM, DMARC — and moving the zone would
mean recreating every one of those records exactly, where a single mistake
breaks registration and verification email silently.

Instead one branch is delegated: `shared/` creates a Route 53 hosted zone for
`staging.auracles.space`, and four NS records added once at Namecheap hand that
subtree to Route 53. Terraform then owns everything beneath it.

Production DNS is not delegated and does not need to be — the production ALB is
never destroyed, so `api.auracles.space` is pointed once by hand.

| Record | Changes | Managed by |
| --- | --- | --- |
| MX / SPF / DKIM / DMARC | never | Namecheap, untouched |
| `auracles.space` → Amplify | once | Namecheap |
| `api.auracles.space` → prod ALB | once | Namecheap |
| `*.staging.auracles.space` | every staging cycle | **Route 53, delegated** |

## State

S3 with **native locking** (`use_lockfile = true`). No DynamoDB table: Terraform
1.10 added conditional-write locking to the S3 backend and 1.11 promoted it to
GA, deprecating the DynamoDB arguments.

The state bucket is created by hand, once, before the first `init` — Terraform
cannot create the bucket that holds its own state. Each stack keys into the same
bucket under a distinct path, so staging and production state never mix.

## Applying

Bucket name varies per account, so the backend takes partial configuration:

```bash
cp backend.hcl.example backend.hcl   # once, per stack; gitignored
terraform init -backend-config=backend.hcl
terraform plan -out=tfplan           # review before every apply
terraform apply tfplan
```

Order matters once: `shared/` before `envs/staging/`, because staging attaches
to the zone and certificate that `shared/` creates.

**Never `apply` without reading the plan.** A plan showing `destroy` or
`replace` on an existing resource is a stop-and-ask, not a proceed.

## Day-to-day operations

The universal pair, always run **in the directory that owns the thing you
changed** (edit `envs/staging/main.tf` → run in `envs/staging/`):

```bash
terraform plan -out=tfplan   # read it: "add" is fine, "change" means check,
                             # "destroy" means stop and be certain
terraform apply tfplan       # executes exactly the plan you read
```

### Configuration: what lives where

| Kind | Lives in | Example |
| --- | --- | --- |
| Plain config | `envs/<env>/main.tf`, `environment_variables` block | `PLATFORM_CURRENCY=NGN` |
| Machine-composed secrets | Secrets Manager, written by Terraform each cycle | `DATABASE_URL`, `REDIS_URL` |
| Hand-entered secrets | Secrets Manager, value entered once by a human | `STRIPE_SECRET_KEY` |

The rule that decides between the first and last row: **would it be fine on
GitHub?** No → it is a secret. Structure lives in Terraform; values live in
AWS. Terraform never sees a secret's value, only its ARN.

Only secrets appear in the Secrets Manager console (10 per page — mind the
pagination arrow). Plain env vars never do; to know what staging runs with,
read the `environment_variables` block, not the AWS console.

### Recipes

**Change or add a plain env var** — edit the `environment_variables` block in
`envs/staging/main.tf`, then plan + apply in `envs/staging/`. ECS rolls new
tasks with the new environment; the api rolls with zero downtime.

**Change a secret's value** (e.g. paste the real Paystack test key) — no
Terraform. Console: Secrets Manager → the secret → *Retrieve secret value* →
*Edit*. Or CLI:

```bash
aws secretsmanager put-secret-value --region eu-west-2 \
  --secret-id auracles/staging/PAYSTACK_SECRET_KEY --secret-string 'sk_test_...'
```

Running tasks keep the value they started with — ECS injects secrets at task
start only. If staging is already up, restart to pick up the new value:

```bash
aws ecs update-service --cluster auracles-staging --service api \
  --force-new-deployment --region eu-west-2   # likewise worker / beat
```

Usually irrelevant in practice: set values first, bring staging up second, and
fresh tasks read fresh values.

**Add a brand-new secret** — three steps across two directories:
1. Add its name to `staging_secret_names` in `shared/secrets.tf`; plan + apply
   in `shared/` (creates an empty shell with an ARN).
2. Put the value in (previous recipe).
3. Plan + apply in `envs/staging/` — task definitions pick the new reference up
   automatically, because staging consumes the whole ARN map.

### Frontend configuration (Amplify)

The frontend's variables live in `shared/amplify.tf`, in the
`branch_environment_variables` block, and reach AWS on `terraform apply` in
`shared/` — same as the backend so far. Then it diverges, in one way that
matters:

> **Applying is not enough. The frontend must be rebuilt.**
> Next.js bakes these values into the compiled bundle at build time, so a
> running app keeps the values it was *built* with. The backend habit —
> apply, force a new deployment, done — does not work here. Terraform changes
> what the *next* build will use; nothing visible changes until one runs.

```bash
# 1. edit the value
#      shared/amplify.tf                 → most variables
#      shared/shared.auto.tfvars         → those exposed as var.* (Stripe key)
# 2. push the change to AWS
terraform -chdir=infra/shared apply
# 3. rebuild, or the live site keeps the old value
make staging-frontend-build
```

**Adding a brand-new variable** has one extra step, and skipping it fails
silently:

1. Add it to `branch_environment_variables` in `shared/amplify.tf`.
2. **If it is server-side** (anything not prefixed `NEXT_PUBLIC_`), also add it
   to the `env | grep -E` pattern in `amplify.yml` at the repository root.
   Amplify exposes variables to the *build*, not to the running SSR server, so
   a value that is not copied into `.env.production` during the build simply
   does not exist at runtime. `NEXT_PUBLIC_*` values need no forwarding —
   `next build` inlines them into the client bundle.
3. Apply, then rebuild.

The failure mode when step 2 is missed is not an error: the variable reads as
`undefined` and the code takes its fallback path. That is how a missing
`SESSION_HINT_SECRET` turns into "every logged-in route redirects to /login"
rather than anything that mentions a variable.

**Staging QA cycle** — from the repo root:

```bash
make staging-status   # am I paying for it right now?
make staging-up       # ~10 min, RDS is the slow piece; prompts before applying
# ... QA pass against https://api.staging.auracles.space ...
make staging-logs                 # tail api; SERVICE=worker or beat for the others
make staging-down     # back to ~$0
```

`make staging-up` refuses to run if no `:staging` image is in ECR, because all
three services would otherwise crash-loop invisibly for ten minutes. CI pushes
that tag on every merge to main touching `backend/`. The underlying Terraform
commands still work directly if you want the saved-plan review flow
(`make staging-plan` writes `tfplan`).

Each cycle brings up an empty database, so the first thing a QA pass needs is
an admin to log in as:

```bash
make staging-bootstrap-admin   # idempotent; safe to re-run
```

It runs `scripts.bootstrap_admin` as a one-off ECS task against the same task
definition the api uses, so the password arrives from Secrets Manager rather
than a command line — ECS task overrides can carry plain environment values
but not secret references, and a password passed as an override would land in
CloudTrail.

The hand-entered secrets (14 of them) are typed **once, ever**: they live in the shared
stack precisely so staging's destroy cannot touch them. Only `DATABASE_URL`
and `REDIS_URL` die and regenerate with each cycle, because each cycle's fresh
RDS and Redis have new hostnames.

## CI/CD — how code reaches an environment

Two workflows, two triggers, one promise: **merging can never deploy to
production; only a `v*` git tag can.**

| Event | Workflow | What happens |
|---|---|---|
| PR opened | `checks.yml` / `infra-checks.yml` | Tests, coverage, fmt/validate. No AWS access. |
| Merge to `main` (touching `backend/`) | `backend-build.yml` | Builds the arm64 image, pushes `:staging` + `sha-<commit>` to ECR. If staging is up, rolls it; if down, the image waits for the next staging-up. |
| Push tag `v1.2.3` | `release.yml` | **No rebuild.** Re-points `:production` at that commit's `sha-<commit>` image — the exact bytes staging QA'd — then rolls production and waits for it to stabilise. |

Auth is OIDC (`shared/github_oidc.tf`): GitHub presents a signed per-run
token, AWS checks it names this repo on `main` or a `v*` tag, and hands out
the `auracles-github-actions` role. No AWS keys exist in GitHub. The role can
push to the one ECR repository and `forceNewDeployment` the known services —
it cannot read secrets, alter task definitions, or touch Terraform state, so
env/secret/infra changes remain human-applied Terraform, exactly as above.

**Releasing** (once production exists):

```bash
git tag v1.0.0 && git push origin v1.0.0   # deploy commit currently on main
# rollback = tag the previous good commit:
git tag v1.0.1 <old-sha> && git push origin v1.0.1
```

A tag on a commit whose build never ran (e.g. it touched only `frontend/`)
fails loudly with instructions instead of deploying something unexpected.
