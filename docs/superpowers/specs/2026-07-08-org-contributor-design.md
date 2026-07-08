# Organizations as Contributors (Sub-project 3) — Design

**Date:** 2026-07-08
**Status:** Approved for planning
**Owner:** William (architect) / agent (senior engineer)
**Depends on:** Organizations Core (`2026-07-03-organizations-core-design.md`, shipped),
Org-as-Attestor (`2026-07-04-org-attestor-design.md`, shipped)
**Extends:** frameworks, projects, financials, organizations modules — additively

## Context

Organizations Core shipped the org entity, membership, roles, teams, invitations, and the
`org_capabilities` status table. Org-as-Attestor (sub-project 2) made the `attestor`
capability real and, in doing so, built org beneficiaries end-to-end in the money path
(`transactions.payee_org_id`, `payout_accounts.org_id`, `payouts.org_id`), the org payout
request + invoicing plumbing, and the derived-role sync scaffold.

This sub-project makes the `contributor` capability real: an organization activates
contributing, its members author Frameworks under the org identity, owners/admins publish
and sell them, the org bids on and delivers Projects, and the org earns and gets paid out
under its legal identity.

**Key divergence from attestor: this is additive, not a replacement.** Individual
contributors are NOT retired — they remain fully supported and self-service. Every
supply-side ownable entity therefore becomes ownable by *either* a user or an
organization, via the XOR pattern already shipped on `payout_accounts` / `transactions` /
`payouts`. There is no clean cutover and no drop migration in this cut.

The contributor-side frontend is out of scope and follows this spec as a separate plan.

## Locked decisions

Resolved 2026-07-08 with the architect:

| # | Question | Decision |
|---|----------|----------|
| 1 | Capability activation | **Lightweight self-activation.** Org owner/admin flips the `contributor` capability on directly — no application, no admin approval, no trial. Authoring/listing opens immediately. Safety comes from three gates that are NOT at activation: (a) payout requires a Connect/Paystack payout account whose provider enforces business KYB/AML + a tax document on file; (b) the per-framework content pipeline (virus/PII/rarity/similarity) gates every publish; (c) platform admin can suspend/revoke the capability. This is the marketplace-standard "fast to list, verified to cash out" model. |
| 2 | Who authors vs publishes | **Any member authors drafts** (create/edit/upload artifacts/submit-to-pipeline). **Owner/admin publishes** and manages all live/money state (publish, unpublish, new version, pricing). `authoring_member_id` recorded on every framework for internal provenance. |
| 3 | Public contributor identity | **Org only.** Explore + framework detail show org name/slug/verification/reputation. Authoring member hidden (internal/admin/audit only), matching the attestor reviewing-member convention. |
| 4 | Projects scope | **Included.** Org bids on and delivers Projects (proposals + member-staffed workspace + org-beneficiary milestone escrow), not only Framework publishing. Proposal submission = owner/admin (money+delivery commitment). Delivery = a single staffed `delivering_member_id`, extensible to multi-member later (YAGNI now). |
| 5 | Invoicing / legal identity | **Shared org legal identity.** Legal name / registration / address / tax document live once on the org (`org_legal_profiles`, 1:1), read by invoicing for all capabilities. Attestor invoicing re-points to it (backward-compatible; attestor application keeps its KYB *verification* stamps). |

## Scope

**In (backend):** `contributor` capability self-activation + suspension/revocation; generalized
derived-role sync (attestor + contributor); XOR framework ownership (user or org);
org-scoped framework CRUD/artifact/submit/publish routes with author-vs-admin RBAC; XOR +
staffing on proposals/deliverables; org project bid → accept → member-staffed delivery →
milestone escrow to org; org contributor profile + org-level reputation aggregate;
contributor org directory; shared `org_legal_profiles` + invoicing re-point; org earnings +
payout (KYB-at-payout gate) reusing attestor financials endpoints; provenance
confidentiality; `user_roles` derived-vs-self marker; GDPR touchpoints; audit; contract
regeneration.

**Out:** all frontend (separate plan); org-as-Operator (sub-project 4); per-member
contributor specializations; multi-member project workspaces; migrating an individual's
existing frameworks to an org; org-to-org subcontracting.

## Architecture & ownership model

Additive. Individual contributors stay. Ownership becomes user-XOR-org on each supply-side
entity, reusing the shipped financial XOR pattern.

```
frameworks
  contributor_id        made nullable            (was NOT NULL FK users)
  + contributor_org_id   UUID FK organizations NULL
  + authoring_member_id  UUID FK org_members  NULL ON DELETE SET NULL  -- internal provenance
  CHECK ((contributor_id IS NULL) != (contributor_org_id IS NULL))     -- XOR seller
  index on (contributor_org_id, status)

proposals
  contributor_id         made nullable
  + contributor_org_id     UUID FK organizations NULL
  + delivering_member_id   UUID FK org_members  NULL ON DELETE SET NULL  -- staffed at submit
  CHECK ((contributor_id IS NULL) != (contributor_org_id IS NULL))
  partial-unique (project_id, contributor_org_id) WHERE status IN ('pending','accepted')

deliverables
  contributor_id         made nullable
  + contributor_org_id     UUID FK organizations NULL  -- seller-of-record
  CHECK ((contributor_id IS NULL) != (contributor_org_id IS NULL))
  (submitting member recorded via the proposal's delivering_member_id)

org_contributor_profiles                 -- lightweight; NOT a matching profile
  id UUID PK
  org_id UUID FK organizations UNIQUE ON DELETE CASCADE
  active bool DEFAULT true               -- org can pause listing intake
  verification_level int DEFAULT 1
  activated_at timestamptz
  reputation_score numeric NULL          -- org-level aggregate (recompute worker)
  created_at / updated_at

org_legal_profiles                       -- shared legal identity, all capabilities
  id UUID PK
  org_id UUID FK organizations UNIQUE ON DELETE CASCADE
  legal_name text
  registration_number text NULL
  address jsonb NULL
  tax_document_type text NULL
  tax_document_key text NULL             -- S3, private bucket
  created_at / updated_at

user_roles
  + source text NOT NULL                 -- 'self' (self-selected) vs 'derived' (org)
  uniqueness: (user_id, role)  →  (user_id, role, source)
                                         -- a user may hold the same role BOTH self-selected
                                         -- and org-derived, as two independent rows. sync
                                         -- manages only the 'derived' row and never selects,
                                         -- grants, or deletes a 'self' row. RBAC passes on any
                                         -- row. All UserRole role-existence queries must be
                                         -- multi-row-tolerant (contributor can have 2 rows).
```

- **No AMM / matching profile** for contributors (unlike attestor). Contributors are found
  via Explore, not matched. `org_contributor_profiles` exists only for verification level,
  directory listing, and the reputation aggregate.
- Money already flows to orgs from the attestor cut; framework sale / milestone release
  credits `payee_org_id` when the seller resolves to an org.
- Seller resolution is one branch (`contributor_org_id` if set, else `contributor_id`),
  applied wherever licensing / earnings / display read the seller.

## Capability activation & suspension

Self-activation (decision 1). No application, no admin review, no trial.

1. **Activate** — org owner/admin activates the `contributor` capability. Preconditions:
   org not suspended/deactivated. Sets `org_capabilities.contributor = active`
   (`activated_at` stamped), creates the `org_contributor_profiles` row
   (`active=true`, `verification_level` default). Fires `sync_derived_roles` for all
   current members → grants the derived user-level `contributor` role.
2. **Author immediately** — members create drafts as soon as the capability is active.
3. **Payout gate deferred** — no KYB at activation. The first **payout** requires: an
   org payout account onboarded (Stripe Connect / Paystack — the provider itself enforces
   business KYB/AML) + a tax document on file. Reuses the org payout gate shipped for
   attestor, re-keyed off "payout account present + tax doc" instead of "approved
   application".
4. **Suspend / revoke** (platform admin) — sets the capability status; suspension blocks
   new publishes + new proposals + payout and hides the org's published frameworks from
   Explore (treated as unlisted); fires `sync_derived_roles`. Existing licensed frameworks
   stay honored for current buyers; in-flight project deliverables continue under existing
   escrow/dispute rules.

**Derived-role sync generalization.** The shipped `sync_derived_roles` is attestor-only
(hard-coded `capability == "attestor"`, role `"attestor"`). Generalize to a
capability→role map (`attestor→attestor`, `contributor→contributor`), iterating each
mapping with the same idempotent grant/revoke and `approved_at` stamp.

**Self-selected vs derived contributor role.** `contributor` is NOT removed from
self-registration — an individual can hold `contributor` self-selected. A user may
therefore hold `contributor` two ways. `user_roles.source` marks the origin;
`sync_derived_roles` only ever grants/revokes rows with `source='derived'` and must never
touch a `source='self'` row. RBAC `require_role("contributor")` passes if either exists.

## Framework authoring & publish flow

Dual-context routes keep RBAC at the dependency layer. Individual routes
(`/v1/frameworks/...`) are untouched.

```
POST   /v1/orgs/{org_id}/frameworks                 create draft   (member;  require_org_capability contributor)
GET    /v1/orgs/{org_id}/frameworks                 list org frameworks (members read; owner/admin full)
GET    /v1/orgs/{org_id}/frameworks/{id}            detail
PATCH  /v1/orgs/{org_id}/frameworks/{id}            edit draft     (member)
POST   /v1/orgs/{org_id}/frameworks/{id}/artifacts... upload/confirm (member) — pipeline unchanged
POST   /v1/orgs/{org_id}/frameworks/{id}/submit     run publish pipeline (member)
POST   /v1/orgs/{org_id}/frameworks/{id}/publish    publish        (OWNER/ADMIN)
POST   /v1/orgs/{org_id}/frameworks/{id}/unpublish  unpublish      (OWNER/ADMIN)
POST   /v1/orgs/{org_id}/frameworks/{id}/version    new version    (OWNER/ADMIN)
PATCH  /v1/orgs/{org_id}/frameworks/{id}/pricing    price change   (OWNER/ADMIN)
```

- **Ownership stamp:** create sets `contributor_org_id = org`, `contributor_id = NULL`,
  `authoring_member_id = caller's org_member`.
- **RBAC split (decision 2):** author actions → `require_org_role("member")` (owner/admin
  inherit); live-state actions → `require_org_role("admin")` (owner inherits).
- **Publish preconditions:** capability `active` + not suspended, framework
  `pipeline_passed`. No payout readiness required at publish (payout is gated separately).
  The content pipeline is the per-framework gate, unchanged.
- **Member leaves org:** frameworks stay org-owned (`contributor_org_id`);
  `authoring_member_id` FK is `ON DELETE SET NULL` — provenance also lives in the audit log.

## Projects supply-side (org bids & delivers)

Grounded in the existing module: `proposals` / `milestones` / `deliverables` carry
`contributor_id → users` with a partial-unique `(project_id, contributor_id)` on
pending/accepted. The org path mirrors this with the XOR + single-staffed-member pattern.

**Flow:**
1. **Bid** — owner/admin submits a Proposal for the org. Sets `contributor_org_id` and
   `delivering_member_id` (the member who will do the work; validated: belongs to org).
   One live proposal per org per project (partial-unique on `contributor_org_id`).
2. **Accept** — Operator accepts (operator side unchanged). Workspace opens for the org.
3. **Deliver** — the `delivering_member_id` does the workspace work and submits
   deliverables (deliverable `contributor_org_id` = org). Owner/admin get read +
   **reassign** (`delivering_member_id`) until work starts; after start, reassign only via
   the dispute/admin path — same window rule as attestor. Both directions audited.
4. **Escrow** — operator funds the milestone; on approval `escrow_service.release` credits
   the contributor share to `payee_org_id`. Escrow semantics untouched; only the
   beneficiary resolves to the org.

**Guards:**
- **Self-deal COI:** an org cannot bid on a Project whose Operator is a member of that
  same org → 422 `self_deal_conflict`.
- **Member leaves** with unstarted delivery → unassigned, org must restaff; with a started
  deliverable → blocked (409) until dispute/admin resolves (existing obligations pattern).
- Suspended capability → no new proposals; in-flight deliveries continue.

**RBAC:** submit/withdraw proposal + reassign → `require_org_role("admin")`; workspace work
→ `delivering_member_id` match; read → org owner/admin.

## Financials, payouts, invoicing (mostly reuse)

The attestor cut built org beneficiaries end-to-end; contributor earnings ride the same
rails.

- **Earnings ledger** — framework sales + project milestone releases where the seller is
  the org land as `transactions.payee_org_id = org`. The org financials read endpoints
  from attestor surface contributor earnings unchanged (they filter by `payee_org_id`,
  source-agnostic). Owner/admin only.
- **Payout account** — reuse `POST /v1/orgs/{org_id}/financials/payout-accounts` (provider
  routing on org `country`). The provider enforces business KYB/AML — this is the safety
  gate (decision 1).
- **Payout request** — reuse `POST /v1/orgs/{org_id}/financials/payouts`, TOTP-gated
  (requester's own TOTP). The contributor payout gate = payout account present + tax
  document on file + capability active (replacing attestor's "approved application"
  key with the same KYB-at-payout control).
- **Invoices** — reuse org invoicing, reading legal identity from `org_legal_profiles`
  (decision 5). Attestor invoicing re-points to the shared identity
  (backward-compatible). Contributor share % unchanged from the individual flow; only the
  payee changes. No new escrow triggers.
- **PII:** payout account details and tax docs never in list endpoints; org financials
  visible to owner/admin only.

## Reputation, directory, public surfaces

- **Org contributor reputation** — `org_contributor_profiles.reputation_score` aggregates
  the org's published frameworks' reviews (existing `reviews` table) plus a completed-
  project signal, computed org-level by the reputation recompute worker keyed on
  `contributor_org_id`. Individual members' personal reputation is separate and untouched.
- **Explore / framework detail** — the seller card resolves to the org (name/slug/
  verification/reputation) when `contributor_org_id` is set, else the individual. Author
  hidden (decision 3).
- **Contributor org directory** — lists contributor **orgs**: profile fields, published
  count, reputation, verification mark, member count (no member identities). Same shape as
  the attestor directory.
- **Provenance confidentiality** — `authoring_member_id` / `delivering_member_id` appear
  only in org-admin, audit, and dispute views. Never in public / buyer / operator
  responses. Enforced by schema-level tests (same leak-guard as attestor reviewing_member).
- **Profiles module** — a user's org-contributor affiliation is not publicly exposed
  unless already public in Org Core.

## API surface (contract-first; paths indicative)

```
Capability (org owner/admin):
POST   /v1/orgs/{org_id}/contributor-capability/activate
POST   /v1/admin/orgs/{org_id}/contributor-capability/suspend|reinstate|revoke

Org legal identity (org owner; TOTP for edits):
GET    /v1/orgs/{org_id}/legal-profile
PUT    /v1/orgs/{org_id}/legal-profile
POST   /v1/orgs/{org_id}/legal-profile/tax-document       upload ticket

Org frameworks (see Framework flow section for full list + RBAC)
Org proposals (org owner/admin):
POST   /v1/orgs/{org_id}/projects/{project_id}/proposals  submit bid (delivering_member_id)
DELETE /v1/orgs/{org_id}/proposals/{proposal_id}          withdraw
POST   /v1/orgs/{org_id}/proposals/{proposal_id}/reassign body: delivering_member_id
GET    /v1/orgs/{org_id}/proposals                        org bids (owner/admin)
GET    /v1/orgs/{org_id}/deliveries                        active workspaces (owner/admin; member sees own)

Financials (org owner/admin) — reuse attestor endpoints:
GET    /v1/orgs/{org_id}/financials/earnings
POST   /v1/orgs/{org_id}/financials/payout-accounts
POST   /v1/orgs/{org_id}/financials/payouts               TOTP-gated
GET    /v1/orgs/{org_id}/financials/invoices

Public:
GET    /v1/contributors                                   directory → contributor orgs
GET    /v1/contributors/{org_slug}                        org contributor public profile
(Explore / framework detail seller identity resolves to org)
```

## Security

- RBAC at the dependency layer only: `require_org_capability("contributor")` +
  `require_org_role(...)` on every org route. Author = member; publish/pricing/proposal/
  reassign/payout = admin; legal-identity edit = owner. Workspace guards check
  `delivering_member_id`.
- Sensitive ops TOTP-gated: org payout request, legal-identity edit (owner).
- Payout KYB gate: payout account (Connect-verified) + tax doc + active capability. No
  money out otherwise.
- Provenance confidentiality: `authoring_member_id` / `delivering_member_id` excluded from
  every public/buyer/operator schema — leakage is a review blocker (schema tests).
- Content pipeline unchanged (virus/PII/rarity/similarity per framework).
- Escrow untouched except beneficiary resolution → `payee_org_id`; all money writes inside
  DB transactions.
- Audited (`module` = `organizations` / `frameworks` / `projects`): capability
  activate/suspend/revoke, publish/unpublish, proposal submit/withdraw, reassign, payout,
  legal-identity change, derived-role sync.
- Rate limiting: framework create + proposal submit + payout per-org (Redis limiter).
- COI: org cannot bid on a Project operated by its own member; an org framework cannot be
  self-reviewed by a member (existing review guard extended).

## Migration ordering

All additive — no drops, so no architect-gated drop migration in this cut. Each migration:
`alembic upgrade head` + `downgrade -1` green.

1. XOR ownership columns on `frameworks` (`contributor_org_id`, `authoring_member_id`,
   nullable `contributor_id`, XOR CHECK, index).
2. XOR + staffing columns on `proposals` and `deliverables` (+ partial-unique on
   `(project_id, contributor_org_id)`).
3. `org_contributor_profiles` table; `contributor` added to the derived-role map.
4. `org_legal_profiles` table (1:1 org); invoicing re-point (attestor + contributor).
5. `user_roles.source` marker column (add nullable → backfill: `attestor`→`'derived'`,
   else→`'self'` → `SET NOT NULL`); swap uniqueness `(user_id, role)` →
   `(user_id, role, source)` so self + derived rows coexist.

## Error handling

Project standards apply. Notable cases: author/publish RBAC mismatch → 403; publish while
capability suspended → 403 `capability_suspended`; second live org proposal on a project →
409; self-deal bid → 422 `self_deal_conflict`; reassign after work start → 409; payout
without account/tax → 403; member removal with started delivery → 409 blocked; activate on
suspended org → 403.

## Testing

- **Unit:** XOR seller resolution (framework + proposal + deliverable); activation grants
  derived `contributor` role and does NOT touch a `source='self'` role; suspend hides
  frameworks + blocks publish/proposal/payout; author-vs-publish RBAC split; one-proposal-
  per-org + self-deal COI 422; reassign window (before/after work start); escrow release
  credits `payee_org_id`; payout gate keys on account+tax not application; reputation
  aggregates the org's frameworks; provenance fields absent from public schemas
  (schema-level test); member-leave blocked/unassign paths.
- **Integration:** every org route happy + 401 + 403 (wrong org role) + suspended; full
  framework lifecycle — activate → author (member) → publish (admin) → sale → org earnings
  → payout; full project lifecycle — bid → accept → deliver → milestone release → org
  earnings; individual contributor path still works unchanged (regression); directory
  shape; GDPR export includes org authoring/delivery history under the org.
- **Migrations:** upgrade head + downgrade -1 green per migration.
- Coverage ≥80% on touched modules. Whole-repo ruff + mypy. Contract regenerated and
  validated; frontend client regen deferred to the frontend plan.

## Risks

- **Breadth:** touches frameworks + projects + financials + organizations + explore +
  reputation + auth (`user_roles`). Mitigation: additive XOR (one seller model), plan
  sliced by module, full-suite gate every task.
- **Derived-vs-self role marker:** the `user_roles.source` distinction is the subtle
  correctness point — `sync_derived_roles` must never revoke a self-selected role. Covered
  by dedicated unit tests.
- **Shared legal identity re-point:** `org_legal_profiles` changes the attestor invoicing
  read path — backward-compatible, flagged for explicit review on that task.
- **Money-path beneficiary:** framework-sale and milestone-release beneficiary resolution
  touches financials; all inside transactions, escrow semantics frozen, explicit review on
  those tasks.
