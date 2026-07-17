# Org Capability Activation UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give org owners/admins a Profile-tab card to self-activate the Contributor and Operator capabilities, closing test-guide steps OC-1 and OO-1 as real UI tests.

**Architecture:** One new client component `OrganizationCapabilities` reads capability status from the existing `useOrganization()` context, renders a status pill + Activate button per capability, and drives activation through the existing generated SDK behind the existing `ConfirmDialog`. It is mounted inside `OrganizationProfile`. No backend, OpenAPI, or SDK changes — the endpoints and generated client functions already exist.

**Tech Stack:** Next.js 15 (App Router, client component), Tailwind, TypeScript, vitest + @testing-library/react.

## Global Constraints

- Frontend only. No backend / OpenAPI / migration / SDK-regeneration changes — endpoints and generated SDK functions already exist.
- Work directly on `main`. No new branches.
- Commit messages: NO `Co-Authored-By` trailer.
- TDD RED→GREEN: write the failing test, watch it fail, then the minimal code to pass.
- Mobile-first: Activate button ≥ 44px touch target (`min-h-11`); rows stack on mobile, align to a row from `sm:` up.
- Owner/admin only; render nothing for non-admins or a suspended org.
- Reuse `@/components/ui/confirm-dialog` (`ConfirmDialog`) — do not build a new modal.
- Verification before "done": run `npx tsc --noEmit` and `npx vitest run <test file>` and read the output.
- Exact SDK function names (already generated, in `@/lib/generated/sdk.gen`):
  - `activateContributorCapabilityV1OrgsOrgIdContributorCapabilityActivatePost`
  - `activateOperatorCapabilityV1OrgsOrgIdOperatorCapabilityActivatePost`
  - Both take `{ path: { org_id: string }, headers }` and return `{ response: { ok: boolean }, error?: { detail?: { error_code?: string } }, data? }`.

---

### Task 1: `OrganizationCapabilities` component

**Files:**
- Create: `frontend/src/components/modules/organizations/organization-capabilities.tsx`
- Test: `frontend/src/components/modules/organizations/organization-capabilities.test.tsx`

**Interfaces:**
- Consumes: `useOrganization()` from `./organization-context` returning `{ orgId: string; role: string; capabilities?: Record<string, string>; isSuspended: boolean }`; `ConfirmDialog` from `@/components/ui/confirm-dialog`; `getAccessTokenHeaders` from `@/lib/auth/form-client`; `useToast` from `@/components/ui/toast` (`{ success(msg), error(msg) }`); `useRouter` from `next/navigation` (`{ refresh() }`).
- Produces: `export function OrganizationCapabilities(): JSX.Element | null` — consumed by Task 2.

All cycles share this test-file preamble. Create it once in Step 1 and keep it at the top of the test file:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useOrganization } from "./organization-context";
import {
  activateContributorCapabilityV1OrgsOrgIdContributorCapabilityActivatePost as activateContributor,
  activateOperatorCapabilityV1OrgsOrgIdOperatorCapabilityActivatePost as activateOperator,
} from "@/lib/generated/sdk.gen";
import { OrganizationCapabilities } from "./organization-capabilities";

const { refresh, toastSuccess, toastError } = vi.hoisted(() => ({
  refresh: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ success: toastSuccess, error: toastError }),
}));
vi.mock("./organization-context", () => ({ useOrganization: vi.fn() }));
vi.mock("@/lib/generated/sdk.gen", () => ({
  activateContributorCapabilityV1OrgsOrgIdContributorCapabilityActivatePost: vi.fn(),
  activateOperatorCapabilityV1OrgsOrgIdOperatorCapabilityActivatePost: vi.fn(),
}));

/** Set the org context the component reads. */
function setOrg(overrides: Partial<{ role: string; capabilities: Record<string, string>; isSuspended: boolean }> = {}) {
  vi.mocked(useOrganization).mockReturnValue({
    orgId: "org-1",
    role: "owner",
    capabilities: {},
    isSuspended: false,
    ...overrides,
  } as never);
}

beforeEach(() => {
  vi.clearAllMocks();
});
```

- [ ] **Step 1: Write the failing tracer test**

Append to the test file:

```tsx
describe("OrganizationCapabilities", () => {
  it("shows an Activate button for a capability that is not active", () => {
    setOrg({ capabilities: {} });
    render(<OrganizationCapabilities />);
    expect(screen.getByRole("button", { name: "Activate Contributor capability" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Activate Operator capability" })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-capabilities.test.tsx`
Expected: FAIL — cannot resolve `./organization-capabilities` (module does not exist).

- [ ] **Step 3: Minimal component — rows + unconditional Activate buttons**

Create `frontend/src/components/modules/organizations/organization-capabilities.tsx`:

```tsx
"use client";

/**
 * Org capability activation card.
 *
 * Lets an org owner/admin self-activate the Contributor and Operator
 * capabilities. Each activation grants every member the derived role, so the
 * action is gated behind a confirm dialog. Attestor is intentionally excluded —
 * it has its own application/NDA front-door.
 *
 * Maps to: test-guide OC-1, OO-1.
 */
import { useOrganization } from "./organization-context";

type CapabilityKey = "contributor" | "operator";

type CapabilityMeta = {
  key: CapabilityKey;
  label: string;
  description: string;
};

const CAPABILITIES: CapabilityMeta[] = [
  {
    key: "contributor",
    label: "Contributor",
    description: "Create and sell frameworks under the organization's identity.",
  },
  {
    key: "operator",
    label: "Operator",
    description: "Purchase frameworks and post projects as the organization.",
  },
];

/**
 * Card of self-service capability rows for org owners/admins.
 */
export function OrganizationCapabilities() {
  const { capabilities } = useOrganization();

  return (
    <section className="max-w-3xl overflow-hidden rounded-3xl border border-border-default bg-surface-1 shadow-sm">
      <div className="border-b border-border-default bg-surface-2/50 px-8 py-6">
        <h2 className="font-heading text-xl font-bold tracking-tight text-foreground">
          Capabilities
        </h2>
        <p className="mt-1 text-sm text-foreground-muted">
          Activate what your organization can do on the marketplace.
        </p>
      </div>

      <ul className="flex flex-col divide-y divide-border-default">
        {CAPABILITIES.map((cap) => (
          <li
            key={cap.key}
            className="flex flex-col gap-3 px-8 py-5 sm:flex-row sm:items-center sm:justify-between"
          >
            <div>
              <p className="text-sm font-semibold text-foreground">{cap.label}</p>
              <p className="mt-0.5 text-sm text-foreground-muted">{cap.description}</p>
            </div>
            <div className="flex items-center gap-3">
              <button
                type="button"
                aria-label={`Activate ${cap.label} capability`}
                className="min-h-11 rounded-xl bg-foreground px-5 py-2 text-sm font-semibold text-background shadow-sm transition hover:bg-foreground/90"
              >
                Activate
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-capabilities.test.tsx`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/modules/organizations/organization-capabilities.tsx frontend/src/components/modules/organizations/organization-capabilities.test.tsx
git commit -m "Add OrganizationCapabilities card with activate rows"
```

- [ ] **Step 6: Write the failing status-state tests**

Append inside the `describe`:

```tsx
  it("shows an Active pill and no Activate button when the capability is active", () => {
    setOrg({ capabilities: { operator: "active" } });
    render(<OrganizationCapabilities />);
    expect(screen.getByText("Active")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Activate Operator capability" })).toBeNull();
  });

  it("shows a Suspended pill and no Activate button when the capability is suspended", () => {
    setOrg({ capabilities: { contributor: "suspended" } });
    render(<OrganizationCapabilities />);
    expect(screen.getByText("Suspended")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Activate Contributor capability" })).toBeNull();
  });

  it("shows a Not active pill for a capability with no status", () => {
    setOrg({ capabilities: {} });
    render(<OrganizationCapabilities />);
    expect(screen.getAllByText("Not active").length).toBe(2);
  });
```

- [ ] **Step 7: Run tests to verify the new ones fail**

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-capabilities.test.tsx`
Expected: FAIL — no "Active"/"Suspended"/"Not active" text; button always rendered.

- [ ] **Step 8: Add StatusPill + gate the Activate button on status**

Add the pill component above `OrganizationCapabilities` in `organization-capabilities.tsx`:

```tsx
/** Render a status pill for a capability's current state. */
function StatusPill({ status }: { status?: string }) {
  if (status === "active") {
    return (
      <span className="rounded-md border border-success/30 bg-success/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-success">
        Active
      </span>
    );
  }
  if (status === "suspended") {
    return (
      <span className="rounded-md border border-warning/30 bg-warning/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-warning">
        Suspended
      </span>
    );
  }
  return (
    <span className="rounded-md border border-border-default bg-surface-2 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-foreground-muted">
      Not active
    </span>
  );
}
```

Replace the row's `<div className="flex items-center gap-3">…</div>` block with a status-aware version:

```tsx
            <div className="flex items-center gap-3">
              <StatusPill status={capabilities?.[cap.key]} />
              {capabilities?.[cap.key] !== "active" && capabilities?.[cap.key] !== "suspended" ? (
                <button
                  type="button"
                  aria-label={`Activate ${cap.label} capability`}
                  className="min-h-11 rounded-xl bg-foreground px-5 py-2 text-sm font-semibold text-background shadow-sm transition hover:bg-foreground/90"
                >
                  Activate
                </button>
              ) : null}
            </div>
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-capabilities.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/modules/organizations/organization-capabilities.tsx frontend/src/components/modules/organizations/organization-capabilities.test.tsx
git commit -m "Gate activate button on capability status with pills"
```

- [ ] **Step 11: Write the failing visibility-guard tests**

Append inside the `describe`:

```tsx
  it("renders nothing for a non-admin member", () => {
    setOrg({ role: "member" });
    const { container } = render(<OrganizationCapabilities />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the org is suspended", () => {
    setOrg({ role: "owner", isSuspended: true });
    const { container } = render(<OrganizationCapabilities />);
    expect(container).toBeEmptyDOMElement();
  });
```

- [ ] **Step 12: Run tests to verify the new ones fail**

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-capabilities.test.tsx`
Expected: FAIL — component renders the card regardless of role / suspension.

- [ ] **Step 13: Add the owner/admin + not-suspended guard**

In `organization-capabilities.tsx`, change the destructure and add an early return at the top of `OrganizationCapabilities`, before the `return (`:

```tsx
  const { role, capabilities, isSuspended } = useOrganization();

  const isAdminOrOwner = role === "owner" || role === "admin";
  if (!isAdminOrOwner || isSuspended) {
    return null;
  }
```

- [ ] **Step 14: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-capabilities.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 15: Commit**

```bash
git add frontend/src/components/modules/organizations/organization-capabilities.tsx frontend/src/components/modules/organizations/organization-capabilities.test.tsx
git commit -m "Hide capabilities card from non-admins and suspended orgs"
```

- [ ] **Step 16: Write the failing activation-success test**

Append inside the `describe`:

```tsx
  it("activates a capability after confirmation, then toasts and refreshes", async () => {
    setOrg({ capabilities: {} });
    vi.mocked(activateContributor).mockResolvedValue({ response: { ok: true } } as never);
    render(<OrganizationCapabilities />);

    fireEvent.click(screen.getByRole("button", { name: "Activate Contributor capability" }));
    // Confirm dialog is now open; its confirm button has a distinct name.
    fireEvent.click(screen.getByRole("button", { name: "Activate Contributor" }));

    await waitFor(() => expect(activateContributor).toHaveBeenCalledTimes(1));
    expect(activateContributor).toHaveBeenCalledWith({
      path: { org_id: "org-1" },
      headers: { Authorization: "Bearer test" },
    });
    expect(activateOperator).not.toHaveBeenCalled();
    expect(toastSuccess).toHaveBeenCalledWith("Contributor capability activated.");
    expect(refresh).toHaveBeenCalledTimes(1);
  });
```

- [ ] **Step 17: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-capabilities.test.tsx`
Expected: FAIL — clicking the row button does nothing; no confirm dialog, SDK never called.

- [ ] **Step 18: Wire the ConfirmDialog + activation handler**

Update the imports at the top of `organization-capabilities.tsx`:

```tsx
"use client";

/**
 * Org capability activation card.
 *
 * Lets an org owner/admin self-activate the Contributor and Operator
 * capabilities. Each activation grants every member the derived role, so the
 * action is gated behind a confirm dialog. Attestor is intentionally excluded —
 * it has its own application/NDA front-door.
 *
 * Maps to: test-guide OC-1, OO-1.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";

import {
  activateContributorCapabilityV1OrgsOrgIdContributorCapabilityActivatePost as activateContributor,
  activateOperatorCapabilityV1OrgsOrgIdOperatorCapabilityActivatePost as activateOperator,
} from "@/lib/generated/sdk.gen";
import { getAccessTokenHeaders } from "@/lib/auth/form-client";
import { useToast } from "@/components/ui/toast";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useOrganization } from "./organization-context";
```

Replace the body of `OrganizationCapabilities` (from the guard through the closing `}`) with the interactive version:

```tsx
export function OrganizationCapabilities() {
  const { orgId, role, capabilities, isSuspended } = useOrganization();
  const router = useRouter();
  const toast = useToast();

  const [pending, setPending] = useState<CapabilityKey | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isAdminOrOwner = role === "owner" || role === "admin";
  if (!isAdminOrOwner || isSuspended) {
    return null;
  }

  const pendingMeta = CAPABILITIES.find((cap) => cap.key === pending) ?? null;

  function openConfirm(key: CapabilityKey) {
    setError(null);
    setPending(key);
  }

  function closeConfirm() {
    if (busy) {
      return;
    }
    setPending(null);
    setError(null);
  }

  async function handleConfirm() {
    if (!pendingMeta) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result =
        pendingMeta.key === "contributor"
          ? await activateContributor({
              path: { org_id: orgId },
              headers: getAccessTokenHeaders(),
            })
          : await activateOperator({
              path: { org_id: orgId },
              headers: getAccessTokenHeaders(),
            });

      if (!result.response.ok) {
        setError(
          result.error?.detail?.error_code ||
            `Failed to activate ${pendingMeta.label} capability`,
        );
        return;
      }

      toast.success(`${pendingMeta.label} capability activated.`);
      setPending(null);
      router.refresh();
    } catch {
      setError("An unexpected error occurred.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="max-w-3xl overflow-hidden rounded-3xl border border-border-default bg-surface-1 shadow-sm">
      <div className="border-b border-border-default bg-surface-2/50 px-8 py-6">
        <h2 className="font-heading text-xl font-bold tracking-tight text-foreground">
          Capabilities
        </h2>
        <p className="mt-1 text-sm text-foreground-muted">
          Activate what your organization can do on the marketplace.
        </p>
      </div>

      <ul className="flex flex-col divide-y divide-border-default">
        {CAPABILITIES.map((cap) => (
          <li
            key={cap.key}
            className="flex flex-col gap-3 px-8 py-5 sm:flex-row sm:items-center sm:justify-between"
          >
            <div>
              <p className="text-sm font-semibold text-foreground">{cap.label}</p>
              <p className="mt-0.5 text-sm text-foreground-muted">{cap.description}</p>
            </div>
            <div className="flex items-center gap-3">
              <StatusPill status={capabilities?.[cap.key]} />
              {capabilities?.[cap.key] !== "active" &&
              capabilities?.[cap.key] !== "suspended" ? (
                <button
                  type="button"
                  aria-label={`Activate ${cap.label} capability`}
                  onClick={() => openConfirm(cap.key)}
                  className="min-h-11 rounded-xl bg-foreground px-5 py-2 text-sm font-semibold text-background shadow-sm transition hover:bg-foreground/90"
                >
                  Activate
                </button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>

      <ConfirmDialog
        open={pendingMeta !== null}
        eyebrow="Capability"
        title={pendingMeta ? `Activate ${pendingMeta.label} capability?` : ""}
        description={
          pendingMeta
            ? `Every current and future member gains the ${pendingMeta.label} role. Only a platform admin can reverse this.`
            : ""
        }
        confirmLabel={pendingMeta ? `Activate ${pendingMeta.label}` : "Activate"}
        busy={busy}
        error={error}
        onConfirm={handleConfirm}
        onClose={closeConfirm}
      />
    </section>
  );
}
```

- [ ] **Step 19: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-capabilities.test.tsx`
Expected: PASS (7 tests).

- [ ] **Step 20: Commit**

```bash
git add frontend/src/components/modules/organizations/organization-capabilities.tsx frontend/src/components/modules/organizations/organization-capabilities.test.tsx
git commit -m "Activate org capability through confirm dialog"
```

- [ ] **Step 21: Write the failing activation-error test**

Append inside the `describe`:

```tsx
  it("surfaces the error and keeps the dialog open when activation fails", async () => {
    setOrg({ capabilities: {} });
    vi.mocked(activateOperator).mockResolvedValue({
      response: { ok: false },
      error: { detail: { error_code: "rate_limited" } },
    } as never);
    render(<OrganizationCapabilities />);

    fireEvent.click(screen.getByRole("button", { name: "Activate Operator capability" }));
    fireEvent.click(screen.getByRole("button", { name: "Activate Operator" }));

    expect(await screen.findByText("rate_limited")).toBeTruthy();
    // Dialog stays open: its title is still present.
    expect(screen.getByText("Activate Operator capability?")).toBeTruthy();
    expect(refresh).not.toHaveBeenCalled();
  });
```

- [ ] **Step 22: Run test to verify it fails or passes**

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-capabilities.test.tsx`
Expected: PASS — the error branch added in Step 18 already handles this. (If it FAILS, fix the error branch until it passes; do not weaken the test.)

- [ ] **Step 23: Commit (only if there are changes)**

```bash
git add frontend/src/components/modules/organizations/organization-capabilities.test.tsx
git commit -m "Lock activation-failure behaviour with a test"
```

- [ ] **Step 24: Typecheck the component**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0, no errors.

---

### Task 2: Mount the card in the Profile tab

**Files:**
- Modify: `frontend/src/components/modules/organizations/organization-profile.tsx`
- Test: `frontend/src/components/modules/organizations/organization-profile.test.tsx` (create if absent)

**Interfaces:**
- Consumes: `OrganizationCapabilities` from `./organization-capabilities` (Task 1).

- [ ] **Step 1: Write the failing wiring test**

Create `frontend/src/components/modules/organizations/organization-profile.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useOrganization } from "./organization-context";
import { OrganizationProfile } from "./organization-profile";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  updateOrganizationV1OrgsOrgIdPatch: vi.fn(),
  activateContributorCapabilityV1OrgsOrgIdContributorCapabilityActivatePost: vi.fn(),
  activateOperatorCapabilityV1OrgsOrgIdOperatorCapabilityActivatePost: vi.fn(),
}));
vi.mock("./organization-context", () => ({ useOrganization: vi.fn() }));
// The logo uploader hits browser APIs not needed for this test.
vi.mock("./organization-logo-uploader", () => ({
  OrganizationLogoUploader: () => null,
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useOrganization).mockReturnValue({
    orgId: "org-1",
    role: "owner",
    org: { id: "org-1", name: "Test Org", website: null, description: null, logo_url: null, suspended_at: null },
    capabilities: {},
    isSuspended: false,
  } as never);
});

describe("OrganizationProfile", () => {
  it("renders the Capabilities card for an owner", () => {
    render(<OrganizationProfile />);
    expect(screen.getByText("Capabilities")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Activate Contributor capability" })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-profile.test.tsx`
Expected: FAIL — "Capabilities" text not found (card not mounted).

- [ ] **Step 3: Import and render the card in `organization-profile.tsx`**

This is exactly three edits. The goal structure: an outer `flex flex-col gap-6` stack whose first child is the existing profile card `div` and whose second child is `<OrganizationCapabilities />`.

**Edit 1** — add the import alongside the other local imports (near line 12, next to the `OrganizationLogoUploader` import):

```tsx
import { OrganizationCapabilities } from "./organization-capabilities";
```

**Edit 2** — the current return opens like this:

```tsx
  return (
    <div className="max-w-3xl overflow-hidden rounded-3xl border border-border-default bg-surface-1 shadow-sm transition hover:shadow-bento">
```

Replace those two lines with an outer stack wrapper plus the inner card `div`:

```tsx
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div className="overflow-hidden rounded-3xl border border-border-default bg-surface-1 shadow-sm transition hover:shadow-bento">
```

**Edit 3** — the current return tail is:

```tsx
      </form>
    </div>
  );
```

Replace it so the profile card closes and the capabilities card becomes the outer stack's second child:

```tsx
      </form>
      </div>
      <OrganizationCapabilities />
    </div>
  );
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-profile.test.tsx`
Expected: PASS.

- [ ] **Step 5: Typecheck and lint**

Run: `cd frontend && npx tsc --noEmit && npx eslint src/components/modules/organizations/organization-capabilities.tsx src/components/modules/organizations/organization-profile.tsx`
Expected: exit 0, no errors.

- [ ] **Step 6: Run both org test files together**

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-capabilities.test.tsx src/components/modules/organizations/organization-profile.test.tsx`
Expected: PASS (8 tests total).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/modules/organizations/organization-profile.tsx frontend/src/components/modules/organizations/organization-profile.test.tsx
git commit -m "Mount capabilities card on the org Profile tab"
```

---

## Notes for the implementer

- The two activation SDK functions have different generated return types; do **not** store them in a shared array typed to one of them. `handleConfirm` branches on `pendingMeta.key` so each call site keeps its own type (as written in Task 1 Step 18).
- The row Activate button (`aria-label="Activate Contributor capability"`) and the confirm button (`confirmLabel="Activate Contributor"`) have deliberately distinct accessible names so tests can target each unambiguously — keep them distinct.
- `capabilities` may be `undefined`; always read it as `capabilities?.[key]`.
- Do not add a deactivate/suspend control — reversal is platform-admin only and out of scope.
