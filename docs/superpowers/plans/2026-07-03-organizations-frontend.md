# Organizations Frontend (Org UI) Implementation Plan

> **For the implementer agent:** This plan defines WHAT to build — surfaces, flows,
> endpoints, states, and acceptance criteria. **You own the UI design.** Invoke the
> `frontend-design` skill before building anything visual; the Brand Book
> (`docs/auracles-brand-book.pdf`) is the visual source of truth. Do not wait for
> mockups from the architect — design, then build, task by task.

**Goal:** Full user-facing and admin UI for the Organizations Core backend (branch work merged to `main`), consuming the regenerated OpenAPI client.

**Backend state:** All `/v1/orgs/*`, `/v1/org-invitations/*`, `/v1/admin/orgs*` endpoints are live, contract (`contracts/openapi.yaml`) regenerated, frontend client (`frontend/src/lib/generated/`) regenerated. No backend work in this plan.

**Out of scope:** Attestation frontend (blocked on the Org-as-Attestor spec, sub-project 2). Capability management UI beyond read-only badges (capabilities are granted server-side; no grant endpoints exist). Org logo upload (no upload endpoint in the contract — display `logo_key` if present, otherwise fallback mark; flag to architect if contributors ask).

## Global Constraints

- **Generated client only.** All API calls via `frontend/src/lib/generated/` SDK. Never hardcode paths.
- **Mobile-first.** Base styles = mobile; enhance with `sm:`/`md:`/`lg:`. 44px min touch targets. Test every surface at 375px. Tables become card stacks on mobile. Modals full-screen on mobile.
- **Rendering:** Public org profile page = SSR (Server Component, SEO). Everything else = Client Components under the authed dashboard.
- **Auth:** Existing token pattern (access token in memory, refresh in HttpOnly cookie). Invitation accept/decline require an authenticated session; preview does not.
- **Components:** primitives in `components/ui/`, feature components in `components/modules/organizations/`. No file over ~200 lines — split.
- **Docs:** File-level and exported-component JSDoc per CLAUDE.md standards.
- **Tests:** Component tests (vitest + testing-library + msw) per surface; coverage ≥ 70% on new components. One Playwright E2E spec for the org lifecycle (Task 10).
- **Gates:** `tsc` + `eslint` clean before every commit. Known pre-existing typecheck errors live in `attestation-workspaces.tsx` (8) and `admin-config-panel.tsx` (1) — do not touch those files; zero NEW errors allowed.
- **Error surface:** API errors carry `detail` (string) or `detail.error_code` (e.g. `org_suspended`). Always render a human message, never raw JSON.
- **Commit after each task.** No `Co-Authored-By` trailer.

## Domain quick-reference

- Org roles: `owner` (exactly one), `admin`, `member`. Invitable roles: `admin | member` only.
- Capabilities: map of `attestor | contributor | operator` → `pending | active | suspended | revoked`. Read-only in this UI.
- Suspended org: mutating org endpoints return 403 with `error_code: "org_suspended"`.
- Key generated types: `OrganizationResponse`, `OrganizationCreateRequest` (`slug`, `name`, `country`, `website?`, `description?`), `OrganizationUpdateRequest`, `MyOrganizationsResponse` (each item: `org`, `role`, `capabilities`), `PublicOrganizationResponse` (adds `active_capabilities[]`, `member_count`), `OrgMemberResponse` (email is `null` for plain members — hide, don't render "null"), `OrgMemberRoleUpdateRequest`, `OrgOwnershipTransferRequest` (`new_owner_member_id`, `totp_code`), `OrgInvitationCreateRequest`, `OrgInvitationResponse`, `OrgInvitationPreviewResponse`, `OrgTeamResponse`, `AdminOrgsResponse` (paginated: `orgs`, `total`, `page`, `page_size`).

---

### Task 1 — My Organizations + Create Organization

**Route:** `/dashboard/organizations` (list) and a create flow (page or modal — your call).

- List the user's orgs via `GET /v1/orgs/mine`: org name, slug, the user's role, capability badges (status-aware: active vs pending vs suspended/revoked must read differently).
- Empty state invites creating an organization.
- Create via `POST /v1/orgs` with `slug`, `name`, `country` (ISO 3166-1 alpha-2 — use a select, not free text), optional `website`, `description`. Creator becomes owner.
- Slug: validate client-side (lowercase, hyphens, no spaces) and surface the 409 duplicate-slug conflict inline on the slug field.
- Success → navigate to the new org's management page (Task 2).
- Add "Organizations" to dashboard navigation (existing nav pattern).

**Tests:** list renders orgs + roles; empty state; create happy path (msw); 409 slug conflict shows field error; 422 validation rendering.

### Task 2 — Org management shell + Profile settings

**Route:** `/dashboard/organizations/[orgId]` with tabs/sections: Profile, Members, Invitations, Teams, Danger zone. Section visibility by the viewer's role (from `/v1/orgs/mine`): members see read-only Profile + Members; admins manage Profile/Invitations/Teams/Members (except role changes); owner sees everything incl. Danger zone.

- Profile: show org fields; admins+ edit `name`, `website`, `description` via `PATCH /v1/orgs/{org_id}`.
- 403 with `error_code: "org_suspended"` anywhere in this shell → persistent suspended banner + disable all mutating controls (Task 8 hardens this).

**Tests:** role-based section visibility (member vs admin vs owner); profile edit happy path; suspended 403 → banner.

### Task 3 — Members

- `GET /v1/orgs/{org_id}/members`: display name, role, joined date; email only when present (null for plain-member viewers).
- Owner: switch member ↔ admin via `PATCH /v1/orgs/{org_id}/members/{member_id}` (`role: admin|member`). Owner row not editable.
- Admin+: remove member via `DELETE /v1/orgs/{org_id}/members/{member_id}` with confirm step. Cannot remove owner; self-removal = leaving the org (confirm copy must say so; on success navigate away if you removed yourself).
- Surface backend 409s (e.g., last-owner protections) as inline errors.

**Tests:** list rendering incl. null email; role change owner-only; remove confirm flow; self-removal navigates away.

### Task 4 — Invitations (org side)

- Admin+: invite by email + role (`admin|member`) via `POST /v1/orgs/{org_id}/invitations`. 409 duplicate pending invite / already-member → inline error.
- Pending list via `GET /v1/orgs/{org_id}/invitations`: email, role, status, expires_at.
- Revoke via `DELETE /v1/orgs/{org_id}/invitations/{invitation_id}` with confirm.

**Tests:** invite happy path; duplicate 409; revoke; expired rows visually distinct from pending.

### Task 5 — Invitation accept flow (invitee side)

**Route:** `/org-invitations/[token]` — public route; recipient arrives from email.

- Preview via `GET /v1/org-invitations/{token}` (no auth): org name, role, expiry. Then Accept / Decline.
- Accept (`POST .../accept`) and Decline (`POST .../decline`) require auth: unauthenticated user → login/register redirect that returns to this page (existing `?next` pattern).
- State handling, each a distinct, clear screen (not a toast): unknown token → 404 not-found; already accepted/declined/revoked → 409 "no longer valid"; expired → 410 with guidance to request a new invite; wrong account email → 403 telling the user which account state is wrong (do NOT echo the invited email — backend detail is the copy source).
- Accept success → land in the org (Task 2 route) with a joined confirmation.

**Tests:** preview render; accept happy path; each of 404/409/410/403 renders its distinct state; unauthenticated redirect preserves return.

### Task 6 — Teams

- Admin+: list (`GET /v1/orgs/{org_id}/teams` — name + member_count), create (`POST`, name), rename (`PATCH /v1/orgs/{org_id}/teams/{team_id}`), delete (`DELETE`, confirm).
- Team membership: add/remove org members to a team via `PUT`/`DELETE /v1/orgs/{org_id}/teams/{team_id}/members/{member_id}`. Picker draws from the Task 3 members list.

**Tests:** CRUD happy paths; delete confirm; add/remove team member.

### Task 7 — Danger zone (owner only)

- **Transfer ownership:** pick a member (`new_owner_member_id`) + TOTP code → `POST /v1/orgs/{org_id}/transfer-ownership`. TOTP-gated: reuse the existing sensitive-action TOTP input pattern (payouts/settings). Invalid code error inline. Success → viewer is now admin; refresh role-gated UI.
- **Deactivate org:** `DELETE /v1/orgs/{org_id}` behind a typed-confirmation (org slug) dialog. Success → back to org list.

**Tests:** transfer requires TOTP; invalid TOTP inline error; role-gated UI updates after transfer; deactivate typed confirm + redirect.

### Task 8 — Suspended-org UX hardening

- Central handling: any `403` + `error_code: "org_suspended"` in the org shell → suspended banner, all mutating controls disabled, read surfaces still work.
- `/v1/orgs/mine` items for suspended orgs get a suspended badge in the Task 1 list.

**Tests:** suspended org list badge; banner + disabled controls on 403.

### Task 9 — Public org profile + Admin surface

- **Public page** `/orgs/[slug]` (SSR): `GET /v1/orgs/{slug}` → name, country, description, website, `active_capabilities` badges, `member_count`, created date. 404 page for unknown slug. No member identities (backend already strips PII — render only what the schema gives).
- **Admin** (existing admin area pattern): paginated org table via `GET /v1/admin/orgs` (`query`, `page`, `page_size`) — slug, name, country, member_count, capabilities, suspended/deactivated markers. Suspend action via `POST /v1/admin/orgs/{org_id}/suspend` (idempotent — safe to re-click) with confirm.

**Tests:** SSR page renders public fields; 404 slug; admin table pagination (trust `total` for pager even when page empty); suspend confirm + row updates.

### Task 10 — E2E lifecycle spec

`frontend/tests/e2e/organizations.spec.ts`: create org → edit profile → invite member (second user accepts via token page) → promote to admin → create team + add member → transfer ownership blocked without TOTP (assert the gate renders) → remove member → deactivate org. Follow existing e2e auth helpers.

---

## Acceptance (whole plan)

- All tasks' component tests green, coverage ≥ 70% on `components/modules/organizations/**`.
- `tsc` + `eslint`: zero new errors (baseline: 9 pre-existing in the two known drift files).
- Every surface verified at 375px.
- E2E spec passes locally.
