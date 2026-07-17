# Team-Scoped Org Capability Rights — Design

**Date:** 2026-07-17
**Status:** Approved
**Module:** organizations (backend) + organizations frontend

## Problem

Org capabilities today are all-or-nothing. When an owner activates the
Contributor / Operator / Attestor capability, `sync_derived_roles` grants the
derived marketplace role to **every** org member. For a platform that moves
money, sells under an org's identity, and makes provenance claims, this
violates least-privilege: any member — a new hire in any team — can publish and
sell Frameworks as the org, or buy and post Projects as the org.

Teams already exist (`OrgTeam`, `OrgTeamMember`) but are inert groupings; they
gate nothing. This design makes team membership the unit that carries a
marketplace right, matching how GitHub/Slack/AWS and marketplace agencies
(Upwork) scope permissions: an org-level capability is an *eligibility gate*,
and the actual right is granted to specific teams.

## The Rule

A member holds a derived marketplace role (`contributor` / `operator` /
`attestor`) for an org **iff both** hold:

1. The org's capability is **active** — the existing eligibility gate
   (`OrgCapability.status == "active"`, org not suspended/deactivated). For
   Attestor this remains approval-gated by the org attestor application; for
   Contributor/Operator it is self-serve activation.
2. The member is **owner or admin** (implicit — governance role carries full
   rights), **OR** the member sits on ≥1 team in that org that has the
   capability enabled.

Multi-org: the derived user role is held if **any** of the user's memberships
qualifies.

This rule applies uniformly to all three capabilities.

## Decisions (locked in brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Owner/admin rights | Owner + admin hold every active capability implicitly; plain members are team-gated. |
| 2 | Team↔capability cardinality | A team holds a **set** of capabilities via link table `org_team_capabilities(team_id, capability)`. |
| 3 | Existing grants on migration | Backfill: create one "All members" team per org with active capabilities, add all current members, enable the active capabilities on it. Zero access loss. |
| 4 | Attestor | Team-scoped too — same rule as Contributor/Operator. |
| 5 | Activation model | Two-step: org capability activation stays as the eligibility gate; a new per-team capability toggle grants it to members. |
| 6 | Spec scope | Backend + team-assignment UI in one spec. |

## Data Model

New table **`org_team_capabilities`**:

| Column | Type | Notes |
|--------|------|-------|
| `team_id` | UUID | FK `org_teams.id` `ON DELETE CASCADE`, PK part 1 |
| `capability` | `org_capability_enum` | `contributor` / `operator` / `attestor`, PK part 2 |
| `created_at` | timestamptz | `CreatedAtMixin` |

Primary key `(team_id, capability)` — a capability is enabled on a team at most
once. Reuses the existing `org_capability_enum` PG type (`create_type=False`).

Model: `class OrgTeamCapability(CreatedAtMixin, Base)`.

## Sync Rewrite — `sync_derived_roles(db, *, user_id)`

Replace the current per-capability existence query. For each
`(capability, role)` in `_DERIVED_ROLE_MAP`, `should_have_role` is true when a
membership row exists for `user_id` in an org where:

- `Organization.suspended_at IS NULL AND Organization.deactivated_at IS NULL`, AND
- an `OrgCapability(org_id, capability, status="active")` row exists, AND
- **either** `OrgMember.role IN ('owner', 'admin')`
  **or** an `OrgTeamCapability` row exists for a team in that org where the
  capability is enabled and the user's `OrgMember` is an `OrgTeamMember` of
  that team.

Everything downstream (grant/revoke of `source="derived"` `UserRole`, audit
`org_derived_role_synced`, `SELECT ... FOR UPDATE` on the role row) stays as-is.

The query is a single `EXISTS`/join per capability; the owner-admin branch is an
`OR` against the team-capability branch.

## Re-Sync Triggers

Every mutation that can change the rule's inputs must recompute the affected
members' derived roles by calling `sync_derived_roles` for each:

| Mutation | Members to re-sync |
|----------|--------------------|
| Enable capability on team | all members of that team |
| Disable capability on team | all members of that team |
| Add member to team | that member |
| Remove member from team | that member |
| Delete team | members who were in it (capture roster **before** delete) |
| Governance role change member↔admin | that member |
| Org capability activate/deactivate | all org members (existing `_sync_org_member_roles`) |
| Add/remove org member | that member (existing) |

A small helper `_sync_team_member_roles(db, team_id)` mirrors the existing
`_sync_org_member_roles`: fetch the team's member user_ids, sync each.

## Endpoints (OrgAdmin-gated)

Added to the organizations router under the existing teams group:

- `PUT /v1/orgs/{org_id}/teams/{team_id}/capabilities/{capability}` — enable
  (idempotent; 200 whether newly enabled or already enabled).
- `DELETE /v1/orgs/{org_id}/teams/{team_id}/capabilities/{capability}` — disable
  (idempotent; 200/204).

`{capability}` is validated against the capability enum (422 on unknown value).

**Order guard:** enabling requires the org capability to already be active. If
not active, respond `422` with
`detail="Activate this capability for the organization first."` This enforces
the two-step model and keeps Attestor approval-gated (a team toggle can never
mint Attestor before the org passes its attestor application).

Team read responses (existing `list_teams` / `list_team_members`) surface each
team's enabled capabilities so the UI can render toggle state without an extra
round-trip.

All endpoints go through the existing `OrgAdmin` dependency (owner/admin). A
plain member → 403 (logged WARNING). Team not found in this org → 404.

## Migration / Backfill

Alembic migration `2026_07_17_add_org_team_capabilities.py`:

1. Create `org_team_capabilities`.
2. Data step: for every org that has ≥1 `OrgCapability` with `status="active"`:
   - Create a team named `"All members"` (skip if that name already exists in
     the org — reuse it).
   - Add every current `OrgMember` of the org as an `OrgTeamMember`.
   - Enable each currently-active capability on that team
     (`org_team_capabilities` rows).

After migration the rule yields the **same** members holding roles as before
(owner/admin implicit + everyone in "All members" with the active capabilities)
→ zero access loss. Owners narrow later by moving people out of "All members"
into scoped teams.

Downgrade drops the table. (The rewritten `sync_derived_roles` lives in code, so
a downgrade is a dev-only operation paired with reverting the code revision; the
migration's own `downgrade()` only drops the table and the backfilled team rows
are left as ordinary teams.)

`alembic upgrade head` and `alembic downgrade -1` must both succeed.

## Frontend

Extend the existing team surfaces — no new pages:

- **`organization-teams.tsx`** (and/or `team-member-manager.tsx`): per-team
  capability toggles for Contributor / Operator / Attestor. Owner/admin only.
- A toggle is **disabled with a hint** when the org capability is not active
  ("Activate this capability for the organization first").
- Enabling a capability opens the existing `ConfirmDialog` (it grants a right to
  a whole team) → on success toast → `refreshOrganization()` so pills/tabs
  update live (same pattern as `organization-capabilities.tsx`). Disabling can
  confirm too, since it revokes a right.
- **`organization-capabilities.tsx`** stays as the org eligibility gate; copy
  updated to explain that activating unlocks the capability for the org and
  members receive the right through teams.
- Mobile-first, 44px touch targets, tested at 375px.

Endpoints consumed via the generated hey-api SDK after `contracts/openapi.yaml`
is updated and the client regenerated.

## Security

- Enable/disable capability = owner/admin only (`OrgAdmin` dependency, never in
  service/model).
- Attestor stays approval-gated at the org level; the team toggle only assigns
  an already-eligible capability — a rogue admin cannot mint Attestor without
  the org passing its attestor application (order guard + org-cap-active
  requirement in the rule).
- Least-privilege realized: plain members no longer auto-hold sell/buy rights.
- Audit `org_team_capability_enabled` / `org_team_capability_disabled` with
  `team_id`, `capability`, actor.
- No secrets involved; standard Pydantic validation on the capability path
  param.

## Risk Flagged

Team-scoping Attestor means that after an org is attestor-approved, the owner
must also assign Attestor to a team for members to hold it (owner/admin still
implicit). This may touch reviewing-member workspace wiring that assumes
org-wide attestor. **Audit that wiring during planning** and confirm the
"All members" backfill covers currently-active attestor so existing
reviewing-members keep access.

## Testing

**Sync unit matrix** (`test_organizations_service` / capability sync tests):

- owner with org-cap active, no team → holds (implicit)
- admin, no team → holds (implicit)
- plain member on a team with capability enabled → holds
- plain member on no team → does **not** hold
- plain member removed from the enabled team → revoked
- capability disabled on the team → members revoked
- org capability inactive → nobody holds, **including owner**
- multi-org: user holds if any membership qualifies
- all three capabilities exercised (contributor, operator, attestor)

**Integration** (endpoint tests):

- enable/disable RBAC: member → 403, admin → 200
- enable when org capability inactive → 422
- enable, then a member on that team gains the derived role
- disable, then that member loses it
- unknown capability path value → 422
- team not in org → 404

**Migration test:**

- seed org + members + active capability → run migration → "All members" team
  exists with the capability enabled and all members in it; derived roles
  unchanged vs pre-migration.

**Frontend** (vitest + testing-library):

- toggle renders for owner, hidden for plain member
- toggle disabled with hint when org capability inactive
- enabling calls the enable endpoint then `refreshOrganization`
- disabling calls the disable endpoint

## Module → FR

Organizations subsystem (see `project_attestation_redefine`); extends the
capability-activation model. No new FR prefix; refines existing org capability
behavior.
