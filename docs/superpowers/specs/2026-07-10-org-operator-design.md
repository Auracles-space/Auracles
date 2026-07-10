# Organizations as Operators (Sub-project 4) — Design

**Date:** 2026-07-10
**Status:** Approved for planning
**Owner:** William (architect) / agent (senior engineer)
**Depends on:** Organizations Core (`2026-07-03-organizations-core-design.md`, shipped),
Org-as-Attestor (`2026-07-04-org-attestor-design.md`, shipped),
Org-as-Contributor (`2026-07-08-org-contributor-design.md`, shipped)
**Extends:** frameworks/licensing, library, projects, financials, organizations modules — additively

## Context

The three shipped org cuts built the org entity, membership, roles, teams, the
`org_capabilities` status table, and the org **money-out** rails (`transactions.payee_org_id`,
`payout_accounts.org_id`, `payouts.org_id`, `org_legal_profiles`, org invoicing). Every
supply-side and trust-side capability is now real for organizations.

This sub-project makes the `operator` capability real: an organization activates operating,
buys Frameworks into a **shared library** its teams and members consume, posts and funds
custom **Projects**, approves deliverables (releasing escrow to Contributors), and pays for
all of it under its legal identity from an org payment method.

**Key divergences from the prior org cuts:**

1. **Two genuinely new surfaces.** Every prior cut built only money-*out* (payouts). Operator
   is the demand side — it builds **pay-in / org billing** (`transactions.payer_org_id`, an org
   Stripe customer + saved payment method) for the first time, and a **shared library**
   (org buys once, allocated members consume) that has no supply-side analogue.
2. **Additive, not a replacement.** Individual operators are NOT retired — they remain fully
   supported and self-service. Every demand-side ownable entity becomes ownable by *either* a
   user or an organization, via the XOR pattern already shipped on the financial tables. No
   clean cutover, no drop migration in this cut.

The operator-side frontend is out of scope and follows this spec as a separate plan.

## Locked decisions

Resolved 2026-07-10 with the architect:

| # | Question | Decision |
|---|----------|----------|
| 1 | Scope | **Both surfaces.** Org buys Frameworks (shared library) AND posts/funds/approves custom Projects. Symmetric with sub-project 3, which put Projects on the supply side. One coherent demand-side identity. |
| 2 | Shared library ownership + access | **Org-owned license, admin-allocated access.** License becomes user-XOR-org (`licensee_org_id`). Admin/owner allocates each org license to **team(s) and/or individual member(s)** via a new `license_grants` table. Download entitlement = member has a direct grant OR belongs to a granted team. Per-member download audit unchanged. (NOT all-members-automatic; NOT the existing seats-assignment columns — grants scope to teams or individuals.) |
| 3 | Spend authority (RBAC) | **Admin/owner only** for every money-committing action: buy Framework, post + fund Project milestone, approve deliverable (release escrow), raise/settle dispute, manage the org payment method. Members browse, consume granted licenses, and read. Symmetric with sub-project 3 (owner/admin held all money state). No budget-capped members (YAGNI). |
| 4 | Capability activation | **Lightweight self-activation.** Owner/admin flips the `operator` capability on directly — no application, no admin approval, no KYB. Buying is money-*in*; the card provider (Stripe/Paystack) authenticates the payment instrument, so there is no platform KYB gate on the demand side. Platform admin can suspend/revoke. |
| 5 | Self-deal COI | **Block both sides.** An org cannot license its own org-published Framework (`contributor_org_id == licensee_org_id` → 422 `self_deal_conflict`), and an org's contributor arm cannot bid on the org's own operator Project (`contributor_org_id == operator_org_id` → 422). Extends the sub-project 3 member-level COI guard to the org level. |

Stated defaults (architect flagged; may be revised during spec review): review authorship
(§Reviews), refunds/disputes/GDPR handling (§Financials, §GDPR), no operator reputation
(§Reputation). Sections 5 (Projects) and 7 (Reviews) flagged as the least-certain match to
intent at design time.

## Scope

**In (backend):** `operator` capability self-activation + suspension/revocation; generalized
derived-role sync extended to `operator→operator`; XOR license ownership (user or org) +
`license_grants` team/individual allocation + grant-aware download entitlement; org shared-
library read endpoints; org **pay-in** (`organizations.stripe_customer_id`, org saved payment
method, `transactions.payer_org_id`) + org checkout/purchase; XOR operator ownership on
`projects` + org project post → fund → approve → escrow-release-to-Contributor; org milestone
funding + deliverable approval with admin-only spend RBAC; self-deal COI (buy-own + bid-own);
org-identity reviews (`reviewer_org_id`); refunds to org payer; provenance confidentiality
(grant/consuming member never public); `user_roles` derived `operator` marker; GDPR
touchpoints; audit; contract regeneration.

**Out:** all frontend (separate plan); budget-capped member spend; seat-by-seat assignment
UI beyond team/individual grants; migrating an individual's existing licenses/projects to an
org; org-to-org purchasing beyond the marketplace; operator public reputation; multi-org
billing consolidation.

## Architecture & ownership model

Additive. Individual operators stay. Ownership becomes user-XOR-org on each demand-side
entity, reusing the shipped financial XOR pattern. The payee side already carries
`payee_org_id` (attestor cut); this cut adds the mirror `payer_org_id` on the pay-in path —
it does not exist yet.

```
licenses
  operator_id         made nullable            (was NOT NULL FK users)
  + licensee_org_id     UUID FK organizations NULL
  CHECK ((operator_id IS NULL) != (licensee_org_id IS NULL))    -- XOR licensee
  UNIQUE(framework_id, licensee_org_id)                          -- one org license per framework
  (existing UNIQUE(framework_id, operator_id) unchanged for individuals)

license_grants                              -- who inside the org may consume an org license
  id UUID PK
  license_id   UUID FK licenses ON DELETE CASCADE
  team_id      UUID FK org_teams   NULL ON DELETE CASCADE
  member_id    UUID FK org_members NULL ON DELETE CASCADE
  CHECK ((team_id IS NULL) != (member_id IS NULL))               -- team XOR individual
  granted_by   UUID FK org_members NULL ON DELETE SET NULL       -- internal provenance
  created_at
  partial-unique (license_id, team_id)   WHERE team_id   IS NOT NULL
  partial-unique (license_id, member_id) WHERE member_id IS NOT NULL
  index on (member_id), (team_id)

projects
  operator_id         made nullable
  + operator_org_id     UUID FK organizations NULL
  + posting_member_id   UUID FK org_members NULL ON DELETE SET NULL   -- internal provenance
  CHECK ((operator_id IS NULL) != (operator_org_id IS NULL))
  index on (operator_org_id, status)

transactions
  payer_id            made nullable            (was NOT NULL FK users)
  + payer_org_id        UUID FK organizations NULL    -- pay-in beneficiary-of-charge
  CHECK ((payer_id IS NULL) != (payer_org_id IS NULL))
  (payee side already XOR from the attestor cut; this adds the payer XOR)

organizations
  + stripe_customer_id  text NULL              -- org billing customer (mirrors users.stripe_customer_id)

reviews
  operator_id         made nullable
  + reviewer_org_id     UUID FK organizations NULL
  + reviewing_member_id UUID FK org_members NULL ON DELETE SET NULL   -- internal provenance
  CHECK ((operator_id IS NULL) != (reviewer_org_id IS NULL))
  UNIQUE(framework_id, reviewer_org_id)
  (existing UNIQUE(framework_id, operator_id) unchanged for individuals)

user_roles
  operator → operator added to the derived-role capability map (source='derived')
  (uniqueness (user_id, role, source) already shipped in sub-project 3)
```

- **No new payout rails.** Operator is demand side — it pays in and, on project approval,
  releases escrow to a Contributor. It never receives platform earnings, so there is no
  operator payout account, no operator tax document, no operator payout gate.
- **Payer resolution** is one branch (`payer_org_id` if the buyer/funder is acting as an org,
  else `payer_id`), applied wherever checkout, refund, and receipts read the payer.
- **Licensee resolution** is one branch (`licensee_org_id` if set, else `operator_id`),
  applied wherever entitlement, library listing, and reviews read the buyer.

## Capability activation & suspension

Self-activation (decision 4). No application, no admin review, no KYB.

1. **Activate** — org owner/admin activates the `operator` capability. Precondition: org not
   suspended/deactivated. Sets `org_capabilities.operator = active` (`activated_at` stamped).
   Fires `sync_derived_roles` for all current members → grants the derived user-level
   `operator` role (`source='derived'`). Members can immediately browse the marketplace and
   consume any license granted to them; **spending requires admin** (decision 3).
2. **Buy immediately** — an org admin can purchase and post projects as soon as the org has a
   payment method on file (no KYB, no waiting period).
3. **No payout gate** — nothing to gate; operators do not cash out. The only money-in control
   is a valid payment method, enforced by the card provider at charge time.
4. **Suspend / revoke** (platform admin) — sets the capability status; suspension blocks new
   purchases + new project postings/funding + new deliverable approvals that release fresh
   escrow, and fires `sync_derived_roles`. Existing granted licenses stay downloadable for
   current members; in-flight funded milestones continue under existing escrow/dispute rules
   (money already committed is honored).

**Derived-role sync generalization.** The capability→role map (shipped generalized in
sub-project 3 as `attestor→attestor`, `contributor→contributor`) gains `operator→operator`,
iterated with the same idempotent grant/revoke + `approved_at` stamp. `operator` remains
self-selectable at registration; a user may hold `operator` both `source='self'` and
`source='derived'`; sync only ever touches the `derived` row, never a `self` row.

## Shared library (buy → allocate → consume)

The defining new concept. Org buys once; admin allocates; scoped members consume.

**Buy (admin/owner).**
```
POST /v1/orgs/{org_id}/frameworks/{framework_id}/purchase   (admin; TOTP not required — card auth is the control)
```
- Checkout charges the org payment method (`transactions.payer_org_id = org`, provider routing
  on org `country`). On success creates a License with `licensee_org_id = org`,
  `operator_id = NULL`, `license_type` per the org tier chosen, `transaction_id` linked.
- **Self-deal guard:** if the Framework's `contributor_org_id == org` → 422
  `self_deal_conflict` before any charge.
- One org license per framework (`UNIQUE(framework_id, licensee_org_id)`); re-purchase → 409.

**Allocate (admin/owner).**
```
POST   /v1/orgs/{org_id}/licenses/{license_id}/grants   body: {team_id} | {member_id}
DELETE /v1/orgs/{org_id}/licenses/{license_id}/grants/{grant_id}
GET    /v1/orgs/{org_id}/licenses/{license_id}/grants
```
- A grant targets exactly one team **or** one individual member (CHECK XOR). Team and member
  must belong to the org. Duplicate grant → 409. Revoke removes the row (audited).
- Admin/owner manage grants; they do not implicitly consume — an admin who wants to download
  grants themselves (directly or via a team they are in).

**Consume (any granted member).**
```
GET  /v1/orgs/{org_id}/library                              members see licenses granted to them
POST /v1/orgs/{org_id}/library/{license_id}/artifacts/{artifact_id}/download   presigned URL
```
- **Entitlement check:** the caller's `org_member` has a direct `license_grants.member_id`
  row for the license, OR belongs (via `org_team_members`) to a team with a
  `license_grants.team_id` row for the license. Otherwise 403.
- Presigned S3 URL only (never proxied); every download written to `artifact_downloads`
  keyed on the consuming `user_id` (per-member audit, unchanged mechanism).
- License check precedes URL generation (platform rule).

**Member leaves org.** `license_grants.member_id` (individual grant) and the member's
`org_team_members` rows cascade-delete → the member loses access automatically. The License
itself stays org-owned. Download history is retained under the org (audit).

## Org billing (pay-in)

First money-*in* rails at org level. Mirrors the per-user Stripe customer + SetupIntent flow.

```
POST /v1/orgs/{org_id}/financials/payment-methods/setup   create SetupIntent (admin; TOTP-gated)
GET  /v1/orgs/{org_id}/financials/payment-methods         list (admin; last4 only, never full PAN)
DELETE /v1/orgs/{org_id}/financials/payment-methods/{id}  remove (admin; TOTP-gated)
```
- `organizations.stripe_customer_id` created lazily on first setup (idempotency key
  `stripe_customer:org:{org_id}`), mirroring `users.stripe_customer_id`.
- Provider routing on org `country` (`select_provider`): Nigeria/NGN → Paystack, else Stripe.
- Payment-method add/remove is a sensitive op → TOTP-gated on the requesting admin's own TOTP.
- All charges (framework purchase, milestone funding) draw the org's default payment method;
  `transactions.payer_org_id = org`.
- **PII:** payment-method details masked (`****1234`), never in list endpoints beyond last4;
  org financials visible to owner/admin only.

## Projects supply-side → operator side (org posts & funds)

Mirrors the individual operator flow with the XOR + posting-member provenance pattern.

**Flow:**
1. **Post (admin/owner)** — org creates a Project (`operator_org_id = org`,
   `operator_id = NULL`, `posting_member_id = caller`). Same validation as individual projects
   (budget range, deliverables, expiry).
2. **Bids arrive** — Contributors (individual or org) submit proposals. **Self-deal guard:**
   a proposal whose `contributor_org_id == operator_org_id` → 422 `self_deal_conflict`; the
   existing member-level COI (contributor is a member of the operating org) still applies.
3. **Accept (admin/owner)** — org admin accepts a proposal; workspace opens (operator side).
4. **Fund (admin/owner)** — admin funds a milestone; checkout charges the org payment method
   into escrow (`transactions.payer_org_id = org`). Escrow semantics untouched.
5. **Approve (admin/owner)** — admin approves the deliverable → `escrow_service.release`
   credits the Contributor share to the Contributor beneficiary (user or `payee_org_id`).
   The **auto-approval window** (operator inaction = implicit approval) still applies; for an
   org project, org admins/owner are notified and are "the operator" for the timer. This
   remains the only automatic escrow release; every other release is an explicit admin action
   or admin override.
6. **Dispute (admin/owner)** — org admin raises/participates in disputes; resolution
   (release/refund/split) routes refunds to the org payer (`payer_org_id`).

**RBAC:** post/accept/fund/approve/dispute → `require_org_role("admin")` (owner inherits).
Workspace reads → org owner/admin (and the individual contributor side per sub-project 3).
Members have no spend or approval authority.

## Financials, refunds, receipts

- **Charges** — framework purchase + milestone funding land as `transactions.payer_org_id = org`.
- **Refunds** (dispute refund, admin refund) route back to the org payment method / org balance
  on the `payer_org_id` side; reuse the existing refund path with payer resolution.
- **Receipts / invoices** — purchase and funding receipts read the org's legal identity from
  the shared `org_legal_profiles` (shipped sub-project 3). No new legal-identity surface.
- **No payout** — demand side; the operator capability adds no payout account, tax doc, or
  payout endpoint.
- **PII** — payment-method + billing details owner/admin only; never in list endpoints.

## Reviews  *(stated default — flagged for spec review)*

- Org-owned license → the review is written under **org identity** by an admin/owner
  (`reviewer_org_id = org`, `operator_id = NULL`, `reviewing_member_id` recorded internally),
  one per Framework per org (`UNIQUE(framework_id, reviewer_org_id)`).
- Feeds the Contributor's reputation exactly like an individual review; only the reviewer
  identity resolves to the org.
- `reviewing_member_id` is internal provenance — never in public review responses.

## Reputation, public surfaces  *(stated default)*

- **No operator reputation.** Operators are buyers; the platform does not publicly rate them.
  No org-operator reputation aggregate, no operator directory. (Only contributor and attestor
  orgs carry public reputation, unchanged.)
- **Explore / framework detail** — buyer identity is never shown on public surfaces, so the
  operator XOR has no public seller-card impact. The seller card continues to resolve to the
  Contributor (individual or org) per sub-project 3.

## Provenance confidentiality

- `license_grants.member_id`, `granted_by`, `posting_member_id`, and `reviewing_member_id`
  are internal provenance — org-admin, audit, and dispute views only. Never in
  public/buyer-facing/Contributor-facing/seller schemas. Enforced by schema-level leak-guard
  tests, matching the attestor `reviewing_member` and contributor `authoring_member`
  conventions.
- A Contributor delivering an org's project sees the operating **org**, not which member
  posted or funded it.

## API surface (contract-first; paths indicative)

```
Capability (org owner/admin):
POST   /v1/orgs/{org_id}/operator-capability/activate
POST   /v1/admin/orgs/{org_id}/operator-capability/suspend|reinstate|revoke

Org billing (org admin; TOTP for payment-method mutations):
POST   /v1/orgs/{org_id}/financials/payment-methods/setup
GET    /v1/orgs/{org_id}/financials/payment-methods
DELETE /v1/orgs/{org_id}/financials/payment-methods/{id}

Shared library:
POST   /v1/orgs/{org_id}/frameworks/{framework_id}/purchase        (admin)
GET    /v1/orgs/{org_id}/licenses                                  (admin; org licenses + grant summary)
POST   /v1/orgs/{org_id}/licenses/{license_id}/grants              (admin) body: team_id|member_id
DELETE /v1/orgs/{org_id}/licenses/{license_id}/grants/{grant_id}   (admin)
GET    /v1/orgs/{org_id}/licenses/{license_id}/grants              (admin)
GET    /v1/orgs/{org_id}/library                                   (granted members)
POST   /v1/orgs/{org_id}/library/{license_id}/artifacts/{artifact_id}/download  (granted member)

Org projects (operator side; org admin):
POST   /v1/orgs/{org_id}/projects                                 post
GET    /v1/orgs/{org_id}/projects                                 org's projects
POST   /v1/orgs/{org_id}/projects/{project_id}/proposals/{proposal_id}/accept
POST   /v1/orgs/{org_id}/projects/{project_id}/milestones/{milestone_id}/fund
POST   /v1/orgs/{org_id}/projects/{project_id}/deliverables/{deliverable_id}/approve
POST   /v1/orgs/{org_id}/projects/{project_id}/disputes           raise/participate

Reviews (org admin):
POST   /v1/orgs/{org_id}/frameworks/{framework_id}/review         write org review
```

## Security

- RBAC at the dependency layer only: `require_org_capability("operator")` +
  `require_org_role(...)` on every org route. Spend/approve/fund/post/purchase/review/
  payment-method = admin (owner inherits); library consume = grant/team entitlement check.
- Sensitive ops TOTP-gated: org payment-method add/remove. (Purchases/funding rely on the
  card provider's auth; no additional TOTP unless architect elevates a threshold later.)
- Shared-library entitlement enforced before every presigned URL; license check precedes URL
  generation; per-member download audit.
- Self-deal COI: org cannot buy its own Framework; org contributor arm cannot bid its own
  operator Project (both 422 `self_deal_conflict`, before any charge).
- Provenance confidentiality: grant/posting/reviewing member ids excluded from every
  public/buyer/Contributor schema — leakage is a review blocker (schema tests).
- Escrow untouched except payer/beneficiary resolution → `payer_org_id` / existing payee
  resolution; all money writes inside DB transactions.
- Audited (`module` = `organizations` / `financials` / `library` / `projects`): capability
  activate/suspend/revoke, payment-method add/remove, framework purchase, license grant/revoke,
  project post/fund, deliverable approve (escrow release), refund, review write, self-deal
  denial, derived-role sync.
- Rate limiting: framework purchase + project post + payment-method setup per-org (Redis
  limiter).

## Migration ordering

All additive — no drops, so no architect-gated drop migration in this cut. Each migration:
`alembic upgrade head` + `downgrade -1` green.

1. XOR licensee columns on `licenses` (`licensee_org_id`, nullable `operator_id`, XOR CHECK,
   `UNIQUE(framework_id, licensee_org_id)`); `license_grants` table (team-XOR-member CHECK,
   partial-uniques, indexes).
2. `organizations.stripe_customer_id`; XOR payer columns on `transactions` (`payer_org_id`,
   nullable `payer_id`, XOR CHECK).
3. XOR operator columns on `projects` (`operator_org_id`, `posting_member_id`, nullable
   `operator_id`, XOR CHECK, index).
4. XOR reviewer columns on `reviews` (`reviewer_org_id`, `reviewing_member_id`, nullable
   `operator_id`, XOR CHECK, `UNIQUE(framework_id, reviewer_org_id)`).
5. `operator` added to the derived-role capability map (no schema change —
   `user_roles.source` already shipped; sync logic + data backfill of existing
   operator-capable orgs' members to `source='derived'` rows where absent).

## Error handling

Project standards apply. Notable cases: spend by non-admin member → 403; consume a license
without a grant → 403; buy own org Framework → 422 `self_deal_conflict`; org bids own project
→ 422 `self_deal_conflict`; second org license on a framework → 409; duplicate grant → 409;
purchase/fund with no payment method → 402 + explicit message; purchase/fund while capability
suspended → 403 `capability_suspended`; grant to a team/member outside the org → 422; activate
on a suspended org → 403; payment-method mutation without TOTP → 401.

## Testing

- **Unit:** licensee XOR resolution; grant entitlement (direct member grant, team grant,
  no-grant 403, member-in-multiple-teams); grant team-XOR-member CHECK; buy-own-framework 422;
  bid-own-project 422; payer XOR resolution; spend-RBAC (member cannot purchase/fund/approve →
  403; admin can); capability activation grants derived `operator` role and never touches a
  `source='self'` row; suspend blocks new purchase/fund/approve but honors existing grants +
  funded milestones; escrow release credits the Contributor beneficiary from an org-funded
  milestone; refund routes to `payer_org_id`; review under org identity, one per framework per
  org; provenance fields absent from public/buyer/Contributor schemas (schema-level test);
  member-leave drops individual + team-derived grants.
- **Integration:** every org route happy + 401 + 403 (wrong org role / no grant) + suspended;
  full library lifecycle — activate → add payment method → purchase → grant to team + to member
  → granted member downloads → non-granted member 403 → revoke → 403; full operator project
  lifecycle — post → accept → fund (org card) → approve → escrow release to Contributor org
  earnings; self-deal buy + self-deal bid both 422; individual operator path unchanged
  (regression); GDPR export includes org purchase/consumption history under the org.
- **Migrations:** upgrade head + downgrade -1 green per migration.
- Coverage ≥80% on touched modules. Whole-repo ruff + mypy. Contract regenerated and
  validated; frontend client regen deferred to the frontend plan.

## Risks

- **Breadth:** touches licensing + library + projects + financials + organizations + auth
  (`user_roles`). Mitigation: additive XOR (one payer + one licensee model), plan sliced by
  module, full-suite gate every task.
- **Pay-in is new surface:** org Stripe customer + `payer_org_id` charging is the first
  money-in path at org level. Mitigation: mirror the audited per-user SetupIntent/charge flow
  exactly; all charges in DB transactions; explicit review on the billing task.
- **Shared-library access-control correctness:** the grant/team entitlement check is the
  security-critical point — a missed check leaks paid artifacts to un-granted members.
  Mitigation: entitlement enforced before every presigned URL + dedicated unit/integration
  tests including member-in-multiple-teams and revoke paths.
- **Money-path payer/beneficiary resolution:** purchase, funding, and refund resolve the payer
  to the org; escrow release resolves the beneficiary to the Contributor. All inside
  transactions, escrow semantics frozen, explicit review on those tasks.
- **Self-deal loops:** org holding both contributor and operator capabilities. Mitigation:
  buy-own + bid-own both blocked before any charge, covered by dedicated tests.
