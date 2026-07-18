# Org Contributor Framework Management UI — Design

**Date:** 2026-07-18
**Status:** Approved (design)
**Modules:** `frameworks` (frontend + backend), `organizations` (backend)

## Problem

Backend already exposes a near-complete set of org-owned Framework endpoints
(`/v1/orgs/{org_id}/frameworks/*`: create, list, get, update metadata, update
pricing, start version, submit, publish, unpublish, artifact upload-url +
confirm, connector import/sync, badges). No frontend surfaces them. A
Contributor working on behalf of an organization cannot create, edit, or
publish a Framework under the org identity through the UI — only under their
personal identity.

Additionally, the org-framework endpoints today gate authoring on
`require_org_capability("contributor")` (org capability active) +
`require_org_role("member")` (any member). This does **not** enforce the
team-scoped capability model (see `[[project_attestation_redefine]]` /
team-scoped capability rights, spec `2026-07-17-team-scoped-capability-rights`):
a plain member who is NOT on a contributor-capability team can still author org
Frameworks once the org capability is active. The team-scoped model must be
enforced here too.

## Goal

Give org members full-parity Framework management UI under the organization
identity, reached through the org dashboard, built by extracting the existing
personal Contributor Framework components into shared, seller-identity-
parameterized components (one code path for personal and org). Enforce the
team-scoped capability grant on org authoring endpoints.

## Locked decisions

| # | Decision | Choice |
|---|----------|--------|
| 1 | Scope | Full parity: create, edit metadata, artifact upload, versioning, submit, publish, unpublish, pricing. |
| 2 | Build strategy | Hybrid — extract personal components into shared, identity-parameterized components; render under both personal and org routes. No parallel duplicate section. |
| 3 | Parameterization | API adapter object (`FrameworkApi` interface + personal/org factories). Components consume the adapter, never import SDK fns directly. |
| 4 | Authoring authority | Enforce team-scoped capability grant: author/edit/submit/artifacts allowed for owner/admin OR a member on a contributor-capability team. Publish/unpublish/pricing/version remain owner/admin only. |
| 5 | Analytics | Org framework analytics (reviews) page is OUT of scope — follow-up. |
| 6 | Operator nav gap | Operator tab visibility for team-granted operators is a separate 15b nav gap — OUT of scope, noted only. |

## Global constraints

- Work on `main`, no branches. Commit messages end at the last meaningful line
  — no `Co-Authored-By` trailer.
- TDD RED→GREEN per behavior. No horizontal slicing.
- OpenAPI-first for any changed endpoint contract: update
  `contracts/openapi.yaml`, then regenerate the frontend client
  (`npm run generate:api`).
- Full-repo lint/type before claiming clean: backend
  `cd backend && uv run ruff check . && uv run mypy app`; frontend
  `npx tsc --noEmit` + `npx eslint`.
- Mobile-first, 44px touch targets, tested at 375px (per CLAUDE.md).
- Backend authoritative for all gating; UI gating is convenience only.

---

## Backend changes

### B1 — `require_org_capability_grant(capability)` dependency

New dependency in `backend/app/modules/organizations/dependencies.py`. Mirrors
`require_org_capability` but additionally enforces the caller's team-scoped
grant.

Behavior:
1. Load org context (org + membership + user) via the existing
   `_load_org_context` helper.
2. If org is suspended/deactivated or membership is None → 403 (same as
   `require_org_role`).
3. Check `OrgCapability` row for `(org_id, capability, status="active")`. If
   absent → 403 `{"error_code": "capability_required", "capability": ...}`.
4. If `membership.role in ("owner", "admin")` → pass.
5. Else check the team-grant EXISTS predicate (reuse the exact join used in
   `sync_derived_roles`, service.py:915): the member belongs to a team in this
   org that has the capability enabled. If present → pass.
6. Else → 403 `{"error_code": "capability_grant_required", "capability": ...}`,
   logged at WARNING with `user_id`, `org_id`, `capability`, `action`.

Returns `OrgContext` (so endpoints can read `context.user` / `context.org`),
matching `require_org_role`'s return so it can replace the member-context
dependency directly.

**Apply to** these org-framework endpoints in
`backend/app/modules/frameworks/router.py`, replacing `OrgMemberContext`:
- `create_org_framework`
- `update_org_framework` (metadata)
- `submit_org_framework`
- `list_org_frameworks`
- `get_org_framework`
- artifact upload-url endpoint (`create organization artifact upload URL`)
- confirm artifact endpoint (`confirm organization artifact upload`)

**Leave unchanged** (already `OrgAdminContext` = admin/owner):
- `update_org_framework_pricing`
- `unpublish_org_framework`
- `publish_org_framework`
- start-version endpoint

Rationale: authoring/reading the org's Framework drafts is a Contributor act
(grant-gated); publishing / pricing / go-live is a commercial-commitment act
(admin/owner). Reading (`list`/`get`) is grant-gated so a non-contributor plain
member does not enumerate org draft Frameworks.

### B2 — Caller-scoped grants on `MyOrganizationResponse`

Add a field to `MyOrganizationResponse`
(`backend/app/modules/organizations/schemas.py:165`):

```python
# True per capability when the CALLER personally holds that capability's grant
# (owner/admin, or a member of a team with the capability enabled) AND the org
# capability is active. Distinct from `capabilities`, which is the org-level
# status regardless of caller.
grants: dict[str, bool] = Field(default_factory=dict)
```

Populate in the my-organizations service path: for each capability the org has
active, set `grants[capability] = True` iff caller is owner/admin OR on a
capability-enabled team. Reuse the team-grant predicate. Keys mirror the
`ORG_CAPABILITY_ENUM` values that are active for the org; inactive capabilities
may be omitted or `False`.

This unblocks the shell showing the Frameworks tab to granted plain members
without an extra request.

### B3 — OpenAPI + client regen

Update `contracts/openapi.yaml`:
- `MyOrganizationResponse.grants` object.
- New `capability_grant_required` error is an existing-shape 403 (no schema
  change needed beyond documenting).

Regenerate the frontend client (`npm run generate:api`).

---

## Frontend changes

### F1 — `FrameworkApi` adapter

New file `frontend/src/lib/frameworks/framework-api.ts`.

```ts
/** Uniform Framework management surface, identity-agnostic. */
export interface FrameworkApi {
  list(): Promise<FrameworkListResponse>;
  get(id: string): Promise<FrameworkResponse>;
  create(body: FrameworkCreate): Promise<FrameworkResponse>;
  update(id: string, body: FrameworkUpdate): Promise<FrameworkResponse>;
  updatePricing(id: string, body: FrameworkPricingUpdate): Promise<FrameworkResponse>;
  startVersion(id: string, body: FrameworkVersionCreate): Promise<FrameworkResponse>;
  submit(id: string): Promise<FrameworkResponse>;
  publish(id: string): Promise<FrameworkResponse>;
  unpublish(id: string): Promise<FrameworkResponse>;
  listArtifacts(id: string): Promise<ArtifactListResponse>;
  createArtifactUpload(id: string, body: ArtifactUploadRequest): Promise<ArtifactUploadResponse>;
  confirmArtifact(id: string, artifactId: string, body: ArtifactConfirm): Promise<ArtifactResponse>;
}

export function personalFrameworkApi(): FrameworkApi { /* binds personal SDK fns */ }
export function orgFrameworkApi(orgId: string): FrameworkApi { /* binds org SDK fns, injects org_id path param */ }
```

(Exact SDK fn names and body/response types come from the generated client;
the plan pins them per method.) The two factories are the ONLY places that
reference concrete SDK fns.

### F2 — Component refactor (in place)

Refactor these to consume an injected `FrameworkApi` instead of importing SDK
fns directly:
- `framework-list.tsx`
- `create-framework-panel.tsx`
- `framework-editor.tsx`
- `framework-form.tsx` (if it issues calls)
- `artifact-uploader.tsx`
- `publish-button.tsx`
- `delist-button.tsx`, `relist-button.tsx`
- `version-radios.tsx`

The adapter arrives via a required prop (`api: FrameworkApi`) on each refactored
component — no context, no default. The route boundary constructs the adapter
and passes it down. Personal routes pass `personalFrameworkApi()`; behavior and
markup unchanged, so existing personal tests stay green.

Admin-gated controls (publish, pricing, start-version, unpublish/delist/relist)
accept a `canManageLiveState: boolean` prop. Personal → always `true`. Org →
`true` only when caller is org admin/owner. When `false`, the control is not
rendered.

### F3 — Org routes

New App Router pages under
`frontend/src/app/(auth)/dashboard/organizations/[orgId]/frameworks/`:
- `page.tsx` — list (renders `FrameworkList` with `orgFrameworkApi(orgId)`).
- `new/page.tsx` — create.
- `[id]/page.tsx` — editor.

Each resolves `orgId` from params, builds `orgFrameworkApi(orgId)`, resolves the
caller's admin status (from the org membership payload) for `canManageLiveState`.

### F4 — Nav

In `organization-shell.tsx`, add a Frameworks tab:

```ts
const contributorGrant = myOrg.grants?.["contributor"] === true;
if (contributorActive && (isAdmin || contributorGrant)) {
  tabs.push({ id: "frameworks", label: "Frameworks" });
}
```

Placed alongside the other capability tabs.

### F5 — Error / empty states

- 403 `capability_grant_required` on an org framework call → friendly empty
  state: "You need the Contributor right for this organization. Ask an admin to
  add you to a team with the Contributor capability." (Do not show a raw error.)
- Ungranted plain member never sees the tab, but the page still handles the 403
  defensively (deep link).
- Artifact pipeline / PII / soft-fail states reuse the existing
  `pipeline-status-panel`, `soft-fail-acknowledgement`, `pii-review-resolution`
  components unchanged.

---

## Data flow

```
Org member opens /dashboard/organizations/[orgId]/frameworks
  -> shell already showed tab because grants.contributor (or isAdmin)
  -> page builds orgFrameworkApi(orgId)
  -> FrameworkList calls api.list() -> GET /v1/orgs/{orgId}/frameworks
       backend: require_org_capability_grant("contributor") gates
  -> create: api.create(body) -> POST /v1/orgs/{orgId}/frameworks (grant-gated)
  -> editor: metadata/submit grant-gated; publish/pricing/version admin-gated
       (control hidden when canManageLiveState=false; backend also rejects)
```

## Testing

**Backend (pytest):**
- `require_org_capability_grant`: owner passes; admin passes; contributor-team
  member passes; plain member (no team) → 403 `capability_grant_required`;
  capability inactive → 403 `capability_required`; suspended org → 403.
- Integration: `create_org_framework` accepts a contributor-team member,
  rejects an ungranted plain member (403); `publish_org_framework` still
  rejects a non-admin.
- `MyOrganizationResponse.grants`: owner → contributor grant true;
  contributor-team member → true; plain member → false; capability inactive →
  false/absent.

**Frontend (vitest + testing-library):**
- Adapter factories: `orgFrameworkApi(orgId)` calls the org SDK fn with the
  correct `org_id` path param; `personalFrameworkApi` calls the personal fn.
- Component tests with a fake `FrameworkApi`: list renders rows; create submits
  via `api.create`; editor submit calls `api.submit`; admin controls hidden
  when `canManageLiveState=false`, shown when true.
- Shell: Frameworks tab shown when `contributorActive && grants.contributor`;
  hidden for ungranted plain member; shown for admin.
- Personal regression: existing framework component tests pass unchanged.

## Out of scope

- Org framework analytics (reviews) page.
- Operator tab visibility for team-granted operators (separate 15b nav gap).
- Connector import/sync UI for org artifacts (backend exists; personal UI may
  already cover via shared components — include only if it comes free with the
  extraction, otherwise defer).

## Discovered backend gaps (planning)

The spec assumed org backend parity was complete. Planning found two org
endpoints missing; both are added by the implementation plan:

- **Org list-artifacts** — no way to list an org-owned Framework's artifacts
  (the personal `GET /frameworks/{id}/artifacts` is `ContributorUser`-scoped).
  Plan adds `GET /orgs/{org_id}/frameworks/{id}/artifacts` (grant-gated) +
  `list_artifacts_for_owner`.
- **Org relist** — org has publish + unpublish but no relist; org `publish`
  requires `pipeline_passed` so it does not subsume relisting a delisted
  Framework. Plan adds `POST /orgs/{org_id}/frameworks/{id}/relist`
  (admin/owner, a commercial act) + `relist_framework_for_owner`.

**Pricing** is not a gap: personal edits pricing inside `updateFramework`
(combined form); org has a separate admin-only pricing endpoint. Resolved in the
adapter — personal `updatePricing` → `updateFramework({pricing})` (personal form
unchanged); org `updatePricing` → the org pricing endpoint via a separate
admin-only control, and the shared metadata form renders pricing inline only for
personal.

## Risks

- **Refactor regression** on personal Framework flows during the extraction.
  Mitigation: personal tests are the safety net; the adapter swap must not
  change markup or behavior. Extract one component at a time, tests green each
  step.
- **Authority correctness**: the grant dependency governs who can author under
  the org identity. Unit-test every branch; backend is authoritative.
