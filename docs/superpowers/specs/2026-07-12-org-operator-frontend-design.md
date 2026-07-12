# Org-Operator Frontend — Design Spec

**Date:** 2026-07-12
**Status:** Approved (design), pending implementation plan
**Depends on:** Org-as-Operator backend (shipped: `229b778`, `e08b978`, `1873bd2`, `8bce523`, `7d49a3d`, `aedcee6`, `91bb1bc`)

## Goal

Build the frontend surfaces that let an Organization act as an **Operator**:
buy Frameworks as the org, consume them through a shared org Library with
member/team access grants, manage operator billing, and run Projects as the
org (post → proposals → accept → fund milestones → approve deliverables →
escrow release). The backend is fully shipped; this spec covers UI only.

## Context

The org dashboard already renders capability-gated tabs via
`frontend/src/components/modules/organizations/organization-shell.tsx`
(role/capability gating: `attestorCap`, `isAdmin`, `isOwner`). Today's tabs:
Profile, Members, NDA, Invitations, Teams, Attestor, Financials, Offers,
Queue, Danger Zone. There is **no** Library, Projects, or operator-Billing
surface. The existing `financials/page.tsx` renders attestor financials only
(`OrgAttestorFinancialsTab` — earnings/payouts, money-IN).

Individual-operator UI already exists and is the reuse source:
`components/modules/library/operator-library.tsx`,
`components/modules/projects/{project-create-form,project-list-shell,project-workspace,milestone-funding-panel,deliverable-review-card,milestone-dispute-panel}.tsx`,
and the checkout flow under `app/(auth)/checkout` + `app/(public)/checkout`.

## Locked decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Scope | All 4 operator surfaces (Purchase, Library, Billing, Projects), one spec, phased plan — each phase independently shippable/testable. |
| 2 | Purchase entry point | Buyer-context selector injected into the existing checkout: `Buy as: [Myself / Org X…]`. Lists only orgs where caller is `admin`+operator-`active`. One buy flow chooses payer. No separate org catalog/browse surface (YAGNI). |
| 3 | Billing placement | One capability-sectioned `Financials` tab: render a **Billing** section (payment methods + invoices, money-OUT) when operator-active, alongside the existing attestor **Earnings** section when contributor/attestor-active. No separate Billing tab. |
| 4 | License grant UX | Per-license expandable grant management inside the Library tab. Grant target is `member_id` XOR `team_id` (backend `OrgLicenseGrantRequest`), revocable. |
| 5 | Navigation model | New surfaces are org-scoped tabs under `[orgId]`, gated on `operator` capability = `active` AND role ∈ {admin, owner}, mirroring the attestor tab gating. |
| 6 | Component reuse boundary | Reuse individual-operator components where the only difference is the API base path; extract that path to a prop/context (org vs self) rather than forking files. Fork only when behavior genuinely diverges. |

## Backend surface (already shipped — UI targets these)

Org router (`/v1/orgs/{org_id}/…`):
- Purchase: `POST /{org_id}/frameworks/{framework_id}/purchase`
- Library: `GET /{org_id}/library`;
  `GET /{org_id}/library/{license_id}/artifacts/{artifact_id}/download`
- Grants: `GET/POST /{org_id}/licenses/{license_id}/grants`;
  `DELETE /{org_id}/licenses/{license_id}/grants/{grant_id}`
- Billing: `GET /{org_id}/financials/payment-methods`;
  `POST /{org_id}/financials/payment-methods/setup` (TOTP);
  `DELETE /{org_id}/financials/payment-methods/{payment_method_id}`;
  `GET /{org_id}/financials/invoices`;
  `GET /{org_id}/financials/purchases/{transaction_id}/invoice`

Projects org router (`/v1/orgs/{org_id}/…`, prefix `org_router` in
`projects/router.py`):
- `POST /orgs/{org_id}/projects` (post), list, `…/proposals/{id}/accept`,
  `…/milestones/{id}/fund`, `…/deliverables/{id}/approve`, disputes.

## Architecture

All surfaces live under the existing org dashboard `[orgId]` tab shell.
`organization-shell.tsx` gains operator tabs behind an
`operatorActive = capabilities?.["operator"] === "active"` check combined with
`isAdmin`:

- **Library** (new tab / route segment `library`)
- **Projects** (new tab / route segment `projects`)
- **Financials** — existing tab, made capability-sectioned to add a Billing
  section

Purchase is not a tab; it is a payer selector injected into checkout.

## Phase breakdown

### Phase 1 — Org Purchase (buy-as-org)
Checkout gains a `Buy as` selector. Options: the caller plus every org where
they are `admin` and operator-capability is `active` (source: an existing
"my orgs" fetch; server re-validates). Selecting an org routes the buy to
`POST /orgs/{org_id}/frameworks/{framework_id}/purchase`, which resolves the
org payment method and enforces TOTP where required. Self remains the default.

### Phase 2 — Org Library
New tab. `GET /{org_id}/library` → shared framework list (reuse
`operator-library.tsx` presentation). Each row expands into **grant
management**:
- List current grants (member/team, `GET …/grants`)
- Add a grant to a member or a team (`POST …/grants`, `member_id` XOR `team_id`)
- Revoke a grant (`DELETE …/grants/{grant_id}`)
- Per-artifact download via presigned URL (`…/artifacts/{artifact_id}/download`)

The grant panel is new and org-unique.

### Phase 3 — Org Billing (Financials section)
Make `financials/page.tsx` capability-aware. When operator-active, render a
**Billing** section:
- Payment methods: list, setup (TOTP-gated), delete
- Invoices: list (`GET …/invoices`), download a purchase invoice
  (`GET …/purchases/{transaction_id}/invoice`)

The existing attestor Earnings section continues to render when
contributor/attestor-active. Sections compose; an org with multiple
capabilities sees multiple sections.

### Phase 4 — Org Projects (as operator)
New tab. Reuse `project-create-form`, `project-list-shell`,
`project-workspace`, `milestone-funding-panel`, `deliverable-review-card`,
`milestone-dispute-panel`, pointed at `/orgs/{org_id}/projects/*` via the
extracted API-base prop/context. Flow: post project → review proposals →
accept → fund milestone → approve deliverable → escrow release → disputes.

## Component strategy

The reuse boundary (decision 6): individual-operator components take their API
base path from a prop or a small context (`{ mode: "self" | "org", orgId? }`)
rather than being duplicated. New components: buyer-context selector,
license-grant panel, org-billing section. Follow mobile-first rules (base
styles target 375px, `44px` touch targets, no hover-only interactions, tables
→ card stacks on mobile) per `CLAUDE.md`.

## Security

- Every operator tab is gated **client-side** on capability+role for UX and
  **server-side** on the `OrgAdmin` dependency — the client gate is never the
  authority.
- Payment-method setup and any payout-touching op keep the TOTP gate.
- Artifact downloads use presigned URLs only; the server checks license +
  grant before minting a URL. The frontend never proxies bytes.
- The payer selector lists only eligible orgs, but the server re-checks
  `admin` + operator-`active` on every purchase (deny by default).
- No PII (KYC, payout account detail) rendered in list surfaces.

## Testing

- **Component (vitest + RTL + msw):** buyer-context selector (eligible-org
  filtering, self default), license-grant panel (grant member, grant team,
  revoke, empty state), billing section (payment-method setup TOTP path,
  invoice list), project components under the org API base.
- **E2E (playwright):** buy-as-org → grant license to a team → member
  downloads artifact → ungranted member blocked; post org project → fund
  milestone → approve deliverable → escrow released to Contributor.
- Coverage: components ≥ 70% per `CLAUDE.md`.

## Out of scope

- Any change to org-operator backend (shipped).
- A standalone org catalog/browse surface (decision 2 — explore is already
  public).
- Contributor/attestor-only surfaces (covered by their own specs).
