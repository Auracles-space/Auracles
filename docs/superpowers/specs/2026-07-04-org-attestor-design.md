# Organizations as Attestors (Sub-project 2) — Design

**Date:** 2026-07-04
**Status:** Approved for planning
**Owner:** William (architect) / agent (senior engineer)
**Depends on:** Organizations Core (`2026-07-03-organizations-core-design.md`, shipped)
**Redefines:** attestation modules 1–6d individual-attestor structures

## Context

Organizations Core shipped the org entity, membership, roles, teams, invitations, and the
`org_capabilities` status table. This sub-project makes the `attestor` capability real:
an organization applies, is vetted, and — once active — receives attestation offers,
staffs them with member reviewers, earns the attestor share, and carries the public
attestation identity. The individual-attestor pipeline (applications, profiles,
self-service role selection) is retired in the same cut — clean cutover, no production
attestor data exists (Org Core locked decision 8).

The attestation flow frontend is blocked on this spec and follows it as a separate plan.

## Locked decisions

All ten resolved 2026-07-03/04:

| # | Question | Decision |
|---|----------|----------|
| 1 | Offer acceptance + staffing | Org admin/owner accepts the offer and picks the reviewing member in the same step. Member must have a signed NDA and headroom under the per-member concurrency cap. Reassignment allowed until review starts. |
| 2 | `attestations.attestor_id` schema strategy | Replace: `attestor_org_id` FK organizations + `reviewing_member_id` FK org_members. `attestor_id` dropped. All services re-pointed. No dual model. |
| 3 | Matching profile | Org-level profile (`org_attestor_profiles`): specializations, jurisdictions, sectors, framework categories at org level. AMM matches orgs. Per-member specializations deferred (YAGNI). |
| 4 | Workload caps | Concurrency cap counted per reviewing member (`DEFAULT_CONCURRENCY_CAP = 5` retained), not per org. Org takes as much as it can staff. |
| 5 | Badge / provenance identity | Public badge and provenance show org identity only (name, slug, verification level). Reviewing member recorded internally — admin and dispute views only. Audit-firm convention: report signed by firm. |
| 6 | Org payout account | Extend `payout_accounts` with nullable `org_id`, XOR constraint with `user_id`. Reuses Stripe/Paystack onboarding and payout plumbing. |
| 7 | Earnings | 90% attestor share unchanged, credited to the org. Member compensation is the org's internal business, off-platform. Invoices issued in the org's legal name. |
| 8 | NDA timing | Personal NDA prompted at invite-accept for orgs with attestor capability pending/active; members who predate the capability sign in-app before first assignment. Unsigned member = unassignable, not removed. |
| 9 | Trial attestation | Org nominates a member to perform the trial. Passing validates the org (its process), not the member. |
| 10 | Individual attestor retirement | `attestor` removed from registration/role selection; individual application endpoints removed from router and contract; `attestor_applications` + `attestor_profiles` dropped by migration (drop reviewed explicitly by architect at migration PR per CLAUDE.md). |

## Scope

**In (backend):** org attestor application + admin review pipeline, gate tracking (KYB,
credentials, COI/confidentiality, payout account, tax document, trial), capability
activation, org matching profile, offer → accept-and-staff flow, reviewer workspace
access rules, settlement to org, org payout requests, org invoicing identity, badge and
provenance re-pointing, directory of attestor orgs, member NDAs, derived-role wiring,
individual-pipeline retirement, GDPR touchpoints, audit, contract regeneration.

**Out:** all frontend (separate plan after this spec; bundles attestation UI + org UI
integration + the two known drift files), per-member specializations, member
compensation mechanics, org-to-org subcontracting, contributor/operator capabilities
(sub-projects 3/4).

## Data model

New tables live in `app/modules/organizations/` (application, profile, NDA are org
concerns); attestation tables stay in `app/modules/attestation/`.

```
org_attestor_applications                    -- replaces attestor_applications
  id UUID PK
  org_id UUID FK organizations ON DELETE CASCADE
  status enum('draft','submitted','needs_info','approved','rejected')
  -- KYB
  legal_name text
  registration_number text
  incorporation_doc_keys text[]              -- S3 keys, private bucket
  kyb_verified_at timestamptz NULL
  kyb_verified_by UUID FK users NULL
  -- matching inputs
  specializations text[], jurisdictions text[], sectors text[], framework_categories text[]
  credentials_summary text
  sample_work jsonb
  professional_references text
  -- undertakings (signed by org owner, TOTP-gated)
  coi_declarations jsonb DEFAULT '[]'
  coi_signed_at timestamptz NULL
  coi_expires_at timestamptz NULL
  confidentiality_signed_at timestamptz NULL
  -- money + tax
  payout_account_id UUID FK payout_accounts NULL
  tax_document_type / tax_document_key NULL
  -- trial
  trial_attestation_id UUID FK attestations NULL
  trial_member_id UUID FK org_members NULL   -- nominated reviewer
  -- review
  admin_feedback text NULL
  reviewed_by UUID FK users NULL
  reviewed_at timestamptz NULL
  created_at / updated_at
  UNIQUE(org_id) WHERE status IN ('draft','submitted','needs_info')   -- one live application

org_attestor_profiles                        -- replaces attestor_profiles
  id UUID PK
  org_id UUID FK organizations UNIQUE ON DELETE CASCADE
  specializations text[], jurisdictions text[], sectors text[], framework_categories text[]
  active bool DEFAULT true                   -- org can pause intake
  verification_level int DEFAULT 1
  approved_at timestamptz
  coi_declarations jsonb, coi_signed_at, coi_expires_at, coi_reminder_sent_at
  confidentiality_signed_at
  late_submission_count int DEFAULT 0
  suspension_review_at timestamptz NULL
  certified_attestor_at timestamptz NULL     -- org-level certification, same recompute rules
  created_at / updated_at
  GIN indexes on specializations, jurisdictions (mirror old profile indexes)

org_member_ndas
  id UUID PK
  member_id UUID FK org_members UNIQUE ON DELETE CASCADE
  nda_version text                           -- matches existing confidentiality doc versioning
  signed_at timestamptz
  created_at
```

Re-pointed columns (single migration wave, backwards-compatible ordering within the
sub-project; drops in a final reviewed migration):

```
attestations
  - attestor_id UUID FK users            → DROP
  + attestor_org_id UUID FK organizations NULL
  + reviewing_member_id UUID FK org_members NULL   -- internal; set at accept
  indexes re-created on (attestor_org_id, status)

attestation_offers
  - attestor_id → + org_id UUID FK organizations
  UNIQUE(attestation_id, org_id)

attestor_trials        → re-keyed: user_id → org_id + nominated member_id
attestation_ratings    → rated party = org
attestor_warnings      → warned party = org
attestation_badges     → attestor identity fields = org (name/slug snapshot at issuance)

payout_accounts
  + org_id UUID FK organizations NULL
  + CHECK ((user_id IS NULL) != (org_id IS NULL))   -- XOR
  user_id made nullable

transactions
  + payee_org_id UUID FK organizations NULL
  + CHECK (payee_id IS NULL OR payee_org_id IS NULL)  -- at most one beneficiary kind
```

## Capability activation flow

Gates in order; each gate independently tracked on the application row; admin sees a
gate checklist. All must pass before activation (Org Core locked decision 4).

1. **Apply** — org owner or admin creates/edits a `draft` application, submits.
   Submission requires all KYB + matching + credentials fields present (Pydantic).
2. **KYB verification** — platform admin reviews legal identity + incorporation docs,
   stamps `kyb_verified_at/by`. `needs_info` bounces back to the org with feedback.
3. **Org credentials** — admin reviews credentials_summary / sample work / references
   as part of the same review queue (no separate table; feedback via `admin_feedback`).
4. **COI + confidentiality undertaking** — org **owner** signs (TOTP-gated, sensitive
   op). Stamps `coi_signed_at`, `confidentiality_signed_at`, sets `coi_expires_at`
   (existing COI renewal machinery re-pointed to org profile after approval).
5. **Payout account** — org onboards a payout account (Stripe Connect / Paystack via
   existing provider routing on org `country`); application links `payout_account_id`.
6. **Tax document** — upload, same types as individual flow.
7. **Trial attestation** — admin triggers trial; org nominates `trial_member_id`
   (NDA-signed member); trial runs through the existing trial machinery re-keyed to
   org; admin grades.
8. **Activation** — admin approves: application `approved`, `org_attestor_profiles`
   row created from application, `org_capabilities.attestor = active`
   (`activated_at` stamped), `sync_derived_roles` fires for **all current members**
   (grants user-level `attestor` role). Rejection: `rejected` + feedback; org may
   reapply (new application row).

Capability suspension/revocation (platform admin): sets `org_capabilities.attestor`
status; suspension pauses matching intake (profile treated inactive) and fires
`sync_derived_roles`; in-flight attestations continue under existing
dispute/reassignment rules.

## Matching + assignment

- AMM matches on `org_attestor_profiles` (same scoring inputs: specializations,
  jurisdictions, sectors, categories, COI screening now against org declarations).
- COI screening additionally excludes orgs where the **requestor is a member** of the
  candidate org, and orgs whose attestation target framework is owned by one of its
  members (self-review guard).
- Offer rows target `org_id`. Offer notifications go to org owner + admins.
- **Accept-and-staff:** org owner/admin accepts, supplying `reviewing_member_id` in the
  same call. Validation: member belongs to org, NDA signed, active concurrent
  attestations for that member `< DEFAULT_CONCURRENCY_CAP (5)`. Decline and expiry per
  existing offer mechanics.
- **Reassignment:** org owner/admin may change `reviewing_member_id` until
  `review_started_at` is set. After review starts, reassignment only via platform
  admin (dispute/incident path). Audited both ways.
- **Workspace access:** reviewing member does the work (rubric scores, annotations,
  clarifications, document uploads, report submission). Org owner/admins get
  read access + reassignment. Requestor-facing surfaces unchanged.
- Member leaving org: unassigned from unstarted attestations (org must restaff);
  if review started, platform admin resolution required before removal completes
  (blocked removal, 409, mirrors existing obligations pattern).

## Settlement, payouts, invoicing

- Escrow release (`release_service` → `escrow_service.release`) credits the 90%
  attestor share to the org: settlement transaction carries `payee_org_id`.
- Org earnings ledger = transactions where `payee_org_id = org`. Exposed via org
  financials read endpoints (owner/admin).
- **Org payout request:** org owner or admin, TOTP-gated (requester's own TOTP),
  requires: org payout account exists, application `approved` (KYB stands in for the
  individual KYC gate). Existing payout task pipeline reused with org beneficiary.
- Invoices (6d) issued in the org's `legal_name` with org address/tax data from the
  application; annual invoicing beat re-pointed to org identities.
- PII rules: payout account details and tax docs never in list endpoints; org
  financials visible to org owner/admin only.

## Badge, provenance, directory, public surfaces

- Badge issuance (`badge_service.publish_badge`) snapshots org identity: org name,
  slug, verification level at issuance. Public badge JSON + provenance endpoints show
  org only.
- `reviewing_member_id` appears only in: platform-admin provenance view, dispute
  records, audit log. Never in public/requestor responses.
- Directory (`directory_service`) lists attestor **orgs**: profile fields, completed
  attestation count, certification mark, member count (no member identities).
- Explore / framework detail attestation surfaces show org attestation identity.
- Profiles module: user public profiles stop advertising individual attestor status;
  a member's org affiliations are not exposed unless already public in Org Core.

## NDA mechanics

- Versioned NDA text (same document-versioning scheme as the existing attestor
  confidentiality undertaking).
- Prompted at invite-accept when the org's attestor capability is `pending` or
  `active` — invitation accept response signals NDA requirement; signing endpoint
  records `org_member_ndas` row. Accept without NDA still joins the org (member is
  simply unassignable).
- Existing members when capability turns active: in-app notification; sign before
  first assignment.
- NDA version bump (config): members with older versions become unassignable until
  re-signed; existing assignments continue.
- Signature rows audited; NDA text content-addressed by version, never mutated.

## Individual attestor retirement (clean cutover)

- `attestor` removed from registration role choices and `POST /v1/auth/roles`
  (validation rejects it); user-level `attestor` role becomes derived-only via
  `sync_derived_roles` (already shipped inert in Org Core).
- Individual application endpoints (`application_service` router paths) removed from
  router + OpenAPI contract. Credential endpoints (`credentials` table) survive —
  user-owned credentials remain a general feature.
- `attestor_applications`, `attestor_profiles` dropped (`attestor_trials` is re-keyed
  to org, not dropped).
  **Drop migration is a separate, final migration in the sequence and requires
  explicit architect review before merge** (CLAUDE.md rule). All earlier migrations
  additive/re-pointing.
- Existing `require_role("attestor")` guards keep working (derived role). Org-scoped
  actions additionally guard via `require_org_role` / `require_org_capability`.
- GDPR: user export includes NDA signatures + reviewing-member assignment history;
  org-attestor application data exports under the org (owner-requested), not the user.
  Account deletion: reviewing member with in-flight (started) attestation blocks
  deletion until resolved (existing obligations pattern).

## API surface (contract-first; paths indicative)

```
Org attestor application (org owner/admin unless noted):
POST   /v1/orgs/{org_id}/attestor-application            create draft / reapply
GET    /v1/orgs/{org_id}/attestor-application            current application + gate checklist
PATCH  /v1/orgs/{org_id}/attestor-application            edit draft / answer needs_info
POST   /v1/orgs/{org_id}/attestor-application/submit
POST   /v1/orgs/{org_id}/attestor-application/sign-undertakings   owner + TOTP
POST   /v1/orgs/{org_id}/attestor-application/tax-document        upload ticket
POST   /v1/orgs/{org_id}/attestor-application/nominate-trial-member

Admin review:
GET    /v1/admin/org-attestor-applications               queue (status filter)
POST   /v1/admin/org-attestor-applications/{id}/verify-kyb
POST   /v1/admin/org-attestor-applications/{id}/needs-info
POST   /v1/admin/org-attestor-applications/{id}/start-trial
POST   /v1/admin/org-attestor-applications/{id}/approve
POST   /v1/admin/org-attestor-applications/{id}/reject
POST   /v1/admin/orgs/{org_id}/attestor-capability/suspend|reinstate|revoke

Offers + staffing (org owner/admin):
GET    /v1/orgs/{org_id}/attestation-offers
POST   /v1/orgs/{org_id}/attestation-offers/{offer_id}/accept    body: reviewing_member_id
POST   /v1/orgs/{org_id}/attestation-offers/{offer_id}/decline
POST   /v1/orgs/{org_id}/attestations/{attestation_id}/reassign  body: reviewing_member_id

Org attestation work views:
GET    /v1/orgs/{org_id}/attestations                    org queue (owner/admin; member sees own)
                                                          -- reviewing member keeps using existing
                                                          -- attestor workspace endpoints (guards
                                                          -- re-pointed to reviewing_member)

NDA:
GET    /v1/orgs/{org_id}/nda                             current version + my signature status
POST   /v1/orgs/{org_id}/nda/sign

Financials (org owner/admin):
GET    /v1/orgs/{org_id}/financials/earnings
POST   /v1/orgs/{org_id}/financials/payout-accounts      onboard (existing provider routing)
POST   /v1/orgs/{org_id}/financials/payouts              TOTP-gated
GET    /v1/orgs/{org_id}/financials/invoices

Public:
GET    /v1/attestors                                     directory → attestor orgs (re-shaped)
GET    /v1/attestors/{org_slug}                          org attestor public profile
(badge + provenance endpoints keep paths; payload identity becomes org)
```

Individual application paths removed from the contract in the same regeneration.

## Security

- RBAC at dependency layer only: `require_org_role("admin")` for application/offers/
  financials; `require_org_role("owner")` for undertakings signing; platform admin
  deps for review queue. Workspace guards check `reviewing_member_id` match.
- Sensitive ops TOTP-gated: undertakings signing, org payout request.
- KYB documents + tax docs: private S3, presigned upload/download, admin-only read,
  never in list payloads.
- Reviewing member identity is confidential: excluded from every public/requestor
  schema; leakage here is a review blocker.
- Offer/accept/reassign/NDA-sign/capability-status-change/payout all audited
  (`module="attestation"` / `"organizations"` per existing action taxonomy).
- Rate limiting: application submission and NDA signing per-org limits (Redis limiter,
  auth-endpoint layer).
- Escrow rules unchanged — release paths untouched except beneficiary; no new release
  triggers.

## Error handling

Project standards apply. Notable cases: accept with unsigned-NDA member → 422
`nda_required`; accept over member cap → 422 `member_at_capacity`; reassign after
review start → 409; second live application → 409; suspended org / suspended
capability → 403 `org_suspended` / `capability_suspended`; payout without approved
application → 403; member removal with started review → 409 blocked.

## Testing

- **Unit:** gate checklist state machine (each gate independently, activation requires
  all), accept-and-staff validations (NDA, cap, membership), reassignment window, COI
  screen excludes requestor-member and member-owned-target orgs, settlement credits
  `payee_org_id`, payout gate (KYB not KYC), derived-role sync on activation +
  suspension, NDA version bump unassignability, badge snapshots org identity,
  reviewing member absent from public schemas (schema-level test), retirement:
  `attestor` role rejected at self-selection.
- **Integration:** every new endpoint happy + 401 + 403 (wrong org role) + suspended;
  full lifecycle test: apply → gates → trial → activate → offer → accept-and-staff →
  workspace → report → release → org earnings → payout request; directory shape;
  GDPR export includes NDA + assignments; removed individual endpoints return 404.
- **Migrations:** upgrade head + downgrade -1 green per migration; drop migration
  isolated and last.
- Coverage ≥80% on touched modules. Whole-repo ruff + mypy. Contract regenerated and
  validated; frontend client regen deferred to the frontend plan.

## Risks

- **Breadth:** re-point touches 16 attestation files + explore, gdpr, invoicing,
  profiles, reputation, 3 workers. Mitigation: decision 2 (hard replace) keeps one
  model; plan slices by service; full-suite gate every task.
- **Financials beneficiary change:** transactions/payout XOR is money-path schema;
  all changes inside transactions, escrow semantics untouched; explicit review on
  those tasks.
- **Table drops:** final reviewed migration only.
- **Reviewer-identity leakage:** enforced by schema tests, checked in review.
