# "Become an Attestor" Front-Door — Design

**Date:** 2026-07-12
**Scope:** Frontend only (Next.js 15 App Router, Tailwind). No spec, contract, or backend change.
**Status:** Approved for planning.

---

## Problem

A person who wants their organization to become an attestor has no guided path.
The backend model (specced in `2026-07-04-org-attestor-design.md` and
`2026-07-06-attestation-frontend-design.md`) is intentionally two acts:

1. Create a **generic** organization (`create_organization` — org-core spec).
2. That org **applies** for the attestor capability through the existing
   8-gate checklist (`attestor-application-tab.tsx`), which collects all the
   "special data" (legal name, registration number, incorporation docs,
   sectors, jurisdictions, credentials, references, KYB, undertakings, tax
   doc, trial).

This model is deliberate — the frontend spec (line 39) chose a **revisitable
gate-checklist, not a linear wizard**, because gates bounce on `needs_info`.
We honor that model. The gate-checklist is **not** rebuilt.

The only gap is the **front door**: today the "Become an Attestor" button on
`/attestors` drops the user at `/dashboard/organizations` (a plain list) with
no guidance to create an org and open its Attestor tab. A user with zero orgs
is stuck.

## Goal

Add a single guided entry point that takes a user from a "Become an Attestor"
CTA to the correct org's Attestor gate-checklist, creating an org first when
needed. Reuse every existing backend endpoint and the existing gate-checklist
UI.

## Non-Goals

- No combined "create attesting org" form (rejected — contradicts the specced
  gate-checklist model; would need spec + backend change).
- No change to the gate-checklist / application flow itself.
- No change to `create_organization` or the attestor-application endpoints.
- No new backend endpoint. All data the front door needs is already returned
  by `GET /v1/orgs/mine`.

---

## Architecture

One smart-resolve **entry route** owns all logic. Every CTA is a plain link to
it, so the routing rule lives in exactly one place.

```
CTA (any surface) ──▶ /dashboard/organizations/become-attestor
                          │  loads GET /v1/orgs/mine
                          │  eligible = role∈{owner,admin} AND
                          │             capabilities.attestor !== "active"
                          ├ 0 eligible ▶ create-org dialog (attestor intent)
                          │               └▶ /dashboard/organizations/{id}/attestor
                          ├ 1 eligible ▶ router.replace →
                          │               /dashboard/organizations/{id}/attestor
                          └ ≥2 eligible ▶ picker
                                           ├ pick org ▶ that org's Attestor tab
                                           └ "Create new org" ▶ dialog (attestor intent)
```

### Data source (existing, no change)

`GET /v1/orgs/mine` → `MyOrganizationsResponse`:

```ts
type MyOrganizationResponse = {
  org: OrganizationResponse;              // has id, slug, name
  role: string;                           // "owner" | "admin" | "member"
  capabilities: { [key: string]: string };// e.g. { attestor: "active" | "pending" | ... }
  nda_required?: boolean;
};
```

Eligibility is computed client-side:

- **Eligible to apply:** `role ∈ {"owner", "admin"}` AND
  `capabilities.attestor !== "active"`.
  - Backend enforces owner/admin on `create_application`; filtering here
    avoids sending members into a 403.
  - An org already `active` attestor 409s on re-apply
    (`"Organization is already an active attestor."`); excluding it avoids the
    error and is not an eligible target.
- **Resume vs Not started (display only):** if `capabilities.attestor` is a
  non-active, non-empty value (e.g. `pending`), label the picker row
  **"Resume"**; otherwise **"Not started"**.

---

## Components

### 1. Entry route — `src/app/(auth)/dashboard/organizations/become-attestor/page.tsx` (new)

Client component. Behavior:

1. On mount: `configureBrowserClient()`, then
   `listMyOrganizationsV1OrgsMineGet({ headers: getAccessTokenHeaders() })`.
2. While loading: spinner (match org list page pattern).
3. On load failure: inline error card + Retry button (match org list page).
4. On success, compute `eligible` (above) and branch:
   - `eligible.length === 0` → open `CreateOrganizationDialog` with attestor
     intent (dialog handles navigation on success).
   - `eligible.length === 1` → `router.replace(
     "/dashboard/organizations/" + eligible[0].org.id + "/attestor")`.
   - `eligible.length >= 2` → render `<BecomeAttestorPicker orgs={eligible} />`.

Auth-gated by the existing `(auth)` route group + middleware. A logged-out
visitor hitting this URL bounces to login and returns via the existing `?next`
mechanism.

### 2. Picker — `src/components/modules/organizations/become-attestor-picker.tsx` (new)

Props: `{ orgs: MyOrganizationResponse[] }`.

Renders (mobile-first, 44px touch targets, `max-w` content container):

- Header: "Choose the organization to apply as an attestor".
- One card/button per eligible org: org name + status badge
  (`Not started` / `Resume`). Click → `router.push` to that org's Attestor
  tab.
- A final "Create a new organization" tile → opens `CreateOrganizationDialog`
  with attestor intent.

No business logic beyond navigation; eligibility is already filtered by the
entry route.

### 3. `CreateOrganizationDialog` — modify `src/components/modules/organizations/create-organization-dialog.tsx`

Add an optional prop:

```ts
type CreateOrganizationDialogProps = {
  open: boolean;
  onClose: () => void;
  redirectIntent?: "attestor";   // NEW — default undefined
};
```

On successful create, choose the redirect target:

- `redirectIntent === "attestor"` →
  `router.push("/dashboard/organizations/" + result.data.id + "/attestor")`.
- otherwise (default, unchanged) →
  `router.push("/dashboard/organizations/" + result.data.id)`.

Existing call sites pass no `redirectIntent`, so their behavior is unchanged.

### 4. CTA wiring (the three approved surfaces)

- **Public `/attestors`** — `src/app/(public)/attestors/page.tsx`: repoint the
  existing "Become an Attestor" `Link` `href` from `/dashboard/organizations`
  to `/dashboard/organizations/become-attestor`.
- **Organizations dashboard** — `src/app/(auth)/dashboard/organizations/page.tsx`:
  add a "Become an Attestor" CTA in the **list header** (next to "Create
  Organization") and in the **empty state** (when the user has zero orgs).
  Both are `Link`s to the entry route.
- **Org Attestor tab hint** — `attestor-application-tab.tsx` /
  `apply-gate.tsx`: minor copy clarity so the "Apply" entry is obvious when no
  application exists. No structural change; the gate already renders.

---

## Error handling

| Case | Handling |
|------|----------|
| `GET /v1/orgs/mine` fails | Inline error card + Retry (match org list page pattern). |
| User has orgs but none eligible (all members, or all already active attestors) | Treated as `0 eligible` → create-org dialog path (they can spin up a new org to apply as). |
| Create-org slug conflict (409) | Existing dialog handling (`"This slug is already taken."`). |
| Logged-out user hits entry route | Middleware bounce to login, return via `?next`. |
| Concurrent: org became active attestor between load and click | Backend 409 on the Attestor tab's apply action (existing behavior); the gate surfaces the "already an active attestor" state. Front door does not need to double-guard. |

---

## Testing (TDD — RED→GREEN per behavior)

**Unit / component (vitest + RTL + msw):**

- Entry-route resolve:
  - 0 eligible orgs → create-org dialog opens.
  - exactly 1 eligible → `router.replace` called with that org's Attestor tab.
  - ≥2 eligible → picker rendered with those orgs.
  - orgs present but all `role === "member"` → treated as 0 eligible.
  - orgs present but all `capabilities.attestor === "active"` → treated as 0
    eligible.
  - my-orgs load failure → error card + Retry.
- Picker:
  - renders only the orgs passed in; each row routes to the right Attestor tab.
  - status badge shows `Resume` for a `pending` attestor cap, `Not started`
    otherwise.
  - "Create new organization" tile opens the dialog with attestor intent.
- `CreateOrganizationDialog`:
  - `redirectIntent="attestor"` → success pushes `/.../{id}/attestor`.
  - no `redirectIntent` → success pushes `/.../{id}` (unchanged).

**E2E (playwright):**

- `become-attestor.spec.ts`: from the public `/attestors` CTA → (logged-in
  user with no org) → create org → land on the org's Attestor gate-checklist.

**Constraints:** mobile-first, verified at 375px; interactive targets ≥
44×44px; content within `max-w` container. No Co-Authored-By trailers; work on
`main`.

---

## Files touched

| Action | Path |
|--------|------|
| Create | `src/app/(auth)/dashboard/organizations/become-attestor/page.tsx` |
| Create | `src/components/modules/organizations/become-attestor-picker.tsx` |
| Modify | `src/components/modules/organizations/create-organization-dialog.tsx` (add `redirectIntent`) |
| Modify | `src/app/(public)/attestors/page.tsx` (repoint CTA href) |
| Modify | `src/app/(auth)/dashboard/organizations/page.tsx` (header + empty-state CTA) |
| Modify | `attestor-application-tab.tsx` / `apply-gate.tsx` (apply-entry copy clarity) |
| Create | `frontend/tests/e2e/become-attestor.spec.ts` |
| Create | component tests colocated per existing convention |
