# Attestation Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile the Auracles frontend with the shipped org-attestor backend — regenerate the API client, delete the retired individual-attestor UI, fix two contract-drift files, and build the new org attestation surfaces (application, NDA, offers + staffing, queue + workspace, financials, admin review, public directory).

**Architecture:** Next.js 15 App Router. Auth-gated dashboards are client components consuming the regenerated `@hey-api` client in `src/lib/generated/`. Org attestor surfaces live as role-gated tabs under `dashboard/organizations/[orgId]/*`, reading org id + role from the existing `OrganizationProvider`. Admin surfaces live under `admin/*`. Public directory/profile are SSR. All new short SDK function names are authored in `scripts/patch-generated-client.mjs` (Task 1) and consumed by every later task.

**Tech Stack:** Next.js 15, TypeScript, Tailwind, `@hey-api/openapi-ts` + `@hey-api/client-fetch` (codegen), `vitest` + `@testing-library/react` + `@testing-library/jest-dom` (tests; SDK mocked via `vi.mock`, no msw).

**Design spec:** `docs/superpowers/specs/2026-07-06-attestation-frontend-design.md`
**Backend spec (endpoint/gate/confidentiality source of truth):** `docs/superpowers/specs/2026-07-04-org-attestor-design.md`

## Global Constraints

- Backend contract (`contracts/openapi.yaml`) is **frozen**. If a task needs an endpoint absent from the contract, STOP and escalate — never invent a client call.
- All API calls go through the regenerated `src/lib/generated/` client via its short aliases. No hardcoded API paths in components.
- Auth: reuse `getAccessTokenHeaders()` from `@/lib/auth/form-client`. Access token in memory only; never localStorage.
- Mobile-first; every interactive element ≥ 44px touch target; test layouts at 375px; match existing token/card/form styling (`surface-1/2`, `border-strong`, `accent`, `foreground-muted`, `border-error/50 bg-error/5` error cards).
- **Confidentiality (review blocker):** `reviewing_member_id` / reviewing-member identity renders ONLY in org owner/admin views and admin dispute views. NEVER in requestor, public directory, public profile, or badge surfaces. Every requestor/public component gets an explicit negative test asserting it is not rendered.
- Presigned URLs (KYB, tax, artifacts) are never logged.
- No component file exceeds ~200 lines without a split rationale.
- Commit after each task. Commit messages end at the last meaningful line — **no `Co-Authored-By` trailer**. Work on `main`; ask before branching.
- Commands (run from `frontend/`): codegen `npm run generate:api`; typecheck `npm run typecheck`; lint `npm run lint`; all tests `npm run test`; single test file `npx vitest run <path>`; coverage `npm run test:coverage` (threshold ≥ 70% on `components/**`).

---

## File Structure

**Regenerated (Task 1):**
- `frontend/src/lib/generated/sdk.gen.ts`, `types.gen.ts` — from contract.
- `frontend/scripts/patch-generated-client.mjs` — alias map: remove retired attestor aliases, add org-attestor aliases (the canonical fn names below).

**Deleted (Task 2):**
- `frontend/src/app/(auth)/attestor/applications/`, `.../attestor/assignments/`, `.../settings/attestor/`, and `.../attestor/` layout if orphaned.
- `frontend/src/components/modules/attestation/attestor-application-prompt.tsx`.
- The `AttestorApplicationPanel` + `AttestorAssignmentsPanel` exports inside `attestation-workspaces.tsx`.
- Tests: `attestor-application-prompt.test.tsx`, `attestor-application-panel.test.tsx`, any assignments-panel test.

**Split out of `attestation-workspaces.tsx` (Tasks 3–4), then delete the emptied file:**
- Create `frontend/src/components/modules/attestation/requestor-panel.tsx` (was `AttestationRequestorPanel`, repointed).
- Create `frontend/src/components/modules/attestation/attestation-status.tsx` (shared `StatusTag`, `ErrorMessage`, `AttestationCard` helpers used by requestor + admin panels).
- Create `frontend/src/components/modules/admin/admin-attestation-panel.tsx` (was `AdminAttestationPanel`, repointed to org+member assign).

**Modified (Task 5):**
- `frontend/src/components/modules/admin/admin-config-panel.tsx` — repoint to regenerated config shape.

**New org attestor surfaces (Tasks 6–14)** under `frontend/src/components/modules/organizations/attestor/`:
- `attestor-application-tab.tsx` (gate-checklist container) + gate sub-components.
- `org-nda-panel.tsx`.
- `attestation-offers-tab.tsx` + `accept-and-staff-dialog.tsx` + `reviewing-member-picker.tsx`.
- `org-attestations-tab.tsx` (queue) + reviewing-member workspace wiring.
- `org-attestor-financials-tab.tsx`.
- New routes under `frontend/src/app/(auth)/dashboard/organizations/[orgId]/` for each tab; tab registration in `organization-shell.tsx`.

**New admin surface (Task 15):** `frontend/src/components/modules/admin/admin-org-attestor-review-panel.tsx` + route.

**New public surfaces (Task 16):** `frontend/src/app/attestors/page.tsx` (directory, SSR) + `frontend/src/app/attestors/[orgId]/page.tsx` (profile, SSR) + presentational components under `frontend/src/components/modules/attestation/directory/`.

**Canonical short SDK aliases authored in Task 1 (consumed everywhere later):**

| Alias | Method + path |
|-------|---------------|
| `getOrgAttestorApplication` | GET `/v1/orgs/{org_id}/attestor-application` |
| `createOrgAttestorApplication` | POST `/v1/orgs/{org_id}/attestor-application` |
| `updateOrgAttestorApplication` | PATCH `/v1/orgs/{org_id}/attestor-application` |
| `submitOrgAttestorApplication` | POST `.../attestor-application/submit` |
| `signOrgAttestorUndertakings` | POST `.../attestor-application/sign-undertakings` |
| `uploadOrgAttestorTaxDocument` | POST `.../attestor-application/tax-document` |
| `nominateOrgAttestorTrialMember` | POST `.../attestor-application/nominate-trial-member` |
| `listOrgAttestationOffers` | GET `/v1/orgs/{org_id}/attestation-offers` |
| `acceptOrgAttestationOffer` | POST `.../attestation-offers/{offer_id}/accept` |
| `declineOrgAttestationOffer` | POST `.../attestation-offers/{offer_id}/decline` |
| `listOrgAttestations` | GET `/v1/orgs/{org_id}/attestations` |
| `reassignOrgAttestation` | POST `.../attestations/{attestation_id}/reassign` |
| `getOrgNda` | GET `/v1/orgs/{org_id}/nda` |
| `signOrgNda` | POST `/v1/orgs/{org_id}/nda/sign` |
| `getOrgAttestorEarnings` | GET `/v1/orgs/{org_id}/financials/earnings` |
| `onboardOrgPayoutAccount` | POST `.../financials/payout-accounts` |
| `requestOrgPayout` | POST `.../financials/payouts` |
| `listOrgInvoices` | GET `.../financials/invoices` |
| `listOrgAttestorApplicationsForAdmin` | GET `/v1/admin/org-attestor-applications` |
| `verifyOrgAttestorKyb` | POST `.../{application_id}/verify-kyb` |
| `orgAttestorNeedsInfo` | POST `.../{application_id}/needs-info` |
| `startOrgAttestorTrial` | POST `.../{application_id}/start-trial` |
| `approveOrgAttestor` | POST `.../{application_id}/approve` |
| `rejectOrgAttestor` | POST `.../{application_id}/reject` |
| `suspendOrgAttestorCapability` | POST `/v1/admin/orgs/{org_id}/attestor-capability/suspend` |
| `reinstateOrgAttestorCapability` | POST `.../attestor-capability/reinstate` |
| `revokeOrgAttestorCapability` | POST `.../attestor-capability/revoke` |
| `listAttestorOrgs` | GET `/v1/attestor-orgs` |
| `getAttestorOrg` | GET `/v1/attestor-orgs/{org_id}` |
| `listAttestorOrgCompleted` | GET `/v1/attestor-orgs/{org_id}/completed` |

`adminAssignAttestation` and `adminRefundAttestation` keep their existing aliases (paths unchanged; only the assign request body changed to `{ attestor_org_id, reviewing_member_id }`).

---

## Task 1: Regenerate client + rewrite alias map

**Files:**
- Regenerate: `frontend/src/lib/generated/sdk.gen.ts`, `frontend/src/lib/generated/types.gen.ts`
- Modify: `frontend/scripts/patch-generated-client.mjs`

**Interfaces:**
- Consumes: `contracts/openapi.yaml` (frozen).
- Produces: every short alias in the File Structure table, re-exported from `@/lib/generated/sdk.gen`. All later tasks import from there.

- [ ] **Step 1: Run codegen**

```bash
cd frontend && npm run generate:api
```

Expected: `src/lib/generated/{sdk.gen.ts,types.gen.ts}` rewritten. The patch script will likely warn or leave dead aliases whose long targets no longer exist — that is what Step 2 fixes.

- [ ] **Step 2: Find the new long function names**

For each new endpoint, grep the freshly generated file for the export whose name encodes that path:

```bash
grep -oE "export const [a-zA-Z0-9]+ =" src/lib/generated/sdk.gen.ts | grep -iE "OrgsOrgId(Attestor|Attestation|Nda|Financials)|AdminOrgAttestor|AdminOrgsOrgIdAttestorCapability|AttestorOrgs"
```

Record the exact long name for each row of the alias table.

- [ ] **Step 3: Rewrite the alias map**

In `scripts/patch-generated-client.mjs`, in the `compatibilityAliases` object:
- **Remove** these retired aliases (their endpoints no longer exist): `acceptAttestationOffer`, `declineAttestationOffer`, `listAttestorAssignments`, `listMyAttestorApplications`, `submitAttestorApplication`, `updateAttestorApplication`, `withdrawAttestorApplication`, `rejectAttestorApplication`, `listAttestorApplicationsForAdmin`.
- **Add** every alias from the File Structure table, each mapped to the long name recorded in Step 2. Example entries (verify the long names against Step 2 output):

```js
  getOrgAttestorApplication: "getOrgAttestorApplicationV1OrgsOrgIdAttestorApplicationGet",
  createOrgAttestorApplication: "createOrgAttestorApplicationV1OrgsOrgIdAttestorApplicationPost",
  updateOrgAttestorApplication: "updateOrgAttestorApplicationV1OrgsOrgIdAttestorApplicationPatch",
  submitOrgAttestorApplication: "submitOrgAttestorApplicationV1OrgsOrgIdAttestorApplicationSubmitPost",
  signOrgAttestorUndertakings: "signUndertakingsV1OrgsOrgIdAttestorApplicationSignUndertakingsPost",
  uploadOrgAttestorTaxDocument: "uploadTaxDocumentV1OrgsOrgIdAttestorApplicationTaxDocumentPost",
  nominateOrgAttestorTrialMember: "nominateTrialMemberV1OrgsOrgIdAttestorApplicationNominateTrialMemberPost",
  listOrgAttestationOffers: "listOrgAttestationOffersV1OrgsOrgIdAttestationOffersGet",
  acceptOrgAttestationOffer: "acceptOrgAttestationOfferV1OrgsOrgIdAttestationOffersOfferIdAcceptPost",
  declineOrgAttestationOffer: "declineOrgAttestationOfferV1OrgsOrgIdAttestationOffersOfferIdDeclinePost",
  listOrgAttestations: "listOrgAttestationsV1OrgsOrgIdAttestationsGet",
  reassignOrgAttestation: "reassignOrgAttestationV1OrgsOrgIdAttestationsAttestationIdReassignPost",
  getOrgNda: "getOrgNdaV1OrgsOrgIdNdaGet",
  signOrgNda: "signOrgNdaV1OrgsOrgIdNdaSignPost",
  getOrgAttestorEarnings: "getOrgAttestorEarningsV1OrgsOrgIdFinancialsEarningsGet",
  onboardOrgPayoutAccount: "onboardOrgPayoutAccountV1OrgsOrgIdFinancialsPayoutAccountsPost",
  requestOrgPayout: "requestOrgPayoutV1OrgsOrgIdFinancialsPayoutsPost",
  listOrgInvoices: "listOrgInvoicesV1OrgsOrgIdFinancialsInvoicesGet",
  listOrgAttestorApplicationsForAdmin: "adminListOrgAttestorApplicationsV1AdminOrgAttestorApplicationsGet",
  verifyOrgAttestorKyb: "adminVerifyKybV1AdminOrgAttestorApplicationsApplicationIdVerifyKybPost",
  orgAttestorNeedsInfo: "adminNeedsInfoV1AdminOrgAttestorApplicationsApplicationIdNeedsInfoPost",
  startOrgAttestorTrial: "adminStartTrialV1AdminOrgAttestorApplicationsApplicationIdStartTrialPost",
  approveOrgAttestor: "adminApproveV1AdminOrgAttestorApplicationsApplicationIdApprovePost",
  rejectOrgAttestor: "adminRejectV1AdminOrgAttestorApplicationsApplicationIdRejectPost",
  suspendOrgAttestorCapability: "adminSuspendAttestorCapabilityV1AdminOrgsOrgIdAttestorCapabilitySuspendPost",
  reinstateOrgAttestorCapability: "adminReinstateAttestorCapabilityV1AdminOrgsOrgIdAttestorCapabilityReinstatePost",
  revokeOrgAttestorCapability: "adminRevokeAttestorCapabilityV1AdminOrgsOrgIdAttestorCapabilityRevokePost",
  listAttestorOrgs: "listAttestorOrgsV1AttestorOrgsGet",
  getAttestorOrg: "getAttestorOrgV1AttestorOrgsOrgIdGet",
  listAttestorOrgCompleted: "listAttestorOrgCompletedV1AttestorOrgsOrgIdCompletedGet",
```

- [ ] **Step 4: Re-run codegen so the patch applies the new aliases**

```bash
npm run generate:api
```

Expected: no error; `grep -c "export const getOrgAttestorApplication " src/lib/generated/sdk.gen.ts` returns `1`.

- [ ] **Step 5: Confirm the retired aliases are gone**

```bash
grep -E "acceptAttestationOffer|listAttestorAssignments|submitAttestorApplication" src/lib/generated/sdk.gen.ts
```

Expected: no matches (exit code 1).

- [ ] **Step 6: Typecheck to reveal the blast radius (expected to fail here)**

```bash
npm run typecheck
```

Expected: FAIL — errors in `attestation-workspaces.tsx`, `admin-config-panel.tsx`, and the dead attestor routes. This is the compile-green sweep backlog for Tasks 2–5. Note: `sdk.gen.ts` carries `// @ts-nocheck` (added by the patch script) so the generated file itself never fails typecheck.

- [ ] **Step 7: Commit**

```bash
git add src/lib/generated scripts/patch-generated-client.mjs
git commit -m "Regenerate API client for org-attestor contract; rewrite SDK alias map"
```

---

## Task 2: Delete retired individual-attestor UI

**Files:**
- Delete: `frontend/src/app/(auth)/attestor/applications/page.tsx`, `frontend/src/app/(auth)/attestor/assignments/page.tsx`, `frontend/src/app/(auth)/settings/attestor/page.tsx`
- Delete (if orphaned after above): `frontend/src/app/(auth)/attestor/layout.tsx` and the `attestor/` dir
- Delete: `frontend/src/components/modules/attestation/attestor-application-prompt.tsx`
- Delete tests: `frontend/tests/unit/components/attestation/attestor-application-prompt.test.tsx`, `frontend/tests/unit/components/attestation/attestor-application-panel.test.tsx`
- Modify: any nav/link source that routes to the deleted paths

**Interfaces:**
- Consumes: nothing.
- Produces: a tree with no references to `/attestor/applications`, `/attestor/assignments`, `/settings/attestor`, or `attestor-application-prompt`.

- [ ] **Step 1: Find every inbound reference**

```bash
grep -rn "attestor/applications\|attestor/assignments\|settings/attestor\|attestor-application-prompt\|AttestorApplicationPrompt" src app tests
```

Record each hit; the nav/redirect hits must be edited in Step 3.

- [ ] **Step 2: Delete the routes, component, and tests**

```bash
git rm -r "src/app/(auth)/attestor/applications" "src/app/(auth)/attestor/assignments" "src/app/(auth)/settings/attestor"
git rm src/components/modules/attestation/attestor-application-prompt.tsx
git rm tests/unit/components/attestation/attestor-application-prompt.test.tsx tests/unit/components/attestation/attestor-application-panel.test.tsx
```

If `src/app/(auth)/attestor/` now contains only `layout.tsx` with no sibling routes that survive, also `git rm -r "src/app/(auth)/attestor"`.

- [ ] **Step 3: Remove nav links / redirects to the deleted paths**

For each non-test hit from Step 1 (e.g. a dashboard nav array, a role-based post-login redirect that sent `attestor` users to `/attestor/assignments`), remove that entry. The `attestor` role is now org-derived; a user with a derived attestor role reaches attestation work through their organization, so a post-login redirect for `attestor` should fall through to the default dashboard.

- [ ] **Step 4: Typecheck — dead-route errors should be gone**

```bash
npm run typecheck
```

Expected: still FAILS, but now only in `attestation-workspaces.tsx` and `admin-config-panel.tsx` (the drift files). No remaining errors reference the deleted routes/component.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Delete retired individual-attestor routes, prompt, and tests"
```

---

## Task 3: Split requestor panel out of the God component + repoint

**Files:**
- Create: `frontend/src/components/modules/attestation/attestation-status.tsx` (shared helpers)
- Create: `frontend/src/components/modules/attestation/requestor-panel.tsx`
- Create test: `frontend/tests/unit/components/attestation/requestor-panel.test.tsx`
- Modify: `frontend/src/components/modules/attestation/attestation-workspaces.tsx` (remove the moved panel; source lines for `AttestationRequestorPanel` are ~125–344, shared helpers `StatusTag` ~54–114 and `ErrorMessage` ~115–124, cards `HeaderCard`/`AttestationCard`/`ApplicationList` ~1006–1173)
- Modify: any importer of `AttestationRequestorPanel` (e.g. `src/app/(auth)/attestations/page.tsx`)

**Interfaces:**
- Consumes: `requestAttestation`, `listAttestations` (existing aliases), `getAccessTokenHeaders`.
- Produces: `export function RequestorPanel()` from `attestation/requestor-panel.tsx`; `StatusTag`, `ErrorMessage`, `AttestationCard` from `attestation/attestation-status.tsx`.

- [ ] **Step 1: Read the current source**

Read `attestation-workspaces.tsx` lines 54–344 and 1006–1173 to capture the exact JSX, className tokens, and request/response handling for the requestor panel and the shared helpers. Preserve styling verbatim.

- [ ] **Step 2: Write the failing test**

```tsx
// tests/unit/components/attestation/requestor-panel.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RequestorPanel } from "@/components/modules/attestation/requestor-panel";
import { listAttestations } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  listAttestations: vi.fn(),
  requestAttestation: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data, error: undefined,
  request: new Request("http://t"), response: new Response(null, { status: 200 }),
});

describe("RequestorPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the attestor org identity and never the reviewing member", async () => {
    vi.mocked(listAttestations).mockResolvedValue(
      ok({ attestations: [{
        id: "att-1", status: "in_review", target_type: "framework",
        attestor_org_id: "org-9", currency: "USD", fee_amount: "500.00",
      }] }) as any,
    );
    render(<RequestorPanel />);
    await waitFor(() => expect(screen.getByText(/org-9/)).toBeInTheDocument());
    expect(screen.queryByText(/reviewing_member/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run it — fails (module missing)**

```bash
npx vitest run tests/unit/components/attestation/requestor-panel.test.tsx
```

Expected: FAIL — cannot resolve `requestor-panel`.

- [ ] **Step 4: Create the shared helpers file**

Move `StatusTag`, `ErrorMessage`, and the card presentational helpers from `attestation-workspaces.tsx` into `attestation/attestation-status.tsx`, exporting each. Keep their implementations byte-for-byte (same classes).

- [ ] **Step 5: Create `requestor-panel.tsx`**

Move `AttestationRequestorPanel` verbatim into `requestor-panel.tsx`, renamed `export function RequestorPanel()`. Repoint: wherever it read `attestation.attestor_id`, read `attestation.attestor_org_id` and render the org identity. Import shared helpers from `./attestation-status`. Do not reference `reviewing_member_id` (not in this schema).

- [ ] **Step 6: Update importers**

In `src/app/(auth)/attestations/page.tsx` (and any other importer found via `grep -rn "AttestationRequestorPanel" src app`), import `RequestorPanel` from the new path.

- [ ] **Step 7: Run the test — passes**

```bash
npx vitest run tests/unit/components/attestation/requestor-panel.test.tsx
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Extract + repoint attestation requestor panel to org identity"
```

---

## Task 4: Move admin attestation panel + repoint assign to org+member

**Files:**
- Create: `frontend/src/components/modules/admin/admin-attestation-panel.tsx`
- Create test: `frontend/tests/unit/components/admin/admin-attestation-panel.test.tsx`
- Modify: `frontend/src/components/modules/attestation/attestation-workspaces.tsx` (remove `AdminAttestationPanel`, ~704–1005; after this the file has no remaining exports — `git rm` it)
- Modify: `frontend/src/app/(auth)/admin/attestations/page.tsx` (import from new path)

**Interfaces:**
- Consumes: `adminAssignAttestation` (body now `{ attestor_org_id, reviewing_member_id }`), `adminRefundAttestation`, shared helpers from `attestation/attestation-status`.
- Produces: `export function AdminAttestationPanel()` from `admin/admin-attestation-panel.tsx`.

- [ ] **Step 1: Write the failing test**

```tsx
// tests/unit/components/admin/admin-attestation-panel.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminAttestationPanel } from "@/components/modules/admin/admin-attestation-panel";
import { adminAssignAttestation, listAttestations } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  listAttestations: vi.fn(),
  adminAssignAttestation: vi.fn(),
  adminRefundAttestation: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data, error: undefined,
  request: new Request("http://t"), response: new Response(null, { status: 200 }),
});

describe("AdminAttestationPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("posts attestor_org_id and reviewing_member_id when assigning", async () => {
    vi.mocked(listAttestations).mockResolvedValue(
      ok({ attestations: [{ id: "att-1", status: "needs_admin", target_type: "framework" }] }) as any,
    );
    vi.mocked(adminAssignAttestation).mockResolvedValue(ok({ id: "att-1" }) as any);
    render(<AdminAttestationPanel />);
    await waitFor(() => screen.getByText(/att-1/));
    fireEvent.change(screen.getByLabelText(/attestor org/i), { target: { value: "org-2" } });
    fireEvent.change(screen.getByLabelText(/reviewing member/i), { target: { value: "mem-3" } });
    fireEvent.click(screen.getByRole("button", { name: /assign/i }));
    await waitFor(() =>
      expect(vi.mocked(adminAssignAttestation)).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { attestor_org_id: "org-2", reviewing_member_id: "mem-3" },
        }),
      ),
    );
  });
});
```

- [ ] **Step 2: Run it — fails (module missing)**

```bash
npx vitest run tests/unit/components/admin/admin-attestation-panel.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Create `admin-attestation-panel.tsx`**

Move `AdminAttestationPanel` from `attestation-workspaces.tsx`. Replace the single attestor-id assign field with two fields — `attestor org` (id) and `reviewing member` (id) — and post `body: { attestor_org_id, reviewing_member_id }` via `adminAssignAttestation`. Import shared helpers from `@/components/modules/attestation/attestation-status`. Keep refund logic unchanged.

- [ ] **Step 4: Delete the now-empty God component + repoint route**

```bash
git rm src/components/modules/attestation/attestation-workspaces.tsx
```

In `src/app/(auth)/admin/attestations/page.tsx`, import `AdminAttestationPanel` from `@/components/modules/admin/admin-attestation-panel`.

- [ ] **Step 5: Run the test — passes; then full typecheck**

```bash
npx vitest run tests/unit/components/admin/admin-attestation-panel.test.tsx
npm run typecheck
```

Expected: test PASS; typecheck now fails only in `admin-config-panel.tsx` (Task 5).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Move admin attestation panel; repoint assign to org + reviewing member"
```

---

## Task 5: Repoint admin platform-config panel

**Files:**
- Modify: `frontend/src/components/modules/admin/admin-config-panel.tsx`
- Modify: `frontend/tests/unit/components/admin/admin-config-panel.test.tsx` (fixture keys if they changed)

**Interfaces:**
- Consumes: `listPlatformConfigV1AdminConfigGet`, `updatePlatformConfigV1AdminConfigPatch`, regenerated `types.gen.ts` config shape.
- Produces: a typecheck-clean admin config panel.

- [ ] **Step 1: Identify the drift**

```bash
npm run typecheck 2>&1 | grep admin-config-panel
```

Read each flagged line. The config item/response type changed with regen (field renames or new attestor-related keys). Map each old field access to the new type.

- [ ] **Step 2: Repoint the component**

Edit `admin-config-panel.tsx` so every property access matches the regenerated config item type (from `types.gen.ts`). Do not add new UI — only reconcile types. Preserve the existing group/search/read-only-notice structure.

- [ ] **Step 3: Update the test fixture if keys changed**

If regen renamed config fields, update the `configItems` fixture in `admin-config-panel.test.tsx` to the new field names so the mock matches the type.

- [ ] **Step 4: Typecheck + test — both green**

```bash
npm run typecheck
npx vitest run tests/unit/components/admin/admin-config-panel.test.tsx
```

Expected: typecheck PASS (whole app now compiles); test PASS.

- [ ] **Step 5: Lint + full test sweep**

```bash
npm run lint && npm run test
```

Expected: lint clean; all tests pass. The compile-green sweep is complete.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Repoint admin config panel to regenerated config shape"
```

---

## Task 6: Attestor tab scaffold + gate-checklist container

**Files:**
- Create: `frontend/src/components/modules/organizations/attestor/attestor-application-tab.tsx`
- Create: `frontend/src/app/(auth)/dashboard/organizations/[orgId]/attestor/page.tsx`
- Create test: `frontend/tests/unit/components/organizations/attestor/attestor-application-tab.test.tsx`
- Modify: `frontend/src/components/modules/organizations/organization-shell.tsx` (register the tab)

**Interfaces:**
- Consumes: `getOrgAttestorApplication`, `OrganizationProvider` context (`useOrganization()` → `{ orgId, role }`), `getAccessTokenHeaders`.
- Produces: `export function AttestorApplicationTab()`; the org-shell "Attestor" tab (owner/admin only).

**Backend response shape** (from `getOrgAttestorApplication`): an application object with `status` (`draft|submitted|needs_info|approved|rejected`) and per-gate fields (`kyb_verified_at`, `credentials_reviewed_at`, `coi_signed_at`, `confidentiality_signed_at`, `payout_account_id`, `tax_document_id`, `trial_status`, `admin_feedback`). Verify exact field names against `types.gen.ts` after Task 1 and use them; if a field is absent, render that gate as "not started".

- [ ] **Step 1: Write the failing test**

```tsx
// tests/unit/components/organizations/attestor/attestor-application-tab.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AttestorApplicationTab } from "@/components/modules/organizations/attestor/attestor-application-tab";
import { getOrgAttestorApplication } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "owner" }),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ getOrgAttestorApplication: vi.fn() }));

const ok = <T,>(data: T) => ({
  data, error: undefined,
  request: new Request("http://t"), response: new Response(null, { status: 200 }),
});

describe("AttestorApplicationTab", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the 8 activation gates with per-gate status", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue(
      ok({ status: "submitted", kyb_verified_at: "2026-07-01T00:00:00Z", admin_feedback: null }) as any,
    );
    render(<AttestorApplicationTab />);
    await waitFor(() => expect(screen.getByText(/KYB verification/i)).toBeInTheDocument());
    expect(screen.getByText(/Apply/i)).toBeInTheDocument();
    expect(screen.getByText(/Trial attestation/i)).toBeInTheDocument();
    expect(screen.getByText(/Activation/i)).toBeInTheDocument();
    // KYB gate shows verified
    expect(screen.getByText(/verified/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it — fails**

```bash
npx vitest run tests/unit/components/organizations/attestor/attestor-application-tab.test.tsx
```

Expected: FAIL — module missing.

- [ ] **Step 3: Implement the gate-checklist container**

Create `attestor-application-tab.tsx` (client component). On mount, call `getOrgAttestorApplication({ path: { org_id: orgId }, headers: getAccessTokenHeaders() })`. Render a fixed ordered list of 8 gate cards: `Apply`, `KYB verification`, `Org credentials`, `COI + confidentiality undertaking`, `Payout account`, `Tax document`, `Trial attestation`, `Activation`. Each card shows a `StatusTag` derived from the matching application field (present/timestamp → "complete/verified"; `needs_info` → show `admin_feedback`; absent → "not started"). Gate action bodies are stubbed here as disabled placeholders; Tasks 7–8 fill them. Use the loading `Spinner` and error-card patterns from `organization-shell.tsx`. Keep the file focused — extract gate cards into sub-components if it approaches 200 lines.

- [ ] **Step 4: Register the tab + route**

In `organization-shell.tsx`, add to the `tabs` array (inside the `if (isAdmin)` block, since application is owner/admin): `tabs.push({ id: "attestor", label: "Attestor" });`. Create `app/(auth)/dashboard/organizations/[orgId]/attestor/page.tsx` that renders `<AttestorApplicationTab />` (mirror the existing sibling route pages like `.../members/page.tsx`).

- [ ] **Step 5: Run the test — passes**

```bash
npx vitest run tests/unit/components/organizations/attestor/attestor-application-tab.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add org attestor application tab with gate checklist"
```

---

## Task 7: Apply gate — draft, edit, submit, needs_info

**Files:**
- Create: `frontend/src/components/modules/organizations/attestor/apply-gate.tsx`
- Create test: `frontend/tests/unit/components/organizations/attestor/apply-gate.test.tsx`
- Modify: `frontend/src/components/modules/organizations/attestor/attestor-application-tab.tsx` (mount `ApplyGate` in the Apply card)

**Interfaces:**
- Consumes: `createOrgAttestorApplication`, `updateOrgAttestorApplication`, `submitOrgAttestorApplication`, org context.
- Produces: `export function ApplyGate({ application, orgId, onChange }: { application: <AppType> | null; orgId: string; onChange: () => void })`. `onChange` re-fetches the application in the parent.

**Application draft fields** (verify names in `types.gen.ts`): `legal_name`, `incorporation_document_id`, `credentials_summary`, `sample_work`, `references`. Submit requires all present (backend enforces; surface the 422 message on failure).

- [ ] **Step 1: Write the failing test**

```tsx
// tests/unit/components/organizations/attestor/apply-gate.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApplyGate } from "@/components/modules/organizations/attestor/apply-gate";
import { submitOrgAttestorApplication, updateOrgAttestorApplication } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  createOrgAttestorApplication: vi.fn(),
  updateOrgAttestorApplication: vi.fn(),
  submitOrgAttestorApplication: vi.fn(),
}));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("ApplyGate", () => {
  beforeEach(() => vi.clearAllMocks());

  it("saves an edited draft field", async () => {
    vi.mocked(updateOrgAttestorApplication).mockResolvedValue(ok({ status: "draft" }) as any);
    const onChange = vi.fn();
    render(<ApplyGate orgId="org-1" onChange={onChange}
      application={{ status: "draft", legal_name: "", credentials_summary: "" } as any} />);
    fireEvent.change(screen.getByLabelText(/legal name/i), { target: { value: "Audit Ltd" } });
    fireEvent.click(screen.getByRole("button", { name: /save draft/i }));
    await waitFor(() => expect(vi.mocked(updateOrgAttestorApplication)).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-1" }, body: expect.objectContaining({ legal_name: "Audit Ltd" }) }),
    ));
    expect(onChange).toHaveBeenCalled();
  });

  it("shows admin feedback when status is needs_info", () => {
    render(<ApplyGate orgId="org-1" onChange={vi.fn()}
      application={{ status: "needs_info", admin_feedback: "Add incorporation cert" } as any} />);
    expect(screen.getByText(/Add incorporation cert/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it — fails**

```bash
npx vitest run tests/unit/components/organizations/attestor/apply-gate.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement `ApplyGate`**

Render the draft form (labelled inputs for `legal_name`, `credentials_summary`, `sample_work`, `references`; an incorporation-document upload affordance that stores the returned id). "Save draft" calls `updateOrgAttestorApplication` (or `createOrgAttestorApplication` if `application` is null), then `onChange()`. "Submit application" calls `submitOrgAttestorApplication`; on 422 render the response error via `describeGeneratedError`. When `status === "needs_info"`, show `admin_feedback` prominently and keep fields editable. When `status` is beyond draft/needs_info, render read-only. Match existing form-field styling from `organization-profile.tsx`.

- [ ] **Step 4: Mount it in the tab**

In `attestor-application-tab.tsx`, render `<ApplyGate application={application} orgId={orgId} onChange={reload} />` inside the Apply card, where `reload` re-invokes `getOrgAttestorApplication`.

- [ ] **Step 5: Run the test — passes**

```bash
npx vitest run tests/unit/components/organizations/attestor/apply-gate.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add attestor application Apply gate (draft/submit/needs_info)"
```

---

## Task 8: Undertakings (owner+TOTP), tax-document upload, trial-member nomination gates

**Files:**
- Create: `frontend/src/components/modules/organizations/attestor/undertakings-gate.tsx`
- Create: `frontend/src/components/modules/organizations/attestor/tax-document-gate.tsx`
- Create: `frontend/src/components/modules/organizations/attestor/trial-member-gate.tsx`
- Create tests: one `.test.tsx` per gate under `tests/unit/components/organizations/attestor/`
- Modify: `attestor-application-tab.tsx` (mount the three gates; pass `role`)

**Interfaces:**
- Consumes: `signOrgAttestorUndertakings` (owner + TOTP), `uploadOrgAttestorTaxDocument`, `nominateOrgAttestorTrialMember`, `listOrgMembers`/existing member-list alias for the trial picker, the existing TOTP step-up flow helper, org context (`role`).
- Produces: `UndertakingsGate`, `TaxDocumentGate`, `TrialMemberGate` components.

**TOTP step-up:** reuse the project's existing 2FA step-up path (the same one payout/email-change use). Find it: `grep -rn "totp\|2fa\|stepUp\|verifyTotp" src/components src/lib | grep -iv test`. The undertakings action must collect a TOTP code and pass it as the backend expects (verify the `signOrgAttestorUndertakings` body in `types.gen.ts`).

- [ ] **Step 1: Write the failing test for the undertakings gate**

```tsx
// tests/unit/components/organizations/attestor/undertakings-gate.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { UndertakingsGate } from "@/components/modules/organizations/attestor/undertakings-gate";

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ signOrgAttestorUndertakings: vi.fn() }));

describe("UndertakingsGate", () => {
  it("disables signing for non-owner admins with an explanation", () => {
    render(<UndertakingsGate orgId="org-1" role="admin" application={{ status: "submitted" } as any} onChange={vi.fn()} />);
    expect(screen.getByText(/only the organization owner/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sign/i })).toBeNull();
  });
});
```

- [ ] **Step 2: Run it — fails**

```bash
npx vitest run tests/unit/components/organizations/attestor/undertakings-gate.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement the three gates**

`UndertakingsGate`: owner-only. If `role !== "owner"`, render "Only the organization owner can sign the confidentiality undertaking." and no button. For the owner, render a sign action that runs the existing TOTP step-up and calls `signOrgAttestorUndertakings`, then `onChange()`. Show signed state from `coi_signed_at`/`confidentiality_signed_at`.

`TaxDocumentGate`: presigned upload via `uploadOrgAttestorTaxDocument` (owner/admin). On success store the returned id and `onChange()`. Never log the presigned URL. Show uploaded state from `tax_document_id`.

`TrialMemberGate`: owner/admin. Member picker (NDA-signed members) → `nominateOrgAttestorTrialMember({ body: { trial_member_id } })`, then `onChange()`. Show `trial_status`/grade when present. Read-only until admin starts the trial.

- [ ] **Step 4: Add per-gate happy-path tests + implementations (TDD, one at a time)**

For `TaxDocumentGate` and `TrialMemberGate`, add a test asserting the correct SDK call with the correct body, then confirm green. Keep each cycle to one behavior.

- [ ] **Step 5: Mount all three in the tab, then run the attestor test suite**

```bash
npx vitest run tests/unit/components/organizations/attestor
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add attestor undertakings (owner+TOTP), tax-doc, and trial-member gates"
```

---

## Task 9: Org NDA panel + invite-accept NDA prompt

**Files:**
- Create: `frontend/src/components/modules/organizations/org-nda-panel.tsx`
- Create test: `frontend/tests/unit/components/organizations/org-nda-panel.test.tsx`
- Modify: `frontend/src/components/modules/organizations/invitation-accept.tsx` (surface NDA sign when the accept response signals it)
- Modify: `organization-shell.tsx` (add an "NDA" tab visible to all members when capability is pending/active) + new route `.../[orgId]/nda/page.tsx`

**Interfaces:**
- Consumes: `getOrgNda`, `signOrgNda`, org context, the existing invitation-accept response type (check whether it carries an `nda_required` / `nda_version` signal in `types.gen.ts`).
- Produces: `export function OrgNdaPanel()`.

- [ ] **Step 1: Write the failing test**

```tsx
// tests/unit/components/organizations/org-nda-panel.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OrgNdaPanel } from "@/components/modules/organizations/org-nda-panel";
import { getOrgNda, signOrgNda } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "member" }),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ getOrgNda: vi.fn(), signOrgNda: vi.fn() }));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("OrgNdaPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("signs the current NDA version", async () => {
    vi.mocked(getOrgNda).mockResolvedValue(ok({ version: "v2", text: "Confidential.", signed: false }) as any);
    vi.mocked(signOrgNda).mockResolvedValue(ok({ signed: true }) as any);
    render(<OrgNdaPanel />);
    await waitFor(() => screen.getByText(/Confidential\./));
    fireEvent.click(screen.getByRole("button", { name: /sign/i }));
    await waitFor(() => expect(vi.mocked(signOrgNda)).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-1" }, body: expect.objectContaining({ version: "v2" }) }),
    ));
  });
});
```

- [ ] **Step 2: Run it — fails**

```bash
npx vitest run tests/unit/components/organizations/org-nda-panel.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement `OrgNdaPanel`**

Fetch `getOrgNda`. Render version + NDA text + signature status. If unsigned (or an older version than current), show a "Sign NDA" button calling `signOrgNda({ body: { version } })` then reloading. If signed and current, show a signed confirmation. Verify field names (`version`, `text`, `signed`/`signed_version`) against `types.gen.ts`.

- [ ] **Step 4: Wire the invite-accept prompt**

In `invitation-accept.tsx`, if the accept response signals NDA requirement (`nda_required`/`nda_version`), render the NDA text + a sign action after joining, with copy making explicit that accepting without signing still joins the org but leaves the member unassignable. Reuse `OrgNdaPanel`'s sign call or a shared inline signer.

- [ ] **Step 5: Register the NDA tab + route**

In `organization-shell.tsx`, push an `{ id: "nda", label: "NDA" }` tab (visible to all roles when the org's attestor capability is `pending`/`active`; read capability from context/org data). Create `.../[orgId]/nda/page.tsx` rendering `<OrgNdaPanel />`.

- [ ] **Step 6: Run tests — pass**

```bash
npx vitest run tests/unit/components/organizations/org-nda-panel.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add org NDA panel + invite-accept NDA prompt"
```

---

## Task 10: Attestation offers list tab

**Files:**
- Create: `frontend/src/components/modules/organizations/attestor/attestation-offers-tab.tsx`
- Create test: `frontend/tests/unit/components/organizations/attestor/attestation-offers-tab.test.tsx`
- Modify: `organization-shell.tsx` (register "Offers" tab, owner/admin) + route `.../[orgId]/offers/page.tsx`

**Interfaces:**
- Consumes: `listOrgAttestationOffers`, org context.
- Produces: `export function AttestationOffersTab()`; renders one row per offer with an "Accept" affordance that opens the dialog built in Task 11 (stubbed button here).

- [ ] **Step 1: Write the failing test**

```tsx
// tests/unit/components/organizations/attestor/attestation-offers-tab.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AttestationOffersTab } from "@/components/modules/organizations/attestor/attestation-offers-tab";
import { listOrgAttestationOffers } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "owner" }),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ listOrgAttestationOffers: vi.fn() }));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("AttestationOffersTab", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists offers with target and expiry, empty state otherwise", async () => {
    vi.mocked(listOrgAttestationOffers).mockResolvedValueOnce(
      ok({ offers: [{ id: "offer-1", attestation_id: "att-1", status: "offered",
        expires_at: "2026-07-20T00:00:00Z", requested_specializations: ["tax"] }] }) as any,
    );
    render(<AttestationOffersTab />);
    await waitFor(() => expect(screen.getByText(/offer-1|att-1/)).toBeInTheDocument());
    expect(screen.getByText(/tax/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it — fails**

```bash
npx vitest run tests/unit/components/organizations/attestor/attestation-offers-tab.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement the offers list**

Fetch `listOrgAttestationOffers({ path: { org_id: orgId }, headers })`. Render each offer: attestation target/id, requested specializations/jurisdictions, an expiry countdown (compute from `expires_at`). Each row has "Accept" and "Decline" buttons (wired in Task 11 — here they can be present but no-op/disabled). Empty state when no offers. Loading/error patterns as elsewhere.

- [ ] **Step 4: Register tab + route**

Push `{ id: "offers", label: "Offers" }` (owner/admin) in `organization-shell.tsx`; create `.../[orgId]/offers/page.tsx` → `<AttestationOffersTab />`.

- [ ] **Step 5: Run the test — passes**

```bash
npx vitest run tests/unit/components/organizations/attestor/attestation-offers-tab.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add org attestation offers list tab"
```

---

## Task 11: Accept-and-staff dialog + decline + reassign

**Files:**
- Create: `frontend/src/components/modules/organizations/attestor/reviewing-member-picker.tsx`
- Create: `frontend/src/components/modules/organizations/attestor/accept-and-staff-dialog.tsx`
- Create tests: `accept-and-staff-dialog.test.tsx`, `reviewing-member-picker.test.tsx`
- Modify: `attestation-offers-tab.tsx` (wire Accept → dialog, Decline → `declineOrgAttestationOffer`)
- Modify: `org-attestations-tab.tsx` reassign control is added in Task 12; here only offer accept/decline

**Interfaces:**
- Consumes: `acceptOrgAttestationOffer` (body `{ reviewing_member_id }`), `declineOrgAttestationOffer`, the existing org members list alias (for the picker), member NDA + active-count fields.
- Produces: `ReviewingMemberPicker` ({ orgId, value, onChange, disableIneligible }) and `AcceptAndStaffDialog` ({ orgId, offerId, onDone }).

**Eligibility:** a member is selectable only if NDA-signed and under the concurrency cap (`< 5` active attestations). Surface the reason a member is disabled ("No NDA on file", "At capacity"). Field names for NDA status / active count come from the members response — verify in `types.gen.ts`; if the list endpoint lacks them, the backend still enforces on accept (a 409/422), so also surface that response error.

- [ ] **Step 1: Write the failing dialog test**

```tsx
// tests/unit/components/organizations/attestor/accept-and-staff-dialog.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AcceptAndStaffDialog } from "@/components/modules/organizations/attestor/accept-and-staff-dialog";
import { acceptOrgAttestationOffer, listOrgMembers } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn((r) => (r?.response?.status === 409 ? "Member at capacity" : "err")),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ acceptOrgAttestationOffer: vi.fn(), listOrgMembers: vi.fn() }));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("AcceptAndStaffDialog", () => {
  beforeEach(() => vi.clearAllMocks());

  it("accepts with the chosen reviewing_member_id", async () => {
    vi.mocked(listOrgMembers).mockResolvedValue(
      ok({ members: [{ id: "mem-1", display_name: "Ada", nda_signed: true, active_attestations: 0 }] }) as any,
    );
    vi.mocked(acceptOrgAttestationOffer).mockResolvedValue(ok({ status: "accepted" }) as any);
    const onDone = vi.fn();
    render(<AcceptAndStaffDialog orgId="org-1" offerId="offer-1" onDone={onDone} />);
    await waitFor(() => screen.getByText(/Ada/));
    fireEvent.click(screen.getByLabelText(/Ada/));
    fireEvent.click(screen.getByRole("button", { name: /accept/i }));
    await waitFor(() => expect(vi.mocked(acceptOrgAttestationOffer)).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { org_id: "org-1", offer_id: "offer-1" },
        body: { reviewing_member_id: "mem-1" },
      }),
    ));
    expect(onDone).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run it — fails**

```bash
npx vitest run tests/unit/components/organizations/attestor/accept-and-staff-dialog.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement the picker + dialog**

`ReviewingMemberPicker`: fetches org members, renders a radio/option per member, disables ineligible members with the reason label. `AcceptAndStaffDialog`: modal (full-screen on mobile, centered on `md:` per CLAUDE.md) hosting the picker + Accept/Cancel. Accept calls `acceptOrgAttestationOffer({ path: { org_id, offer_id }, body: { reviewing_member_id } })`; on 409/422 render the response error (e.g. "Member at capacity"); on success `onDone()`.

- [ ] **Step 4: Wire the tab**

In `attestation-offers-tab.tsx`, Accept opens `AcceptAndStaffDialog`; Decline calls `declineOrgAttestationOffer({ path: { org_id, offer_id } })` then reloads. Add a picker unit test (ineligible member is disabled with reason) and confirm green.

- [ ] **Step 5: Run the attestor suite — passes**

```bash
npx vitest run tests/unit/components/organizations/attestor
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add accept-and-staff dialog, member picker, and decline wiring"
```

---

## Task 12: Org attestation queue + reassign

**Files:**
- Create: `frontend/src/components/modules/organizations/attestor/org-attestations-tab.tsx`
- Create test: `frontend/tests/unit/components/organizations/attestor/org-attestations-tab.test.tsx`
- Modify: `organization-shell.tsx` (register "Attestations" tab) + route `.../[orgId]/attestations/page.tsx`

**Interfaces:**
- Consumes: `listOrgAttestations`, `reassignOrgAttestation`, org context (`role`).
- Produces: `export function OrgAttestationsTab()`; links each row to the workspace (Task 13).

**Visibility rule:** owner/admin see all org attestations (row shows reviewing member); a plain member sees only their own and the reviewing-member column is not shown to non-admins. Reassign control appears only for owner/admin AND only while `review_started_at` is null.

- [ ] **Step 1: Write the failing test**

```tsx
// tests/unit/components/organizations/attestor/org-attestations-tab.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OrgAttestationsTab } from "@/components/modules/organizations/attestor/org-attestations-tab";
import { listOrgAttestations } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
let mockRole = "owner";
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: mockRole }),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ listOrgAttestations: vi.fn(), reassignOrgAttestation: vi.fn() }));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("OrgAttestationsTab", () => {
  beforeEach(() => { vi.clearAllMocks(); mockRole = "owner"; });

  it("shows the reviewing member column for owner/admin", async () => {
    vi.mocked(listOrgAttestations).mockResolvedValue(
      ok({ attestations: [{ id: "att-1", status: "in_review", reviewing_member_id: "mem-1",
        reviewing_member_name: "Ada", review_started_at: null }] }) as any,
    );
    render(<OrgAttestationsTab />);
    await waitFor(() => expect(screen.getByText(/Ada/)).toBeInTheDocument());
  });

  it("hides the reviewing member from a plain member view", async () => {
    mockRole = "member";
    vi.mocked(listOrgAttestations).mockResolvedValue(
      ok({ attestations: [{ id: "att-1", status: "in_review", reviewing_member_name: "Ada" }] }) as any,
    );
    render(<OrgAttestationsTab />);
    await waitFor(() => screen.getByText(/att-1/));
    expect(screen.queryByText(/Ada/)).toBeNull();
  });
});
```

- [ ] **Step 2: Run it — fails**

```bash
npx vitest run tests/unit/components/organizations/attestor/org-attestations-tab.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement the queue**

Fetch `listOrgAttestations`. Render a card-stack on mobile / table on `md:` (per CLAUDE.md). Columns: target, status, dates, and — **only when `role` is owner/admin** — reviewing member. When owner/admin and `review_started_at == null`, show a "Reassign" action opening the `ReviewingMemberPicker` (from Task 11) that calls `reassignOrgAttestation({ path: { org_id, attestation_id }, body: { reviewing_member_id } })`. Each row links to the workspace route (Task 13). Do not render reviewing-member identity for non-admin roles.

- [ ] **Step 4: Register tab + route; run tests**

Push `{ id: "attestations", label: "Attestations" }` in `organization-shell.tsx` (all roles; content self-gates). Create `.../[orgId]/attestations/page.tsx` → `<OrgAttestationsTab />`.

```bash
npx vitest run tests/unit/components/organizations/attestor/org-attestations-tab.test.tsx
```

Expected: PASS (both cases).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add org attestation queue with role-gated reviewing member + reassign"
```

---

## Task 13: Reviewing-member workspace (reuse + repoint)

**Files:**
- Locate the existing attestor workspace component (Step 1 finds the exact file).
- Create: `frontend/src/app/(auth)/dashboard/organizations/[orgId]/attestations/[attestationId]/page.tsx`
- Modify: the existing workspace component (repoint any individual-attestor assumptions to org context)
- Create/modify test: workspace repoint test

**Interfaces:**
- Consumes: existing attestor workspace endpoints (rubric scores, annotations, clarifications, document uploads, report submission) — these are re-pointed backend-side to guard on `reviewing_member_id`.
- Produces: a workspace route reachable from the queue; write access for the assigned reviewing member, read-only for owner/admin.

- [ ] **Step 1: Find the workspace component + its endpoints**

```bash
grep -rln "rubric\|submitAttestationReport\|acceptAttestationReport\|clarification\|annotation" src/components src/app | grep -iv test
```

Read the primary match. Identify any assumption that the current user *is* the attestor (e.g. "your assignment", a `listAttestorAssignments` call — now removed) and the report-submit call site.

- [ ] **Step 2: Write the failing repoint test**

Write a test that renders the workspace for an attestation whose `reviewing_member_id` matches the current member (write mode: report-submit control present) and one where it does not but the viewer is owner/admin (read-only: no submit control). Assert on presence/absence of the submit control. Mock the workspace fetch + `submitAttestationReport`.

```bash
npx vitest run <workspace-test-path>
```

Expected: FAIL.

- [ ] **Step 3: Repoint the component**

Replace removed `listAttestorAssignments`-style data with the org attestation context: the workspace loads the attestation by id and determines write vs read from whether the current member is the `reviewing_member_id` (write) or an owner/admin (read-only). Keep rubric/annotation/clarification/upload/report-submit calls (their endpoints are unchanged in path; the guard moved server-side). Remove any "my assignments" navigation that referenced deleted routes.

- [ ] **Step 4: Add the org-scoped workspace route**

Create `.../[orgId]/attestations/[attestationId]/page.tsx` rendering the workspace for that attestation, inside `OrganizationProvider`. Link the queue rows (Task 12) here.

- [ ] **Step 5: Run tests — pass**

```bash
npx vitest run <workspace-test-path>
```

Expected: PASS. If reuse fights the component (assumptions too deep to repoint cleanly), STOP and escalate rather than force it (design spec risk note).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Repoint attestor workspace to org reviewing-member context"
```

---

## Task 14: Org attestor financials tab

**Files:**
- Create: `frontend/src/components/modules/organizations/attestor/org-attestor-financials-tab.tsx`
- Create test: `frontend/tests/unit/components/organizations/attestor/org-attestor-financials-tab.test.tsx`
- Modify: `organization-shell.tsx` (register "Financials" tab, owner/admin) + route `.../[orgId]/financials/page.tsx`

**Interfaces:**
- Consumes: `getOrgAttestorEarnings`, `onboardOrgPayoutAccount`, `requestOrgPayout` (TOTP-gated), `listOrgInvoices`, existing TOTP step-up, org context.
- Produces: `export function OrgAttestorFinancialsTab()`.

**Gating:** payout request enabled only when a payout account exists AND the application is approved. TOTP step-up (requester's own) before `requestOrgPayout`. Never render payout-account detail or tax docs in any list.

- [ ] **Step 1: Write the failing test**

```tsx
// tests/unit/components/organizations/attestor/org-attestor-financials-tab.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OrgAttestorFinancialsTab } from "@/components/modules/organizations/attestor/org-attestor-financials-tab";
import { getOrgAttestorEarnings, listOrgInvoices } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "owner" }),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  getOrgAttestorEarnings: vi.fn(), onboardOrgPayoutAccount: vi.fn(),
  requestOrgPayout: vi.fn(), listOrgInvoices: vi.fn(),
}));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("OrgAttestorFinancialsTab", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders earnings and disables payout without an approved account", async () => {
    vi.mocked(getOrgAttestorEarnings).mockResolvedValue(
      ok({ total_earned: "450.00", currency: "USD", payout_account_id: null, application_approved: false, transactions: [] }) as any,
    );
    vi.mocked(listOrgInvoices).mockResolvedValue(ok({ invoices: [] }) as any);
    render(<OrgAttestorFinancialsTab />);
    await waitFor(() => expect(screen.getByText(/450\.00/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /request payout/i })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run it — fails**

```bash
npx vitest run tests/unit/components/organizations/attestor/org-attestor-financials-tab.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement the tab**

Sections: earnings summary + ledger (`getOrgAttestorEarnings`), payout account onboard/status (`onboardOrgPayoutAccount`), payout request (`requestOrgPayout` behind TOTP step-up; disabled unless payout account exists and application approved), invoices list (`listOrgInvoices`). Never show account numbers/tax docs. Verify field names against `types.gen.ts`.

- [ ] **Step 4: Register tab + route; run test**

Push `{ id: "financials", label: "Financials" }` (owner/admin) in `organization-shell.tsx`; create `.../[orgId]/financials/page.tsx` → `<OrgAttestorFinancialsTab />`.

```bash
npx vitest run tests/unit/components/organizations/attestor/org-attestor-financials-tab.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add org attestor financials tab (earnings, payout, invoices)"
```

---

## Task 15: Admin org-attestor review panel

**Files:**
- Create: `frontend/src/components/modules/admin/admin-org-attestor-review-panel.tsx`
- Create test: `frontend/tests/unit/components/admin/admin-org-attestor-review-panel.test.tsx`
- Create route: `frontend/src/app/(auth)/admin/org-attestors/page.tsx`
- Modify: admin nav (add "Org Attestors" entry — find the admin nav array via `grep -rn "admin/organizations\|admin/credentials" src/components/modules/admin src/app`)

**Interfaces:**
- Consumes: `listOrgAttestorApplicationsForAdmin`, `verifyOrgAttestorKyb`, `orgAttestorNeedsInfo`, `startOrgAttestorTrial`, `approveOrgAttestor`, `rejectOrgAttestor`, `suspendOrgAttestorCapability`, `reinstateOrgAttestorCapability`, `revokeOrgAttestorCapability`, admin session helper (`loadCurrentUserSession`).
- Produces: `export function AdminOrgAttestorReviewPanel()`.

- [ ] **Step 1: Write the failing test**

```tsx
// tests/unit/components/admin/admin-org-attestor-review-panel.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminOrgAttestorReviewPanel } from "@/components/modules/admin/admin-org-attestor-review-panel";
import { listOrgAttestorApplicationsForAdmin, verifyOrgAttestorKyb } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin" })),
}));
vi.mock("@/lib/auth/current-user-session", () => ({ loadCurrentUserSession: vi.fn(async () => ({ isSuperAdmin: true })) }));
vi.mock("@/lib/generated/sdk.gen", () => ({
  listOrgAttestorApplicationsForAdmin: vi.fn(),
  verifyOrgAttestorKyb: vi.fn(), orgAttestorNeedsInfo: vi.fn(),
  startOrgAttestorTrial: vi.fn(), approveOrgAttestor: vi.fn(), rejectOrgAttestor: vi.fn(),
  suspendOrgAttestorCapability: vi.fn(), reinstateOrgAttestorCapability: vi.fn(), revokeOrgAttestorCapability: vi.fn(),
}));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("AdminOrgAttestorReviewPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("verifies KYB for an application", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(
      ok({ applications: [{ id: "app-1", org_id: "org-1", org_name: "Audit Ltd", status: "submitted", kyb_verified_at: null }] }) as any,
    );
    vi.mocked(verifyOrgAttestorKyb).mockResolvedValue(ok({ id: "app-1" }) as any);
    render(<AdminOrgAttestorReviewPanel />);
    await waitFor(() => screen.getByText(/Audit Ltd/));
    fireEvent.click(screen.getByRole("button", { name: /verify kyb/i }));
    await waitFor(() => expect(vi.mocked(verifyOrgAttestorKyb)).toHaveBeenCalledWith(
      expect.objectContaining({ path: { application_id: "app-1" } }),
    ));
  });
});
```

- [ ] **Step 2: Run it — fails**

```bash
npx vitest run tests/unit/components/admin/admin-org-attestor-review-panel.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement the panel**

Model it on an existing admin review panel (read `admin-credential-review-panel.tsx` for the queue + action pattern, super-admin gating via `loadCurrentUserSession`, and error/loading conventions). Render a status-filterable queue of applications, each with a gate checklist and the gate action buttons mapping to the aliases: verify-kyb, needs-info (feedback textarea), start-trial, approve, reject (feedback). Add a capability-control section per active org: suspend/reinstate/revoke with a confirmation. KYB/tax documents open via admin-only presigned download — never rendered inline in the list.

- [ ] **Step 4: Add route + nav; run test**

Create `admin/org-attestors/page.tsx` rendering the panel (mirror `admin/credentials/page.tsx`). Add the admin nav entry. 

```bash
npx vitest run tests/unit/components/admin/admin-org-attestor-review-panel.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add admin org-attestor review panel + capability controls"
```

---

## Task 16: Public attestor directory + org profile (SSR)

**Files:**
- Create: `frontend/src/app/attestors/page.tsx` (directory, Server Component)
- Create: `frontend/src/app/attestors/[orgId]/page.tsx` (profile, Server Component)
- Create: `frontend/src/components/modules/attestation/directory/attestor-org-card.tsx` + `attestor-org-profile.tsx` (presentational)
- Create tests: `frontend/tests/unit/components/attestation/directory/attestor-org-card.test.tsx`, `attestor-org-profile.test.tsx`

**Interfaces:**
- Consumes: `listAttestorOrgs`, `getAttestorOrg`, `listAttestorOrgCompleted`. Server Components fetch directly from the API base URL (no auth header), mirroring the `/explore` SSR pattern (read `src/app/explore/page.tsx` for the fetch + config).
- Produces: SSR directory + profile pages keyed by `org_id`.

**Confidentiality:** these are public. Render org identity only (name, slug, verification level, completed count, certification mark, member count). NEVER render any member identity or `reviewing_member_id`.

- [ ] **Step 1: Write the failing presentational tests**

```tsx
// tests/unit/components/attestation/directory/attestor-org-card.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AttestorOrgCard } from "@/components/modules/attestation/directory/attestor-org-card";

describe("AttestorOrgCard", () => {
  it("renders org identity and completed count, never member identities", () => {
    render(<AttestorOrgCard org={{
      org_id: "org-1", name: "Audit Ltd", slug: "audit-ltd",
      verification_level: "verified", completed_count: 12, member_count: 4,
      reviewing_member_name: "SHOULD-NOT-RENDER",
    } as any} />);
    expect(screen.getByText("Audit Ltd")).toBeInTheDocument();
    expect(screen.getByText(/12/)).toBeInTheDocument();
    expect(screen.queryByText(/SHOULD-NOT-RENDER/)).toBeNull();
  });
});
```

Write the analogous `attestor-org-profile.test.tsx` asserting profile fields render and no member identity appears.

- [ ] **Step 2: Run them — fail**

```bash
npx vitest run tests/unit/components/attestation/directory
```

Expected: FAIL.

- [ ] **Step 3: Implement the presentational components**

`AttestorOrgCard` and `AttestorOrgProfile` render only the whitelisted org fields (name, slug, verification level, completed count, certification mark, member count). No prop that could carry a member identity is rendered even if present in the payload. Match `/explore` card styling.

- [ ] **Step 4: Implement the SSR pages**

`app/attestors/page.tsx`: Server Component that fetches `listAttestorOrgs` from the API base URL and maps to `AttestorOrgCard`. `app/attestors/[orgId]/page.tsx`: fetches `getAttestorOrg({ path: { org_id } })` + `listAttestorOrgCompleted` and renders `AttestorOrgProfile`. Follow the exact server-fetch approach in `src/app/explore/page.tsx`.

- [ ] **Step 5: Run tests — pass; then full gate**

```bash
npx vitest run tests/unit/components/attestation/directory
npm run test && npm run typecheck && npm run lint && npm run test:coverage
```

Expected: all green; coverage on `components/**` ≥ 70%.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add public attestor directory + org profile (SSR)"
```

---

## Task 17: Rewrite the attestation e2e flow

**Files:**
- Modify: `frontend/tests/e2e/attestation.spec.ts`

**Interfaces:**
- Consumes: the full stack (requires the app + backend running per the project's e2e setup).
- Produces: an e2e covering the org attestation lifecycle.

- [ ] **Step 1: Read the current e2e + its harness**

Read `tests/e2e/attestation.spec.ts` and `playwright.config.*` to learn the existing login/fixture helpers. The current spec drives the retired individual flow and will fail against the new backend.

- [ ] **Step 2: Rewrite the flow**

Cover: org applies for attestor capability → admin approves → offer received → accept-and-staff → reviewing member submits report → published; and assert the requestor view shows the org identity and never a member identity. Reuse existing auth/fixture helpers; do not hardcode paths the app doesn't expose.

- [ ] **Step 3: Run it**

```bash
npm run test:e2e -- attestation
```

Expected: PASS against a running stack. If the environment can't run e2e here, mark the spec complete when it type-checks and its steps match live routes, and flag that a staging run is required before release (per CLAUDE.md E2E gate).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "Rewrite attestation e2e for org-attestor lifecycle"
```

---

## Self-review notes

- **Spec coverage:** surfaces A–J map to Tasks 1 (A), 2 (B), 3–5 (C), 6–8 (D), 9 (E), 10–11 (F), 12–13 (G), 14 (H), 15 (I), 16 (J); e2e requirement → Task 17. No spec surface is unassigned.
- **Confidentiality:** negative `reviewing_member_id` assertions are baked into Tasks 3 (requestor), 12 (member view), 16 (public) — the three surfaces that must not leak it.
- **Naming:** every task consumes the short aliases authored in Task 1's alias table; `adminAssignAttestation`/`adminRefundAttestation` retain existing aliases.
- **Field-name caveat:** response field names (e.g. gate timestamps, `nda_signed`, `active_attestations`, earnings fields) are the best mapping from the backend spec; each task instructs verifying the exact name against the regenerated `types.gen.ts` and adjusting. This is a deliberate, called-out verification step, not a placeholder.
- **Escalation points:** contract gaps (any task), and workspace-reuse friction (Task 13) both instruct STOP-and-escalate rather than invent.
