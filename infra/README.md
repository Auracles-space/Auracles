# Auracles infrastructure

Terraform for the Phase 1.5 hybrid: AWS runs compute, the data plane stays on
Neon and Resend. Authoritative design:
`docs/superpowers/specs/2026-08-24-aws-hybrid-infra-design.md`.

Region is **us-east-1** for everything, chosen to match the existing Neon
project. Neon's region is fixed at project creation, so it is the constraint
and AWS follows it — the API is server-rendered, and a cross-continent hop on
every query would land on the Phase 6 sub-3s target for `/explore`.

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
