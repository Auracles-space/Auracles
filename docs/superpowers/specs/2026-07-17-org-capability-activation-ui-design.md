# Org Capability Activation UI — Design

**Date:** 2026-07-17
**Status:** Approved (brainstorming)
**Maps to:** test-guide OC-1 (Contributor activate), OO-1 (Operator activate) in `docs/auracles-ui-full-test-scenarios.md`

## Problem

The backend exposes self-service capability activation for org owners/admins:

- `POST /v1/orgs/{org_id}/contributor-capability/activate`
- `POST /v1/orgs/{org_id}/operator-capability/activate`

Both are live, gated by `OrgAdmin` (owner/admin), rate-limited (5/hr), take no
prerequisites, and grant the derived role to all org members on success. The
generated SDK exposes them
(`activateContributorCapabilityV1OrgsOrgIdContributorCapabilityActivatePost`,
`activateOperatorCapabilityV1OrgsOrgIdOperatorCapabilityActivatePost`).

**No frontend UI calls them.** The org shell reads capability status to decide
which tabs to show (Operator, Projects, Financials) but offers no way to turn a
capability on. So test-guide steps OC-1 and OO-1 cannot be executed through the
UI — they require a raw API call. This closes that gap.

Attestor capability is out of scope: it has its own front-door (become-attestor)
and Attestor tab, and needs application + NDA + calibration trial — not a
one-click activate.

## Design

### Placement

A new **Capabilities** card rendered inside `OrganizationProfile`, below the
existing profile form. Owner/admin only; hidden entirely for non-admins and when
the org is suspended.

```
Organization Profile
[ logo / name / website / description form ]
────────────────────────────────────────────
Capabilities
  Contributor   [ Not active ]   (Activate)
  Operator      [ Active ]
```

### Component: `OrganizationCapabilities`

- Client component, new file `organization-capabilities.tsx`.
- Reads `orgId`, `role`, `capabilities`, `isSuspended` from `useOrganization()`.
- Returns `null` unless `role` is `owner` or `admin`.
- Returns `null` when the org is suspended (`isSuspended`) — no activation while suspended.
- Renders one row per capability in a fixed list: Contributor, Operator.

Each row shows a label, a short description of what the capability unlocks, a
status pill, and (when eligible) an Activate button.

### Status states

Derived from `capabilities[key]` (the value is a status string or `undefined`):

| Capability value | Pill        | Action           |
| ---------------- | ----------- | ---------------- |
| `undefined`      | Not active  | Activate button  |
| `active`         | Active      | none             |
| `suspended`      | Suspended   | none (platform admin only reverses) |

### Interaction

1. Click **Activate** on a row → opens `ConfirmDialog` (existing primitive,
   `components/ui/confirm-dialog.tsx`) scoped to that capability.
   - title: `Activate Operator capability?` (or Contributor)
   - description: `Every current and future member gains the Operator role. Only a platform admin can reverse this.`
   - confirmLabel: `Activate Operator`
2. Confirm → `busy` true → call the matching generated SDK function with
   `path: { org_id: orgId }` and `headers: getAccessTokenHeaders()`.
3. On `result.response.ok` → success toast (`Operator capability activated.`),
   close dialog, `router.refresh()` so the shell re-derives tabs and the card
   re-renders the new status.
4. On failure → surface `result.error?.detail?.error_code` in the dialog's
   `error` slot, else a generic message; leave the dialog open. `catch` →
   generic error, dialog open.

Only one dialog open at a time; track which capability is pending in local
state (`pending: "contributor" | "operator" | null`).

### Files

- **Create:** `frontend/src/components/modules/organizations/organization-capabilities.tsx`
- **Create:** `frontend/src/components/modules/organizations/organization-capabilities.test.tsx`
- **Modify:** `frontend/src/components/modules/organizations/organization-profile.tsx`
  — render `<OrganizationCapabilities />` after the profile form.
- **No backend change** — endpoints and SDK already exist.
- **No OpenAPI change** — contract already covers both endpoints.

### Mobile-first

Rows stack label/description above the status+action on narrow screens, align to
a row from `sm:` up. Activate button ≥ 44px touch target. Tested at 375px.
`ConfirmDialog` already renders as a bottom sheet on mobile.

## Testing (vitest + @testing-library/react)

`organization-capabilities.test.tsx`, wrapping the component in a mock
`OrganizationProvider` (or mocking `useOrganization`) and mocking the SDK module
+ `useToast` + `next/navigation`:

1. Undefined capability → row shows "Not active" and an Activate button.
2. `active` capability → shows "Active" pill, no Activate button.
3. `suspended` capability → shows "Suspended" pill, no Activate button.
4. Non-admin role → component renders nothing.
5. Suspended org → component renders nothing.
6. Click Activate → confirm dialog appears → confirm → the correct SDK function
   is called once with `{ path: { org_id } }`; success toast + `router.refresh`.
7. SDK returns non-ok → error surfaced in the dialog, dialog stays open.

## Out of scope

- Deactivation / suspension from the UI (platform-admin only, backend-gated).
- Attestor activation (separate front-door + application flow).
- Any change to the settlement gates OC-2 (legal profile / tax doc) — those flow
  through the existing Financials UI.
