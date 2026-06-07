# Auracles

## Authority

**Human is architect. Agent is senior engineer.**

- Check `docs/superpowers/specs/` before every task. Doc hierarchy: FRD (what to build) → TDD (how to build: schema, API, security, Celery) → Pre-scale infra design (where to deploy, overrides TDD infra section only for Phase 1).
- Before starting any feature: invoke `grill-me` skill to stress-test requirements as developer questions and not just decide.
- Before building anything visual: invoke `frontend-design` skill.
- Before debugging: invoke `diagnose` skill.
- Every feature is test-driven: write failing test first, then implementation. Invoke `tdd` skill before any feature work.
- Never make architecture decisions autonomously — present 2–3 options with trade-offs, human chooses.
- Never bulk-generate code. One module, one feature, one migration at a time.
- Remind human to commit after each meaningful change.
- If stuck or ambiguous: ask. Never guess on product behaviour.
- Flag risks — security, data integrity, cost implications — immediately and explicitly.

---

## Project

Auracles is a **knowledge marketplace**. Contributors package professional expertise into licensed Frameworks. Operators purchase and implement them. Attestors verify their quality. The platform manages provenance, trust, transactions, and value exchange.

### Key Docs

| Doc             | Path                                                          | Purpose                                             |
| --------------- | ------------------------------------------------------------- | --------------------------------------------------- |
| PRD             | `docs/auracles-prd.md`                                        | Short PRD — start here for onboarding               |
| Full Spec       | `docs/auracles-full-spec.md`                                  | PRD + full ontology + taxonomy (source of truth)    |
| FRD             | `docs/superpowers/specs/2026-06-06-auracles-frd.md`           | Functional requirements (~76 FRs, ~24 BRs)          |
| TDD             | `docs/superpowers/specs/2026-06-06-auracles-tdd.md`           | Technical design: schema, API, infra, security      |
| Infra (Phase 1) | `docs/superpowers/specs/2026-06-07-pre-scale-infra-design.md` | Pre-scale hosting: Render + Neon + Upstash + Resend |
| Brand Book      | `docs/auracles-brand-book.pdf`                                | Auracles design system. Trillo-inspired light-mode only, warm orange accent, bento-box shadows, solid black/white buttons. |

---

## Tech Stack

Two-phase deployment. Code is identical in both phases — only env vars and deploy targets change.

### Phase 1 — Pre-Scale (current)

| Layer              | Technology                                  |
| ------------------ | ------------------------------------------- |
| Frontend           | Next.js 15 (App Router)                     |
| Styling            | Tailwind CSS                                |
| Frontend hosting   | Vercel                                      |
| Backend            | FastAPI (Python 3.13)                       |
| Backend hosting    | Render (Web Service)                        |
| Async workers      | Celery + Redis — Render (Background Worker) |
| Scheduler          | Celery Beat — Render (Background Worker)    |
| Database           | PostgreSQL 16 (Neon — serverless)           |
| Cache + broker     | Redis (Upstash — serverless)                |
| File storage       | AWS S3                                      |
| Virus scan         | Celery task (ClamAV in worker image)        |
| Payments (global)  | Stripe + Stripe Connect                     |
| Payments (Nigeria) | Paystack                                    |
| Email              | Resend (`noreply@auracles.space`)           |
| API contract       | OpenAPI spec (`contracts/openapi.yaml`)     |
| Migrations         | Alembic                                     |
| ORM                | SQLAlchemy (async)                          |
| Validation         | Pydantic v2                                 |
| CI/CD              | GitHub Actions → GHCR → Render deploy hooks |

### Phase 2 — AWS (at scale)

| Layer           | Technology                                 |
| --------------- | ------------------------------------------ |
| Backend hosting | AWS ECS Fargate                            |
| Scheduler       | Celery Beat (ECS singleton task)           |
| Database        | PostgreSQL 16 (AWS RDS)                    |
| Cache + broker  | Redis (AWS ElastiCache)                    |
| File events     | AWS Lambda (S3 trigger → virus scan)       |
| Email           | AWS SES (or Resend — optional swap)        |
| Infrastructure  | Terraform                                  |
| Terraform state | AWS S3 + DynamoDB (remote state + locking) |
| CI/CD           | GitHub Actions → ECR → ECS rolling deploy  |

See `docs/superpowers/specs/2026-06-07-pre-scale-infra-design.md` for migration steps.

---

## Repository Layout

```
auracles/
├── frontend/          # Next.js
├── backend/           # FastAPI + Celery
│   └── app/
│       ├── modules/   # auth | explore | frameworks | projects | attestation | financials | settings
│       ├── core/      # config, database, security, dependencies
│       ├── shared/    # base models and schemas
│       └── workers/   # Celery app, tasks, beat schedule
├── infra/             # Terraform
│   ├── modules/       # Reusable TF modules (ecs, rds, redis, s3, lambda)
│   ├── envs/
│   │   ├── staging/   # staging.tfvars + backend config
│   │   └── production/ # production.tfvars + backend config
│   └── main.tf
├── contracts/
│   └── openapi.yaml   # API contract — frontend types generated from this
└── docs/
    └── superpowers/specs/
```

---

## Security First — Core Development Principle

**Every implementation decision starts with security.** Not a checklist at the end — a design constraint from the beginning.

Before writing any feature, ask:

1. Who can call this endpoint? → RBAC dependency applied before service logic
2. What data is exposed? → Response schema exposes minimum necessary fields
3. Can this be abused? → Rate limiting, input validation, idempotency considered
4. What happens if it fails? → Partial writes, Escrow state, money movement must be atomic
5. Is this logged? → Security-relevant actions (login, download, payout, dispute) always audited

### Mandatory security requirements on every feature

| Concern          | Rule                                                                                                        |
| ---------------- | ----------------------------------------------------------------------------------------------------------- |
| Input validation | Pydantic schema on every request body. No raw dict access.                                                  |
| Auth             | JWT verified via dependency before any handler runs.                                                        |
| RBAC             | Role checked via FastAPI dependency, never inside service or model.                                         |
| File access      | S3 artifacts delivered via presigned URL only, never proxied. License checked before URL generated.         |
| Money + Escrow   | All financial state changes inside DB transactions. Escrow never modified outside explicit service methods. |
| Webhooks         | Signature verified before payload parsed. Unverified = 400 + audit log.                                     |
| Secrets          | Zero secrets in code or logs. AWS Secrets Manager in prod. `.env` local only, gitignored.                   |
| PII              | No sensitive user fields (KYC docs, payout account details) returned in list endpoints.                     |
| Audit trail      | Downloads, payouts, role changes, KYC updates, Escrow releases all written to audit log.                    |
| Rate limiting    | Auth endpoints (login, register, reset-password) rate-limited at ALB or Redis layer.                        |

When in doubt: **deny by default, log the denial, surface to human if ambiguous.**

---

## Architecture Decisions (locked)

These are decided. Do not re-open without explicit human instruction.

| Decision               | Choice                                             | Reason                                                      |
| ---------------------- | -------------------------------------------------- | ----------------------------------------------------------- |
| Repo structure         | Monorepo (`frontend/` + `backend/` + `contracts/`) | Single CI/CD, shared OpenAPI contract                       |
| Backend framework      | FastAPI (not Express, not Django)                  | Python ML ecosystem, auto-generates OpenAPI, async          |
| Background jobs        | Celery + Redis                                     | Same Python codebase, Redis already in stack, Beat for cron |
| File events            | Lambda (S3 trigger only)                           | Stateless, event-driven, isolated from main API             |
| Payment routing        | Stripe (global) + Paystack (Nigeria/NGN)           | Coverage + local payout rails                               |
| Auth                   | JWT (15m) + Redis refresh tokens (30d)             | Stateless access, revocable refresh                         |
| Artifact access        | S3 presigned URLs (15m expiry)                     | Secure, no proxy required                                   |
| Frontend rendering     | SSR for public pages, Client for dashboards        | SEO on Explore + Framework detail                           |
| Search (MVP)           | Postgres full-text search (GIN index)              | Zero extra infra, migrate to Typesense at scale             |
| Admin tooling          | Custom admin module (`/v1/admin/*`)                | Full control, consistent auth model                         |
| Infrastructure as Code | Terraform (not CDK, not manual)                    | Portable, reproducible, staging/prod parity                 |

---

## Backend Code Standards (FastAPI)

### Module structure — always follow this pattern

```
app/modules/{module}/
├── router.py      # Thin: parse request → call service → return response
├── service.py     # Business logic, BR enforcement, task dispatch
├── models.py      # SQLAlchemy async ORM models
├── schemas.py     # Pydantic v2 request/response schemas
└── dependencies.py  # Module-specific FastAPI dependencies (if needed)
```

Never put business logic in `router.py`. Never do DB queries in `router.py`.

### DB access

- All DB operations via SQLAlchemy async sessions.
- Sessions injected via FastAPI dependency: `db: AsyncSession = Depends(get_db)`.
- Never use `Session.execute()` raw SQL — use ORM unless a complex query justifies it.
- Every write operation that touches multiple tables uses a transaction: `async with db.begin()`.

### Schemas

- All API inputs validated with Pydantic v2 models. No raw dicts at router level.
- Response models always explicit — never return ORM objects directly.
- Use `model_config = ConfigDict(from_attributes=True)` on response schemas.

### Error handling

- Business rule violations → `HTTPException(422, detail=...)`.
- Auth failures → `HTTPException(401)` or `HTTPException(403)`.
- Not found → `HTTPException(404)`.
- Never raise bare `Exception` — always typed HTTP exceptions.
- Never swallow exceptions silently. If caught, log it, then either re-raise or return a typed error.
- External service failures (Stripe, Paystack, S3, Resend) → catch specific SDK exceptions, log with full context, raise `HTTPException(502)`.
- Always handle the unhappy path before the happy path — validate inputs, check preconditions, then execute.

### Edge case handling

Every feature must explicitly handle:

| Edge case                      | Required handling                                       |
| ------------------------------ | ------------------------------------------------------- |
| Unauthenticated request        | 401 — logged at INFO                                    |
| Insufficient role              | 403 — logged at WARNING with user_id + attempted action |
| Resource not found             | 404 — no logging needed (not an error)                  |
| Duplicate action (idempotency) | 200/409 depending on context — never 500                |
| Malformed input                | 422 via Pydantic — automatic, no extra code             |
| External service timeout       | Retry via Celery task, return 202 if async, 502 if sync |
| Webhook invalid signature      | 400 + audit log — never process payload                 |
| File too large                 | 413 — validated before S3 upload attempt                |
| Concurrent write conflict      | DB transaction rollback + 409                           |
| Escrow insufficient funds      | 402 + explicit error message + audit log                |

Never assume the happy path. Every service method must consider: what if the record doesn't exist, what if a concurrent request already did this, what if the external call fails.

### Celery tasks

- Tasks in `app/workers/tasks/` — one file per domain (notifications, reputation, payouts, scheduled).
- Tasks must be idempotent — safe to retry.
- Always use `bind=True` + `self.retry(exc=exc, countdown=60)` for transient failures.
- Never call tasks synchronously in a request path unless absolutely necessary.

### Migrations

- Every schema change = new Alembic migration. No manual DB edits.
- Migration filenames: `YYYY_MM_DD_description.py`.
- All migrations backwards-compatible with the previous deployed version.
- Test: `alembic upgrade head` and `alembic downgrade -1` must both succeed.

---

## Logging Standards (Non-Negotiable)

### Library: `loguru` (backend)

All backend logging uses `loguru`. Never use `print()`. Never use Python's stdlib `logging` directly in application code.

```python
from loguru import logger

# Always bind context before logging in a request
logger.bind(module="frameworks", action="publish", user_id=user.id, framework_id=fw.id)
logger.info("Framework submitted for review")
```

### Format

| Environment  | Format                            | Sink                      |
| ------------ | --------------------------------- | ------------------------- | ----------------- | ---------- | ------ |
| Dev (local)  | Colored, human-readable — `{time} | {level}                   | {module}.{action} | {message}` | stdout |
| Staging/Prod | JSON structured                   | stdout → Render log drain |

Controlled by `LOG_FORMAT=json` env var in production. Dev defaults to colored.

### Mandatory context tags

Every log entry must include:

| Tag              | When required                                                                                |
| ---------------- | -------------------------------------------------------------------------------------------- |
| `module`         | Always — matches the module name (auth, frameworks, financials, etc.)                        |
| `action`         | Always — snake_case verb describing what's happening (`publish_framework`, `release_escrow`) |
| `user_id`        | Whenever a user is authenticated                                                             |
| `request_id`     | On every HTTP request — injected by middleware                                               |
| `framework_id`   | On any framework operation                                                                   |
| `transaction_id` | On any financial operation                                                                   |
| `task_id`        | On any Celery task                                                                           |

### Log levels — use precisely

| Level      | Use for                                                                                          |
| ---------- | ------------------------------------------------------------------------------------------------ |
| `DEBUG`    | Internal state, query results, branching decisions — dev only                                    |
| `INFO`     | Normal operations: login, purchase, publish, payout requested                                    |
| `WARNING`  | Unexpected but handled: RBAC denial, webhook retry, rate limit hit                               |
| `ERROR`    | Failures that need investigation: external service down, DB write failed, task exhausted retries |
| `CRITICAL` | Data integrity risk: Escrow inconsistency, payment mismatch, audit log write failure             |

### What always gets logged (non-negotiable)

These events must be logged regardless of where they occur:

```
AUTH        INFO     login_success, login_failure, token_refresh, password_reset
AUTH        WARNING  invalid_token, expired_token, 2fa_failed
RBAC        WARNING  access_denied (user_id, role, attempted_action, resource)
FRAMEWORKS  INFO     created, submitted, published, unpublished, version_bumped
ARTIFACTS   INFO     uploaded, processing_started, processing_complete, download_requested
ARTIFACTS   ERROR    virus_detected, pii_detected, processing_failed
FINANCIALS  INFO     purchase_initiated, escrow_funded, payout_requested
FINANCIALS  INFO     escrow_released, payout_completed, refund_issued
FINANCIALS  CRITICAL escrow_mismatch, double_charge_detected
WEBHOOKS    INFO     received, verified, processed (provider, event_type)
WEBHOOKS    WARNING  signature_invalid, unknown_event_type
ATTESTATION INFO     assigned, report_submitted, published, rejected
ADMIN       INFO     user_suspended, content_flagged, commission_tier_changed
```

### FastAPI request middleware

Every request gets a `request_id` (UUID) and structured log entry:

```python
# app/core/logging.py
import uuid
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = str(uuid.uuid4())
        with logger.contextualize(request_id=request_id):
            logger.info(
                "request_started",
                method=request.method,
                path=request.url.path,
            )
            response = await call_next(request)
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
            )
        return response
```

### Celery task logging

```python
@app.task(bind=True)
def process_artifact(self, artifact_id: str):
    log = logger.bind(module="artifacts", action="process_artifact", task_id=self.request.id, artifact_id=artifact_id)
    log.info("task_started")
    try:
        # ... processing
        log.info("task_completed")
    except Exception as exc:
        log.error("task_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60)
```

### Never log secrets

- No passwords, tokens, API keys, or webhook payloads in logs.
- Mask card/account numbers: `****1234`.
- Never log full S3 presigned URLs — log `artifact_id` only.

---

## Code Documentation Standards (Non-Negotiable)

**Every file, every public function, every class is documented.** Code is read more than it is written. The next agent or human picking up the file should understand intent without reading the implementation.

### Python (Backend) — Google-style docstrings

**Module-level docstring** at top of every `.py` file:

```python
"""Framework service layer.

Handles framework CRUD, versioning, publish/review workflow,
and dispatches artifact processing tasks.

Maps to: FR-FWK-001 through FR-FWK-024.
"""
```

**Class docstring** on every class:

```python
class FrameworkService:
    """Service layer for Framework operations.

    Encapsulates business rules for framework lifecycle:
    create, edit, version, submit, publish, unpublish.

    Attributes:
        db: Async SQLAlchemy session for DB operations.
        celery: Celery app for dispatching background tasks.
    """
```

**Function/method docstring** on every public function:

```python
async def publish_framework(self, framework_id: UUID, user_id: UUID) -> Framework:
    """Publish a framework, making it visible in the marketplace.

    Validates that the framework has passed review (BR-FWK-007) and the
    requesting user is the owner (BR-FWK-002). Triggers reputation
    recalculation and a notification to the contributor.

    Args:
        framework_id: UUID of the framework to publish.
        user_id: UUID of the requesting user (must be owner).

    Returns:
        The published Framework instance with updated status.

    Raises:
        HTTPException(403): If user is not the framework owner.
        HTTPException(422): If framework has not passed review.
    """
```

**Inline comments** — only for non-obvious WHY, never for WHAT:

```python
# Use SELECT FOR UPDATE to prevent race conditions on concurrent purchases
license = await db.execute(stmt.with_for_update())
```

Private helpers (`_method`) get a one-line docstring. No exceptions for "self-explanatory" code.

### TypeScript (Frontend) — JSDoc / TSDoc

**File-level comment** at top of every `.ts` / `.tsx` file:

```typescript
/**
 * Framework detail page (SSR).
 *
 * Renders public framework metadata, attestations, contributor info,
 * and purchase CTA. SEO-critical — must SSR fully.
 *
 * Maps to: FR-EXP-008, FR-FWK-014.
 */
```

**Component JSDoc** on every exported component:

```typescript
/**
 * Card displaying a single framework in the Explore feed.
 *
 * @param framework - Framework metadata to render.
 * @param onSave - Callback when user clicks save button.
 * @param compact - If true, renders a denser variant for sidebar use.
 */
export function FrameworkCard({ framework, onSave, compact = false }: FrameworkCardProps) {
```

**Function JSDoc** on every exported utility:

```typescript
/**
 * Formats a price for display, respecting the user's locale and currency.
 *
 * @param amountMinor - Amount in minor units (cents/kobo).
 * @param currency - ISO 4217 currency code (USD, NGN, etc.).
 * @returns Formatted string with currency symbol.
 */
export function formatPrice(amountMinor: number, currency: string): string {
```

### Migration files (Alembic)

Every migration starts with the WHY:

```python
"""Add artifact_fingerprints table for rarity scoring.

Supports FR-FWK-019 (artifact processing pipeline) by storing
sentence-transformer embeddings used for nearest-neighbor lookup
via pgvector IVFFlat index.

Revision ID: a3f2c9b1d4e5
Revises: 7e8d3c1f9a02
Create Date: 2026-06-15
"""
```

### Test files

Every test class and test function gets a docstring describing the behavior under test, not the implementation:

```python
async def test_publish_framework_blocks_unreviewed():
    """Publishing a framework that has not passed review must raise 422.

    Enforces BR-FWK-007.
    """
```

### Rules

- Never write a comment that restates what the code does. Comments answer WHY.
- Never leave a placeholder docstring (`"""TODO"""`). Either write it properly or don't merge.
- Every TODO/FIXME comment includes the author, date, and FR if applicable: `# TODO(william, 2026-06-15, FR-FIN-012): handle multi-currency rounding`
- Public APIs (router endpoints) get OpenAPI summary + description in the FastAPI decorator AND a Python docstring.
- Update docstrings when behavior changes. Stale docstrings are worse than no docstrings.

---

## Frontend Code Standards (Next.js)

### Rendering strategy

| Page                               | Strategy               | Reason                  |
| ---------------------------------- | ---------------------- | ----------------------- |
| `/explore`                         | SSR (Server Component) | SEO, fast TTFB          |
| `/explore/[id]` (Framework detail) | SSR                    | SEO-critical            |
| `/dashboard/*`                     | Client Component       | Auth-gated, interactive |
| `/projects/[id]` (Workspace)       | Client Component       | Real-time WebSocket     |

### Mobile-First (Non-Negotiable)

Every component, every page, every layout is built **mobile-first**. Design at the smallest screen first, then progressively enhance for larger breakpoints.

**Rules:**

- Base Tailwind styles target mobile (no breakpoint prefix). Use `sm:` / `md:` / `lg:` / `xl:` only to enhance for larger screens — never to shrink down.
- Yes: `className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3"`
- No: `className="grid grid-cols-3 md:grid-cols-2 sm:grid-cols-1"` (desktop-first — banned)
- Touch targets minimum `44px × 44px` (Apple HIG) on all interactive elements — buttons, links, inputs.
- Tap-friendly spacing on mobile: `py-3` minimum on list items, `gap-4` minimum between actionable items.
- No hover-only interactions — every hover state has an equivalent tap/focus alternative.
- Navigation: bottom sheet / drawer on mobile, persistent sidebar on `md:` and up.
- Tables: card-stack layout on mobile, true table on `md:` and up. Never horizontal-scroll a data table on mobile.
- Modals: full-screen on mobile, centered overlay on `md:` and up.
- Test every new component at 375px (iPhone SE) before committing.

**Breakpoints (Tailwind defaults — do not customize):**

| Prefix | Min width | Use case                          |
| ------ | --------- | --------------------------------- |
| (none) | 0px       | Phones (portrait)                 |
| `sm:`  | 640px     | Phones (landscape), small tablets |
| `md:`  | 768px     | Tablets                           |
| `lg:`  | 1024px    | Laptops                           |
| `xl:`  | 1280px    | Desktops                          |
| `2xl:` | 1536px    | Large desktops                    |

Max content width still respects the spec: `max-w-[1280px]` on the content container, regardless of viewport.

### API calls

- All API calls via generated client from `contracts/openapi.yaml` (use `openapi-typescript-codegen` or `hey-api`).
- Never hardcode API paths in components — always use generated client.
- Server Components fetch directly from the FastAPI base URL.
- Client Components use the generated client with `Authorization: Bearer <token>`.

### Auth

- Access token in memory only (never localStorage, never cookies with JS access).
- Refresh token in `HttpOnly` cookie.
- Auth guard via Next.js middleware checking token validity.

### Components

- `components/ui/` — primitive, reusable, no business logic.
- `components/modules/` — feature-specific, may call API, tied to one module.
- No God components. If a file exceeds ~200 lines, split it.

---

## Payment Integration

Both Stripe and Paystack are **always integrated**. This is not a choice between them — both run simultaneously.

- **Stripe + Stripe Connect** — global purchases, contributor payouts outside Nigeria
- **Paystack** — Nigerian operator charges, Nigerian contributor payouts (NGN rails)

Routing rule (applied at transaction creation):

```python
def select_provider(user_country: str, currency: str) -> str:
    if user_country == "NG" or currency == "NGN":
        return "paystack"
    return "stripe"
```

Webhook handlers required for both:

- `POST /v1/webhooks/stripe` — verify `Stripe-Signature` header before processing
- `POST /v1/webhooks/paystack` — verify HMAC SHA-512 before processing

Never process a webhook without signature verification. Drop unverified payloads silently, log for audit.

---

## Security Rules (Non-Negotiable)

- **No secrets in code.** All secrets via AWS Secrets Manager (prod) or `.env` (local, gitignored).
- **S3 artifacts are private.** Access only via presigned URLs generated after license check.
- **KYC before payout.** `users.kyc_status == 'verified'` required for `POST /v1/financials/payouts`.
- **2FA before sensitive ops.** Payout, email change, payment method change require verified TOTP.
- **RBAC enforced at dependency layer.** Never check roles inside service layer — use FastAPI dependencies.
- **Audit artifact downloads.** Every download logged to `artifact_downloads` — no exceptions.
- **Webhook verification.** Stripe webhooks verified via `stripe-signature` header. Paystack via HMAC SHA-512. Reject unverified payloads with `400`.
- **Escrow is sacred.** Never release Escrow funds without explicit Operator approval or Admin override. No automatic release.
- **Pydantic on all inputs.** No raw dict access on any API input. Pydantic schema always.

---

## Infrastructure as Code — Terraform Rules

All AWS infrastructure is defined in `infra/`. **Never create or modify AWS resources manually in the console** — if you do, Terraform will overwrite it on next apply.

### Structure

```
infra/
├── modules/
│   ├── ecs/        # ECS cluster, services (api, worker, beat), task definitions
│   ├── rds/        # RDS PostgreSQL, subnet group, parameter group
│   ├── redis/      # ElastiCache Redis cluster
│   ├── s3/         # S3 buckets (artifacts, avatars, reports) + policies
│   ├── lambda/     # Lambda function (virus scan), S3 trigger
│   ├── alb/        # Application Load Balancer, target groups, listeners
│   └── networking/ # VPC, subnets, security groups, NAT gateway
├── envs/
│   ├── staging/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── backend.tf   # Remote state: S3 bucket + DynamoDB lock table
│   └── production/
│       ├── main.tf
│       ├── variables.tf
│       └── backend.tf
└── main.tf          # Root module — calls child modules
```

### Rules

- Remote state stored in S3 with DynamoDB locking — never use local state.
- State files for staging and production are separate — never share state between environments.
- All secrets passed as variables referencing AWS Secrets Manager ARNs — never hardcoded in `.tf` files.
- Run `terraform plan` and show output to human before any `terraform apply`.
- Destructive changes (resource deletion, replacement) require explicit human approval — never apply blindly.
- Infra changes follow the same PR process as code — reviewed before merge.
- `terraform fmt` and `terraform validate` run in CI on every PR touching `infra/`.

### Environment parity rule

Staging must mirror production architecture exactly — same services, same resource types, smaller instance sizes only. No services that exist in production but not staging.

---

## Test-Driven Development — Mandatory

**No feature ships without tests. No exceptions.**

### The loop (always follow this order)

```
1. Write failing test (red)
2. Write minimum code to pass (green)
3. Refactor, keeping tests green
4. Repeat per behaviour
```

Never write implementation before writing the test that proves it works.

---

### Backend test stack

| Tool                                | Purpose                                                 |
| ----------------------------------- | ------------------------------------------------------- |
| `pytest`                            | Test runner                                             |
| `pytest-asyncio`                    | Async test support                                      |
| `httpx` + `AsyncClient`             | FastAPI endpoint integration tests                      |
| `pytest-factoryboy` / `factory_boy` | Test data factories                                     |
| `pytest-cov`                        | Coverage reporting                                      |
| `freezegun`                         | Time-dependent test control (token expiry, Celery Beat) |

### Backend test structure

```
backend/tests/
├── conftest.py               # DB session, app client, shared fixtures
├── factories/                # factory_boy model factories
├── unit/
│   ├── modules/
│   │   ├── test_auth_service.py
│   │   ├── test_frameworks_service.py
│   │   ├── test_projects_service.py
│   │   ├── test_attestation_service.py
│   │   ├── test_financials_service.py
│   │   └── ...
│   └── workers/
│       ├── test_reputation_tasks.py
│       └── test_notification_tasks.py
└── integration/
    ├── test_auth_endpoints.py
    ├── test_explore_endpoints.py
    ├── test_frameworks_endpoints.py
    ├── test_projects_endpoints.py
    ├── test_attestation_endpoints.py
    ├── test_financials_endpoints.py
    └── test_webhooks.py
```

### What to test per layer

**Unit tests (service layer):**

- Every business rule (BR-\*) has a dedicated test proving it's enforced
- Every state machine transition tested: valid transitions pass, invalid transitions raise
- Escrow release only fires after correct conditions
- Payment routing selects correct provider per country/currency
- Reputation score calculation produces expected output per input combination

**Integration tests (endpoint layer):**

- Every endpoint tested: happy path + at least 2 error cases
- Auth: unauthenticated → 401, wrong role → 403, correct role → 2xx
- File upload: valid file passes, oversized file → 413, wrong type → 415
- Webhook endpoints: valid signature → processed, invalid signature → 400

**Celery tasks:**

- All tasks tested with `task.apply()` (synchronous execution in tests)
- Idempotency: calling a task twice produces same result as calling once

---

### Frontend test stack

| Tool                        | Purpose                        |
| --------------------------- | ------------------------------ |
| `vitest`                    | Unit + component test runner   |
| `@testing-library/react`    | Component tests                |
| `playwright`                | End-to-end tests               |
| `msw` (Mock Service Worker) | API mocking in component tests |

### Frontend test structure

```
frontend/tests/
├── unit/
│   └── components/           # Component unit tests
└── e2e/
    ├── auth.spec.ts           # Registration, login, 2FA
    ├── explore.spec.ts        # Search, filter, framework detail
    ├── framework-publish.spec.ts  # Contributor: create → submit → publish
    ├── purchase.spec.ts       # Operator: purchase → access library
    ├── project.spec.ts        # Create project → proposal → workspace → milestone
    └── attestation.spec.ts    # Request → assign → report → publish
```

### E2E coverage requirements

These critical flows must have E2E tests before going to staging:

| Flow                                                                                                               | Test file                   |
| ------------------------------------------------------------------------------------------------------------------ | --------------------------- |
| Register → verify email → select role                                                                              | `auth.spec.ts`              |
| Contributor: create framework → upload artifact → submit → published                                               | `framework-publish.spec.ts` |
| Operator: search → purchase → download artifact                                                                    | `purchase.spec.ts`          |
| Operator: create project → Contributor bids → accepted → milestone funded → deliverable approved → Escrow released | `project.spec.ts`           |
| Attestation: request → Attestor assigned → report submitted → published                                            | `attestation.spec.ts`       |
| Contributor: request payout (with 2FA)                                                                             | `financials.spec.ts`        |

---

### Coverage thresholds (enforced in CI)

```
Backend:   ≥ 80% line coverage on app/modules/** and app/workers/**
Frontend:  ≥ 70% line coverage on components/**
E2E:       All flows in the table above must pass in staging before release
```

### CI gates — PR cannot merge if

- Any unit test fails
- Any integration test fails
- Coverage drops below threshold
- Any E2E test on the critical flow list fails
- `alembic upgrade head` + `alembic downgrade -1` fails

---

## Build Sequence — Phase by Phase

**Rule:** Backend endpoints always precede frontend for the same feature. Within each phase: implement backend → update `contracts/openapi.yaml` → regenerate frontend client → build frontend UI.

Never start a phase until the previous phase's tests are green.

---

### Phase 0 — Foundation

**Backend**

- Docker Compose local dev stack (Postgres + Redis + API + Celery + Beat)
- FastAPI project scaffold — module structure, `app/core/`, `app/shared/`
- `loguru` logging setup — colored dev, JSON prod, `RequestLoggingMiddleware`
- Alembic init — base migration, `DATABASE_URL` from env
- Health endpoint `GET /health` — DB ping + Redis ping
- `contracts/openapi.yaml` stub with health endpoint

**Frontend**

- Next.js 15 scaffold — App Router, Tailwind, folder structure
- `hey-api` codegen wired to `contracts/openapi.yaml`
- Component structure: `components/ui/`, `components/modules/`
- Environment config (`NEXT_PUBLIC_API_URL`)

---

### Phase 1 — Auth & Identity

**Backend** (FR-AUTH-\*)

- User registration + email verification (Resend)
- Login — JWT (15m) + Redis refresh tokens (30d)
- Token refresh + logout (revoke refresh token)
- TOTP 2FA setup + verification
- RBAC dependency (`require_role`)
- Role assignment endpoint

**Frontend**

- Register / login / email verify pages
- 2FA setup + prompt flow
- Token management: access token in memory, refresh in HttpOnly cookie
- Next.js middleware auth guard
- Role-based redirect on login

---

### Phase 2 — Core Marketplace

**Backend** (FR-EXP-_, FR-FWK-_)

- Explore: search, filters, pagination (GIN full-text index)
- Framework CRUD + versioning
- Artifact upload → S3 → `process_artifact` Celery task (virus scan → extract → PII → fingerprint → rarity → thumbnail → index)
- License model
- Framework publish/review workflow

**Frontend**

- `/explore` SSR page — search, filters, framework cards
- `/explore/[id]` SSR — framework detail, preview, pricing
- Contributor dashboard — create/edit framework, upload artifacts, publish
- Artifact upload UI with processing status polling

---

### Phase 3 — Transactions & Financials

**Backend** (FR-FIN-\*)

- Stripe + Paystack integration, provider routing
- Purchase flow — license creation, Escrow funding
- Stripe Connect + Paystack onboarding for contributors
- Webhook handlers (both providers, signature verified)
- Payout request (KYC check + 2FA gate)
- Contributor earnings + payout history

**Frontend**

- Purchase flow — checkout, payment method, confirmation
- Operator library — purchased frameworks + download (presigned URL)
- Contributor financials — earnings dashboard, payout request with 2FA

---

### Phase 4 — Projects + Attestation

**Backend** (FR-PROJ-_, FR-ATT-_)

- Project posting, proposal submission, acceptance
- Workspace, Milestones, Deliverable submission + approval
- Escrow fund → release flow
- Attestation request, Attestor assignment, report submission + publish

**Frontend**

- Operator: project creation, proposal review, milestone approval
- Contributor: proposal submission, workspace, deliverable upload
- Attestor: assignment dashboard, report submission
- Workspace — real-time activity (WebSocket)

---

### Phase 5 — Developer Platform + Admin + Polish

**Backend** (FR-DEV-_, FR-COL-_, FR-SRCH-_, FR-GDPR-_, FR-ADMIN-\*)

- API key generation + management, Partner API endpoints
- Partner webhook delivery + retry
- Collections, Saved searches + email alerts
- GDPR export + deletion requests
- Admin module — user management, content moderation, analytics
- Reputation scoring (Celery Beat tasks)
- Notification system

**Frontend**

- Developer portal — apply, API keys, usage, commissions
- Settings — profile, security, notifications, GDPR
- Admin UI — user list, content queue, analytics
- Collections + saved search UI

---

### Phase 6 — Pre-Launch

- All E2E tests passing (6 critical flows in `frontend/tests/e2e/`)
- Backend coverage ≥ 80%, frontend coverage ≥ 70%
- CI/CD fully live on Render (all deploy hooks wired)
- Security review: RBAC, Escrow logic, webhook verification, presigned URLs
- Performance: sub-3s page loads on `/explore` and `/explore/[id]`
- Render + Neon + Upstash + Resend all production-configured

---

## Workflow Rules

1. **Read the FRD first.** Every feature maps to an FR. Know which one before writing code.
2. **One feature, one PR.** Don't bundle unrelated changes.
3. **Schema change = migration.** Never alter DB schema without an Alembic migration file.
4. **Test-driven, always.** Write the failing test first. Then implement. Unit test per service method, integration test per endpoint, E2E test per critical user flow. No feature is done until all three levels pass.
5. **Presigned URL for all file delivery.** Never proxy file downloads through FastAPI.
6. **Celery for anything async.** Don't block the request thread for email, reputation recalc, index updates.
7. **OpenAPI first.** When adding an endpoint, update `contracts/openapi.yaml` first. Then implement. Then regenerate frontend client.
8. **Options, not assumptions.** Unclear product behaviour → present options, human decides.
9. **Small diffs.** Surgical edits only. No refactor-while-fixing.
10. **Explain the why.** After each change, state what changed and why — not a summary of the diff.

---

## Module → FR Mapping

When implementing, always look up the relevant FRs and BRs in the FRD first.

| Module          | FR prefix | BR prefix |
| --------------- | --------- | --------- |
| Auth & Identity | FR-AUTH   | BR-AUTH   |
| Explore         | FR-EXP    | BR-EXP    |
| Frameworks      | FR-FWK    | BR-FWK    |
| Projects        | FR-PROJ   | BR-PROJ   |
| Attestation     | FR-ATT    | BR-ATT    |
| Financials      | FR-FIN    | BR-FIN    |
| Settings        | FR-SET    | BR-SET    |

---

## Domain Language (use exactly)

| Term            | Meaning                                                                |
| --------------- | ---------------------------------------------------------------------- |
| **Framework**   | Core marketplace asset — structured, licensable professional knowledge |
| **Artifact**    | File attached to a Framework (PDF, DOCX, XLSX, etc.)                   |
| **License**     | Right to access a Framework purchased by an Operator                   |
| **Attestation** | Formal verification issued by an Attestor                              |
| **Project**     | Custom work request posted by an Operator                              |
| **Proposal**    | Contributor's bid on a Project                                         |
| **Milestone**   | Checkpoint within a Project with associated Escrow                     |
| **Deliverable** | Output submitted by Contributor per Milestone                          |
| **Workspace**   | Collaboration environment for an assigned Project                      |
| **Escrow**      | Held funds pending Deliverable approval                                |
| **Contributor** | Supply-side user — creates and sells Frameworks                        |
| **Operator**    | Demand-side user — purchases and implements Frameworks                 |
| **Attestor**    | Trust-layer user — verifies Frameworks, contributors, credentials      |

Never abbreviate these. Never invent synonyms. Consistency = searchability.

---

## What the Agent Cannot Do

- Deploy to AWS or Vercel directly.
- Change the confirmed tech stack without explicit human approval.
- Make product decisions — scope, pricing, feature priority is human's call.
- Override FRD business rules without explicit instruction.
- Write migrations that drop columns or tables without human review.
- Release or modify Escrow logic without human sign-off.
- Add dependencies without justifying the addition (what it replaces, why it's needed).
