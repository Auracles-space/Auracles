# Organizations Core — Design

**Date:** 2026-07-03
**Status:** Approved for planning
**Owner:** William (architect) / agent (senior engineer)

## Context

Attestation is being redefined: attestations will be performed by **organizations** that
register as attestor orgs, with individual users as reviewing members. During brainstorming
the scope widened into a platform-wide Organizations subsystem: orgs can also publish
Frameworks and purchase licenses for their members (GitHub-style teams, AWS-style access
grants). The work is decomposed into four sub-projects, each with its own spec → plan →
implementation cycle:

1. **Org Core** (this spec) — org entity, membership, teams, invitations, capability skeleton.
2. **Org as Attestor** — attestor capability application (KYB, COI, confidentiality, payout,
   tax, trial), re-pointing of attestation assignment/settlement/badges/provenance/invoicing
   (modules 6a–6d) at orgs. Attestation frontend follows this sub-project.
3. **Org as Contributor** — contributor capability, org publishes Frameworks, members access
   org-published Frameworks, revenue to org payout.
4. **Org as Operator** — operator capability, org purchases licenses and grants access to
   chosen members or teams (AWS-style group access). Requires pricing decisions (seat vs
   flat) before design.

Build order: 1 → 2 → 3 → 4. The attestation flow frontend is deferred until sub-project 2
lands.

## Locked decisions (from brainstorm)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Attestor model | Org wrapper over individual reviewers: org owns identity, trust, vetting, money; members (users) do the review work. Reviewing member recorded for provenance/audit. |
| 2 | Vetting | Org-level application per capability. Members are vouched for by the org — no per-member vetting pipeline. Attestor-org members sign a personal NDA at invite-accept (sub-project 2). |
| 3 | Org types | No org types. One `organizations` entity + per-capability status (`attestor` / `contributor` / `operator`), Stripe-capabilities style. "Normal org" = base entity; "attesting org" = base entity + hard-earned active `attestor` capability. |
| 4 | Attestor capability gates (sub-project 2 preview) | KYB (legal identity + incorporation docs) → org credentials verified → org COI + confidentiality undertaking → payout account → tax document → trial attestation → admin activation. All gates required before approval. |
| 5 | Roles + teams | Fixed org roles `owner` / `admin` / `member`. GitHub-style teams as permissionless grouping primitive; consumers (sub-projects 3/4) attach meaning (access grants target member or team). |
| 6 | Org creation | Any registered user creates an org (becomes owner). Base org unverified and non-commercial. Users may belong to multiple orgs; personal roles unaffected. |
| 7 | Membership consent | Invitation flow with explicit accept/decline via email (Resend) + in-app. No silent adds. Admin adds/removes members. |
| 8 | Migration | Clean cutover — no real attestor data in production. Individual-attestor structures are redefined directly in sub-project 2; no dual-model period, no org-of-one auto-migration. |
| 9 | Individual `attestor` user role | Removed from self-registration/role-selection. Becomes derived: granted when a user joins an org with active `attestor` capability, revoked on leaving the last one. Existing `require_role("attestor")` guards keep working. |
| 10 | Architecture | New `app/modules/organizations/` module (standard router/service/models/schemas/dependencies layout). No auth-module extension, no party abstraction. |

## Scope

**In (Org Core, backend only):** org CRUD, membership + roles, invitations, teams,
capability status table + read path, org RBAC dependencies, derived-role sync utility,
audit, rate limiting, GDPR touchpoints, admin suspend.

**Out (later sub-projects):** capability applications and activation flows, KYB, NDA
signing, payout accounts, attestation re-pointing, framework access grants, purchasing,
all frontend (org UI ships bundled with sub-project 2 frontend).

## Data model

Six tables in `app/modules/organizations/models.py`, delivered as cohesive Alembic
migrations (org+members, invitations, teams+capabilities).

```
organizations
  id UUID PK
  slug           citext UNIQUE            -- public URL identity, /orgs/{slug}
  name           varchar(120)
  logo_key       varchar NULL             -- S3 key, avatars bucket pattern
  country        char(2)                  -- ISO 3166-1; drives payment routing later
  website        varchar NULL
  description    text NULL
  created_by     UUID FK users.id         -- creator; also seeded as owner member
  deactivated_at timestamptz NULL         -- soft delete
  created_at / updated_at

org_members
  id UUID PK
  org_id    UUID FK organizations.id ON DELETE CASCADE
  user_id   UUID FK users.id
  role      enum('owner','admin','member')
  joined_at timestamptz
  UNIQUE(org_id, user_id)
  -- exactly one owner per org: service-layer invariant + partial unique index
  --   CREATE UNIQUE INDEX uq_org_single_owner ON org_members(org_id) WHERE role='owner'

org_invitations
  id UUID PK
  org_id       UUID FK ON DELETE CASCADE
  email        citext
  role         enum('admin','member')     -- owner never invited, only transferred
  invited_by   UUID FK users.id
  status       enum('pending','accepted','declined','revoked','expired')
  token_hash   varchar                    -- 32-byte random token, emailed raw, stored hashed
  expires_at   timestamptz                -- 7 days from creation
  responded_at timestamptz NULL
  created_at
  UNIQUE(org_id, email) WHERE status='pending'

org_teams
  id UUID PK
  org_id UUID FK ON DELETE CASCADE
  name   varchar(80)
  created_at
  UNIQUE(org_id, name)

org_team_members
  team_id   UUID FK org_teams.id ON DELETE CASCADE
  member_id UUID FK org_members.id ON DELETE CASCADE
  PK(team_id, member_id)
  -- references membership, not user: org removal cascades out of all teams

org_capabilities
  id UUID PK
  org_id       UUID FK ON DELETE CASCADE
  capability   enum('attestor','contributor','operator')
  status       enum('pending','active','suspended','revoked')
  activated_at timestamptz NULL
  created_at / updated_at
  UNIQUE(org_id, capability)
  -- rows created by capability sub-projects; Org Core ships table + read path only
```

## API surface (`contracts/openapi.yaml` first, then implementation)

```
POST   /v1/orgs                                    create org (any authed user)
GET    /v1/orgs/mine                               my orgs (role + capability statuses)
GET    /v1/orgs/{slug}                             public profile (no member list, no PII)
PATCH  /v1/orgs/{org_id}                           update profile (admin+)
DELETE /v1/orgs/{org_id}                           deactivate (owner; blocked while any capability active)

GET    /v1/orgs/{org_id}/members                   list (member+; emails admin+ only)
PATCH  /v1/orgs/{org_id}/members/{member_id}       role change member<->admin (owner)
DELETE /v1/orgs/{org_id}/members/{member_id}       remove (admin+); self-removal = leave;
                                                   owner unremovable; admin cannot remove admin (owner can)
POST   /v1/orgs/{org_id}/transfer-ownership        owner -> member (owner, TOTP 2FA-gated)

POST   /v1/orgs/{org_id}/invitations               invite by email (admin+, rate-limited)
GET    /v1/orgs/{org_id}/invitations               list pending (admin+)
DELETE /v1/orgs/{org_id}/invitations/{invitation_id}  revoke (admin+)
GET    /v1/org-invitations/{token}                 preview (org name, role)
POST   /v1/org-invitations/{token}/accept          accept (authed; email must match)
POST   /v1/org-invitations/{token}/decline         decline

POST   /v1/orgs/{org_id}/teams                     create (admin+)
GET    /v1/orgs/{org_id}/teams                     list + member counts (member+)
PATCH  /v1/orgs/{org_id}/teams/{team_id}           rename (admin+)
DELETE /v1/orgs/{org_id}/teams/{team_id}           delete (admin+)
PUT    /v1/orgs/{org_id}/teams/{team_id}/members/{member_id}     add (admin+)
DELETE /v1/orgs/{org_id}/teams/{team_id}/members/{member_id}     remove (admin+)

GET    /v1/admin/orgs                              platform-admin list/search
POST   /v1/admin/orgs/{org_id}/suspend             platform-admin suspend
```

## RBAC + security

- `organizations/dependencies.py` exposes `require_org_role(role)` and
  `require_org_capability(capability)` as FastAPI dependencies layered after
  `get_current_user`. Role hierarchy: owner > admin > member. RBAC never inside services.
- Suspended org → 403 `org_suspended` on all org endpoints except read-own.
- Ownership transfer is TOTP 2FA-gated (payout accounts hang off orgs in later
  sub-projects; treat as sensitive from day one).
- Invitation tokens: 32-byte random, hashed at rest (refresh-token pattern); raw token
  only in the email link. Never logged.
- Invitation creation rate-limited per org per hour (Redis limiter, same layer as auth
  endpoints) — invite spam is an email-abuse vector.
- Member emails visible to admin+ only; public org profile exposes no member data.
- Audit log (existing `audit_log`): org created/deactivated, member invited / joined /
  removed / role-changed, ownership transferred, team created/deleted, capability status
  changes, admin suspend, all org RBAC denials (`access_denied`, target_type `org_rbac`).
- GDPR: user export includes org memberships; account deletion blocked while the user is
  sole owner of an org with any active capability (transfer or wind down first — mirrors
  existing deletion-blocked-by-obligations pattern).

## Invitation flow

1. Admin invites (email + role) → `org_invitations` row + Resend email
   (`org_invitation` template: org name, role, accept link carrying raw token).
2. Accept requires an authenticated user whose verified email equals the invite email
   (citext compare); mismatch → 403. Non-users register with that email first; the link
   survives until expiry.
3. Accept flips invitation status and creates the `org_members` row in one DB
   transaction. Decline / revoke / expired are terminal states.
4. Daily Celery Beat sweep marks expired invitations.
5. In-app notifications: invitee on invite; inviter on accept/decline.

## Derived attestor role sync

`organizations/service.py` exposes `sync_derived_roles(user_id)`:

- Grants the user-level `attestor` role when the user belongs to ≥1 org whose `attestor`
  capability is `active`; revokes it when that count reaches 0.
- Called on member add/remove and on capability status change.
- Inert in Org Core (no capability activation path exists yet) but implemented and tested
  now so sub-project 2 only wires the calls.
- `attestor` is removed from self-service role selection (registration + `POST
  /v1/auth/roles`) in sub-project 2, when the individual pipeline is retired.

## Error handling

Standard project rules apply: 401 unauthenticated, 403 wrong org role / suspended /
email mismatch, 404 unknown org/member/team/invitation, 409 duplicate pending invite /
duplicate team name / owner-removal attempts, 422 Pydantic validation, all writes in
transactions, idempotent accept (second accept of same token → 409, membership unchanged).

## Testing

- **Unit (service):** single-owner invariant, role hierarchy, invite email match, token
  expiry, idempotent accept, sole-owner deletion block, derived-role sync grant/revoke,
  team cascade on member removal, deactivation blocked by active capability.
- **Integration (endpoints):** every endpoint happy path + 401 + 403 (wrong org role);
  invite accept/decline/revoke/expired; suspended-org lockout; rate-limit hit → 429.
- Coverage ≥80% on the module (CI-enforced).
- Backend-only: no frontend/E2E in this sub-project; org UI ships with sub-project 2.
