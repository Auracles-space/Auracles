# Org-Operator Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the frontend surfaces that let an Organization act as an Operator — buy Frameworks as the org, consume them through a shared org Library with member/team grants, manage operator billing, and run Projects as the org.

**Architecture:** All surfaces are org-scoped tabs/pages under the existing org dashboard `[orgId]` shell (`organization-shell.tsx`), gated on `operator` capability = `active` AND admin role, mirroring the shipped attestor gating. Reuse individual-operator components by parameterising which generated SDK function they call (org-variant takes `path: { org_id, ... }`) via a small mode object, rather than forking files. Purchase is a payer selector injected into the existing checkout, not a tab.

**Tech Stack:** Next.js 15 (App Router), React 18, TypeScript, Tailwind, `@hey-api/openapi-ts` generated client, Stripe Elements, vitest + @testing-library/react (jsdom) for component tests, Playwright for e2e.

## Global Constraints

- Backend is fully shipped and MUST NOT be modified. This plan is frontend-only. Endpoints already exist in `contracts/openapi.yaml`.
- Mobile-first: base Tailwind styles target 375px; use `sm:`/`md:`/`lg:` only to enhance. Touch targets ≥ `44px`. No hover-only interactions. Tables → card-stack on mobile. Modals full-screen on mobile, centered on `md:`+. Max content width `max-w-[1280px]`.
- Access token in memory only (never localStorage/JS-cookie). Client calls pass `headers: getAccessTokenHeaders()`. Server components use `configureServerMarketplaceClient()` (public reads only).
- All API calls go through the generated client (`@/lib/generated/sdk.gen`). Never hardcode API paths in components.
- Client-side capability/role gates are UX only — the server (`OrgAdmin` dependency) is the authority. Never treat the client gate as security.
- Artifact/invoice files are delivered via presigned URL returned by the backend; the frontend opens the URL, never proxies bytes.
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit. One behavior per cycle.
- Component coverage ≥ 70% (`CLAUDE.md`). Test files live under `frontend/tests/unit/components/organizations/…`.
- Commit messages: imperative, no `Co-Authored-By`/Claude/AI trailer. Work directly on `main`.
- Every new `.tsx` gets a file-level JSDoc comment; every exported component gets a component JSDoc (per `CLAUDE.md` frontend doc standard).
- Run `npm run lint` and `npx tsc --noEmit` clean before considering any task done. Note: `sdk.gen.ts` starts with `// @ts-nocheck` (generated) — that is expected.

## Reference: existing patterns to copy

- **Generated response envelope:** every SDK call returns `{ data, error, request, response }`. Success = `result.response.ok && result.data`. Error text via `describeGeneratedError(result.error)`.
- **Org component + context:** `useOrganization()` from `@/components/modules/organizations/organization-context` yields at least `{ orgId, role }`. Org SDK calls take `path: { org_id: orgId, ... }`.
- **Test mock pattern** (from `tests/unit/components/organizations/org-nda-panel.test.tsx`):
  ```tsx
  vi.mock("@/lib/auth/form-client", () => ({
    describeGeneratedError: vi.fn(() => "err"),
    getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
    configureBrowserClient: vi.fn(),
  }));
  vi.mock("@/components/modules/organizations/organization-context", () => ({
    useOrganization: () => ({ orgId: "org-1", role: "admin" }),
  }));
  vi.mock("@/lib/generated/sdk.gen", () => ({ someFn: vi.fn() }));
  const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });
  const fail = (status = 400) => ({ data: undefined, error: { detail: "nope" }, request: new Request("http://t"), response: new Response(null, { status }) });
  ```
- **Checkout:** `app/(auth)/checkout/[framework_id]/page.tsx` (server) renders `<CheckoutForm framework={...} />` from `@/components/modules/financials/checkout-form`. `CheckoutForm` calls `createFrameworkPurchase({ body: { license_type }, headers, path: { framework_id } })`.
- **Library:** `@/components/modules/library/operator-library.tsx` — `OperatorLibrary()` calls `listOperatorLibrary({ headers, query: { page, page_size } })`, renders `LibraryItem[]`, per-card artifact download.
- **Org tab shell:** `@/components/modules/organizations/organization-shell.tsx` builds a `tabs` array (`{ id, label }`) around `role`/`capabilities`. Route pages live at `app/(auth)/dashboard/organizations/[orgId]/<segment>/page.tsx`.

---

## File Structure

**Create:**
- `frontend/src/lib/marketplace/purchase-context.ts` — resolves the buyer options list (self + eligible orgs) and the correct purchase SDK call per mode.
- `frontend/src/components/modules/financials/buyer-context-selector.tsx` — "Buy as" selector UI.
- `frontend/src/components/modules/organizations/operator/org-library-tab.tsx` — org shared library list.
- `frontend/src/components/modules/organizations/operator/org-license-grant-panel.tsx` — per-license grant management.
- `frontend/src/components/modules/organizations/operator/org-billing-section.tsx` — payment methods + invoices.
- `frontend/src/components/modules/organizations/operator/org-projects-tab.tsx` — org operator projects list + create entry.
- `frontend/src/lib/projects/project-api-mode.ts` — selects individual-vs-org project SDK calls.
- Route pages:
  - `frontend/src/app/(auth)/dashboard/organizations/[orgId]/library/page.tsx`
  - `frontend/src/app/(auth)/dashboard/organizations/[orgId]/projects/page.tsx`
- Tests under `frontend/tests/unit/components/organizations/operator/…` and `frontend/tests/unit/lib/…`, plus `frontend/tests/e2e/org-operator.spec.ts`.

**Modify:**
- `frontend/scripts/patch-generated-client.mjs` — add org-operator compatibility aliases.
- `frontend/src/lib/generated/{sdk.gen.ts,types.gen.ts}` — regenerated (do not hand-edit).
- `frontend/src/components/modules/financials/checkout-form.tsx` — accept + use buyer context.
- `frontend/src/components/modules/organizations/organization-shell.tsx` — add operator-gated Library/Projects tabs.
- `frontend/src/app/(auth)/dashboard/organizations/[orgId]/financials/page.tsx` — render Billing section when operator-active.

---

## Task 0: Regenerate client + add org-operator aliases

The org-operator endpoints exist in `contracts/openapi.yaml` but the generated SDK is stale (0 org-operator functions). Regenerate, then add short compatibility aliases (the repo convention in `patch-generated-client.mjs`).

**Files:**
- Modify: `frontend/scripts/patch-generated-client.mjs`
- Regenerate: `frontend/src/lib/generated/sdk.gen.ts`, `frontend/src/lib/generated/types.gen.ts`

**Interfaces:**
- Produces (short alias names later tasks import from `@/lib/generated/sdk.gen`): `createOrgFrameworkPurchase`, `listOrgLibrary`, `requestOrgLibraryArtifactDownload`, `listOrgLicenseGrants`, `addOrgLicenseGrant`, `revokeOrgLicenseGrant`, `createOrgPaymentMethodSetup`, `listOrgPaymentMethods`, `deleteOrgPaymentMethod`, `getOrgPurchaseInvoice`, `createOrgProject`, `acceptOrgProposal`, `fundOrgMilestone`, `approveOrgDeliverable`, `createOrgDispute`. Also already present: `listOrgInvoices`, `listMyOrganizationsV1OrgsMineGet`.

- [ ] **Step 1: Regenerate the client**

Run:
```bash
cd frontend && npm run generate:api
```
Expected: `src/lib/generated/sdk.gen.ts` now contains full-name exports for the org-operator operations (e.g. `createOrgFrameworkPurchaseV1OrgsOrgIdFrameworksFrameworkIdPurchasePost`).

- [ ] **Step 2: Confirm the exact generated full names**

Run:
```bash
cd frontend && grep -oE "export const (createOrgFrameworkPurchase|listOrgLibrary|requestOrgLibraryArtifactDownload|listOrgLicenseGrants|addOrgLicenseGrant|revokeOrgLicenseGrant|createOrgPaymentMethodSetup|listOrgPaymentMethods|deleteOrgPaymentMethod|getOrgPurchaseInvoice|createOrgProject|acceptOrgProposal|fundOrgMilestone|approveOrgDeliverable|createOrgDispute)[A-Za-z0-9]*" src/lib/generated/sdk.gen.ts | sort -u
```
Expected: 15 lines, each the full generated export name. **Copy these exact names** — the alias map throws at build if a value does not match an existing export.

- [ ] **Step 3: Add aliases to the patch script**

In `frontend/scripts/patch-generated-client.mjs`, add entries to the `compatibilityAliases` object using the names confirmed in Step 2. Expected values (verify against Step 2 output; hey-api collapses `__param__` path segments to PascalCase):

```js
  createOrgFrameworkPurchase: "createOrgFrameworkPurchaseV1OrgsOrgIdFrameworksFrameworkIdPurchasePost",
  listOrgLibrary: "listOrgLibraryV1OrgsOrgIdLibraryGet",
  requestOrgLibraryArtifactDownload: "requestOrgLibraryArtifactDownloadV1OrgsOrgIdLibraryLicenseIdArtifactsArtifactIdDownloadPost",
  listOrgLicenseGrants: "listOrgLicenseGrantsV1OrgsOrgIdLicensesLicenseIdGrantsGet",
  addOrgLicenseGrant: "addOrgLicenseGrantV1OrgsOrgIdLicensesLicenseIdGrantsPost",
  revokeOrgLicenseGrant: "revokeOrgLicenseGrantV1OrgsOrgIdLicensesLicenseIdGrantsGrantIdDelete",
  createOrgPaymentMethodSetup: "createOrgPaymentMethodSetupV1OrgsOrgIdFinancialsPaymentMethodsSetupPost",
  listOrgPaymentMethods: "listOrgPaymentMethodsV1OrgsOrgIdFinancialsPaymentMethodsGet",
  deleteOrgPaymentMethod: "deleteOrgPaymentMethodV1OrgsOrgIdFinancialsPaymentMethodsPaymentMethodIdDelete",
  getOrgPurchaseInvoice: "getOrgPurchaseInvoiceV1OrgsOrgIdFinancialsPurchasesTransactionIdInvoiceGet",
  createOrgProject: "createOrgProjectV1OrgsOrgIdProjectsPost",
  acceptOrgProposal: "acceptOrgProposalV1OrgsOrgIdProjectsProjectIdProposalsProposalIdAcceptPost",
  fundOrgMilestone: "fundOrgMilestoneV1OrgsOrgIdProjectsProjectIdMilestonesMilestoneIdFundPost",
  approveOrgDeliverable: "approveOrgDeliverableV1OrgsOrgIdProjectsProjectIdDeliverablesDeliverableIdApprovePost",
  createOrgDispute: "createOrgDisputeV1OrgsOrgIdProjectsProjectIdDisputesPost",
```

- [ ] **Step 4: Re-run patch and verify aliases resolve**

Run:
```bash
cd frontend && node scripts/patch-generated-client.mjs && grep -c "export const createOrgFrameworkPurchase " src/lib/generated/sdk.gen.ts
```
Expected: `1` (alias export written). If the patch script throws "alias target not found", the value did not match Step 2 — fix it.

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd frontend && git add scripts/patch-generated-client.mjs src/lib/generated/sdk.gen.ts src/lib/generated/types.gen.ts
git commit -m "Regenerate frontend client with org-operator endpoints and aliases"
```

---

## Phase 1 — Org Purchase (buy-as-org)

### Task 1: Purchase-context resolver

A pure module that turns the caller's org list into buyer options and performs the right purchase call per selection. Keeping it pure makes the selector and checkout trivially testable.

**Files:**
- Create: `frontend/src/lib/marketplace/purchase-context.ts`
- Test: `frontend/tests/unit/lib/purchase-context.test.ts`

**Interfaces:**
- Consumes: `createFrameworkPurchase`, `createOrgFrameworkPurchase` from `@/lib/generated/sdk.gen`; `MyOrganizationResponse` from `@/lib/generated/types.gen`.
- Produces:
  - `type BuyerOption = { kind: "self"; label: string } | { kind: "org"; orgId: string; label: string }`
  - `eligibleOrgBuyers(orgs: MyOrganizationResponse[]): BuyerOption[]` — orgs where `role ∈ {admin, owner}` and `capabilities.operator === "active"`.
  - `buyerOptions(orgs: MyOrganizationResponse[]): BuyerOption[]` — `[{kind:"self",label:"Myself"}, ...eligibleOrgBuyers]`.
  - `async function startPurchase(args: { buyer: BuyerOption; frameworkId: string; licenseType: string; headers: Record<string,string> }): Promise<{ clientSecret: string; transactionId: string } | { error: unknown }>`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/tests/unit/lib/purchase-context.test.ts
import { describe, expect, it, vi } from "vitest";
import { buyerOptions, eligibleOrgBuyers, startPurchase } from "@/lib/marketplace/purchase-context";
import * as sdk from "@/lib/generated/sdk.gen";

vi.mock("@/lib/generated/sdk.gen", () => ({
  createFrameworkPurchase: vi.fn(),
  createOrgFrameworkPurchase: vi.fn(),
}));

const org = (id: string, role: string, operator: string) =>
  ({ org: { id, name: `Org ${id}` }, role, capabilities: { operator } }) as never;

describe("eligibleOrgBuyers", () => {
  it("includes only admin/owner orgs with active operator capability", () => {
    const result = eligibleOrgBuyers([
      org("a", "admin", "active"),
      org("b", "member", "active"),
      org("c", "owner", "suspended"),
      org("d", "owner", "active"),
    ]);
    expect(result.map((o) => (o.kind === "org" ? o.orgId : "self"))).toEqual(["a", "d"]);
  });
});

describe("buyerOptions", () => {
  it("prepends a self option", () => {
    const result = buyerOptions([org("a", "admin", "active")]);
    expect(result[0]).toEqual({ kind: "self", label: "Myself" });
    expect(result).toHaveLength(2);
  });
});

describe("startPurchase", () => {
  const okEnvelope = { data: { client_secret: "cs", transaction_id: "tx" }, error: undefined, response: { ok: true } };

  it("routes a self purchase through createFrameworkPurchase", async () => {
    vi.mocked(sdk.createFrameworkPurchase).mockResolvedValue(okEnvelope as never);
    const res = await startPurchase({ buyer: { kind: "self", label: "Myself" }, frameworkId: "fw", licenseType: "team", headers: { Authorization: "Bearer t" } });
    expect(sdk.createFrameworkPurchase).toHaveBeenCalledWith(
      expect.objectContaining({ body: { license_type: "team" }, path: { framework_id: "fw" } }),
    );
    expect(res).toEqual({ clientSecret: "cs", transactionId: "tx" });
  });

  it("routes an org purchase through createOrgFrameworkPurchase with org_id", async () => {
    vi.mocked(sdk.createOrgFrameworkPurchase).mockResolvedValue(okEnvelope as never);
    await startPurchase({ buyer: { kind: "org", orgId: "org-9", label: "Org 9" }, frameworkId: "fw", licenseType: "organizational", headers: {} });
    expect(sdk.createOrgFrameworkPurchase).toHaveBeenCalledWith(
      expect.objectContaining({ body: { license_type: "organizational" }, path: { org_id: "org-9", framework_id: "fw" } }),
    );
  });

  it("returns the error envelope on failure", async () => {
    vi.mocked(sdk.createFrameworkPurchase).mockResolvedValue({ data: undefined, error: { detail: "x" }, response: { ok: false } } as never);
    const res = await startPurchase({ buyer: { kind: "self", label: "Myself" }, frameworkId: "fw", licenseType: "team", headers: {} });
    expect(res).toEqual({ error: { detail: "x" } });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run tests/unit/lib/purchase-context.test.ts`
Expected: FAIL — module `@/lib/marketplace/purchase-context` not found.

- [ ] **Step 3: Implement the resolver**

```ts
// frontend/src/lib/marketplace/purchase-context.ts
/**
 * Buyer-context resolution for Framework checkout.
 *
 * Turns the caller's organization memberships into "Buy as" options and routes
 * a purchase to the correct backend call (self vs organization). The client
 * gate here is UX only — the backend re-checks operator capability + admin role.
 */
import { createFrameworkPurchase, createOrgFrameworkPurchase } from "@/lib/generated/sdk.gen";
import type { MyOrganizationResponse } from "@/lib/generated/types.gen";

export type BuyerOption =
  | { kind: "self"; label: string }
  | { kind: "org"; orgId: string; label: string };

/** Orgs the caller may purchase on behalf of (admin/owner + active operator capability). */
export function eligibleOrgBuyers(orgs: MyOrganizationResponse[]): BuyerOption[] {
  return orgs
    .filter((o) => (o.role === "admin" || o.role === "owner") && o.capabilities?.operator === "active")
    .map((o) => ({ kind: "org", orgId: o.org.id, label: o.org.name }));
}

/** Self option followed by eligible org buyers. */
export function buyerOptions(orgs: MyOrganizationResponse[]): BuyerOption[] {
  return [{ kind: "self", label: "Myself" }, ...eligibleOrgBuyers(orgs)];
}

type StartPurchaseArgs = {
  buyer: BuyerOption;
  frameworkId: string;
  licenseType: string;
  headers: Record<string, string>;
};

type PurchaseSession = { clientSecret: string; transactionId: string };

/** Start a purchase transaction as self or as an org; returns a session or an error envelope. */
export async function startPurchase(
  args: StartPurchaseArgs,
): Promise<PurchaseSession | { error: unknown }> {
  const { buyer, frameworkId, licenseType, headers } = args;
  const body = { license_type: licenseType } as never;
  const result =
    buyer.kind === "self"
      ? await createFrameworkPurchase({ body, headers, path: { framework_id: frameworkId } })
      : await createOrgFrameworkPurchase({ body, headers, path: { org_id: buyer.orgId, framework_id: frameworkId } });

  if (!result.response.ok || !result.data) {
    return { error: result.error };
  }
  return { clientSecret: result.data.client_secret, transactionId: result.data.transaction_id };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run tests/unit/lib/purchase-context.test.ts`
Expected: PASS (6 assertions across 4 tests).

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/lib/marketplace/purchase-context.ts tests/unit/lib/purchase-context.test.ts
git commit -m "Add buyer-context resolver for self vs org Framework purchase"
```

### Task 2: Buyer-context selector + checkout wiring

Inject a "Buy as" selector into the checkout form. Self is default; the selector appears only when the caller has at least one eligible org.

**Files:**
- Create: `frontend/src/components/modules/financials/buyer-context-selector.tsx`
- Modify: `frontend/src/components/modules/financials/checkout-form.tsx`
- Test: `frontend/tests/unit/components/financials/buyer-context-selector.test.tsx`, `frontend/tests/unit/components/financials/checkout-form.buyer.test.tsx`

**Interfaces:**
- Consumes: `BuyerOption`, `buyerOptions`, `startPurchase` from `@/lib/marketplace/purchase-context`; `listMyOrganizationsV1OrgsMineGet` from `@/lib/generated/sdk.gen`.
- Produces: `<BuyerContextSelector options={BuyerOption[]} value={BuyerOption} onChange={(b:BuyerOption)=>void} />`.

- [ ] **Step 1: Write the failing selector test**

```tsx
// frontend/tests/unit/components/financials/buyer-context-selector.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BuyerContextSelector } from "@/components/modules/financials/buyer-context-selector";
import type { BuyerOption } from "@/lib/marketplace/purchase-context";

const options: BuyerOption[] = [
  { kind: "self", label: "Myself" },
  { kind: "org", orgId: "org-1", label: "Acme" },
];

describe("BuyerContextSelector", () => {
  it("renders one radio per option with a 44px touch target and marks the value selected", () => {
    render(<BuyerContextSelector options={options} value={options[0]} onChange={() => {}} />);
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(2);
    expect(screen.getByRole("radio", { name: /myself/i })).toBeChecked();
  });

  it("emits the chosen option on change", () => {
    const onChange = vi.fn();
    render(<BuyerContextSelector options={options} value={options[0]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: /acme/i }));
    expect(onChange).toHaveBeenCalledWith(options[1]);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run tests/unit/components/financials/buyer-context-selector.test.tsx`
Expected: FAIL — component not found.

- [ ] **Step 3: Implement the selector**

```tsx
// frontend/src/components/modules/financials/buyer-context-selector.tsx
"use client";

/**
 * "Buy as" selector for Framework checkout.
 *
 * Lets an Operator purchase for themselves or on behalf of an organization
 * they administer. Rendered only when at least one eligible org exists.
 */
import type { BuyerOption } from "@/lib/marketplace/purchase-context";

type BuyerContextSelectorProps = {
  options: BuyerOption[];
  value: BuyerOption;
  onChange: (buyer: BuyerOption) => void;
};

function keyFor(option: BuyerOption): string {
  return option.kind === "self" ? "self" : `org:${option.orgId}`;
}

/**
 * Render a radio group of purchase identities.
 *
 * @param props - Available buyer options, current value, and change handler.
 */
export function BuyerContextSelector({ options, value, onChange }: BuyerContextSelectorProps) {
  return (
    <fieldset className="mt-6 grid gap-3">
      <legend className="text-sm font-semibold text-foreground">Purchase as</legend>
      {options.map((option) => {
        const selected = keyFor(option) === keyFor(value);
        return (
          <label
            key={keyFor(option)}
            className={[
              "flex min-h-[44px] cursor-pointer items-center gap-3 rounded-xl border p-4 transition-colors",
              selected
                ? "border-accent bg-accent/5 ring-1 ring-accent"
                : "border-border-default bg-surface-1 hover:border-border-strong hover:bg-surface-2",
            ].join(" ")}
          >
            <input
              type="radio"
              name="buyer-context"
              className="h-4 w-4"
              checked={selected}
              onChange={() => onChange(option)}
              aria-label={option.label}
            />
            <span className="text-sm font-medium text-foreground">{option.label}</span>
          </label>
        );
      })}
    </fieldset>
  );
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run tests/unit/components/financials/buyer-context-selector.test.tsx`
Expected: PASS.

- [ ] **Step 5: Write the failing checkout-wiring test**

```tsx
// frontend/tests/unit/components/financials/checkout-form.buyer.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CheckoutForm } from "@/components/modules/financials/checkout-form";
import * as sdk from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/financials/stripe-client", () => ({ getStripeClient: vi.fn(() => Promise.resolve(null)) }));
vi.mock("@stripe/react-stripe-js", () => ({
  Elements: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PaymentElement: () => <div />,
  useElements: () => null,
  useStripe: () => null,
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  createFrameworkPurchase: vi.fn(),
  createOrgFrameworkPurchase: vi.fn(),
  listMyOrganizationsV1OrgsMineGet: vi.fn(),
  getExploreCollectionDetail: vi.fn(),
}));

const framework = { id: "fw", license_types: ["organizational"], price: 1000, currency: "USD" } as never;
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("CheckoutForm buyer context", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the buyer selector when an eligible org exists and routes the org purchase", async () => {
    vi.mocked(sdk.listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok([{ org: { id: "org-1", name: "Acme" }, role: "admin", capabilities: { operator: "active" } }]) as never,
    );
    vi.mocked(sdk.createOrgFrameworkPurchase).mockResolvedValue(ok({ client_secret: "cs", transaction_id: "tx" }) as never);

    render(<CheckoutForm framework={framework} />);
    await waitFor(() => screen.getByRole("radio", { name: /acme/i }));

    screen.getByRole("radio", { name: /acme/i }).click();
    screen.getByRole("button", { name: /start checkout|license this framework|pay/i }).click();

    await waitFor(() =>
      expect(sdk.createOrgFrameworkPurchase).toHaveBeenCalledWith(
        expect.objectContaining({ path: { org_id: "org-1", framework_id: "fw" } }),
      ),
    );
  });

  it("hides the buyer selector when there are no eligible orgs", async () => {
    vi.mocked(sdk.listMyOrganizationsV1OrgsMineGet).mockResolvedValue(ok([]) as never);
    render(<CheckoutForm framework={framework} />);
    await waitFor(() => expect(sdk.listMyOrganizationsV1OrgsMineGet).toHaveBeenCalled());
    expect(screen.queryByText(/purchase as/i)).toBeNull();
  });
});
```

- [ ] **Step 6: Run to verify it fails**

Run: `cd frontend && npx vitest run tests/unit/components/financials/checkout-form.buyer.test.tsx`
Expected: FAIL — `CheckoutForm` does not fetch orgs / render the selector yet.

- [ ] **Step 7: Wire the selector into `CheckoutForm`**

In `frontend/src/components/modules/financials/checkout-form.tsx`:
1. Add imports:
   ```tsx
   import { BuyerContextSelector } from "./buyer-context-selector";
   import { buyerOptions, startPurchase, type BuyerOption } from "@/lib/marketplace/purchase-context";
   import { listMyOrganizationsV1OrgsMineGet } from "@/lib/generated/sdk.gen";
   ```
2. Inside `CheckoutForm`, add state + an effect that loads eligible buyers:
   ```tsx
   const [buyers, setBuyers] = useState<BuyerOption[]>([{ kind: "self", label: "Myself" }]);
   const [buyer, setBuyer] = useState<BuyerOption>({ kind: "self", label: "Myself" });

   useEffect(() => {
     let active = true;
     async function loadBuyers() {
       configureBrowserClient();
       const result = await listMyOrganizationsV1OrgsMineGet({ headers: getAccessTokenHeaders() });
       if (!active || !result.response.ok || !result.data) return;
       setBuyers(buyerOptions(result.data));
     }
     void loadBuyers();
     return () => {
       active = false;
     };
   }, []);
   ```
3. Replace the body of `handleStartCheckout` so it delegates to `startPurchase`:
   ```tsx
   async function handleStartCheckout() {
     setError(null);
     setSubmitting(true);
     configureBrowserClient();
     const outcome = await startPurchase({
       buyer,
       frameworkId: framework.id,
       licenseType,
       headers: getAccessTokenHeaders(),
     });
     setSubmitting(false);
     if ("error" in outcome) {
       setError(describeGeneratedError(outcome.error));
       return;
     }
     setSession({ clientSecret: outcome.clientSecret, transactionId: outcome.transactionId });
   }
   ```
4. Render the selector above the license fieldset, only when more than the self option exists:
   ```tsx
   {buyers.length > 1 && (
     <BuyerContextSelector options={buyers} value={buyer} onChange={setBuyer} />
   )}
   ```

- [ ] **Step 8: Run to verify it passes**

Run: `cd frontend && npx vitest run tests/unit/components/financials/checkout-form.buyer.test.tsx`
Expected: PASS. If the button name assertion fails, adjust the regex in the test to the real submit button label rendered by `CheckoutForm`.

- [ ] **Step 9: Lint + typecheck**

Run: `cd frontend && npm run lint && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 10: Commit**

```bash
cd frontend && git add src/components/modules/financials/buyer-context-selector.tsx src/components/modules/financials/checkout-form.tsx tests/unit/components/financials/
git commit -m "Add buy-as-org selector to Framework checkout"
```

---

## Phase 2 — Org Library

### Task 3: Operator tab gating in the org shell

Add operator-gated Library and Projects tabs (Projects page arrives in Phase 4; the tab is wired now so gating is done once).

**Files:**
- Modify: `frontend/src/components/modules/organizations/organization-shell.tsx`
- Test: `frontend/tests/unit/components/organizations/organization-shell.operator.test.tsx`

**Interfaces:**
- Consumes: existing `myOrg.capabilities`, `myOrg.role` in the shell.
- Produces: tabs `{ id: "library", label: "Library" }` and `{ id: "projects", label: "Projects" }` rendered when `operatorActive && isAdmin`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/tests/unit/components/organizations/organization-shell.operator.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard/organizations/org-1" }));
const myOrgRef: { current: unknown } = { current: null };
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => myOrgRef.current,
}));

import { OrganizationShell } from "@/components/modules/organizations/organization-shell";

function setOrg(role: string, operator?: string) {
  myOrgRef.current = {
    org: { id: "org-1", name: "Acme", slug: "acme" },
    role,
    capabilities: operator ? { operator } : {},
    error: null,
  };
}

describe("OrganizationShell operator tabs", () => {
  it("shows Library and Projects tabs for an admin with active operator capability", () => {
    setOrg("admin", "active");
    render(<OrganizationShell><div /></OrganizationShell>);
    expect(screen.getByRole("link", { name: /library/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /projects/i })).toBeInTheDocument();
  });

  it("hides them when operator capability is not active", () => {
    setOrg("admin", "suspended");
    render(<OrganizationShell><div /></OrganizationShell>);
    expect(screen.queryByRole("link", { name: /library/i })).toBeNull();
  });

  it("hides them for a non-admin even if operator is active", () => {
    setOrg("member", "active");
    render(<OrganizationShell><div /></OrganizationShell>);
    expect(screen.queryByRole("link", { name: /library/i })).toBeNull();
  });
});
```

Note: match the real `useOrganization()` shape and the shell's tab-render markup. If the shell consumes a hook that returns `{ myOrg, ... }` rather than the org directly, adjust the mock so `myOrg` is populated — read the current `organization-shell.tsx` head before writing the mock.

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run tests/unit/components/organizations/organization-shell.operator.test.tsx`
Expected: FAIL — no Library/Projects tabs.

- [ ] **Step 3: Add operator gating**

In `organization-shell.tsx`, after the existing `const attestorCap = ...` block and within the tab assembly, add:
```tsx
const operatorActive = myOrg.capabilities?.["operator"] === "active";
```
Then inside the `if (isAdmin) { ... }` block, add:
```tsx
if (operatorActive) {
  tabs.push({ id: "library", label: "Library" });
  tabs.push({ id: "projects", label: "Projects" });
}
```
Place these pushes before the `financials` push so tab order reads Library, Projects, Financials.

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run tests/unit/components/organizations/organization-shell.operator.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/components/modules/organizations/organization-shell.tsx tests/unit/components/organizations/organization-shell.operator.test.tsx
git commit -m "Gate org Library and Projects tabs on active operator capability"
```

### Task 4: License grant panel

Per-license grant management: list grants, add a grant to a member or a team, revoke.

**Files:**
- Create: `frontend/src/components/modules/organizations/operator/org-license-grant-panel.tsx`
- Test: `frontend/tests/unit/components/organizations/operator/org-license-grant-panel.test.tsx`

**Interfaces:**
- Consumes: `listOrgLicenseGrants`, `addOrgLicenseGrant`, `revokeOrgLicenseGrant` from `@/lib/generated/sdk.gen`; `useOrganization`.
- Produces: `<OrgLicenseGrantPanel licenseId={string} members={{id:string,label:string}[]} teams={{id:string,label:string}[]} />`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/tests/unit/components/organizations/operator/org-license-grant-panel.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OrgLicenseGrantPanel } from "@/components/modules/organizations/operator/org-license-grant-panel";
import * as sdk from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "admin" }),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  listOrgLicenseGrants: vi.fn(),
  addOrgLicenseGrant: vi.fn(),
  revokeOrgLicenseGrant: vi.fn(),
}));

const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });
const members = [{ id: "m1", label: "Ada" }];
const teams = [{ id: "t1", label: "Delivery" }];

describe("OrgLicenseGrantPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists existing grants", async () => {
    vi.mocked(sdk.listOrgLicenseGrants).mockResolvedValue(ok({ grants: [{ id: "g1", member_id: "m1", team_id: null }] }) as never);
    render(<OrgLicenseGrantPanel licenseId="lic-1" members={members} teams={teams} />);
    await waitFor(() =>
      expect(sdk.listOrgLicenseGrants).toHaveBeenCalledWith(expect.objectContaining({ path: { org_id: "org-1", license_id: "lic-1" } })),
    );
    expect(screen.getByText(/ada/i)).toBeInTheDocument();
  });

  it("adds a member grant with member_id and no team_id", async () => {
    vi.mocked(sdk.listOrgLicenseGrants).mockResolvedValue(ok({ grants: [] }) as never);
    vi.mocked(sdk.addOrgLicenseGrant).mockResolvedValue(ok({ id: "g2", member_id: "m1", team_id: null }) as never);
    render(<OrgLicenseGrantPanel licenseId="lic-1" members={members} teams={teams} />);
    await waitFor(() => expect(sdk.listOrgLicenseGrants).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText(/grant to member/i), { target: { value: "m1" } });
    fireEvent.click(screen.getByRole("button", { name: /grant member/i }));
    await waitFor(() =>
      expect(sdk.addOrgLicenseGrant).toHaveBeenCalledWith(
        expect.objectContaining({ path: { org_id: "org-1", license_id: "lic-1" }, body: { member_id: "m1", team_id: null } }),
      ),
    );
  });

  it("revokes a grant by id", async () => {
    vi.mocked(sdk.listOrgLicenseGrants).mockResolvedValue(ok({ grants: [{ id: "g1", member_id: "m1", team_id: null }] }) as never);
    vi.mocked(sdk.revokeOrgLicenseGrant).mockResolvedValue(ok({}) as never);
    render(<OrgLicenseGrantPanel licenseId="lic-1" members={members} teams={teams} />);
    await waitFor(() => screen.getByText(/ada/i));
    fireEvent.click(screen.getByRole("button", { name: /revoke/i }));
    await waitFor(() =>
      expect(sdk.revokeOrgLicenseGrant).toHaveBeenCalledWith(
        expect.objectContaining({ path: { org_id: "org-1", license_id: "lic-1", grant_id: "g1" } }),
      ),
    );
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run tests/unit/components/organizations/operator/org-license-grant-panel.test.tsx`
Expected: FAIL — component not found.

- [ ] **Step 3: Implement the panel**

```tsx
// frontend/src/components/modules/organizations/operator/org-license-grant-panel.tsx
"use client";

/**
 * Per-license access grant management for an org's shared library.
 *
 * Grants a purchased license to a single member or a whole team (member_id XOR
 * team_id) and revokes existing grants. The backend re-checks admin role.
 */
import { useEffect, useState } from "react";

import {
  addOrgLicenseGrant,
  listOrgLicenseGrants,
  revokeOrgLicenseGrant,
} from "@/lib/generated/sdk.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { useOrganization } from "@/components/modules/organizations/organization-context";

type NamedRef = { id: string; label: string };
type Grant = { id: string; member_id: string | null; team_id: string | null };

type OrgLicenseGrantPanelProps = {
  licenseId: string;
  members: NamedRef[];
  teams: NamedRef[];
};

/**
 * Render the grant list plus member/team grant controls for one license.
 *
 * @param props - License id and the org's members/teams to grant to.
 */
export function OrgLicenseGrantPanel({ licenseId, members, teams }: OrgLicenseGrantPanelProps) {
  const { orgId } = useOrganization();
  const [grants, setGrants] = useState<Grant[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [memberId, setMemberId] = useState("");
  const [teamId, setTeamId] = useState("");
  const [busy, setBusy] = useState(false);

  async function reload() {
    configureBrowserClient();
    const result = await listOrgLicenseGrants({
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId, license_id: licenseId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setGrants(result.data.grants);
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, licenseId]);

  async function grant(body: { member_id: string | null; team_id: string | null }) {
    setBusy(true);
    setError(null);
    configureBrowserClient();
    const result = await addOrgLicenseGrant({
      body,
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId, license_id: licenseId },
    });
    setBusy(false);
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setMemberId("");
    setTeamId("");
    await reload();
  }

  async function revoke(grantId: string) {
    setBusy(true);
    setError(null);
    configureBrowserClient();
    const result = await revokeOrgLicenseGrant({
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId, license_id: licenseId, grant_id: grantId },
    });
    setBusy(false);
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    await reload();
  }

  function labelForGrant(g: Grant): string {
    if (g.member_id) return members.find((m) => m.id === g.member_id)?.label ?? "Member";
    if (g.team_id) return teams.find((t) => t.id === g.team_id)?.label ?? "Team";
    return "Grant";
  }

  return (
    <div className="mt-4 rounded-xl border border-border-default bg-surface-2 p-4">
      {error && <p className="mb-3 text-sm text-error">{error}</p>}
      <ul className="grid gap-2">
        {grants.map((g) => (
          <li key={g.id} className="flex min-h-[44px] items-center justify-between gap-3 rounded-lg bg-surface-1 px-3">
            <span className="text-sm text-foreground">{labelForGrant(g)}</span>
            <button
              type="button"
              disabled={busy}
              onClick={() => void revoke(g.id)}
              className="min-h-[44px] px-3 text-sm font-semibold text-error"
            >
              Revoke
            </button>
          </li>
        ))}
        {grants.length === 0 && <li className="text-sm text-foreground-muted">No access granted yet.</li>}
      </ul>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="grid gap-2">
          <label htmlFor={`grant-member-${licenseId}`} className="text-sm font-medium text-foreground">Grant to member</label>
          <select
            id={`grant-member-${licenseId}`}
            value={memberId}
            onChange={(e) => setMemberId(e.target.value)}
            className="min-h-[44px] rounded-lg border border-border-default bg-surface-1 px-3 text-sm"
          >
            <option value="">Select a member…</option>
            {members.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
          <button
            type="button"
            disabled={busy || !memberId}
            onClick={() => void grant({ member_id: memberId, team_id: null })}
            className="min-h-[44px] rounded-lg bg-accent px-4 text-sm font-semibold text-white disabled:opacity-50"
          >
            Grant member
          </button>
        </div>

        <div className="grid gap-2">
          <label htmlFor={`grant-team-${licenseId}`} className="text-sm font-medium text-foreground">Grant to team</label>
          <select
            id={`grant-team-${licenseId}`}
            value={teamId}
            onChange={(e) => setTeamId(e.target.value)}
            className="min-h-[44px] rounded-lg border border-border-default bg-surface-1 px-3 text-sm"
          >
            <option value="">Select a team…</option>
            {teams.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
          <button
            type="button"
            disabled={busy || !teamId}
            onClick={() => void grant({ member_id: null, team_id: teamId })}
            className="min-h-[44px] rounded-lg bg-accent px-4 text-sm font-semibold text-white disabled:opacity-50"
          >
            Grant team
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run tests/unit/components/organizations/operator/org-license-grant-panel.test.tsx`
Expected: PASS. If the real `listOrgLicenseGrants` response shape is a bare array rather than `{ grants: [...] }`, confirm against `types.gen.ts` (`OrgLicenseGrantsResponse`) and adjust both the component's `result.data.grants` read and the test's `ok({...})` payload to match.

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/components/modules/organizations/operator/org-license-grant-panel.tsx tests/unit/components/organizations/operator/org-license-grant-panel.test.tsx
git commit -m "Add per-license grant panel for org shared library"
```

### Task 5: Org library tab + route

List the org's shared library; each row expands to the grant panel and offers per-artifact download via presigned URL.

**Files:**
- Create: `frontend/src/components/modules/organizations/operator/org-library-tab.tsx`
- Create: `frontend/src/app/(auth)/dashboard/organizations/[orgId]/library/page.tsx`
- Test: `frontend/tests/unit/components/organizations/operator/org-library-tab.test.tsx`

**Interfaces:**
- Consumes: `listOrgLibrary`, `requestOrgLibraryArtifactDownload` from `@/lib/generated/sdk.gen`; `OrgLicenseGrantPanel`; `useOrganization`.
- Produces: `<OrgLibraryTab />` (reads `orgId` from context).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/tests/unit/components/organizations/operator/org-library-tab.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OrgLibraryTab } from "@/components/modules/organizations/operator/org-library-tab";
import * as sdk from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "admin" }),
}));
vi.mock("@/components/modules/organizations/operator/org-license-grant-panel", () => ({
  OrgLicenseGrantPanel: () => <div data-testid="grant-panel" />,
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  listOrgLibrary: vi.fn(),
  requestOrgLibraryArtifactDownload: vi.fn(),
}));

const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("OrgLibraryTab", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists licensed frameworks for the org", async () => {
    vi.mocked(sdk.listOrgLibrary).mockResolvedValue(
      ok({ items: [{ license_id: "lic-1", framework: { id: "fw-1", title: "Growth Playbook" }, artifacts: [] }] }) as never,
    );
    render(<OrgLibraryTab />);
    await waitFor(() =>
      expect(sdk.listOrgLibrary).toHaveBeenCalledWith(expect.objectContaining({ path: { org_id: "org-1" } })),
    );
    expect(screen.getByText(/growth playbook/i)).toBeInTheDocument();
  });

  it("opens a presigned download URL for an artifact", async () => {
    const open = vi.fn();
    vi.stubGlobal("open", open);
    vi.mocked(sdk.listOrgLibrary).mockResolvedValue(
      ok({ items: [{ license_id: "lic-1", framework: { id: "fw-1", title: "Growth Playbook" }, artifacts: [{ id: "a1", filename: "guide.pdf" }] }] }) as never,
    );
    vi.mocked(sdk.requestOrgLibraryArtifactDownload).mockResolvedValue(ok({ download_url: "https://s3/signed" }) as never);
    render(<OrgLibraryTab />);
    await waitFor(() => screen.getByText(/guide\.pdf/i));
    fireEvent.click(screen.getByRole("button", { name: /download/i }));
    await waitFor(() =>
      expect(sdk.requestOrgLibraryArtifactDownload).toHaveBeenCalledWith(
        expect.objectContaining({ path: { org_id: "org-1", license_id: "lic-1", artifact_id: "a1" } }),
      ),
    );
    await waitFor(() => expect(open).toHaveBeenCalledWith("https://s3/signed", "_blank", "noopener,noreferrer"));
    vi.unstubAllGlobals();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run tests/unit/components/organizations/operator/org-library-tab.test.tsx`
Expected: FAIL — component not found.

- [ ] **Step 3: Implement the tab**

```tsx
// frontend/src/components/modules/organizations/operator/org-library-tab.tsx
"use client";

/**
 * Organization shared-library tab.
 *
 * Lists the org's purchased Frameworks, exposes per-license grant management,
 * and downloads artifacts via short-lived presigned URLs from the backend.
 */
import { useEffect, useState } from "react";

import { listOrgLibrary, requestOrgLibraryArtifactDownload } from "@/lib/generated/sdk.gen";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { useOrganization } from "@/components/modules/organizations/organization-context";
import { OrgLicenseGrantPanel } from "./org-license-grant-panel";

type Artifact = { id: string; filename: string };
type LibraryRow = {
  license_id: string;
  framework: { id: string; title: string };
  artifacts: Artifact[];
};

/**
 * Render the org's shared library with grant + download controls.
 */
export function OrgLibraryTab() {
  const { orgId } = useOrganization();
  const [rows, setRows] = useState<LibraryRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      configureBrowserClient();
      const result = await listOrgLibrary({
        headers: getAccessTokenHeaders(),
        path: { org_id: orgId },
        query: { page: 1, page_size: 25 },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        setLoading(false);
        return;
      }
      setRows(result.data.items);
      setLoading(false);
    }
    void load();
  }, [orgId]);

  async function download(licenseId: string, artifactId: string) {
    configureBrowserClient();
    const result = await requestOrgLibraryArtifactDownload({
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId, license_id: licenseId, artifact_id: artifactId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    window.open(result.data.download_url, "_blank", "noopener,noreferrer");
  }

  if (loading) return <p className="p-6 text-sm text-foreground-muted">Loading library…</p>;
  if (error) return <p className="p-6 text-sm text-error">{error}</p>;
  if (rows.length === 0) return <p className="p-6 text-sm text-foreground-muted">No purchased Frameworks yet.</p>;

  return (
    <div className="grid gap-4 p-4 md:p-6">
      {rows.map((row) => (
        <article key={row.license_id} className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm">
          <header className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <h3 className="font-heading text-lg font-bold text-foreground">{row.framework.title}</h3>
            <button
              type="button"
              onClick={() => setExpanded(expanded === row.license_id ? null : row.license_id)}
              className="min-h-[44px] rounded-lg border border-border-default px-4 text-sm font-semibold text-foreground"
            >
              {expanded === row.license_id ? "Hide access" : "Manage access"}
            </button>
          </header>

          <ul className="mt-3 grid gap-2">
            {row.artifacts.map((a) => (
              <li key={a.id} className="flex min-h-[44px] items-center justify-between gap-3 rounded-lg bg-surface-2 px-3">
                <span className="text-sm text-foreground">{a.filename}</span>
                <button
                  type="button"
                  onClick={() => void download(row.license_id, a.id)}
                  className="min-h-[44px] px-3 text-sm font-semibold text-accent"
                >
                  Download
                </button>
              </li>
            ))}
          </ul>

          {expanded === row.license_id && (
            <OrgLicenseGrantPanel licenseId={row.license_id} members={[]} teams={[]} />
          )}
        </article>
      ))}
    </div>
  );
}
```

Note: `members`/`teams` are passed empty here; Task 6 threads real member/team lists in. The grant panel already tolerates empty arrays (renders empty selects), so this task's tests pass without them.

- [ ] **Step 4: Create the route page**

```tsx
// frontend/src/app/(auth)/dashboard/organizations/[orgId]/library/page.tsx
/**
 * Org shared-library route.
 *
 * Renders the operator library tab inside the org dashboard shell. Access is
 * gated server-side by the backend (OrgAdmin) on every underlying call.
 */
import { OrgLibraryTab } from "@/components/modules/organizations/operator/org-library-tab";

export default function OrgLibraryPage() {
  return <OrgLibraryTab />;
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx vitest run tests/unit/components/organizations/operator/org-library-tab.test.tsx`
Expected: PASS. Confirm the real `listOrgLibrary` item shape (`OrgLibraryItem`/`OrgLibraryResponse` in `types.gen.ts`) matches `items[].{license_id,framework,artifacts}`; if field names differ, align component + test to the generated type.

- [ ] **Step 6: Lint + typecheck + commit**

```bash
cd frontend && npm run lint && npx tsc --noEmit
git add "src/app/(auth)/dashboard/organizations/[orgId]/library/page.tsx" src/components/modules/organizations/operator/org-library-tab.tsx tests/unit/components/organizations/operator/org-library-tab.test.tsx
git commit -m "Add org shared-library tab with per-license grants and downloads"
```

### Task 6: Thread real members/teams into grant controls

Give the grant panel the org's actual members and teams so admins pick real people/teams.

**Files:**
- Modify: `frontend/src/components/modules/organizations/operator/org-library-tab.tsx`
- Test: extend `frontend/tests/unit/components/organizations/operator/org-library-tab.test.tsx`

**Interfaces:**
- Consumes: the org members list fn and teams list fn already used elsewhere — read `organization-members.tsx` and `organization-teams.tsx` to find the exact generated fn names (e.g. `listOrgMembers…`, `listOrgTeams…`) and response shapes. Do not invent names.

- [ ] **Step 1: Identify the member/team list fns**

Run:
```bash
cd frontend && grep -oE "list(Org)?(Members|Teams)[A-Za-z0-9]*" src/components/modules/organizations/organization-members.tsx src/components/modules/organizations/organization-teams.tsx
```
Record the exact fn names for Step 3.

- [ ] **Step 2: Write the failing test (extend the file)**

Add a test asserting the grant panel receives non-empty `members`/`teams`. Because `OrgLicenseGrantPanel` is mocked in this file, assert on the props it is called with:
```tsx
// add near the other mocks: capture props
const grantPanelProps: unknown[] = [];
vi.mock("@/components/modules/organizations/operator/org-license-grant-panel", () => ({
  OrgLicenseGrantPanel: (props: unknown) => { grantPanelProps.push(props); return <div data-testid="grant-panel" />; },
}));

it("passes org members and teams into the grant panel", async () => {
  vi.mocked(sdk.listOrgLibrary).mockResolvedValue(ok({ items: [{ license_id: "lic-1", framework: { id: "fw-1", title: "T" }, artifacts: [] }] }) as never);
  // mock the member/team list fns discovered in Step 1 to return one each
  render(<OrgLibraryTab />);
  await waitFor(() => screen.getByText("T"));
  fireEvent.click(screen.getByRole("button", { name: /manage access/i }));
  await waitFor(() => expect(grantPanelProps.at(-1)).toEqual(expect.objectContaining({
    members: [{ id: "m1", label: "Ada" }],
    teams: [{ id: "t1", label: "Delivery" }],
  })));
});
```
Fill the member/team mock returns using the exact fns + shapes from Step 1.

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npx vitest run tests/unit/components/organizations/operator/org-library-tab.test.tsx`
Expected: FAIL — `members`/`teams` still empty.

- [ ] **Step 4: Load members/teams in the tab**

In `org-library-tab.tsx`, add state + a load effect calling the two list fns (mapping to `{ id, label }` where label is the member display name / team name), and pass them to `<OrgLicenseGrantPanel members={members} teams={teams} />`.

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx vitest run tests/unit/components/organizations/operator/org-library-tab.test.tsx`
Expected: PASS.

- [ ] **Step 6: Lint + typecheck + commit**

```bash
cd frontend && npm run lint && npx tsc --noEmit
git add src/components/modules/organizations/operator/org-library-tab.tsx tests/unit/components/organizations/operator/org-library-tab.test.tsx
git commit -m "Thread org members and teams into library grant controls"
```

---

## Phase 3 — Org Billing (Financials section)

### Task 7: Org billing section (payment methods + invoices)

**Files:**
- Create: `frontend/src/components/modules/organizations/operator/org-billing-section.tsx`
- Test: `frontend/tests/unit/components/organizations/operator/org-billing-section.test.tsx`

**Interfaces:**
- Consumes: `listOrgPaymentMethods`, `createOrgPaymentMethodSetup`, `deleteOrgPaymentMethod`, `listOrgInvoices`, `getOrgPurchaseInvoice` from `@/lib/generated/sdk.gen`; `useOrganization`. Reuse the existing TOTP-collection UX from the individual payment-method setup component — read `src/components/modules/financials/` for the current setup component and mirror its TOTP field handling.
- Produces: `<OrgBillingSection />`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/tests/unit/components/organizations/operator/org-billing-section.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OrgBillingSection } from "@/components/modules/organizations/operator/org-billing-section";
import * as sdk from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "admin" }),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  listOrgPaymentMethods: vi.fn(),
  createOrgPaymentMethodSetup: vi.fn(),
  deleteOrgPaymentMethod: vi.fn(),
  listOrgInvoices: vi.fn(),
  getOrgPurchaseInvoice: vi.fn(),
}));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("OrgBillingSection", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists payment methods and invoices for the org", async () => {
    vi.mocked(sdk.listOrgPaymentMethods).mockResolvedValue(ok({ payment_methods: [{ id: "pm1", brand: "visa", last4: "4242" }] }) as never);
    vi.mocked(sdk.listOrgInvoices).mockResolvedValue(ok({ invoices: [{ transaction_id: "tx1", amount: 1000, currency: "USD" }] }) as never);
    render(<OrgBillingSection />);
    await waitFor(() => expect(sdk.listOrgPaymentMethods).toHaveBeenCalledWith(expect.objectContaining({ path: { org_id: "org-1" } })));
    expect(screen.getByText(/4242/)).toBeInTheDocument();
    expect(screen.getByText(/tx1/i)).toBeInTheDocument();
  });

  it("requires a TOTP code to start payment-method setup", async () => {
    vi.mocked(sdk.listOrgPaymentMethods).mockResolvedValue(ok({ payment_methods: [] }) as never);
    vi.mocked(sdk.listOrgInvoices).mockResolvedValue(ok({ invoices: [] }) as never);
    vi.mocked(sdk.createOrgPaymentMethodSetup).mockResolvedValue(ok({ client_secret: "seti_cs" }) as never);
    render(<OrgBillingSection />);
    await waitFor(() => expect(sdk.listOrgPaymentMethods).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText(/totp|authentication code|2fa/i), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /add payment method/i }));
    await waitFor(() =>
      expect(sdk.createOrgPaymentMethodSetup).toHaveBeenCalledWith(
        expect.objectContaining({ path: { org_id: "org-1" }, body: expect.objectContaining({ totp_code: "123456" }) }),
      ),
    );
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run tests/unit/components/organizations/operator/org-billing-section.test.tsx`
Expected: FAIL — component not found.

- [ ] **Step 3: Implement the section**

Build `OrgBillingSection` with two blocks — Payment methods (list, TOTP-gated setup that calls `createOrgPaymentMethodSetup({ path: { org_id }, body: { totp_code } })` then hands `client_secret` to Stripe Elements exactly as the individual setup component does, delete via `deleteOrgPaymentMethod({ path: { org_id, payment_method_id } })`) and Invoices (list via `listOrgInvoices`, each row a button calling `getOrgPurchaseInvoice({ path: { org_id, transaction_id } })` then `window.open(data.invoice_url, "_blank", "noopener,noreferrer")`). Confirm the exact request `body` field for TOTP (`totp_code`) and the setup + invoice response field names against `types.gen.ts` before finalizing; align component and test if they differ. Apply mobile-first classes and `min-h-[44px]` on every button/select/input.

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run tests/unit/components/organizations/operator/org-billing-section.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/components/modules/organizations/operator/org-billing-section.tsx tests/unit/components/organizations/operator/org-billing-section.test.tsx
git commit -m "Add org operator billing section (payment methods + invoices)"
```

### Task 8: Render Billing in the capability-sectioned Financials tab

**Files:**
- Modify: `frontend/src/app/(auth)/dashboard/organizations/[orgId]/financials/page.tsx`
- Create: `frontend/src/components/modules/organizations/operator/org-financials-tab.tsx` (client wrapper that composes sections by capability)
- Test: `frontend/tests/unit/components/organizations/operator/org-financials-tab.test.tsx`

**Interfaces:**
- Consumes: `useOrganization` (for `capabilities`), `OrgBillingSection`, existing `OrgAttestorFinancialsTab`.
- Produces: `<OrgFinancialsTab />` rendering Billing when `operator === "active"` and Earnings when `attestor`/`contributor` active.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/tests/unit/components/organizations/operator/org-financials-tab.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const caps: { current: Record<string, string> } = { current: {} };
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "admin", capabilities: caps.current }),
}));
vi.mock("@/components/modules/organizations/operator/org-billing-section", () => ({
  OrgBillingSection: () => <div data-testid="billing" />,
}));
vi.mock("@/components/modules/organizations/attestor/org-attestor-financials-tab", () => ({
  OrgAttestorFinancialsTab: () => <div data-testid="earnings" />,
}));
import { OrgFinancialsTab } from "@/components/modules/organizations/operator/org-financials-tab";

describe("OrgFinancialsTab", () => {
  it("renders Billing when operator is active", () => {
    caps.current = { operator: "active" };
    render(<OrgFinancialsTab orgId="org-1" />);
    expect(screen.getByTestId("billing")).toBeInTheDocument();
    expect(screen.queryByTestId("earnings")).toBeNull();
  });

  it("renders Earnings when attestor is active and Billing when both active", () => {
    caps.current = { operator: "active", attestor: "active" };
    render(<OrgFinancialsTab orgId="org-1" />);
    expect(screen.getByTestId("billing")).toBeInTheDocument();
    expect(screen.getByTestId("earnings")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run tests/unit/components/organizations/operator/org-financials-tab.test.tsx`
Expected: FAIL — component not found.

- [ ] **Step 3: Implement the wrapper**

```tsx
// frontend/src/components/modules/organizations/operator/org-financials-tab.tsx
"use client";

/**
 * Capability-sectioned org Financials tab.
 *
 * Composes money-OUT (operator Billing) and money-IN (contributor/attestor
 * Earnings) sections based on the org's active capabilities.
 */
import { useOrganization } from "@/components/modules/organizations/organization-context";
import { OrgBillingSection } from "./org-billing-section";
import { OrgAttestorFinancialsTab } from "@/components/modules/organizations/attestor/org-attestor-financials-tab";

/**
 * Render org financial sections that apply to the org's capabilities.
 *
 * @param props.orgId - Organization id (for the earnings sub-tab).
 */
export function OrgFinancialsTab({ orgId }: { orgId: string }) {
  const { capabilities } = useOrganization();
  const operatorActive = capabilities?.operator === "active";
  const earnsMoney = capabilities?.attestor === "active" || capabilities?.contributor === "active";

  return (
    <div className="grid gap-8">
      {operatorActive && (
        <section>
          <h2 className="px-4 pt-4 font-heading text-xl font-bold text-foreground md:px-6">Billing</h2>
          <OrgBillingSection />
        </section>
      )}
      {earnsMoney && (
        <section>
          <h2 className="px-4 pt-4 font-heading text-xl font-bold text-foreground md:px-6">Earnings</h2>
          <OrgAttestorFinancialsTab orgId={orgId} />
        </section>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Point the route page at the wrapper**

Replace the body of `frontend/src/app/(auth)/dashboard/organizations/[orgId]/financials/page.tsx` so it renders `<OrgFinancialsTab orgId={resolvedParams.orgId} />` instead of `<OrgAttestorFinancialsTab .../>` (keep the async `params` unwrap).

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx vitest run tests/unit/components/organizations/operator/org-financials-tab.test.tsx`
Expected: PASS. Confirm the real `useOrganization()` exposes `capabilities`; if capabilities live on a nested field, adjust the reads.

- [ ] **Step 6: Lint + typecheck + commit**

```bash
cd frontend && npm run lint && npx tsc --noEmit
git add "src/app/(auth)/dashboard/organizations/[orgId]/financials/page.tsx" src/components/modules/organizations/operator/org-financials-tab.tsx tests/unit/components/organizations/operator/org-financials-tab.test.tsx
git commit -m "Compose org Financials tab from operator Billing and attestor Earnings"
```

---

## Phase 4 — Org Projects (as operator)

### Task 9: Project API-mode selector

A small module that returns the correct project SDK calls for self vs org, so the existing project components can operate in org mode without forking.

**Files:**
- Create: `frontend/src/lib/projects/project-api-mode.ts`
- Test: `frontend/tests/unit/lib/project-api-mode.test.ts`

**Interfaces:**
- Consumes: `createProject`, `createOrgProject`, `acceptProposal`, `acceptOrgProposal`, `fundMilestone`, `fundOrgMilestone`, `approveDeliverable`, `approveOrgDeliverable`, `createDispute`, `createOrgDispute` from `@/lib/generated/sdk.gen`.
- Produces:
  - `type ProjectApiMode = { kind: "self" } | { kind: "org"; orgId: string }`
  - `projectApi(mode: ProjectApiMode)` → object with `createProject(body)`, `acceptProposal(projectId, proposalId)`, `fundMilestone(projectId, milestoneId, body)`, `approveDeliverable(projectId, milestoneId, deliverableId)`, `createDispute(projectId, body)` — each already binds `path` correctly and passes `headers`.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/tests/unit/lib/project-api-mode.test.ts
import { describe, expect, it, vi } from "vitest";
import { projectApi } from "@/lib/projects/project-api-mode";
import * as sdk from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  createProject: vi.fn(), createOrgProject: vi.fn(),
  acceptProposal: vi.fn(), acceptOrgProposal: vi.fn(),
  fundMilestone: vi.fn(), fundOrgMilestone: vi.fn(),
  approveDeliverable: vi.fn(), approveOrgDeliverable: vi.fn(),
  createDispute: vi.fn(), createOrgDispute: vi.fn(),
}));

describe("projectApi self mode", () => {
  it("createProject calls the self SDK with body only", async () => {
    await projectApi({ kind: "self" }).createProject({ title: "P" } as never);
    expect(sdk.createProject).toHaveBeenCalledWith(expect.objectContaining({ body: { title: "P" } }));
  });
});

describe("projectApi org mode", () => {
  it("createProject calls the org SDK with org_id path", async () => {
    await projectApi({ kind: "org", orgId: "org-1" }).createProject({ title: "P" } as never);
    expect(sdk.createOrgProject).toHaveBeenCalledWith(expect.objectContaining({ path: { org_id: "org-1" }, body: { title: "P" } }));
  });

  it("fundMilestone binds org_id, project_id, milestone_id", async () => {
    await projectApi({ kind: "org", orgId: "org-1" }).fundMilestone("proj-1", "ms-1", { payment_method_id: "pm1" } as never);
    expect(sdk.fundOrgMilestone).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-1", project_id: "proj-1", milestone_id: "ms-1" }, body: { payment_method_id: "pm1" } }),
    );
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run tests/unit/lib/project-api-mode.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the mode selector**

```ts
// frontend/src/lib/projects/project-api-mode.ts
/**
 * Project API mode selector.
 *
 * Returns project operations bound to either the individual endpoints or the
 * organization endpoints (path prefixed with org_id), so shared project
 * components run in org-operator mode without duplication.
 */
import {
  createProject, createOrgProject,
  acceptProposal, acceptOrgProposal,
  fundMilestone, fundOrgMilestone,
  approveDeliverable, approveOrgDeliverable,
  createDispute, createOrgDispute,
} from "@/lib/generated/sdk.gen";
import { configureBrowserClient, getAccessTokenHeaders } from "@/lib/auth/form-client";

export type ProjectApiMode = { kind: "self" } | { kind: "org"; orgId: string };

/** Build project operations bound to the given identity mode. */
export function projectApi(mode: ProjectApiMode) {
  const headers = () => {
    configureBrowserClient();
    return getAccessTokenHeaders();
  };
  const orgPath = (extra: Record<string, string>) =>
    mode.kind === "org" ? { org_id: mode.orgId, ...extra } : extra;

  return {
    createProject: (body: unknown) =>
      mode.kind === "org"
        ? createOrgProject({ body: body as never, headers: headers(), path: { org_id: mode.orgId } })
        : createProject({ body: body as never, headers: headers() }),
    acceptProposal: (projectId: string, proposalId: string) => {
      const path = orgPath({ project_id: projectId, proposal_id: proposalId }) as never;
      return mode.kind === "org"
        ? acceptOrgProposal({ headers: headers(), path })
        : acceptProposal({ headers: headers(), path });
    },
    fundMilestone: (projectId: string, milestoneId: string, body: unknown) => {
      const path = orgPath({ project_id: projectId, milestone_id: milestoneId }) as never;
      return mode.kind === "org"
        ? fundOrgMilestone({ body: body as never, headers: headers(), path })
        : fundMilestone({ body: body as never, headers: headers(), path });
    },
    approveDeliverable: (projectId: string, milestoneId: string, deliverableId: string) => {
      const path = orgPath({ project_id: projectId, milestone_id: milestoneId, deliverable_id: deliverableId }) as never;
      return mode.kind === "org"
        ? approveOrgDeliverable({ headers: headers(), path })
        : approveDeliverable({ headers: headers(), path });
    },
    createDispute: (projectId: string, body: unknown) => {
      const path = orgPath({ project_id: projectId }) as never;
      return mode.kind === "org"
        ? createOrgDispute({ body: body as never, headers: headers(), path })
        : createDispute({ body: body as never, headers: headers(), path });
    },
  };
}
```

Note: the org milestone-fund / deliverable-approve paths in the OpenAPI (`…/milestones/{milestone_id}/fund`, `…/deliverables/{deliverable_id}/approve`) omit the intermediate `milestones/{milestone_id}` segment for the deliverable approve on the org router — verify the exact `path` params each generated org fn expects against `sdk.gen.ts` and drop any param the fn does not declare. Align the test accordingly.

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run tests/unit/lib/project-api-mode.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/lib/projects/project-api-mode.ts tests/unit/lib/project-api-mode.test.ts
git commit -m "Add project API-mode selector for self vs org operations"
```

### Task 10: Org projects tab + route

List the org's operator projects and expose create. Reuse `project-create-form` and `project-list-shell` in org mode.

**Files:**
- Create: `frontend/src/components/modules/organizations/operator/org-projects-tab.tsx`
- Create: `frontend/src/app/(auth)/dashboard/organizations/[orgId]/projects/page.tsx`
- Modify: `frontend/src/components/modules/projects/project-create-form.tsx` (accept an optional `mode` prop; default `{ kind: "self" }`)
- Test: `frontend/tests/unit/components/organizations/operator/org-projects-tab.test.tsx`, and extend the project-create-form test

**Interfaces:**
- Consumes: `projectApi` from `@/lib/projects/project-api-mode`; existing `ProjectCreateForm`, `ProjectListShell`.
- Produces: `<OrgProjectsTab />`.

- [ ] **Step 1: Read the reuse targets**

Run:
```bash
cd frontend && sed -n '1,60p' src/components/modules/projects/project-create-form.tsx && echo "---" && sed -n '1,40p' src/components/modules/projects/project-list-shell.tsx
```
Record their current props and which SDK fn `project-create-form` calls, and how `project-list-shell` fetches (it likely needs an org-scoped list fn — find the generated `listOrgProjects…` name; if org project listing is a GET on `/v1/orgs/{org_id}/projects`, add its alias in Task 0's map first, or use the full generated name).

- [ ] **Step 2: Write the failing create-form mode test**

Add to `frontend/tests/unit/components/projects/project-create-form.test.tsx` (create the file if absent, mirroring the mock pattern) a test that, given `mode={{ kind: "org", orgId: "org-1" }}`, submitting the form routes through `createOrgProject` with `path: { org_id: "org-1" }`. Mock `@/lib/projects/project-api-mode` `projectApi` and assert its `createProject` is invoked, OR mock the SDK directly and assert `createOrgProject`.

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npx vitest run tests/unit/components/projects/project-create-form.test.tsx`
Expected: FAIL — form ignores `mode`.

- [ ] **Step 4: Add `mode` to `ProjectCreateForm`**

Give `ProjectCreateForm` an optional `mode?: ProjectApiMode` prop defaulting to `{ kind: "self" }`, and replace its direct `createProject(...)` call with `projectApi(mode).createProject(body)`. This preserves existing self behavior (the default), so existing tests stay green.

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx vitest run tests/unit/components/projects/project-create-form.test.tsx`
Expected: PASS.

- [ ] **Step 6: Write the failing projects-tab test**

```tsx
// frontend/tests/unit/components/organizations/operator/org-projects-tab.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { OrgProjectsTab } from "@/components/modules/organizations/operator/org-projects-tab";

vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "admin" }),
}));
vi.mock("@/components/modules/projects/project-create-form", () => ({
  ProjectCreateForm: (props: { mode?: { kind: string; orgId?: string } }) => (
    <div data-testid="create-form">{props.mode?.kind}:{props.mode?.orgId}</div>
  ),
}));
vi.mock("@/components/modules/projects/project-list-shell", () => ({
  ProjectListShell: (props: { mode?: { kind: string; orgId?: string } }) => (
    <div data-testid="list-shell">{props.mode?.kind}:{props.mode?.orgId}</div>
  ),
}));

describe("OrgProjectsTab", () => {
  it("renders create + list in org mode bound to the org id", () => {
    render(<OrgProjectsTab />);
    expect(screen.getByTestId("create-form")).toHaveTextContent("org:org-1");
    expect(screen.getByTestId("list-shell")).toHaveTextContent("org:org-1");
  });
});
```

- [ ] **Step 7: Run to verify it fails**

Run: `cd frontend && npx vitest run tests/unit/components/organizations/operator/org-projects-tab.test.tsx`
Expected: FAIL — component not found.

- [ ] **Step 8: Implement the tab + route**

```tsx
// frontend/src/components/modules/organizations/operator/org-projects-tab.tsx
"use client";

/**
 * Org operator Projects tab.
 *
 * Lets an organization post Projects and manage them in org mode, reusing the
 * individual project components bound to the org's API endpoints.
 */
import { useOrganization } from "@/components/modules/organizations/organization-context";
import { ProjectCreateForm } from "@/components/modules/projects/project-create-form";
import { ProjectListShell } from "@/components/modules/projects/project-list-shell";
import type { ProjectApiMode } from "@/lib/projects/project-api-mode";

/**
 * Render org project creation + listing in org-operator mode.
 */
export function OrgProjectsTab() {
  const { orgId } = useOrganization();
  const mode: ProjectApiMode = { kind: "org", orgId };
  return (
    <div className="grid gap-6 p-4 md:p-6">
      <ProjectCreateForm mode={mode} />
      <ProjectListShell mode={mode} />
    </div>
  );
}
```

```tsx
// frontend/src/app/(auth)/dashboard/organizations/[orgId]/projects/page.tsx
/**
 * Org operator Projects route.
 *
 * Renders the org projects tab inside the dashboard shell. Backend OrgAdmin
 * gating applies on every underlying call.
 */
import { OrgProjectsTab } from "@/components/modules/organizations/operator/org-projects-tab";

export default function OrgProjectsPage() {
  return <OrgProjectsTab />;
}
```

If `ProjectListShell` does not yet accept a `mode` prop / cannot list org projects, add a `mode?: ProjectApiMode` prop and switch its list fetch to the org project-list generated fn when in org mode (mirror the `project-api-mode` pattern; add a `listOrgProjects` alias in the Task 0 map if missing). Keep the self default unchanged so existing tests pass.

- [ ] **Step 9: Run to verify it passes**

Run: `cd frontend && npx vitest run tests/unit/components/organizations/operator/org-projects-tab.test.tsx`
Expected: PASS.

- [ ] **Step 10: Lint + typecheck + commit**

```bash
cd frontend && npm run lint && npx tsc --noEmit
git add "src/app/(auth)/dashboard/organizations/[orgId]/projects/page.tsx" src/components/modules/organizations/operator/org-projects-tab.tsx src/components/modules/projects/project-create-form.tsx src/components/modules/projects/project-list-shell.tsx tests/unit/components/organizations/operator/org-projects-tab.test.tsx tests/unit/components/projects/project-create-form.test.tsx
git commit -m "Add org operator Projects tab reusing project components in org mode"
```

### Task 11: Org project workspace actions (accept, fund, approve, dispute)

Wire the milestone-funding, deliverable-review, and dispute components to operate in org mode when reached from the org projects tab.

**Files:**
- Modify: `frontend/src/components/modules/projects/milestone-funding-panel.tsx`, `deliverable-review-card.tsx`, `milestone-dispute-panel.tsx`, and `project-workspace.tsx` (thread `mode` down)
- Test: extend each component's test (or create) with an org-mode case

**Interfaces:**
- Consumes: `projectApi` mode selector.
- Produces: each component accepts an optional `mode?: ProjectApiMode` (default self) and routes its mutating call through `projectApi(mode)`.

- [ ] **Step 1: For each of the three action components, write a failing org-mode test**

For `milestone-funding-panel.tsx`: given `mode={{ kind: "org", orgId: "org-1" }}`, confirming funding routes through `fundOrgMilestone` with `path` including `org_id: "org-1"`. Mirror for `deliverable-review-card` (`approveOrgDeliverable`) and `milestone-dispute-panel` (`createOrgDispute`). Use the established SDK mock pattern; assert the org fn is called with the org_id-bearing path.

- [ ] **Step 2: Run each to verify failure**

Run: `cd frontend && npx vitest run tests/unit/components/projects/`
Expected: the three new org-mode assertions FAIL (components ignore `mode`).

- [ ] **Step 3: Thread `mode` through**

Add `mode?: ProjectApiMode` (default `{ kind: "self" }`) to each component and to `project-workspace.tsx`, replacing direct `fundMilestone`/`approveDeliverable`/`createDispute` calls with `projectApi(mode).*`. `project-workspace.tsx` passes its `mode` down to the child panels. Keep self as default so existing tests stay green.

- [ ] **Step 4: Run to verify passes**

Run: `cd frontend && npx vitest run tests/unit/components/projects/`
Expected: PASS (existing self tests + new org-mode tests).

- [ ] **Step 5: Lint + typecheck + commit**

```bash
cd frontend && npm run lint && npx tsc --noEmit
git add src/components/modules/projects/ tests/unit/components/projects/
git commit -m "Route org project milestone funding, deliverable approval, and disputes through org mode"
```

---

## Phase 5 — E2E

### Task 12: Playwright e2e for the org-operator critical flows

**Files:**
- Create: `frontend/tests/e2e/org-operator.spec.ts`

**Interfaces:**
- Consumes: the running app + seeded backend (same harness the existing e2e specs use — read `frontend/tests/e2e/purchase.spec.ts` and `project.spec.ts` for the login/seed helpers and base URL setup; reuse them, do not invent new fixtures).

- [ ] **Step 1: Write the buy-as-org → grant → download flow**

Following the existing e2e helper pattern, script: sign in as an org admin (operator-active org) → open a published Framework → checkout → select the org in the buyer selector → complete Stripe test payment → open the org Library tab → expand a license → grant to a team → sign in as a member of that team → download the artifact succeeds; a non-granted member gets blocked. Assert on visible UI state at each step.

- [ ] **Step 2: Write the org project → fund → approve → escrow-release flow**

Script: org admin posts a project from the org Projects tab → a contributor submits a proposal → org accepts → org funds a milestone (org payment method + TOTP) → contributor submits a deliverable → org approves → assert escrow released to the contributor (via the visible project/milestone state).

- [ ] **Step 3: Run the e2e specs**

Run: `cd frontend && npx playwright test tests/e2e/org-operator.spec.ts`
Expected: PASS against the staging/dev harness. If the shared harness cannot seed an operator-active org, add the seed step to the existing e2e setup used by `purchase.spec.ts` rather than mocking.

- [ ] **Step 4: Commit**

```bash
cd frontend && git add tests/e2e/org-operator.spec.ts
git commit -m "Add org-operator e2e coverage (buy-as-org, grants, project escrow)"
```

---

## Self-Review

**Spec coverage:**
- Buy-as-org selector (spec Phase 1 / decision 2) → Tasks 1–2. ✓
- Org Library + per-license member/team grants (Phase 2 / decision 4) → Tasks 4–6. ✓
- Presigned artifact download (security) → Task 5. ✓
- Capability-sectioned Financials Billing (Phase 3 / decision 3) → Tasks 7–8. ✓
- Org Projects as operator, reuse via mode (Phase 4 / decision 6) → Tasks 9–11. ✓
- Operator tab gating on capability+admin (decision 5) → Task 3. ✓
- E2E critical flows (spec Testing) → Task 12. ✓
- Client regen (implicit prerequisite; endpoints were missing from SDK) → Task 0. ✓

**Type consistency:** Generated fn short names are defined once in Task 0 and reused verbatim in every later task. `ProjectApiMode` defined in Task 9, consumed in Tasks 10–11. `BuyerOption` defined in Task 1, consumed in Task 2. Each reuse-shape task carries an explicit "verify against `types.gen.ts`" instruction because response field names (`items`, `grants`, `download_url`, `invoice_url`, `totp_code`) are asserted but must be confirmed post-regen.

**Known verification points the implementer must resolve against the regenerated client (not guesses to hardcode):** exact generated full-names for the alias map (Task 0 Step 2); `useOrganization()` shape for `capabilities` (Tasks 3, 8); library/grant/invoice response field names; org milestone/deliverable path params (Task 9). Each is flagged inline with how to reconcile.

**Placeholder scan:** No TBD/TODO. Every code step ships real code; reuse tasks that depend on unread files (project-list-shell, member/team list fns) include an explicit read-first step plus the exact reconciliation rule rather than a vague "wire it up."
