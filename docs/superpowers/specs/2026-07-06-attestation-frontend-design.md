# Attestation Frontend (Sub-project 2 — Frontend) — Design

## Context

Sub-project 2 backend ("Organizations as Attestors") is shipped: the individual-attestor
pipeline is retired and the attestor capability is now org-derived. Attestations carry
`attestor_org_id` + `reviewing_member_id` (internal-only); the fee credits the org at escrow
release. The backend contract (`contracts/openapi.yaml`) is updated and the individual
application/assignment endpoints are removed.

The frontend has **not** caught up. Three problems, in order of severity:

1. **Generated client is stale.** `frontend/src/lib/generated/` still exports the removed
   individual fns (`acceptAttestationOffer`, `listAttestorAssignments`,
   `submitAttestorApplication`, …) and lacks the new org-scoped fns. Every attestation surface
   is typed against a contract the backend no longer serves.
2. **Dead UI hits removed endpoints.** `/attestor/applications`, `/attestor/assignments`,
   `/settings/attestor`, and `attestor-application-prompt.tsx` call endpoints that 404 now.
3. **No org attestation UI exists.** Nothing surfaces the org capability application, offer
   queue, accept-and-staff, reviewing-member workspace, org financials, or the admin
   org-attestor review queue.

This spec defines the frontend to reconcile all three: regenerate the client, delete dead UI,
fix the two contract-drift files in place, and build the new org attestation surfaces.

Backend design of record: `docs/superpowers/specs/2026-07-04-org-attestor-design.md`
(its "API surface", "Capability activation flow", "Matching + assignment", "Settlement,
payouts, invoicing", "Badge, provenance, directory", "NDA mechanics", "Security" sections
are the source of truth for endpoints, gates, and confidentiality rules).

## Locked decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Scope | Full frontend: client regen + dead-UI removal + drift fixes + all new org attestation surfaces (requestor, attestor-org, admin, public). |
| 2 | Attestor surface home | Under `dashboard/organizations/[orgId]/*` as new role-gated tabs (matches existing Org Core `Tabs` IA). Attestor is org-derived. |
| 3 | Dead individual UI | Delete routes + components + tests. Individual pipeline is retired backend-side; nothing to repoint to. |
| 4 | Two drift files | Fix in place (repoint to regenerated client types), not rebuild. |
| 5 | Application UX | Gate-checklist page: each of the 8 activation gates is a status card + inline action. Not a forced linear wizard — gates bounce on `needs_info` and must be revisitable. |
| 6 | Reviewing-member workspace | Reuse the existing attestor workspace component, repointed to the re-pointed workspace endpoints. Wiring, not rebuild. |
| 7 | God-component split | `attestation-workspaces.tsx` (1173 lines, 4 panels) splits along its own seam: the 2 surviving panels move to focused files while repointed; the 2 dead panels are deleted. |

## Scope

**In:**
- Regenerate `frontend/src/lib/generated/` from the updated `contracts/openapi.yaml`.
- Delete dead individual-attestor routes, components, and their tests.
- Fix `attestation-workspaces.tsx` (split + repoint survivors) and `admin-config-panel.tsx` (repoint).
- Org dashboard tabs: Attestor application, NDA, Offers + staffing, Attestation queue,
  reviewing-member workspace, Org financials.
- Admin: org-attestor application review queue + gate actions; capability suspend/reinstate/revoke.
- Public: attestor directory reshaped to orgs; org attestor public profile.

**Out (separate later work):**
- Backend changes of any kind (contract is frozen for this plan).
- Real-time workspace WebSocket beyond what the existing workspace component already does.
- Reputation/analytics visual redesign.
- Non-attestation admin config fields (only the attestor-related drift in `admin-config-panel.tsx`).

## Architecture

Next.js 15 App Router, client components for all auth-gated dashboards (per CLAUDE.md rendering
table: dashboards = client, workspace = client). Public directory/profile = SSR (SEO-critical,
matches `/explore` treatment).

All API calls go through the regenerated `hey-api` client in `src/lib/generated/`, never
hardcoded paths. Client components attach `getAccessTokenHeaders()` (existing helper). Org-scoped
components read org id + role from the existing `OrganizationProvider` context.

Component placement follows the established split:
- `components/ui/*` — primitives (reuse `Button`, `Tabs`, `Spinner`, form fields, cards).
- `components/modules/attestation/*` — attestation feature components.
- `components/modules/organizations/*` — org-scoped tabs (attestor surfaces live here, consuming
  `OrganizationProvider`).
- `components/modules/admin/*` — admin panels.

Mobile-first, 44px touch targets, tested at 375px, per CLAUDE.md. Match existing form-field and
card styling exactly (surface-1/2, border-strong, accent, foreground-muted tokens).

## Surfaces

### A. Foundational — client regeneration

Regenerate `frontend/src/lib/generated/` (`sdk.gen.ts`, `types.gen.ts`) from
`contracts/openapi.yaml` using the project's existing codegen command. This is a prerequisite
for every other surface: it removes the dead individual fns and adds the org-scoped fns
(`/orgs/{org_id}/attestation-offers`, `/orgs/{org_id}/attestations`,
`/orgs/{org_id}/attestor-application`, `/admin/org-attestor-applications/*`, org financials, NDA).
After regen, the two drift files and the surviving requestor/admin panels will fail typecheck —
that is expected and is fixed in surface C.

### B. Dead UI removal

Delete (routes): `app/(auth)/attestor/applications/`, `app/(auth)/attestor/assignments/`,
`app/(auth)/settings/attestor/`. Remove the now-empty `app/(auth)/attestor/` layout if nothing
else lives under it.

Delete (components): `attestor-application-prompt.tsx`, and from `attestation-workspaces.tsx` the
`AttestorApplicationPanel` and `AttestorAssignmentsPanel` exports.

Delete (tests): `attestor-application-prompt.test.tsx`, `attestor-application-panel.test.tsx`, and
any assignment-panel test.

Remove nav entries / links that route to the deleted paths (dashboard nav, settings nav, any
role-based redirect that sent attestors to `/attestor/*`).

### C. Drift fixes (fix in place)

`attestation-workspaces.tsx` splits:
- `AttestationRequestorPanel` → new `attestation/requestor-panel.tsx`, repointed. Requestor
  (Operator/Contributor) requests an attestation and views their attestation list/status. Response
  now exposes `attestor_org_id` (was `attestor_id`); render org identity, never
  `reviewing_member_id` (it is not in the requestor schema).
- `AdminAttestationPanel` → moves to `admin/admin-attestation-panel.tsx`, repointed. Manual assign
  now posts `{ attestor_org_id, reviewing_member_id }` (was `attestor_id`); refund unchanged.
- Shared helpers (`StatusTag`, `ErrorMessage`, card sub-components) move to a small shared module
  or are duplicated minimally — do not leave them stranded in a deleted file.

`admin-config-panel.tsx` — repoint `listPlatformConfig` / `updatePlatformConfig` reads/writes to
the regenerated config shape (attestor-related config keys changed with the org migration).

### D. Org attestor capability application (owner/admin)

New org tab "Attestor" → gate-checklist page. Consumes `GET /orgs/{id}/attestor-application`
(current application + per-gate status) and renders 8 gate cards in order (backend spec
"Capability activation flow"):

1. **Apply** — draft form (KYB legal identity, incorporation docs upload, credentials summary,
   sample work, references). Save draft (`PATCH`), submit (`POST .../submit`). `needs_info` shows
   `admin_feedback` and reopens the relevant fields.
2. **KYB verification** — read-only status (admin-driven); show `kyb_verified_at` or pending/needs_info.
3. **Org credentials** — read-only review status.
4. **COI + confidentiality undertaking** — owner-only action, TOTP-gated
   (`POST .../sign-undertakings`). Reuse existing 2FA step-up UI.
5. **Payout account** — onboard via existing provider-routing onboarding
   (`POST /orgs/{id}/financials/payout-accounts`); show linked/not-linked.
6. **Tax document** — presigned upload (`POST .../tax-document`). Never log the presigned URL.
7. **Trial attestation** — nominate an NDA-signed member (`POST .../nominate-trial-member`); show
   trial status + grade once admin runs it.
8. **Activation** — read-only terminal status (approved / rejected + feedback; reapply CTA on reject).

Tab visible to owner/admin only. Owner-only actions (gate 4) disabled with explanation for admins.

### E. NDA signing

- **Invite-accept prompt:** when the invitation-accept response signals NDA requirement
  (capability `pending`/`active`), surface the NDA text + sign action inline in `invitation-accept.tsx`.
  Accept-without-sign still joins (member simply unassignable); make that consequence explicit.
- **Org NDA tab / banner:** current version + my signature status (`GET /orgs/{id}/nda`), sign action
  (`POST /orgs/{id}/nda/sign`). Existing members prompted in-app when capability turns active, and
  when the NDA version bumps (older signature → unassignable until re-signed).

### F. Offers + accept-and-staff (owner/admin)

Org tab "Offers":
- Offer list (`GET /orgs/{id}/attestation-offers`) — attestation summary, requested
  specializations/jurisdictions, expiry countdown.
- **Accept modal:** pick `reviewing_member_id` from a member picker filtered to NDA-signed members
  under the concurrency cap (surface why a member is ineligible: no NDA, or ≥5 active). Accept posts
  `{ reviewing_member_id }` (`POST .../accept`).
- **Decline** (`POST .../decline`).
- **Reassign:** on an accepted attestation before review starts, owner/admin may change the
  reviewing member (`POST /orgs/{id}/attestations/{id}/reassign`). Hidden once review has started
  (post-start reassignment is platform-admin only).

### G. Org attestation queue + reviewing-member workspace

Org tab "Attestations":
- **Queue** (`GET /orgs/{id}/attestations`) — owner/admin see all org attestations; a plain member
  sees only their own. Columns: target, status, reviewing member (owner/admin view only), dates.
- **Reviewing-member workspace:** reuse the existing attestor workspace component (rubric scores,
  annotations, clarifications, document uploads, report submission), repointed to the re-pointed
  workspace endpoints (guards now key on `reviewing_member_id`). Owner/admin get read-only workspace
  access; the assigned reviewing member gets write.

### H. Org attestor financials (owner/admin)

Org tab "Financials" (or a section within an existing org financials tab if one exists):
- **Earnings ledger** (`GET /orgs/{id}/financials/earnings`) — settlement transactions where the org
  is payee.
- **Payout account** onboard/status (`POST /orgs/{id}/financials/payout-accounts`).
- **Payout request** (`POST /orgs/{id}/financials/payouts`) — TOTP-gated (requester's own TOTP),
  enabled only when a payout account exists and the application is approved.
- **Invoices** (`GET /orgs/{id}/financials/invoices`) — issued in the org legal name.
- PII: never render payout account detail or tax docs in list views; financials visible to
  owner/admin only.

### I. Admin org-attestor review

Admin surface (`admin/*`):
- **Review queue** (`GET /admin/org-attestor-applications`, status filter) — one row per application
  with the gate checklist state.
- **Gate actions:** verify-kyb, needs-info (with feedback), start-trial, approve, reject (with
  feedback). Each maps to its `POST /admin/org-attestor-applications/{id}/*` endpoint. KYB and tax
  documents viewed via admin-only presigned download; never in the list payload.
- **Capability control:** suspend / reinstate / revoke
  (`POST /admin/orgs/{org_id}/attestor-capability/*`) with confirmation.

### J. Public directory + org attestor profile

- **Directory** `/attestors` (SSR) — `GET /v1/attestor-orgs`. Lists attestor **orgs**: profile
  fields, completed attestation count, certification mark, member count. No member identities.
- **Org attestor profile** `/attestors/[orgId]` (SSR) — `GET /v1/attestor-orgs/{org_id}` (keyed by
  **org_id**, not slug) + completed attestations from `GET /v1/attestor-orgs/{org_id}/completed`.
- **Badge** — `GET /v1/frameworks/{framework_id}/attestation-badges` renders org identity (name,
  slug, verification level). There is no separate provenance endpoint in the contract; org identity
  is carried in the badge payload. `reviewing_member_id` never appears in any public/requestor surface.

## Data flow

Org-scoped surfaces (D–H): `OrganizationShell` loads the org + role into `OrganizationProvider`;
attestor tabs are gated on role (owner/admin) and on `org.capabilities.attestor` status. Tab
components call org-scoped endpoints with the org id from context + `getAccessTokenHeaders()`.

Admin surfaces (I): existing admin workspace shell + role guard; panels call `/admin/*` endpoints.

Public surfaces (J): Server Components fetch directory/profile directly from the API base URL (no
auth header), matching the `/explore` SSR pattern.

## Error handling

- Loading = existing `Spinner`; error = existing inline error card pattern (`border-error/50 bg-error/5`).
- 401 → auth redirect (existing middleware/guard). 403 → "not permitted" inline, do not crash the tab.
- 404 on an org/attestation → "not found or no access" inline (mirrors `OrganizationShell`).
- 409 (concurrency cap, blocked reassignment, blocked member removal) → surface the specific reason
  from the response, never a generic failure.
- TOTP-gated actions that return a 2FA challenge → route into the existing 2FA step-up flow.
- Presigned upload failures → retry affordance; never log the URL.

## Confidentiality (hard rules — review blockers)

- `reviewing_member_id` / reviewing-member identity renders **only** in: org owner/admin views and
  admin dispute views. Never in requestor, public directory, public profile, or badge surfaces.
  Every component that renders an attestation checks which schema it received the field from.
- Payout account details + tax documents never in list payloads; detail only via admin-only or
  owner/admin presigned download.
- Presigned URLs (KYB, tax, artifacts) never logged.

## Testing

Per CLAUDE.md frontend stack (`vitest` + `@testing-library/react`, `msw` for API mocking,
`playwright` for e2e), TDD RED→GREEN per component.

- **Component tests** for each new panel: happy render, role gating (owner/admin vs member),
  empty state, error state, and — for requestor/public panels — an explicit assertion that
  `reviewing_member_id` is **not** rendered.
- **Accept-and-staff:** member picker excludes non-NDA / over-cap members; accept posts the member id.
- **Drift fixes:** requestor panel renders `attestor_org_id`; admin assign posts org + member.
- **e2e (`attestation.spec.ts`, rewritten):** org applies for attestor capability → admin approves →
  offer received → accept-and-staff → reviewing member submits report → published; requestor sees org
  identity only.
- Coverage ≥ 70% on `components/**` (CI threshold). `tsc` + `eslint` clean.

## Global constraints (bind every task)

- Backend contract is frozen. If a surface needs an endpoint that does not exist in
  `contracts/openapi.yaml`, stop and flag — do not invent client calls.
- All API calls via the regenerated `src/lib/generated/` client. No hardcoded paths.
- Mobile-first; 44px touch targets; tested at 375px; match existing token/card/form styling.
- Access token in memory only; never localStorage. Reuse `getAccessTokenHeaders()`.
- Reviewing-member identity confidentiality rules above are non-negotiable review blockers.
- No file exceeds ~200 lines without a split rationale (the God-component split exists to honor this).
- Commits end at the last meaningful line — no `Co-Authored-By` trailer. Work on `main`; ask before branching.

## Risks

- **Client regen churn:** regeneration will break every attestation-touching file at once. The plan
  sequences regen first, then a compile-green sweep (delete dead + fix drift) before building new
  surfaces, so the tree is never left broken across many tasks.
- **Confidentiality leakage:** the single highest risk. `reviewing_member_id` in a requestor/public
  payload is a review blocker; every requestor/public component gets an explicit negative test.
- **Workspace reuse fit:** the existing attestor workspace component assumed an individual attestor;
  repointing may surface assumptions (e.g. "my assignment") that need org-context adaptation. If reuse
  turns out to fight the component, escalate rather than force it.
- **Contract gaps:** all assumed endpoints verified present in `contracts/openapi.yaml` at spec time
  (org application/offers/attestations/financials/NDA, admin review + capability control, public
  `/v1/attestor-orgs*`, framework attestation-badges). The public directory is `/v1/attestor-orgs`
  (not `/v1/attestors`) and the profile is keyed by `org_id` (not slug); there is no standalone
  provenance endpoint. Any further gap found during regen is an escalation, not an invented client call.
