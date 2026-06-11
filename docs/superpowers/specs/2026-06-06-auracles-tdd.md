# Auracles — Technical Design Document (TDD)

**Version:** 1.0  
**Status:** Draft  
**Date:** 2026-06-06  
**Companion:** [Auracles FRD v1.0](./2026-06-06-auracles-frd.md)

---

## Change Log

| Version | Date | Notes |
|---|---|---|
| 1.0 | 2026-06-06 | Initial draft |

---

## 1. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         USERS (Browser)                          │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTPS
                    ┌────────▼────────┐
                    │   CloudFront    │ CDN + WAF
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
     ┌────────▼──────┐             ┌────────▼────────┐
     │  Vercel        │             │  ALB             │
     │  (Next.js)     │             │  (Load Balancer) │
     └───────────────┘             └────────┬─────────┘
                                            │
                                   ┌────────▼────────┐
                                   │  ECS Fargate     │
                                   │  FastAPI         │
                                   │  (API cluster)   │
                                   └────────┬─────────┘
                                            │
                    ┌───────────────────────┼──────────────────┐
                    │                       │                  │
           ┌────────▼──────┐      ┌─────────▼──────┐  ┌───────▼───────┐
           │  RDS           │      │  ElastiCache   │  │  S3            │
           │  PostgreSQL    │      │  Redis         │  │  (artifacts,   │
           └───────────────┘      └────────────────┘  │   avatars)     │
                                            │          └───────┬────────┘
                                   ┌────────▼────────┐        │ S3 event
                                   │  ECS Fargate    │  ┌─────▼─────────┐
                                   │  Celery workers │  │  Lambda        │
                                   │  + Beat         │  │  (virus scan)  │
                                   └─────────────────┘  └───────────────┘

External integrations:
  Stripe    → payment processing (global)
  Paystack  → payment processing (Nigeria)
  AWS SES   → transactional email
```

### Component Responsibilities

| Component | Role |
|---|---|
| CloudFront + WAF | CDN, DDoS protection, SSL termination |
| Vercel | Next.js hosting, edge rendering, preview deployments |
| ALB | Load balancing across ECS API tasks, health checks |
| ECS Fargate (API) | FastAPI application servers, auto-scaling group |
| ECS Fargate (Workers) | Celery workers — async task processing |
| ECS Fargate (Beat) | Celery Beat — scheduled task dispatcher (single task) |
| RDS PostgreSQL | Primary data store, Multi-AZ in production |
| ElastiCache Redis | Celery broker + result backend, session cache, rate limiting |
| S3 | Artifact storage, avatar storage, presigned URL delivery |
| Lambda | S3 event handler — artifact uploaded → virus scan → trigger processing pipeline |
| Stripe | Framework purchases, payouts (Stripe Connect) |
| Paystack | Nigerian operator payments, Nigerian contributor payouts |
| AWS SES | Transactional emails (verification, notifications, receipts) |

---

## 2. Repository Structure

```
auracles/                          # Monorepo root
├── frontend/                      # Next.js application
│   ├── src/
│   │   ├── app/                   # App Router pages
│   │   │   ├── (public)/          # Unauthenticated routes
│   │   │   │   ├── explore/
│   │   │   │   └── frameworks/[id]/
│   │   │   ├── (auth)/            # Auth-gated routes
│   │   │   │   ├── dashboard/
│   │   │   │   ├── frameworks/
│   │   │   │   ├── projects/
│   │   │   │   ├── attestation/
│   │   │   │   ├── financials/
│   │   │   │   └── settings/
│   │   │   └── api/               # Next.js API routes (thin proxy only)
│   │   ├── components/
│   │   │   ├── ui/                # Primitive components
│   │   │   └── modules/           # Module-specific components
│   │   ├── lib/
│   │   │   ├── api-client.ts      # Generated from OpenAPI spec
│   │   │   └── auth.ts
│   │   └── types/                 # Generated from contracts/openapi.yaml
│   ├── public/
│   ├── next.config.ts
│   └── package.json
│
├── backend/                       # FastAPI application
│   ├── app/
│   │   ├── main.py                # FastAPI app init, router registration
│   │   ├── modules/
│   │   │   ├── auth/
│   │   │   │   ├── router.py
│   │   │   │   ├── service.py
│   │   │   │   ├── models.py
│   │   │   │   └── schemas.py
│   │   │   ├── explore/
│   │   │   ├── frameworks/
│   │   │   ├── projects/
│   │   │   ├── attestation/
│   │   │   ├── financials/
│   │   │   ├── settings/
│   │   │   └── developer/         # developer portal (JWT) + partner API (X-API-Key)
│   │   ├── core/
│   │   │   ├── config.py          # Settings (pydantic-settings)
│   │   │   ├── database.py        # SQLAlchemy async engine + session
│   │   │   ├── security.py        # JWT, password hashing, 2FA, API key auth
│   │   │   └── dependencies.py    # FastAPI dependency injectors (JWT + API key)
│   │   ├── shared/
│   │   │   ├── models/            # SQLAlchemy base models
│   │   │   └── schemas/           # Shared Pydantic schemas
│   │   └── workers/
│   │       ├── celery_app.py      # Celery app init
│   │       ├── tasks/
│   │       │   ├── notifications.py
│   │       │   ├── reputation.py
│   │       │   ├── payouts.py
│   │       │   └── scheduled.py   # Celery Beat tasks
│   │       └── beat_schedule.py
│   ├── migrations/                # Alembic migrations
│   ├── tests/
│   ├── Dockerfile
│   ├── docker-compose.yml         # Local dev
│   ├── pyproject.toml
│   └── alembic.ini
│
├── contracts/
│   └── openapi.yaml               # API contract — source of truth
│
├── .github/
│   └── workflows/
│       ├── backend.yml
│       └── frontend.yml
│
└── README.md
```

---

## 3. Database Schema

### Conventions
- All tables use `uuid` primary keys
- All tables have `created_at TIMESTAMPTZ DEFAULT now()` and `updated_at TIMESTAMPTZ`
- Soft deletes via `deleted_at TIMESTAMPTZ NULL`
- Enum types defined at DB level

### Tables

#### `users`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
email           VARCHAR(255) UNIQUE NOT NULL
password_hash   VARCHAR(255)                        -- NULL for OAuth users
display_name    VARCHAR(100) NOT NULL
avatar_url      TEXT
bio             TEXT
location        VARCHAR(100)
website         TEXT
kyc_status      kyc_status_enum NOT NULL DEFAULT 'unverified'
email_verified  BOOLEAN NOT NULL DEFAULT false
totp_secret     VARCHAR(255)                        -- encrypted
totp_enabled    BOOLEAN NOT NULL DEFAULT false
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
deactivated_at  TIMESTAMPTZ
```

#### `user_roles`
```sql
id          UUID PRIMARY KEY DEFAULT gen_random_uuid()
user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE
role        role_enum NOT NULL                     -- contributor|operator|attestor|admin
approved_at TIMESTAMPTZ                            -- NULL until admin approves (attestor)
approved_by UUID REFERENCES users(id)
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
UNIQUE(user_id, role)
```

#### `oauth_accounts`
```sql
id          UUID PRIMARY KEY DEFAULT gen_random_uuid()
user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE
provider    VARCHAR(50) NOT NULL                   -- google|linkedin
provider_id VARCHAR(255) NOT NULL
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
UNIQUE(provider, provider_id)
```

#### `frameworks`
```sql
id                  UUID PRIMARY KEY DEFAULT gen_random_uuid()
contributor_id      UUID NOT NULL REFERENCES users(id)
title               VARCHAR(255) NOT NULL
description         TEXT NOT NULL
version             VARCHAR(20) NOT NULL DEFAULT '1.0.0'
status              framework_status_enum NOT NULL DEFAULT 'draft'
category            VARCHAR(100) NOT NULL
sector              VARCHAR(100)
industry            VARCHAR(100)
function            VARCHAR(100)
tags                TEXT[]
jurisdiction        VARCHAR(100)
complexity          SMALLINT                        -- 1-5
org_size            org_size_enum
lifecycle_stage     VARCHAR(100)
price               NUMERIC(12,2) NOT NULL
currency            CHAR(3) NOT NULL DEFAULT 'USD'
license_types       license_type_enum[] NOT NULL
commercial_rights   TEXT
usage_restrictions  TEXT
preview_artifact_id UUID                            -- FK set after artifact insert
rejection_reason    TEXT
published_at        TIMESTAMPTZ
created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
deleted_at          TIMESTAMPTZ
```

#### `framework_versions`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
framework_id    UUID NOT NULL REFERENCES frameworks(id)
version         VARCHAR(20) NOT NULL
change_log      TEXT
published_at    TIMESTAMPTZ NOT NULL DEFAULT now()
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `artifacts`
```sql
id                  UUID PRIMARY KEY DEFAULT gen_random_uuid()
framework_id        UUID NOT NULL REFERENCES frameworks(id) ON DELETE CASCADE
name                VARCHAR(255) NOT NULL
file_key            TEXT NOT NULL                      -- S3 object key (original)
clean_file_key      TEXT                               -- S3 key of PII-redacted version
file_size           BIGINT NOT NULL                    -- bytes
mime_type           VARCHAR(100) NOT NULL
scan_status         scan_status_enum NOT NULL DEFAULT 'pending'
processing_status   processing_status_enum NOT NULL DEFAULT 'pending'
pii_detected        BOOLEAN NOT NULL DEFAULT false
pii_review_needed   BOOLEAN NOT NULL DEFAULT false     -- low-confidence PII detections
rarity_score        NUMERIC(5,4)                       -- 0.0 (duplicate) to 1.0 (unique)
nearest_match_id    UUID REFERENCES artifacts(id)      -- most similar artifact found
created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `artifact_fingerprints`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
artifact_id     UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE
framework_version VARCHAR(20) NOT NULL
embedding       vector(1536)                           -- pgvector: semantic fingerprint
text_hash       VARCHAR(64) NOT NULL                   -- SHA-256 of anonymised text
char_count      INTEGER
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `artifact_pii_audit`
```sql
id                  UUID PRIMARY KEY DEFAULT gen_random_uuid()
artifact_id         UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE
pii_types_found     TEXT[] NOT NULL DEFAULT '{}'       -- ['NAME','ADDRESS','EMAIL','PHONE',...]
auto_redacted       BOOLEAN NOT NULL DEFAULT false
flagged_for_review  BOOLEAN NOT NULL DEFAULT false
reviewed_by         UUID REFERENCES users(id)
reviewed_at         TIMESTAMPTZ
processed_at        TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `licenses`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
framework_id    UUID NOT NULL REFERENCES frameworks(id)
operator_id     UUID NOT NULL REFERENCES users(id)
transaction_id  UUID NOT NULL REFERENCES transactions(id)
type            license_type_enum NOT NULL
status          license_status_enum NOT NULL DEFAULT 'active'
version_at_grant VARCHAR(20) NOT NULL
granted_at      TIMESTAMPTZ NOT NULL DEFAULT now()
expires_at      TIMESTAMPTZ
UNIQUE(framework_id, operator_id)
```

#### `artifact_downloads`
```sql
id          UUID PRIMARY KEY DEFAULT gen_random_uuid()
license_id  UUID NOT NULL REFERENCES licenses(id)
artifact_id UUID NOT NULL REFERENCES artifacts(id)
user_id     UUID NOT NULL REFERENCES users(id)
ip_address  INET
downloaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `transactions`
```sql
id                  UUID PRIMARY KEY DEFAULT gen_random_uuid()
payer_id            UUID NOT NULL REFERENCES users(id)
payee_id            UUID REFERENCES users(id)       -- NULL for platform revenue
amount              NUMERIC(12,2) NOT NULL
currency            CHAR(3) NOT NULL DEFAULT 'USD'
platform_commission NUMERIC(12,2) NOT NULL DEFAULT 0
net_amount          NUMERIC(12,2) NOT NULL
type                transaction_type_enum NOT NULL  -- purchase|milestone|attestation_fee|payout
status              transaction_status_enum NOT NULL DEFAULT 'pending'
provider            payment_provider_enum           -- stripe|paystack
provider_ref        VARCHAR(255)                    -- Stripe/Paystack transaction ID
ref_id              UUID                            -- license_id|milestone_id|attestation_id
ref_type            VARCHAR(50)
created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `escrows`
```sql
id                  UUID PRIMARY KEY DEFAULT gen_random_uuid()
ref_id              UUID NOT NULL
ref_type            VARCHAR(50) NOT NULL            -- project_milestone|attestation
amount              NUMERIC(12,2) NOT NULL
currency            CHAR(3) NOT NULL DEFAULT 'USD'
status              escrow_status_enum NOT NULL DEFAULT 'held'
release_conditions  JSONB
held_at             TIMESTAMPTZ NOT NULL DEFAULT now()
released_at         TIMESTAMPTZ
released_by         UUID REFERENCES users(id)
```

#### `payouts`
```sql
id                  UUID PRIMARY KEY DEFAULT gen_random_uuid()
contributor_id      UUID NOT NULL REFERENCES users(id)
payout_account_id   UUID NOT NULL REFERENCES payout_accounts(id)
amount              NUMERIC(12,2) NOT NULL
currency            CHAR(3) NOT NULL DEFAULT 'USD'
commission_deducted NUMERIC(12,2) NOT NULL
net_amount          NUMERIC(12,2) NOT NULL
status              payout_status_enum NOT NULL DEFAULT 'pending'
provider_ref        VARCHAR(255)
initiated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
completed_at        TIMESTAMPTZ
```

#### `payout_accounts`
```sql
id                      UUID PRIMARY KEY DEFAULT gen_random_uuid()
user_id                 UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE
type                    VARCHAR(50) NOT NULL           -- bank_account|stripe_connect|paystack
provider                payment_provider_enum NOT NULL
account_details         JSONB NOT NULL                 -- encrypted at application layer
is_default              BOOLEAN NOT NULL DEFAULT false
verified_at             TIMESTAMPTZ
created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `projects`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
operator_id     UUID NOT NULL REFERENCES users(id)
title           VARCHAR(255) NOT NULL
description     TEXT NOT NULL
category        VARCHAR(100)
budget_min      NUMERIC(12,2)
budget_max      NUMERIC(12,2)
currency        CHAR(3) NOT NULL DEFAULT 'USD'
deadline        DATE
status          project_status_enum NOT NULL DEFAULT 'open'
expires_at      TIMESTAMPTZ                            -- auto-close trigger
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
deleted_at      TIMESTAMPTZ
```

#### `proposals`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
project_id      UUID NOT NULL REFERENCES projects(id)
contributor_id  UUID NOT NULL REFERENCES users(id)
scope           TEXT NOT NULL
budget          NUMERIC(12,2) NOT NULL
currency        CHAR(3) NOT NULL DEFAULT 'USD'
timeline_days   INTEGER NOT NULL
deliverables    JSONB NOT NULL
status          proposal_status_enum NOT NULL DEFAULT 'pending'
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `milestones`
```sql
id          UUID PRIMARY KEY DEFAULT gen_random_uuid()
project_id  UUID NOT NULL REFERENCES projects(id)
escrow_id   UUID REFERENCES escrows(id)
name        VARCHAR(255) NOT NULL
description TEXT
budget      NUMERIC(12,2) NOT NULL
currency    CHAR(3) NOT NULL DEFAULT 'USD'
due_date    DATE
status      milestone_status_enum NOT NULL DEFAULT 'pending'
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `deliverables`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
milestone_id    UUID NOT NULL REFERENCES milestones(id)
contributor_id  UUID NOT NULL REFERENCES users(id)
name            VARCHAR(255) NOT NULL
description     TEXT
file_keys       TEXT[]                             -- S3 object keys
status          deliverable_status_enum NOT NULL DEFAULT 'submitted'
revision_note   TEXT
submitted_at    TIMESTAMPTZ NOT NULL DEFAULT now()
approved_at     TIMESTAMPTZ
```

#### `workspace_messages`
```sql
id          UUID PRIMARY KEY DEFAULT gen_random_uuid()
project_id  UUID NOT NULL REFERENCES projects(id)
sender_id   UUID NOT NULL REFERENCES users(id)
body        TEXT NOT NULL
file_keys   TEXT[]
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `attestations`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
target_type     VARCHAR(50) NOT NULL               -- framework|contributor|operator|credential
target_id       UUID NOT NULL
attestor_id     UUID REFERENCES users(id)
requestor_id    UUID NOT NULL REFERENCES users(id)
escrow_id       UUID REFERENCES escrows(id)
status          attestation_status_enum NOT NULL DEFAULT 'requested'
outcome         attestation_outcome_enum           -- approved|conditional|rejected
findings        TEXT
report_key      TEXT                               -- S3 key for PDF report
sla_deadline    TIMESTAMPTZ
issued_at       TIMESTAMPTZ
expires_at      TIMESTAMPTZ
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `credentials`
```sql
id               UUID PRIMARY KEY DEFAULT gen_random_uuid()
user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE
type             VARCHAR(100) NOT NULL
name             VARCHAR(255) NOT NULL
issuer           VARCHAR(255)
issued_at        DATE
expiry_at        DATE
verification_url TEXT
verified         BOOLEAN NOT NULL DEFAULT false
created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `reviews`
```sql
id          UUID PRIMARY KEY DEFAULT gen_random_uuid()
reviewer_id UUID NOT NULL REFERENCES users(id)
target_type VARCHAR(50) NOT NULL                   -- framework|contributor
target_id   UUID NOT NULL
score       SMALLINT NOT NULL CHECK (score BETWEEN 1 AND 5)
body        TEXT
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
UNIQUE(reviewer_id, target_type, target_id)
```

#### `reputation_scores`
```sql
id                  UUID PRIMARY KEY DEFAULT gen_random_uuid()
subject_id          UUID NOT NULL
subject_type        VARCHAR(50) NOT NULL            -- framework|contributor|operator
score               NUMERIC(5,2) NOT NULL DEFAULT 0
components          JSONB NOT NULL DEFAULT '{}'
last_calculated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
UNIQUE(subject_id, subject_type)
```

#### `disputes`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
project_id      UUID NOT NULL REFERENCES projects(id)
milestone_id    UUID REFERENCES milestones(id)
raised_by       UUID NOT NULL REFERENCES users(id)
reason          TEXT NOT NULL
status          dispute_status_enum NOT NULL DEFAULT 'open'
resolution      TEXT
admin_id        UUID REFERENCES users(id)
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
resolved_at     TIMESTAMPTZ
```

#### `watchlists`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE
framework_id    UUID NOT NULL REFERENCES frameworks(id) ON DELETE CASCADE
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
UNIQUE(user_id, framework_id)
```

#### `platform_config`
```sql
key         VARCHAR(100) PRIMARY KEY
value       TEXT NOT NULL
updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
updated_by  UUID REFERENCES users(id)
-- Rows: commission_rate, min_payout_threshold, max_active_projects, etc.
```

#### `notifications`
```sql
id          UUID PRIMARY KEY DEFAULT gen_random_uuid()
user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE
type        VARCHAR(100) NOT NULL
payload     JSONB NOT NULL DEFAULT '{}'
read_at     TIMESTAMPTZ
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
```

### Enum Types

```sql
CREATE TYPE kyc_status_enum AS ENUM ('unverified', 'pending', 'verified', 'rejected');
CREATE TYPE role_enum AS ENUM ('contributor', 'operator', 'attestor', 'admin');
CREATE TYPE framework_status_enum AS ENUM ('draft', 'submitted', 'under_review', 'published', 'unpublished', 'rejected');
CREATE TYPE license_type_enum AS ENUM ('personal', 'team', 'organizational', 'enterprise', 'white_label');
CREATE TYPE license_status_enum AS ENUM ('active', 'expired', 'revoked');
CREATE TYPE org_size_enum AS ENUM ('startup', 'small_business', 'sme', 'mid_market', 'enterprise');
CREATE TYPE transaction_type_enum AS ENUM ('purchase', 'milestone', 'attestation_fee', 'payout', 'refund');
CREATE TYPE transaction_status_enum AS ENUM ('pending', 'completed', 'failed', 'refunded');
CREATE TYPE payment_provider_enum AS ENUM ('stripe', 'paystack');
CREATE TYPE escrow_status_enum AS ENUM ('held', 'released', 'refunded');
CREATE TYPE payout_status_enum AS ENUM ('pending', 'processing', 'completed', 'failed');
CREATE TYPE project_status_enum AS ENUM ('open', 'assigned', 'in_progress', 'delivered', 'closed', 'disputed');
CREATE TYPE proposal_status_enum AS ENUM ('pending', 'accepted', 'rejected', 'withdrawn');
CREATE TYPE milestone_status_enum AS ENUM ('pending', 'funded', 'in_progress', 'submitted', 'approved', 'revision_requested', 'disputed');
CREATE TYPE deliverable_status_enum AS ENUM ('submitted', 'approved', 'revision_requested');
CREATE TYPE attestation_status_enum AS ENUM ('requested', 'assigned', 'under_review', 'issued', 'declined', 'disputed');
CREATE TYPE attestation_outcome_enum AS ENUM ('approved', 'conditional', 'rejected');
CREATE TYPE dispute_status_enum AS ENUM ('open', 'under_review', 'resolved');
CREATE TYPE scan_status_enum AS ENUM ('pending', 'clean', 'infected');
CREATE TYPE processing_status_enum AS ENUM ('pending', 'processing', 'processed', 'failed', 'flagged_pii', 'flagged_rarity');
```

#### `developer_applications`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
user_id         UUID NOT NULL REFERENCES users(id)
company_name    VARCHAR(255) NOT NULL
website         TEXT NOT NULL
use_case        TEXT NOT NULL
status          VARCHAR(20) NOT NULL DEFAULT 'pending'   -- pending|approved|rejected
reviewed_by     UUID REFERENCES users(id)
feedback        TEXT
reviewed_at     TIMESTAMPTZ
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `developer_accounts`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
user_id         UUID NOT NULL REFERENCES users(id) UNIQUE
application_id  UUID NOT NULL REFERENCES developer_applications(id)
company_name    VARCHAR(255) NOT NULL
commission_tier SMALLINT NOT NULL DEFAULT 1              -- 1|2|3
status          VARCHAR(20) NOT NULL DEFAULT 'active'   -- active|suspended
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `api_keys`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
developer_id    UUID NOT NULL REFERENCES developer_accounts(id)
name            VARCHAR(100) NOT NULL
key_prefix      VARCHAR(12) NOT NULL                    -- ak_live_XXXX — display only
key_hash        VARCHAR(64) NOT NULL UNIQUE             -- SHA-256 of full raw key
scopes          TEXT[] NOT NULL                         -- catalog:read|preview:read|attestations:read|purchase:write
rate_limit_rpm  INTEGER NOT NULL DEFAULT 60
webhook_url     TEXT
webhook_secret  VARCHAR(64)                             -- HMAC signing secret for this key's webhooks
expires_at      TIMESTAMPTZ
last_used_at    TIMESTAMPTZ
status          VARCHAR(20) NOT NULL DEFAULT 'active'   -- active|revoked
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `api_key_usage`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
api_key_id      UUID NOT NULL REFERENCES api_keys(id)
endpoint        VARCHAR(255) NOT NULL
method          VARCHAR(10) NOT NULL
status_code     SMALLINT NOT NULL
response_ms     INTEGER
ip_address      INET
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `partner_commissions`
```sql
id                  UUID PRIMARY KEY DEFAULT gen_random_uuid()
developer_id        UUID NOT NULL REFERENCES developer_accounts(id)
api_key_id          UUID NOT NULL REFERENCES api_keys(id)
transaction_id      UUID NOT NULL REFERENCES transactions(id)
framework_id        UUID NOT NULL REFERENCES frameworks(id)
sale_amount         NUMERIC(12,2) NOT NULL
commission_rate     NUMERIC(5,4) NOT NULL               -- e.g. 0.05 = 5%
commission_amount   NUMERIC(12,2) NOT NULL
currency            CHAR(3) NOT NULL DEFAULT 'USD'
tier_at_sale        SMALLINT NOT NULL
status              VARCHAR(20) NOT NULL DEFAULT 'pending' -- pending|cleared|paid
cleared_at          TIMESTAMPTZ
created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `partner_payouts`
```sql
id                  UUID PRIMARY KEY DEFAULT gen_random_uuid()
developer_id        UUID NOT NULL REFERENCES developer_accounts(id)
payout_account_id   UUID NOT NULL REFERENCES payout_accounts(id)
amount              NUMERIC(12,2) NOT NULL
currency            CHAR(3) NOT NULL DEFAULT 'USD'
status              payout_status_enum NOT NULL DEFAULT 'pending'
provider_ref        VARCHAR(255)
initiated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
completed_at        TIMESTAMPTZ
```

#### `framework_collections`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
contributor_id  UUID NOT NULL REFERENCES users(id)
title           VARCHAR(255) NOT NULL
description     TEXT NOT NULL
price           NUMERIC(12,2) NOT NULL
currency        CHAR(3) NOT NULL DEFAULT 'USD'
status          framework_status_enum NOT NULL DEFAULT 'draft'
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `collection_frameworks`
```sql
collection_id   UUID NOT NULL REFERENCES framework_collections(id) ON DELETE CASCADE
framework_id    UUID NOT NULL REFERENCES frameworks(id)
PRIMARY KEY (collection_id, framework_id)
```

#### `saved_searches`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE
name            VARCHAR(100) NOT NULL
filters         JSONB NOT NULL DEFAULT '{}'
alert_enabled   BOOLEAN NOT NULL DEFAULT false
last_alerted_at TIMESTAMPTZ
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
```

#### `gdpr_requests`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
user_id         UUID NOT NULL REFERENCES users(id)
type            VARCHAR(20) NOT NULL                    -- export|deletion
status          VARCHAR(20) NOT NULL DEFAULT 'pending'  -- pending|processing|completed
download_key    TEXT                                    -- S3 key of export archive
expires_at      TIMESTAMPTZ                             -- download link expiry
created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
completed_at    TIMESTAMPTZ
```

#### `consent_logs`
```sql
id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
user_id         UUID NOT NULL REFERENCES users(id)
document_type   VARCHAR(50) NOT NULL                    -- terms_of_service|privacy_policy
document_version VARCHAR(20) NOT NULL
ip_address      INET
accepted_at     TIMESTAMPTZ NOT NULL DEFAULT now()
```

### Key Indexes

```sql
-- Framework search and filtering
CREATE INDEX idx_frameworks_status ON frameworks(status);
CREATE INDEX idx_frameworks_contributor ON frameworks(contributor_id);
CREATE INDEX idx_frameworks_category ON frameworks(category);
CREATE INDEX idx_frameworks_sector ON frameworks(sector);
CREATE INDEX idx_frameworks_price ON frameworks(price);
CREATE INDEX idx_frameworks_search ON frameworks USING GIN(to_tsvector('english', title || ' ' || description));
CREATE INDEX idx_frameworks_tags ON frameworks USING GIN(tags);

-- License lookup
CREATE INDEX idx_licenses_operator ON licenses(operator_id);
CREATE INDEX idx_licenses_framework ON licenses(framework_id);

-- Notifications
CREATE INDEX idx_notifications_user_unread ON notifications(user_id) WHERE read_at IS NULL;

-- Projects
CREATE INDEX idx_projects_status ON projects(status);
CREATE INDEX idx_projects_operator ON projects(operator_id);

-- Attestations
CREATE INDEX idx_attestations_target ON attestations(target_type, target_id);

-- API key lookup (hot path — every partner request)
CREATE INDEX idx_api_keys_hash ON api_keys(key_hash) WHERE status = 'active';
CREATE INDEX idx_api_key_usage_key_time ON api_key_usage(api_key_id, created_at DESC);

-- Partner commissions
CREATE INDEX idx_partner_commissions_dev ON partner_commissions(developer_id, status);
CREATE INDEX idx_partner_commissions_tx ON partner_commissions(transaction_id);

-- Saved searches with alerts
CREATE INDEX idx_saved_searches_alerts ON saved_searches(user_id) WHERE alert_enabled = true;
```

---

## 4. API Design

### Base URL
```
Production:  https://api.auracles.com/v1
Staging:     https://api-staging.auracles.com/v1
Local:       http://localhost:8000/v1
```

### Authentication
All protected endpoints require:
```
Authorization: Bearer <access_token>
```

### Versioning
URL path versioning (`/v1/`). Breaking changes increment the version.

### Router Structure (FastAPI)

```python
# main.py
app.include_router(auth_router,        prefix="/v1/auth",        tags=["auth"])
app.include_router(explore_router,     prefix="/v1/explore",     tags=["explore"])
app.include_router(frameworks_router,  prefix="/v1/frameworks",  tags=["frameworks"])
app.include_router(projects_router,    prefix="/v1/projects",    tags=["projects"])
app.include_router(attestation_router, prefix="/v1/attestation", tags=["attestation"])
app.include_router(financials_router,  prefix="/v1/financials",  tags=["financials"])
app.include_router(settings_router,    prefix="/v1/settings",    tags=["settings"])
app.include_router(admin_router,       prefix="/v1/admin",       tags=["admin"])
app.include_router(webhooks_router,    prefix="/v1/webhooks",    tags=["webhooks"])
app.include_router(developer_router,   prefix="/v1/developer",   tags=["developer"])  # JWT auth — account mgmt
app.include_router(partner_router,     prefix="/v1/partner",     tags=["partner"])    # X-API-Key auth
```

### Endpoint Overview

#### Auth (`/v1/auth`)
```
POST   /register
POST   /login
POST   /logout
POST   /refresh
POST   /verify-email
POST   /resend-verification
POST   /forgot-password
POST   /reset-password
POST   /oauth/{provider}
POST   /2fa/setup
POST   /2fa/verify
POST   /2fa/disable
```

#### Explore (`/v1/explore`)
```
GET    /frameworks                  # paginated catalog, search, filter
GET    /frameworks/{id}             # framework detail
GET    /frameworks/{id}/related     # related frameworks
POST   /watchlist/{framework_id}    # add to watchlist
DELETE /watchlist/{framework_id}
GET    /watchlist
```

#### Frameworks (`/v1/frameworks`)
```
POST   /                            # create draft
GET    /                            # contributor: list own frameworks
GET    /{id}
PATCH  /{id}
DELETE /{id}
POST   /{id}/submit                 # submit for review
POST   /{id}/unpublish
POST   /{id}/version                # create new version
GET    /{id}/artifacts
POST   /{id}/artifacts              # upload artifact
DELETE /{id}/artifacts/{artifact_id}
GET    /{id}/artifacts/{artifact_id}/download   # presigned URL
GET    /{id}/analytics
POST   /{id}/reviews                # operator: submit review
GET    /{id}/reviews
```

#### Projects (`/v1/projects`)
```
POST   /                            # operator: create project
GET    /                            # contributor: browse open | operator: own
GET    /{id}
PATCH  /{id}
POST   /{id}/proposals              # contributor: submit proposal
GET    /{id}/proposals              # operator: list proposals
POST   /{id}/proposals/{prop_id}/accept
POST   /{id}/milestones             # contributor: create milestone
GET    /{id}/milestones
POST   /{id}/milestones/{m_id}/fund # operator: fund escrow
POST   /{id}/milestones/{m_id}/deliverables
POST   /{id}/milestones/{m_id}/deliverables/{d_id}/approve
POST   /{id}/milestones/{m_id}/deliverables/{d_id}/request-revision
POST   /{id}/disputes               # raise dispute
GET    /{id}/messages               # workspace messages
POST   /{id}/messages
WS     /{id}/ws                     # WebSocket for real-time messaging
```

#### Attestation (`/v1/attestation`)
```
POST   /apply                       # attestor: apply for role
GET    /assignments                 # attestor: list assignments
POST   /assignments/{id}/accept
POST   /assignments/{id}/decline
POST   /assignments/{id}/submit     # submit report
POST   /requests                    # contributor/operator: request attestation
GET    /requests                    # list own requests
GET    /requests/{id}
POST   /requests/{id}/dispute
```

#### Financials (`/v1/financials`)
```
GET    /earnings                    # contributor: earnings dashboard
GET    /payouts                     # contributor: payout history
POST   /payouts                     # request payout
GET    /purchases                   # operator: purchase history
GET    /purchases/{id}/invoice      # download invoice PDF
POST   /payment-methods             # operator: add payment method
GET    /payment-methods
DELETE /payment-methods/{id}
POST   /payout-accounts             # contributor: add payout account
GET    /payout-accounts
DELETE /payout-accounts/{id}
```

#### Settings (`/v1/settings`)
```
GET    /profile
PATCH  /profile
POST   /profile/avatar              # upload avatar
GET    /organization
PATCH  /organization
GET    /credentials
POST   /credentials
DELETE /credentials/{id}
GET    /kyc
POST   /kyc/submit
GET    /sessions
DELETE /sessions/{id}
GET    /notifications/preferences
PATCH  /notifications/preferences
POST   /account/deactivate
```

#### Webhooks (`/v1/webhooks`)
```
POST   /stripe                      # Stripe webhook handler
POST   /paystack                    # Paystack webhook handler
```

#### Admin (`/v1/admin`) — admin role required
```
GET    /users
GET    /users/{id}
PATCH  /users/{id}/roles
PATCH  /users/{id}/kyc
POST   /users/{id}/suspend
GET    /frameworks/pending          # review queue
POST   /frameworks/{id}/approve
POST   /frameworks/{id}/reject
GET    /frameworks/flagged          # rarity + PII flags
GET    /attestors/applications
POST   /attestors/{id}/approve
POST   /attestors/{id}/reject
GET    /disputes
POST   /disputes/{id}/resolve
PATCH  /config                      # commission rate, feature flags, tier thresholds
GET    /analytics                   # platform GMV, user growth, attestation activity
GET    /developer/applications
POST   /developer/applications/{id}/approve
POST   /developer/applications/{id}/reject
PATCH  /developer/accounts/{id}/tier
```

#### Developer (`/v1/developer`) — JWT auth, approved developer account required
```
POST   /apply                       # submit developer application
GET    /account                     # account details + tier + progress
GET    /api-keys
POST   /api-keys                    # generate key — returns raw key ONCE
DELETE /api-keys/{id}               # revoke key
GET    /usage                       # API key usage analytics
GET    /commissions                 # commission history + status
GET    /earnings                    # cleared + pending totals
POST   /payouts                     # request commission payout (requires 2FA)
GET    /payouts                     # payout history
GET    /webhooks                    # registered webhook URLs
POST   /webhooks                    # register webhook endpoint
DELETE /webhooks/{id}
```

#### Partner (`/v1/partner`) — X-API-Key auth only
```
GET    /frameworks                  # catalog:read — paginated, filterable
GET    /frameworks/{id}             # catalog:read — framework detail
GET    /frameworks/{id}/preview     # preview:read — preview artifact presigned URL
GET    /frameworks/{id}/attestations # attestations:read
POST   /frameworks/{id}/purchase    # purchase:write — initiate, returns payment intent
POST   /frameworks/{id}/purchase/confirm  # purchase:write — confirm, creates license
GET    /collections                 # catalog:read — bundle listings
GET    /collections/{id}            # catalog:read — collection detail
POST   /collections/{id}/purchase   # purchase:write
```

---

## 5. Module Structure — FastAPI

Each module follows this internal structure:

```
modules/{module}/
├── router.py       # FastAPI APIRouter, endpoint handlers (thin)
├── service.py      # Business logic, orchestration
├── models.py       # SQLAlchemy ORM models
├── schemas.py      # Pydantic request/response schemas
└── dependencies.py # Module-specific FastAPI dependencies (optional)
```

**Module layer responsibilities:**

| Layer | Does | Does not |
|---|---|---|
| `router.py` | Parse request, call service, return response | Business logic |
| `service.py` | Enforce business rules, call models, trigger tasks | HTTP concerns |
| `models.py` | DB queries, relationships | Business rules |
| `schemas.py` | Validation, serialization | DB queries |

---

## 6. Module Structure — Next.js

```
frontend/src/app/
├── (public)/
│   ├── page.tsx               # Landing page
│   ├── explore/
│   │   ├── page.tsx           # Catalog (SSR)
│   │   └── [id]/
│   │       └── page.tsx       # Framework detail (SSR)
│   └── login/
│       └── page.tsx
├── (auth)/
│   ├── layout.tsx             # Auth guard
│   ├── dashboard/page.tsx
│   ├── frameworks/
│   │   ├── page.tsx           # Contributor: my frameworks
│   │   ├── new/page.tsx
│   │   └── [id]/edit/page.tsx
│   ├── library/page.tsx       # Operator: licensed frameworks
│   ├── projects/
│   │   ├── page.tsx
│   │   ├── new/page.tsx
│   │   └── [id]/
│   │       └── page.tsx       # Workspace
│   ├── attestation/page.tsx
│   ├── financials/page.tsx
│   └── settings/
│       └── page.tsx
```

Server Components for data-heavy pages (Explore, Framework detail).  
Client Components for interactive pages (Workspace, forms, real-time).

---

## 7. Infrastructure Design

### ECS Services

| Service | Task CPU | Task Memory | Min tasks | Max tasks | Scale trigger |
|---|---|---|---|---|---|
| api | 1 vCPU | 2 GB | 2 | 20 | CPU > 70% |
| celery-worker | 1 vCPU | 2 GB | 1 | 10 | SQS queue depth |
| celery-beat | 256 CPU | 512 MB | 1 | 1 | — (singleton) |

All services use the same Docker image (`backend/Dockerfile`), different `CMD`:
```
api:           uvicorn app.main:app --host 0.0.0.0 --port 8000
celery-worker: celery -A app.workers.celery_app worker --loglevel=info
celery-beat:   celery -A app.workers.celery_app beat --loglevel=info
```

### RDS PostgreSQL
- Instance: `db.t4g.medium` (dev) → `db.r8g.large` (prod)
- Multi-AZ: enabled in production
- Automated backups: 7-day retention
- Encryption at rest: enabled

### ElastiCache Redis
- Mode: Cluster disabled (single-node for MVP, enable cluster for scale)
- Instance: `cache.t4g.small`
- Used for: Celery broker, Celery result backend, session storage, rate limiting

### S3 Buckets
```
auracles-artifacts-{env}    # Framework artifacts — private, presigned URL access
auracles-avatars-{env}      # User avatars — public read
auracles-reports-{env}      # Attestation reports — private, presigned URL access
```

### Lambda (S3 Trigger)
- Trigger: `s3:ObjectCreated:*` on `auracles-artifacts-{env}`
- Runtime: Python 3.13
- Action: Scan artifact → update `artifacts.scan_status` → notify API via internal endpoint

### ALB
- HTTPS listener (port 443) → forward to ECS API target group
- Health check: `GET /v1/health` → 200

### CloudFront
- Origins: ALB (API), S3 (avatars)
- Behaviours: `/api/*` → ALB, `/avatars/*` → S3

---

## 8. Security Design

### JWT Flow
```
1. POST /v1/auth/login → returns { access_token, refresh_token }
2. access_token: JWT, 15-minute expiry, signed HS256
3. refresh_token: opaque token, stored in Redis, 30-day expiry
4. POST /v1/auth/refresh → validates refresh token in Redis → issues new access_token
5. POST /v1/auth/logout → deletes refresh token from Redis
```

JWT payload:
```json
{
  "sub": "<user_id>",
  "roles": ["contributor", "operator"],
  "email": "user@example.com",
  "exp": 1234567890,
  "iat": 1234567890,
  "jti": "<unique_token_id>"
}
```

### 2FA (TOTP)
```
1. POST /v1/auth/2fa/setup → generate TOTP secret → return QR code URI
2. POST /v1/auth/2fa/verify → verify TOTP code → enable 2FA on account
3. On login with 2FA enabled → access_token withheld until TOTP verified
4. Sensitive endpoints check totp_verified claim in token
```

### RBAC
FastAPI dependencies enforce role checks:
```python
# core/dependencies.py
async def require_role(role: str):
    def checker(current_user: User = Depends(get_current_user)):
        if role not in current_user.roles:
            raise HTTPException(403, "Insufficient permissions")
    return checker

# Usage in router
@router.post("/frameworks/{id}/approve")
async def approve_framework(
    _: None = Depends(require_role("admin"))
):
```

### API Key Authentication

```python
# core/security.py
import secrets, hashlib

def generate_api_key(env: str = "live") -> tuple[str, str]:
    """Returns (raw_key, key_hash). raw_key shown ONCE, key_hash stored in DB."""
    raw = f"ak_{env}_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    prefix = raw[:12]           # stored as key_prefix for display
    return raw, key_hash

# core/dependencies.py
async def get_partner_account(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> DeveloperAccount:
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    api_key = await db.scalar(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.status == "active")
    )
    if not api_key:
        raise HTTPException(401, "Invalid or revoked API key")
    if api_key.expires_at and api_key.expires_at < datetime.utcnow():
        raise HTTPException(401, "API key expired")
    # Log usage asynchronously — never block the request
    background_tasks.add_task(log_api_usage, api_key.id, request)
    await db.execute(
        update(ApiKey).where(ApiKey.id == api_key.id).values(last_used_at=datetime.utcnow())
    )
    return api_key.developer_account

def require_scope(scope: str):
    """Dependency factory — checks API key has required scope."""
    async def checker(account: DeveloperAccount = Depends(get_partner_account)):
        if scope not in account.current_key.scopes:
            raise HTTPException(403, f"This action requires the `{scope}` scope.")
        return account
    return checker
```

Rate limiting enforced at Redis layer per `api_key_id`:
```python
async def check_rate_limit(api_key_id: UUID, limit_rpm: int, redis: Redis):
    key = f"ratelimit:{api_key_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)
    if count > limit_rpm:
        raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": "60"})
```

### Webhook Signing (Partner Webhooks)

```python
import hmac, hashlib, json

def sign_webhook_payload(payload: dict, secret: str) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

# Partner verifies:
# X-Auracles-Signature: sha256=<hex>
# if not hmac.compare_digest(expected, received): reject
```

### Artifact Access Control
- Artifacts stored in private S3 bucket
- Access via presigned URLs (15-minute expiry)
- Presigned URL only generated if `license.status == active` for the requesting user
- All artifact downloads logged to `artifact_downloads`

### KYC
- Document upload → stored encrypted in S3
- Manual review by Admin (MVP) or Stripe Identity / Smile Identity (future)
- `users.kyc_status` updated by Admin or webhook

### Secrets Management
- All secrets in AWS Secrets Manager
- ECS task role grants read access to specific secrets
- Local dev: `.env` file (gitignored)

---

## 9. Integration Design

### Stripe
- **Framework purchases:** Stripe Payment Intents → webhook confirms → create License + Transaction
- **Contributor payouts:** Stripe Connect (Express accounts) → `POST /v1/financials/payouts` triggers Transfer
- **Escrow:** Stripe funds held in platform account; released via Transfer on milestone approval
- Webhook events handled at `POST /v1/webhooks/stripe`:
  - `payment_intent.succeeded`
  - `payment_intent.payment_failed`
  - `transfer.created`
  - `payout.paid`
  - `payout.failed`

### Paystack
- Used for Nigerian operators (charge) and Nigerian contributors (payout)
- **Charges:** Paystack Initialize → redirect → webhook confirms → create License + Transaction
- **Payouts:** Paystack Transfer API → contributor linked bank account
- Webhook events at `POST /v1/webhooks/paystack`:
  - `charge.success`
  - `transfer.success`
  - `transfer.failed`

### Currency routing logic:
```python
def select_provider(user_country: str, currency: str) -> str:
    if user_country == "NG" or currency == "NGN":
        return "paystack"
    return "stripe"
```

### AWS SES
- Transactional emails via SES + templated emails
- Celery task: `tasks/notifications.send_email`
- Templates: email verification, purchase receipt, framework approved/rejected, attestation assigned, payout processed, dispute raised

### Celery Tasks

| Task | Module | Trigger |
|---|---|---|
| `send_email` | notifications | Any event requiring email |
| `recalculate_reputation` | reputation | New review, attestation, purchase, rarity score |
| `process_payout` | payouts | Payout request approved |
| `update_search_index` | explore | Framework published/updated |
| `notify_version_update` | frameworks | New framework version published |
| `check_dispute_escalation` | projects | Celery Beat — every hour |
| `close_expired_projects` | projects | Celery Beat — daily |
| `check_attestation_sla` | attestation | Celery Beat — every hour |
| `check_license_expiry` | financials | Celery Beat — daily |
| `process_artifact` | artifacts | Lambda calls API after clean scan → chains subtasks below |
| `extract_text` | artifacts | Chained from `process_artifact` |
| `detect_redact_pii` | artifacts | Chained after `extract_text` |
| `generate_fingerprint` | artifacts | Chained after `detect_redact_pii` |
| `compute_rarity_score` | artifacts | Chained after `generate_fingerprint` |
| `generate_thumbnail` | artifacts | Chained after `compute_rarity_score` |
| `index_artifact_content` | artifacts | Chained after `generate_thumbnail` |
| `flag_low_rarity` | artifacts | Triggered if rarity_score < threshold → notify admin + contributor |
| `clear_partner_commissions` | developer | Celery Beat — daily: mark commissions as `cleared` after 48h refund window |
| `upgrade_partner_tiers` | developer | Celery Beat — monthly: recalculate tier based on last 30 days' attributed sales |
| `deliver_partner_webhook` | developer | Triggered on purchase.confirmed, commission.cleared, framework.updated |
| `retry_failed_webhooks` | developer | Celery Beat — hourly: retry failed webhook deliveries (max 5 attempts, exponential backoff) |
| `dispatch_saved_search_alerts` | explore | Celery Beat — daily: check new published frameworks against saved searches with alerts enabled |
| `process_gdpr_export` | settings | Triggered by GDPR data export request → compile JSON → upload to S3 → notify user |
| `process_gdpr_deletion` | settings | Triggered by GDPR deletion request → hard-delete PII, anonymise transactions |

### S3 Presigned URLs
```python
# Generate upload URL (contributor uploads artifact)
url = s3.generate_presigned_url(
    "put_object",
    Params={"Bucket": ARTIFACTS_BUCKET, "Key": file_key, "ContentType": mime_type},
    ExpiresIn=3600
)

# Generate download URL (operator downloads artifact)
url = s3.generate_presigned_url(
    "get_object",
    Params={"Bucket": ARTIFACTS_BUCKET, "Key": file_key},
    ExpiresIn=900  # 15 minutes
)
```

### WebSocket (Workspace Messaging)
```
Client connects: WS /v1/projects/{id}/ws?token={access_token}
Server validates token → joins project room
Message broadcast: Redis pub/sub channel per project_id
FastAPI + asyncio handles concurrent connections
```

---

## 10. Dev Environment

### Prerequisites
- Docker + Docker Compose
- Node.js 20+
- Python 3.13+
- pnpm

### Local Stack (docker-compose.yml)
```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: auracles
      POSTGRES_USER: auracles
      POSTGRES_PASSWORD: secret
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  localstack:
    image: localstack/localstack
    environment:
      SERVICES: s3,ses
    ports: ["4566:4566"]

  api:
    build: ./backend
    command: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    volumes: ["./backend:/app"]
    ports: ["8000:8000"]
    depends_on: [postgres, redis]
    env_file: ./backend/.env

  worker:
    build: ./backend
    command: celery -A app.workers.celery_app worker --loglevel=info
    volumes: ["./backend:/app"]
    depends_on: [redis]
    env_file: ./backend/.env

  beat:
    build: ./backend
    command: celery -A app.workers.celery_app beat --loglevel=info
    volumes: ["./backend:/app"]
    depends_on: [redis]
    env_file: ./backend/.env
```

### Backend `.env`
```
DATABASE_URL=postgresql+asyncpg://auracles:secret@localhost:5432/auracles
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=<generate: openssl rand -hex 32>
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
AWS_DEFAULT_REGION=us-east-1
AWS_ENDPOINT_URL=http://localhost:4566
S3_ARTIFACTS_BUCKET=auracles-artifacts-dev
S3_AVATARS_BUCKET=auracles-avatars-dev
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
PAYSTACK_SECRET_KEY=sk_test_...
SES_FROM_ADDRESS=noreply@auracles.com
PLATFORM_COMMISSION_RATE=0.15
```

### Frontend `.env.local`
```
NEXT_PUBLIC_API_URL=http://localhost:8000/v1
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_...
```

### Setup Commands
```bash
# Clone and setup
git clone git@github.com:auracles/auracles.git
cd auracles

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# Frontend
cd ../frontend
pnpm install
cp .env.local.example .env.local

# Start local stack
docker compose up -d postgres redis localstack

# Run migrations
cd backend
alembic upgrade head

# Start services
uvicorn app.main:app --reload     # API
celery -A app.workers.celery_app worker  # Worker

# Start frontend
cd ../frontend && pnpm dev
```

---

## 11. Deployment Pipeline

### Backend CI/CD (GitHub Actions)
```
Push to main →
  1. Run tests (pytest)
  2. Run linting (ruff, mypy)
  3. Build Docker image
  4. Push to ECR
  5. Run Alembic migrations (ECS task)
  6. Update ECS service (rolling deploy)
     → api service
     → celery-worker service
     → celery-beat service
```

### Frontend CI/CD
```
Push to main →
  Vercel auto-deploys (zero config)
  Preview URL on every PR branch
```

### Environments

| Env | Backend | Frontend | DB |
|---|---|---|---|
| Local | Docker Compose | `pnpm dev` | Local Postgres |
| Staging | ECS Fargate | Vercel Preview | RDS (staging) |
| Production | ECS Fargate | Vercel Production | RDS Multi-AZ |

### Alembic Migration Strategy
- Migrations run as a one-off ECS task before service update
- All migrations must be backwards-compatible (no destructive changes in same deploy as code change)
- Rollback: `alembic downgrade -1`

---

## 12. Artifact Processing Pipeline

Every artifact uploaded to S3 passes through a sequential processing pipeline. Each stage is an idempotent Celery task. Failures at any stage set `processing_status = 'failed'` and notify the contributor.

### Pipeline Flow

```
UPLOAD → S3 (auracles-artifacts-{env})
    │
    ▼  S3 event trigger
[1] Lambda: Virus Scan (ClamAV or VirusTotal API)
    │  infected → delete from S3, mark artifact infected, notify contributor, STOP
    │  clean    → POST /internal/artifacts/{id}/process (triggers Celery chain)
    ▼
[2] Celery: extract_text
    │  PDF     → pdfplumber
    │  DOCX    → python-docx
    │  XLSX    → openpyxl
    │  PPTX    → python-pptx
    │  ZIP     → extract contents, process each file, combine text
    │  Unsupported format → mark failed, notify contributor
    ▼
[3] Celery: detect_redact_pii
    │  Tool: Microsoft Presidio (open source) + AWS Comprehend fallback
    │  Detects: PERSON, LOCATION, EMAIL, PHONE, NRP (ID numbers), CREDIT_CARD, IBAN, etc.
    │  High confidence (≥ 0.85) → auto-redact in extracted text
    │  Low confidence (< 0.85)  → flag token, set pii_review_needed = true
    │  All detections → written to artifact_pii_audit
    │  Redacted text → used for all downstream steps (original file untouched in S3)
    ▼
[4] Celery: generate_fingerprint
    │  Input: anonymised extracted text
    │  Embedding model: sentence-transformers (all-MiniLM-L6-v2) or Claude Embeddings API
    │  Output: vector(1536) stored in artifact_fingerprints
    │  Also stores: SHA-256 text hash, char_count
    ▼
[5] Celery: compute_internal_rarity
    │  Query: MinHash-Jaccard against published Artifact signatures
    │  internal_rarity = 1.0 - max_jaccard (legacy stored score)
    │  nearest_match_id = highest-Jaccard Artifact id
    │  Stored on artifact: internal_rarity, nearest_match_id
    │  Stored in artifact_rarity_audit: internal_jaccard, nearest_match_id
    │
    │  Copy-risk policy:
    │    jaccard ≥ 0.90 → HARD BLOCK (near-duplicate / likely copy)
    │    0.70 ≤ jaccard < 0.90 → NOTICE (similar topic, non-blocking)
    │    jaccard < 0.70 → PASS
    ▼
[6] Celery: generate_thumbnail
    │  PDF → pdf2image → first page → JPEG → S3 (auracles-avatars bucket)
    │  DOCX/PPTX → LibreOffice headless → PDF → thumbnail
    │  thumbnail_key stored on artifact
    ▼
[7] Celery: index_artifact_content
    │  Anonymised text → Postgres GIN FTS index (frameworks table search vector)
    │  Triggers update_search_index task
    ▼
[8] Mark artifact: processing_status = 'processed'
    Trigger: recalculate_reputation (rarity_score feeds reputation component)
    Notify contributor: artifact ready / any flags to review
```

### Internal Similarity Policy

| Jaccard Range | Label | Action |
|---|---|---|
| 0.90 – 1.00 | Near-duplicate | Pipeline hard-blocks until admin override |
| 0.70 – 0.89 | Similar | Non-blocking similarity notice; publish remains available after other gates pass |
| 0.00 – 0.69 | Clear | Pipeline continues normally |

The gate targets copy-risk, not marketplace quality. Review scores and
Attestation carry quality context; Jaccard only distinguishes near-duplicate
overlap from same-topic similarity.

### Fingerprint Versioning

- Each framework version gets its own fingerprint row in `artifact_fingerprints`
- New version compared against all other frameworks' fingerprints (not its own previous versions)
- Own previous versions excluded from rarity comparison to avoid penalising legitimate updates

### PII Review Flow (low-confidence detections)

```
pii_review_needed = true
    → Admin notified of flagged artifact
    → Admin reviews flagged tokens in admin panel
    → Admin: approve (redact flagged tokens) or dismiss (false positive)
    → reviewed_by + reviewed_at written to artifact_pii_audit
    → Pipeline continues after review
```

### Docker Image Additions (Celery worker)

```dockerfile
# Added to backend/Dockerfile for worker image
RUN apt-get install -y \
    libreoffice-headless \
    poppler-utils \
    tesseract-ocr

RUN pip install \
    pdfplumber \
    python-docx \
    openpyxl \
    python-pptx \
    pdf2image \
    Pillow \
    presidio-analyzer \
    presidio-anonymizer \
    sentence-transformers \
    pgvector
```

### Infrastructure Additions

- **pgvector** — enabled as RDS PostgreSQL extension: `CREATE EXTENSION IF NOT EXISTS vector;`
- **IVFFlat index** on `artifact_fingerprints.embedding` for fast approximate nearest-neighbour search at scale:
  ```sql
  CREATE INDEX ON artifact_fingerprints USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
  ```
- **S3 internal API endpoint** — Lambda calls `POST /internal/artifacts/{id}/process` via VPC-internal ALB (not public internet). Protected by shared secret header, not JWT.

---

## 13. Open Technical Decisions

| # | Decision | Options | Status |
|---|---|---|---|
| OTD-001 | KYC provider | Manual (admin) → Stripe Identity → Smile Identity | Manual for MVP |
| OTD-002 | Search engine | Postgres FTS → Typesense → OpenSearch | Postgres FTS for MVP |
| OTD-003 | WebSocket scaling | Single ECS task → Redis pub/sub → managed WS service | Redis pub/sub |
| OTD-004 | Email templates | SES raw → React Email → Postmark | To decide |
| OTD-005 | Virus scanning | ClamAV (Lambda) → SaaS (VirusTotal API) | To decide |
| OTD-006 | Multi-currency | Stripe handles conversion → manual FX rates | Stripe handles |

---

*End of Auracles TDD v1.0*
