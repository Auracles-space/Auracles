# Become-Attestor Front-Door Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a user a single guided path from a "Become an Attestor" CTA to the correct organization's attestor gate-checklist, creating an org first when they have none.

**Architecture:** One auth-gated smart-resolve entry route (`/dashboard/organizations/become-attestor`) loads `GET /v1/orgs/mine`, computes attestor-eligible orgs client-side, and branches: 0 eligible → create-org dialog (attestor intent); exactly 1 → redirect to its Attestor tab; ≥2 → picker. Every CTA is a plain link to that route. Frontend-only; no spec, contract, or backend change; reuses the existing dialog, endpoints, and gate-checklist UI.

**Tech Stack:** Next.js 15 (App Router, client components), Tailwind, vitest + @testing-library/react, playwright. Generated API client in `src/lib/generated/sdk.gen.ts`.

## Global Constraints

- Frontend only. No change to `contracts/openapi.yaml`, backend, or the regenerated client. Reuse existing endpoints only.
- Do NOT rebuild or alter the attestor gate-checklist (`attestor-application-tab.tsx`) or the application flow.
- Mobile-first: base styles target 375px; enhance with `sm:`/`md:`/`lg:`. Every interactive element ≥ 44×44px. Content within a `max-w` container.
- TDD: write the failing test first, watch it fail, then minimal implementation. One behavior per cycle.
- Component tests live in `frontend/tests/unit/components/organizations/`. E2E in `frontend/tests/e2e/`.
- Test mocking convention: `vi.mock("@/lib/generated/sdk.gen", …)`, `vi.mock("@/lib/auth/form-client", …)`, `vi.mock("next/navigation", …)`; `ok<T>()` result helper.
- Commit messages end at the last meaningful line — **no `Co-Authored-By` trailer**. Work directly on `main`; do not create a branch.
- All commands run from `frontend/`.

**Eligibility rule (used verbatim in Tasks 2–4):** an org is attestor-eligible when `role ∈ {"owner","admin"}` AND `capabilities.attestor !== "active"`.

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/components/modules/organizations/become-attestor.ts` | Pure eligibility + resolve logic (no React). |
| Create | `src/components/modules/organizations/become-attestor-picker.tsx` | Picker UI for ≥2 eligible orgs + "create new" tile. |
| Create | `src/app/(auth)/dashboard/organizations/become-attestor/page.tsx` | Entry route: load orgs, resolve, branch. |
| Modify | `src/components/modules/organizations/create-organization-dialog.tsx` | Add `redirectIntent?: "attestor"` prop. |
| Modify | `src/app/(public)/attestors/page.tsx` | Repoint CTA href to entry route. |
| Modify | `src/app/(auth)/dashboard/organizations/page.tsx` | Header + empty-state "Become an Attestor" CTA. |
| Modify | `src/components/modules/organizations/attestor/attestor-application-tab.tsx` | Apply-entry copy clarity when no application exists. |
| Create | `tests/unit/components/organizations/become-attestor.test.ts` | Resolve-logic unit tests. |
| Create | `tests/unit/components/organizations/become-attestor-picker.test.tsx` | Picker tests. |
| Create | `tests/unit/components/organizations/become-attestor-page.test.tsx` | Entry-route branch tests. |
| Create | `tests/unit/components/organizations/create-organization-dialog.test.tsx` | Dialog redirect-intent tests. |
| Create | `tests/e2e/become-attestor.spec.ts` | CTA → create org → Attestor checklist. |

---

### Task 1: `CreateOrganizationDialog` gains `redirectIntent`

**Files:**
- Modify: `src/components/modules/organizations/create-organization-dialog.tsx`
- Test: `tests/unit/components/organizations/create-organization-dialog.test.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `CreateOrganizationDialog` prop `redirectIntent?: "attestor"`. When `"attestor"`, a successful create navigates to `/dashboard/organizations/{id}/attestor`; otherwise to `/dashboard/organizations/{id}` (unchanged).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/components/organizations/create-organization-dialog.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CreateOrganizationDialog } from "@/components/modules/organizations/create-organization-dialog";
import { createOrganizationV1OrgsPost } from "@/lib/generated/sdk.gen";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ createOrganizationV1OrgsPost: vi.fn() }));

const ok = <T,>(d: T) => ({
  data: d,
  error: undefined,
  request: new Request("http://t"),
  response: new Response(null, { status: 200 }),
});

async function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText(/Organization Name/i), { target: { value: "Acme" } });
  fireEvent.change(screen.getByLabelText(/Slug/i), { target: { value: "acme" } });
  fireEvent.click(screen.getByRole("button", { name: /^Create Organization$/i }));
}

describe("CreateOrganizationDialog redirect intent", () => {
  beforeEach(() => vi.clearAllMocks());

  it("routes to the org's Attestor tab when redirectIntent is attestor", async () => {
    vi.mocked(createOrganizationV1OrgsPost).mockResolvedValue(ok({ id: "org-9" }));
    render(<CreateOrganizationDialog open onClose={() => {}} redirectIntent="attestor" />);
    await fillAndSubmit();
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/dashboard/organizations/org-9/attestor"),
    );
  });

  it("routes to the org page by default (no redirectIntent)", async () => {
    vi.mocked(createOrganizationV1OrgsPost).mockResolvedValue(ok({ id: "org-9" }));
    render(<CreateOrganizationDialog open onClose={() => {}} />);
    await fillAndSubmit();
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/dashboard/organizations/org-9"),
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/unit/components/organizations/create-organization-dialog.test.tsx`
Expected: FAIL — the attestor case routes to `/dashboard/organizations/org-9` (no `/attestor` suffix) because the prop does not exist yet.

- [ ] **Step 3: Implement the minimal change**

In `src/components/modules/organizations/create-organization-dialog.tsx`, extend the props type (lines 13-16):

```tsx
type CreateOrganizationDialogProps = {
  open: boolean;
  onClose: () => void;
  /** When "attestor", a successful create lands on the org's Attestor gate-checklist. */
  redirectIntent?: "attestor";
};
```

Update the component signature (line 29):

```tsx
export function CreateOrganizationDialog({
  open,
  onClose,
  redirectIntent,
}: CreateOrganizationDialogProps) {
```

Replace the success navigation (line 79) with an intent-aware target:

```tsx
      // Success — attestor intent lands on the gate-checklist; default keeps the org page.
      const orgId = result.data?.id;
      router.push(
        redirectIntent === "attestor"
          ? `/dashboard/organizations/${orgId}/attestor`
          : `/dashboard/organizations/${orgId}`,
      );
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run tests/unit/components/organizations/create-organization-dialog.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/modules/organizations/create-organization-dialog.tsx tests/unit/components/organizations/create-organization-dialog.test.tsx
git commit -m "Add redirectIntent to CreateOrganizationDialog for attestor onboarding"
```

---

### Task 2: Eligibility + resolve logic (pure)

**Files:**
- Create: `src/components/modules/organizations/become-attestor.ts`
- Test: `tests/unit/components/organizations/become-attestor.test.ts`

**Interfaces:**
- Consumes: `MyOrganizationResponse` from `@/lib/generated/types.gen` (`{ org: { id, name, ... }, role, capabilities: Record<string,string> }`).
- Produces:
  - `type AttestorEligibleOrg = { id: string; name: string; attestorStatus: string | null }`
  - `type AttestorEntryResolution = { kind: "create" } | { kind: "direct"; orgId: string } | { kind: "picker"; orgs: AttestorEligibleOrg[] }`
  - `eligibleAttestorOrgs(orgs: MyOrganizationResponse[]): AttestorEligibleOrg[]`
  - `resolveAttestorEntry(orgs: MyOrganizationResponse[]): AttestorEntryResolution`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/components/organizations/become-attestor.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { MyOrganizationResponse } from "@/lib/generated/types.gen";
import {
  eligibleAttestorOrgs,
  resolveAttestorEntry,
} from "@/components/modules/organizations/become-attestor";

function org(
  id: string,
  role: string,
  capabilities: Record<string, string> = {},
): MyOrganizationResponse {
  return {
    org: { id, name: `Org ${id}`, slug: id, country: "US" },
    role,
    capabilities,
  } as MyOrganizationResponse;
}

describe("eligibleAttestorOrgs", () => {
  it("keeps owner/admin orgs that are not already active attestors", () => {
    const orgs = [
      org("a", "owner"),
      org("b", "admin", { attestor: "pending" }),
      org("c", "member"),
      org("d", "owner", { attestor: "active" }),
    ];
    expect(eligibleAttestorOrgs(orgs).map((o) => o.id)).toEqual(["a", "b"]);
  });

  it("carries the attestor capability status (or null) for display", () => {
    const orgs = [org("a", "owner"), org("b", "admin", { attestor: "pending" })];
    const result = eligibleAttestorOrgs(orgs);
    expect(result[0]).toMatchObject({ id: "a", attestorStatus: null });
    expect(result[1]).toMatchObject({ id: "b", attestorStatus: "pending" });
  });
});

describe("resolveAttestorEntry", () => {
  it("returns create when there are no eligible orgs", () => {
    expect(resolveAttestorEntry([org("d", "owner", { attestor: "active" })])).toEqual({
      kind: "create",
    });
    expect(resolveAttestorEntry([org("c", "member")])).toEqual({ kind: "create" });
    expect(resolveAttestorEntry([])).toEqual({ kind: "create" });
  });

  it("returns direct when exactly one org is eligible", () => {
    expect(resolveAttestorEntry([org("a", "owner"), org("c", "member")])).toEqual({
      kind: "direct",
      orgId: "a",
    });
  });

  it("returns picker when two or more orgs are eligible", () => {
    const res = resolveAttestorEntry([org("a", "owner"), org("b", "admin")]);
    expect(res.kind).toBe("picker");
    if (res.kind === "picker") {
      expect(res.orgs.map((o) => o.id)).toEqual(["a", "b"]);
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/unit/components/organizations/become-attestor.test.ts`
Expected: FAIL — module `become-attestor` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `src/components/modules/organizations/become-attestor.ts`:

```ts
/**
 * Become-attestor entry resolution.
 *
 * Pure client-side logic that decides, from the user's organizations, how the
 * "Become an Attestor" front door should route: create a new org, jump to a
 * single eligible org's gate-checklist, or present a picker.
 *
 * Maps to: become-attestor front-door design (2026-07-12).
 */
import type { MyOrganizationResponse } from "@/lib/generated/types.gen";

/** An org the current user may apply as an attestor with, plus its display status. */
export type AttestorEligibleOrg = {
  id: string;
  name: string;
  /** capabilities.attestor value (e.g. "pending"), or null when no application exists. */
  attestorStatus: string | null;
};

/** Where the front door should send the user. */
export type AttestorEntryResolution =
  | { kind: "create" }
  | { kind: "direct"; orgId: string }
  | { kind: "picker"; orgs: AttestorEligibleOrg[] };

const APPLY_ROLES = new Set(["owner", "admin"]);

/**
 * Filter the user's orgs to those they can open an attestor application for.
 *
 * Eligible = owner/admin AND not already an active attestor. Backend enforces
 * owner/admin on create; an active-attestor org 409s on re-apply.
 */
export function eligibleAttestorOrgs(
  orgs: MyOrganizationResponse[],
): AttestorEligibleOrg[] {
  return orgs
    .filter(
      (o) => APPLY_ROLES.has(o.role) && o.capabilities?.attestor !== "active",
    )
    .map((o) => ({
      id: o.org.id,
      name: o.org.name,
      attestorStatus: o.capabilities?.attestor ?? null,
    }));
}

/**
 * Decide how the "Become an Attestor" CTA resolves for this user's orgs.
 */
export function resolveAttestorEntry(
  orgs: MyOrganizationResponse[],
): AttestorEntryResolution {
  const eligible = eligibleAttestorOrgs(orgs);
  if (eligible.length === 0) return { kind: "create" };
  if (eligible.length === 1) return { kind: "direct", orgId: eligible[0].id };
  return { kind: "picker", orgs: eligible };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run tests/unit/components/organizations/become-attestor.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/modules/organizations/become-attestor.ts tests/unit/components/organizations/become-attestor.test.ts
git commit -m "Add become-attestor eligibility and entry resolution logic"
```

---

### Task 3: Picker component

**Files:**
- Create: `src/components/modules/organizations/become-attestor-picker.tsx`
- Test: `tests/unit/components/organizations/become-attestor-picker.test.tsx`

**Interfaces:**
- Consumes: `AttestorEligibleOrg` (Task 2); `CreateOrganizationDialog` with `redirectIntent` (Task 1).
- Produces: `BecomeAttestorPicker({ orgs }: { orgs: AttestorEligibleOrg[] })`. Each org row navigates (`router.push`) to `/dashboard/organizations/{id}/attestor`. A "Create a new organization" tile opens `CreateOrganizationDialog` with `redirectIntent="attestor"`. Rows show `Resume` when `attestorStatus` is truthy, else `Not started`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/components/organizations/become-attestor-picker.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BecomeAttestorPicker } from "@/components/modules/organizations/become-attestor-picker";
import type { AttestorEligibleOrg } from "@/components/modules/organizations/become-attestor";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const orgs: AttestorEligibleOrg[] = [
  { id: "a", name: "Alpha", attestorStatus: null },
  { id: "b", name: "Beta", attestorStatus: "pending" },
];

describe("BecomeAttestorPicker", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders each org with the right status label", () => {
    render(<BecomeAttestorPicker orgs={orgs} />);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText(/Not started/i)).toBeInTheDocument();
    expect(screen.getByText(/Resume/i)).toBeInTheDocument();
  });

  it("routes to an org's Attestor tab when its row is chosen", () => {
    render(<BecomeAttestorPicker orgs={orgs} />);
    fireEvent.click(screen.getByRole("button", { name: /Alpha/i }));
    expect(push).toHaveBeenCalledWith("/dashboard/organizations/a/attestor");
  });

  it("opens the create dialog with attestor intent from the create tile", () => {
    render(<BecomeAttestorPicker orgs={orgs} />);
    fireEvent.click(screen.getByRole("button", { name: /Create a new organization/i }));
    // Dialog title appears once the dialog is open.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/unit/components/organizations/become-attestor-picker.test.tsx`
Expected: FAIL — module `become-attestor-picker` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `src/components/modules/organizations/become-attestor-picker.tsx`:

```tsx
"use client";

/**
 * Organization picker for the become-attestor front door.
 *
 * Shown when the user owns/administers two or more attestor-eligible orgs.
 * Choosing a row opens that org's attestor gate-checklist; the trailing tile
 * creates a new organization with attestor intent.
 *
 * Maps to: become-attestor front-door design (2026-07-12).
 */
import { useState } from "react";
import { useRouter } from "next/navigation";

import type { AttestorEligibleOrg } from "./become-attestor";
import { CreateOrganizationDialog } from "./create-organization-dialog";

/**
 * Render the eligible-org chooser plus a create-new-org tile.
 *
 * @param orgs - Attestor-eligible orgs (already filtered upstream).
 */
export function BecomeAttestorPicker({ orgs }: { orgs: AttestorEligibleOrg[] }) {
  const router = useRouter();
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-10 md:py-16">
      <header className="mb-8">
        <h1 className="font-heading text-2xl font-bold tracking-tight text-foreground md:text-3xl">
          Choose an organization
        </h1>
        <p className="mt-2 text-sm text-foreground-muted">
          Pick the organization that will apply to become an attestor, or create a new one.
        </p>
      </header>

      <ul className="flex flex-col gap-3">
        {orgs.map((o) => (
          <li key={o.id}>
            <button
              type="button"
              onClick={() => router.push(`/dashboard/organizations/${o.id}/attestor`)}
              className="flex min-h-[44px] w-full items-center justify-between gap-4 rounded-2xl border border-border-default bg-surface-1 p-4 text-left transition hover:border-accent/30 hover:shadow-bento"
            >
              <span className="font-heading text-base font-bold text-foreground">
                {o.name}
              </span>
              <span className="rounded-badge bg-surface-2 px-2 py-1 text-xs font-medium text-foreground-muted">
                {o.attestorStatus ? "Resume" : "Not started"}
              </span>
            </button>
          </li>
        ))}
        <li>
          <button
            type="button"
            onClick={() => setIsCreateOpen(true)}
            className="flex min-h-[44px] w-full items-center justify-center gap-2 rounded-2xl border border-dashed border-border-default bg-surface-1 p-4 text-sm font-semibold text-foreground transition hover:border-accent/30"
          >
            Create a new organization
          </button>
        </li>
      </ul>

      <CreateOrganizationDialog
        open={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        redirectIntent="attestor"
      />
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run tests/unit/components/organizations/become-attestor-picker.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/components/modules/organizations/become-attestor-picker.tsx tests/unit/components/organizations/become-attestor-picker.test.tsx
git commit -m "Add become-attestor org picker component"
```

---

### Task 4: Entry route page

**Files:**
- Create: `src/app/(auth)/dashboard/organizations/become-attestor/page.tsx`
- Test: `tests/unit/components/organizations/become-attestor-page.test.tsx`

**Interfaces:**
- Consumes: `resolveAttestorEntry` (Task 2), `BecomeAttestorPicker` (Task 3), `CreateOrganizationDialog` with `redirectIntent` (Task 1); `listMyOrganizationsV1OrgsMineGet` from `@/lib/generated/sdk.gen`; `getAccessTokenHeaders`, `configureBrowserClient` from `@/lib/auth/form-client`.
- Produces: default-exported `BecomeAttestorPage` React component (the route).

Note: the test file lives under `tests/unit/components/...` (not the app dir) so it is picked up with the other component tests; it imports the page via its `@/app/...` path alias.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/components/organizations/become-attestor-page.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BecomeAttestorPage from "@/app/(auth)/dashboard/organizations/become-attestor/page";
import { listMyOrganizationsV1OrgsMineGet } from "@/lib/generated/sdk.gen";

const replace = vi.fn();
const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push }) }));
vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  listMyOrganizationsV1OrgsMineGet: vi.fn(),
}));

const ok = <T,>(d: T) => ({
  data: d,
  error: undefined,
  request: new Request("http://t"),
  response: new Response(null, { status: 200 }),
});
const fail = () => ({
  data: undefined,
  error: { detail: "x" },
  request: new Request("http://t"),
  response: new Response(null, { status: 500 }),
});
const org = (id: string, role: string, capabilities = {}) => ({
  org: { id, name: `Org ${id}`, slug: id, country: "US" },
  role,
  capabilities,
});

describe("BecomeAttestorPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("redirects to the single eligible org's Attestor tab", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({ organizations: [org("a", "owner")] }),
    );
    render(<BecomeAttestorPage />);
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/dashboard/organizations/a/attestor"),
    );
  });

  it("renders the picker when two or more orgs are eligible", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({ organizations: [org("a", "owner"), org("b", "admin")] }),
    );
    render(<BecomeAttestorPage />);
    await waitFor(() =>
      expect(screen.getByText(/Choose an organization/i)).toBeInTheDocument(),
    );
    expect(replace).not.toHaveBeenCalled();
  });

  it("opens the create dialog when no org is eligible", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({ organizations: [org("c", "member")] }),
    );
    render(<BecomeAttestorPage />);
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
  });

  it("shows an error with retry when loading fails", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(fail());
    render(<BecomeAttestorPage />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Retry/i })).toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/unit/components/organizations/become-attestor-page.test.tsx`
Expected: FAIL — page module does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `src/app/(auth)/dashboard/organizations/become-attestor/page.tsx`:

```tsx
"use client";

/**
 * Become-attestor front-door entry route.
 *
 * Loads the user's organizations, resolves how to route (create a new org,
 * jump to the sole eligible org's gate-checklist, or show a picker), and
 * renders that outcome. Auth-gated by the (auth) route group.
 *
 * Maps to: become-attestor front-door design (2026-07-12).
 */
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  configureBrowserClient,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { listMyOrganizationsV1OrgsMineGet } from "@/lib/generated/sdk.gen";
import type { AttestorEntryResolution } from "@/components/modules/organizations/become-attestor";
import { resolveAttestorEntry } from "@/components/modules/organizations/become-attestor";
import { BecomeAttestorPicker } from "@/components/modules/organizations/become-attestor-picker";
import { CreateOrganizationDialog } from "@/components/modules/organizations/create-organization-dialog";

/**
 * Render the smart-resolve entry point for becoming an attestor.
 */
export default function BecomeAttestorPage() {
  const router = useRouter();
  const [resolution, setResolution] = useState<AttestorEntryResolution | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    configureBrowserClient();
    try {
      const result = await listMyOrganizationsV1OrgsMineGet({
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok || !result.data) {
        setError("We couldn't load your organizations.");
        setLoading(false);
        return;
      }
      const next = resolveAttestorEntry(result.data.organizations);
      // A single eligible org needs no UI — send them straight to the checklist.
      if (next.kind === "direct") {
        router.replace(`/dashboard/organizations/${next.orgId}/attestor`);
        return;
      }
      setResolution(next);
      setLoading(false);
    } catch {
      setError("Something went wrong loading your organizations.");
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <Spinner className="h-8 w-8 text-accent" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto w-full max-w-2xl px-4 py-16">
        <div className="rounded-2xl border border-error/50 bg-error/5 p-6 text-center">
          <p className="text-error">{error}</p>
          <Button className="mt-4" variant="secondary" onClick={() => void load()}>
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (resolution?.kind === "picker") {
    return <BecomeAttestorPicker orgs={resolution.orgs} />;
  }

  // kind === "create": no eligible org — open the dialog with attestor intent.
  // Cancelling returns to the organizations list.
  return (
    <CreateOrganizationDialog
      open
      onClose={() => router.push("/dashboard/organizations")}
      redirectIntent="attestor"
    />
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run tests/unit/components/organizations/become-attestor-page.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add "src/app/(auth)/dashboard/organizations/become-attestor/page.tsx" tests/unit/components/organizations/become-attestor-page.test.tsx
git commit -m "Add become-attestor smart-resolve entry route"
```

---

### Task 5: Wire the CTA surfaces

**Files:**
- Modify: `src/app/(public)/attestors/page.tsx:39-44`
- Modify: `src/app/(auth)/dashboard/organizations/page.tsx`
- Modify: `src/components/modules/organizations/attestor/attestor-application-tab.tsx`
- Test: `tests/unit/components/organizations/become-attestor-page.test.tsx` (already covers the entry route; this task adds a dashboard-CTA assertion below)

**Interfaces:**
- Consumes: the entry route URL `/dashboard/organizations/become-attestor` (Task 4).
- Produces: no new exports. Three surfaces now link to the entry route; the attestor tab clarifies its apply entry.

- [ ] **Step 1: Write the failing test (dashboard CTA)**

Append to `tests/unit/components/organizations/become-attestor-page.test.tsx` a new describe block for the org list header CTA. First add the imports/mocks at the top if not present, then:

```tsx
// --- Organizations dashboard CTA ---
import OrganizationsPage from "@/app/(auth)/dashboard/organizations/page";

describe("Organizations dashboard become-attestor CTA", () => {
  beforeEach(() => vi.clearAllMocks());

  it("links to the become-attestor entry route in the header", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({ organizations: [org("a", "owner")] }),
    );
    render(<OrganizationsPage />);
    await waitFor(() =>
      expect(screen.getByRole("link", { name: /Become an Attestor/i })).toHaveAttribute(
        "href",
        "/dashboard/organizations/become-attestor",
      ),
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/unit/components/organizations/become-attestor-page.test.tsx`
Expected: FAIL — no "Become an Attestor" link on the organizations dashboard yet.

- [ ] **Step 3: Implement the three wirings**

**(a) Public directory** — `src/app/(public)/attestors/page.tsx`, change the CTA `href` (line 40) from `/dashboard/organizations` to the entry route:

```tsx
        <Link 
          href="/dashboard/organizations/become-attestor"
          className="inline-flex h-11 shrink-0 items-center justify-center rounded-control bg-foreground px-4 text-sm font-medium text-background transition hover:opacity-90"
        >
          Become an Attestor
        </Link>
```

(`h-10` → `h-11` meets the 44px touch-target constraint.)

**(b) Organizations dashboard** — `src/app/(auth)/dashboard/organizations/page.tsx`. In the header (replace the single `Button` at line 50) render the create button plus a link CTA:

```tsx
        <div className="flex flex-col gap-2 sm:flex-row">
          <Link
            href="/dashboard/organizations/become-attestor"
            className="inline-flex min-h-[44px] items-center justify-center rounded-control border border-border-default bg-surface-1 px-4 text-sm font-medium text-foreground transition hover:border-accent/30"
          >
            Become an Attestor
          </Link>
          <Button onClick={() => setIsCreateOpen(true)}>Create Organization</Button>
        </div>
```

In the empty state (after the existing "Create Organization" button at line 111), add the same link:

```tsx
          <Button onClick={() => setIsCreateOpen(true)}>Create Organization</Button>
          <Link
            href="/dashboard/organizations/become-attestor"
            className="mt-3 inline-flex min-h-[44px] items-center justify-center text-sm font-medium text-accent hover:underline"
          >
            Become an Attestor
          </Link>
```

(`Link` is already imported in this file.)

**(c) Attestor tab apply-entry clarity** — `src/components/modules/organizations/attestor/attestor-application-tab.tsx`, in the header block (the `<p>` under "Attestor Application", around line 174), make the first-step intent explicit when nothing is submitted yet. Replace that paragraph with:

```tsx
        <p className="mt-1 text-sm text-foreground-muted">
          Complete the following checklist to become a verified Org Attestor on
          Auracles. Start with <span className="font-semibold text-foreground">Apply</span> below.
        </p>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run tests/unit/components/organizations/become-attestor-page.test.tsx`
Expected: PASS (all blocks, including the new dashboard CTA test).

- [ ] **Step 5: Commit**

```bash
git add "src/app/(public)/attestors/page.tsx" "src/app/(auth)/dashboard/organizations/page.tsx" src/components/modules/organizations/attestor/attestor-application-tab.tsx tests/unit/components/organizations/become-attestor-page.test.tsx
git commit -m "Wire become-attestor CTA into directory, dashboard, and attestor tab"
```

---

### Task 6: End-to-end flow

**Files:**
- Create: `tests/e2e/become-attestor.spec.ts`

**Interfaces:**
- Consumes: the full wired flow (Tasks 1–5).
- Produces: a playwright spec exercising CTA → create org → land on the Attestor gate-checklist.

Study `tests/e2e/organizations.spec.ts` first for the project's auth/setup helpers (login fixture, base URL, how orgs are seeded) and mirror them. The assertions below are the required behavior; adapt selectors/fixtures to match that file's conventions.

- [ ] **Step 1: Write the failing e2e test**

Create `tests/e2e/become-attestor.spec.ts`:

```ts
import { test, expect } from "@playwright/test";
// Reuse the project's auth helper as used in organizations.spec.ts.
// import { loginAsNewUser } from "./helpers/auth";  // match the real helper path/name

test.describe("Become an attestor front door", () => {
  test("a user with no org creates one and lands on the attestor checklist", async ({ page }) => {
    // 1. Authenticate as a fresh user with no organizations (project helper).
    // await loginAsNewUser(page);

    // 2. Enter via the public directory CTA.
    await page.goto("/attestors");
    await page.getByRole("link", { name: /Become an Attestor/i }).click();

    // 3. No eligible org -> create-org dialog appears.
    await expect(page.getByRole("dialog")).toBeVisible();
    const suffix = Date.now();
    await page.getByLabel(/Organization Name/i).fill("E2E Attestor Org");
    await page.getByLabel(/Slug/i).fill(`e2e-attestor-${suffix}`);
    await page.getByRole("button", { name: /^Create Organization$/i }).click();

    // 4. Lands on that org's attestor gate-checklist.
    await expect(page).toHaveURL(/\/dashboard\/organizations\/[^/]+\/attestor$/);
    await expect(page.getByText(/Attestor Application/i)).toBeVisible();
    await expect(page.getByText(/Apply/i)).toBeVisible();
  });
});
```

- [ ] **Step 2: Run test to verify it fails (or is pending fixture wiring)**

Run: `npx playwright test tests/e2e/become-attestor.spec.ts`
Expected: FAIL until the auth helper import is wired to match `organizations.spec.ts`. Wire the login fixture, then the test drives the real flow.

- [ ] **Step 3: Wire the auth fixture**

Replace the commented `loginAsNewUser` import and call with the actual helper used by `tests/e2e/organizations.spec.ts` (same import path, same invocation). No app code changes — the flow already works from Tasks 1–5.

- [ ] **Step 4: Run test to verify it passes**

Run: `npx playwright test tests/e2e/become-attestor.spec.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/become-attestor.spec.ts
git commit -m "Add e2e coverage for become-attestor front door"
```

---

## Final verification

- [ ] `npx vitest run tests/unit/components/organizations` — all green.
- [ ] `npx tsc --noEmit` — no type errors.
- [ ] `npx eslint src/components/modules/organizations/become-attestor.ts src/components/modules/organizations/become-attestor-picker.tsx "src/app/(auth)/dashboard/organizations/become-attestor/page.tsx"` — clean.
- [ ] `npx playwright test tests/e2e/become-attestor.spec.ts` — passes.
- [ ] Manually verify at 375px: entry route, picker, and dashboard CTA render without horizontal scroll; all buttons/links ≥ 44px.
