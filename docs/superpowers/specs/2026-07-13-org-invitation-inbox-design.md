# Org Invitation Inbox + Dead-Link Fix (Slice A) — Design

**Date:** 2026-07-13
**Status:** Approved (brainstorm)
**Slice:** A of 2 (this ships first; typeahead B+C is a separate spec: `2026-07-13-org-invitation-typeahead-design.md`)

## Problem

Org invitations today are token-only. `create_invitation` emails a token link; `accept_invitation` / `decline_invitation` require the raw token from the URL. Two gaps:

1. **No in-app invitee surface.** There is no endpoint that lists pending invitations addressed to the logged-in user's email. A brand-new invitee who loses the email has no way to find the invite. If they log in directly (not via the email link), they see nothing.
2. **Dead notification link.** For users who already had an account at invite time, `create_invitation` writes an `org_invitation_received` notification linking to `/settings/organizations` (`service.py:1007`). That route does not exist — the notification 404s.

## Goal

An in-app "Pending invitations" inbox at `/settings/organizations` where an invitee can see and Accept/Decline invitations without the email token, plus discoverability so a freshly-registered invitee notices the invite. Fixing the dead link falls out for free because the page now exists.

## Scope (YAGNI)

- Keep the existing token-link accept/decline path untouched.
- No invite-by-user-id here (that is Slice B).
- No changes to invite creation rules other than emitting the notification for not-yet-registered invitees.

## Backend

> **Route naming (supersedes the paths below):** the id-based endpoints live under a
> literal `/received` segment — `GET /org-invitations/received`,
> `POST /org-invitations/received/{invitation_id}/accept|decline` — and MUST be registered
> before the existing `/{token}` routes. Reason: `/org-invitations/{invitation_id}/...` is the
> same path shape as the existing `/org-invitations/{token}/...`, so they collide in Starlette;
> `GET /mine` would likewise bind as `token="mine"`. See the implementation plan.

### New endpoint: list my pending invitations

`GET /org-invitations/received` — authenticated; no token.

- Query `OrgInvitation` where `status == "pending"` and `func.lower(email) == user.email.lower()`, joined to the org (must be an active org).
- Response: list of `MyInvitationResponse`:
  - `id: UUID`
  - `org: { id, name, slug, logo_url }` (reuse the existing org logo_url computed field)
  - `role: str`
  - `invited_by_name: str | None` (display name of `invited_by` user)
  - `created_at: datetime`
- **Never** returns `token_hash` or any token.
- Empty list when none. Always 200 for an authenticated user.

### New endpoints: accept / decline by id

`POST /org-invitations/received/{invitation_id}/accept`
`POST /org-invitations/received/{invitation_id}/decline`

- Authenticated; email-match enforced exactly like the token path: load invitation by id, if `user.email.lower() != invitation.email` → `HTTPException(403)` "This invitation was sent to a different email address."
- 404 if invitation id unknown or its org is dead.
- 409 if invitation status is not `pending` (already accepted/declined/revoked) — never 500.
- On accept: create `OrgMember(org_id, user_id, role)`, set invitation `status="accepted"`, `responded_at`, write audit `org_member_joined`, notify inviter — identical effects to `accept_invitation`. Use `SELECT ... FOR UPDATE` on the invitation to prevent double-accept races, same as the token path.
- On decline: set `status="declined"`, `responded_at`, audit + notify inviter — identical to `decline_invitation`.

**Refactor:** extract the shared post-resolution logic from the existing token-based `accept_invitation` / `decline_invitation` so both the token path and the id path call one internal helper that takes the already-resolved `(invitation, organization, user)`. The token functions resolve via `_get_live_invitation(token=...)`; the id functions resolve via id + email-match. No duplicated transaction/lock/notify blocks.

### Notification for not-yet-registered invitees

`create_invitation` (`service.py:997-1010`) creates the `org_invitation_received` notification only when `invitee is not None`. A brand-new invitee has no `user_id` yet, so no notification row can be written at invite time (`create_notification` requires a `user_id`).

**Decision:** reconcile on registration. When a user registers, look up pending `OrgInvitation`s whose email matches the new account and create an `org_invitation_received` notification for each (deduped by the existing `dedupe_key` scheme `org-invitation-received:{invitation.id}`). This makes the in-app notification consistent for new and existing invitees. Existing-user behavior at invite time is unchanged. The badge + toast (below) is the primary discoverability driver; this reconciliation keeps the notifications list correct.

## Discoverability (badge + toast)

- On authenticated app load, the client calls `GET /org-invitations/mine`. If count > 0:
  - Show a count **badge** on the settings/account nav entry.
  - Show a **one-time toast** ("You have N pending invitation(s)" → links to `/settings/organizations`), deduped in `localStorage` keyed by the sorted set of invitation ids, so it reappears only when the set changes (new invite arrives), not on every login.
- No backend work beyond the `mine` endpoint.

## Frontend

New page `/settings/organizations` (client component; auth-gated like other settings pages). Two sections:

1. **My organizations** — from `listMyOrganizationsV1OrgsMineGet`. Each row: org name/logo, my role, link to the org dashboard.
2. **Pending invitations** — from `GET /org-invitations/mine`. Each row: org name/logo, role offered, invited-by name, "Accept" + "Decline" buttons. Accept/Decline call the by-id endpoints; on success the row is removed and (accept) redirect/link to the org. Mobile-first, 44px touch targets, tested at 375px, card-stack on mobile.

This page is the target of the previously-dead `/settings/organizations` notification link — no repointing needed.

## OpenAPI

Add the three endpoints (`mine`, accept-by-id, decline-by-id) and the `MyInvitationResponse` schema to `contracts/openapi.yaml`, then regenerate the frontend client. OpenAPI-first per project rules.

## Error handling

| Case | Handling |
|------|----------|
| Unauthenticated | 401 |
| Email mismatch on accept/decline-by-id | 403 + logged WARNING |
| Invitation id unknown / org dead | 404 |
| Invitation not pending (dup accept/decline) | 409 — never 500 |
| Concurrent accept race | `SELECT FOR UPDATE` → second caller gets 409 |

## Logging

`module="organizations"`, actions `invitation_accepted`, `invitation_declined` (INFO, with `user_id`, org id, invitation id); email-mismatch → WARNING `invitation_email_mismatch`.

## Tests (TDD RED→GREEN per behavior)

**Unit (service):**
- `list_my_invitations` returns only pending invites matching the caller's email; excludes other emails, non-pending, dead orgs; never leaks token.
- accept-by-id: happy path creates member + marks accepted; email mismatch → 403; non-pending → 409; unknown id → 404.
- decline-by-id: marks declined; same guards.
- Shared-helper refactor: token accept still behaves identically (regression).
- register reconciliation: registering with an email that has a pending invite creates the `org_invitation_received` notification (deduped); no pending invite → no notification.

**Integration (endpoints):**
- `GET /org-invitations/mine` → 200 list for authed user; 401 unauthenticated.
- accept/decline-by-id → 200 happy; 403 mismatch; 409 dup.

**Frontend (vitest + RTL):**
- Inbox renders pending rows from mocked `mine`.
- Accept removes the row / triggers success path.
- Empty state when no invites.
- Badge/toast: count>0 shows badge; toast deduped by localStorage key.

## Build order

Backend endpoints + OpenAPI → regenerate client → frontend page + badge/toast. Backend-before-frontend per project rules.
