# Org Invite Typeahead + Enumeration Guard (Slice B+C) — Design

**Date:** 2026-07-13
**Status:** Approved (brainstorm)
**Slice:** B+C of 2 (ships after Slice A: `2026-07-13-org-invitation-inbox-design.md`)

## Problem

The org invite form is a plain email input. An admin inviting an existing colleague must know and type their exact address. We want typeahead: as the admin types, suggest matching existing accounts to pick from.

The naive version — an endpoint returning users matching an email prefix — is a **user-enumeration surface**: any org admin could sweep the alphabet and harvest every account email on the platform. The design must make typeahead useful while making harvest slow, logged, and — critically — yield unusable data.

## Goal

Typeahead that helps an admin recognize and pick an existing colleague, built so it cannot be turned into an email-harvesting tool. The manual "type any email" path stays for inviting outsiders.

## Security model (the core of this slice)

Enumeration is bounded by construction:

- **Admin-only.** Search requires org owner/admin (invite permission), enforced by RBAC dependency — same gate as `create_invitation`.
- **Min 3 chars.** `q` shorter than 3 → empty result (no single-letter sweeps).
- **Capped.** At most 10 results per query.
- **Rate-limited.** Per-user Redis rate limit on the search endpoint.
- **Audited.** Each search writes an audit entry (`org_member_searched`, INFO, with caller id, org id, query length — not the raw query).
- **Masked emails.** Results carry `masked_email` (`jo•••@x.com`), never the full address.
- **Invite by id.** Picking a suggestion sends the invite by `user_id`; the server resolves the email internally. The admin never sees full emails they didn't already know — so even harvested results are not usable addresses.
- **Exclusions.** Results exclude users already members of this org or with a pending invite to it (also avoids leaking membership as a side channel beyond what the admin already sees on the members tab).

## Backend

### New endpoint: member search (typeahead)

`GET /orgs/{org_id}/member-search?q=<str>` — org owner/admin only.

- If `len(q.strip()) < 3` → 200 with empty list (not an error).
- Prefix match: `email ILIKE q || '%'` OR `display_name ILIKE q || '%'`.
- Exclude users who are already `OrgMember` of `org_id` or have a `pending` `OrgInvitation` for `org_id`.
- Order by display_name; cap 10.
- Rate-limited (Redis, per caller). Over limit → 429.
- Audit `org_member_searched`.
- Response: list of `MemberSearchResult`:
  - `user_id: UUID`
  - `display_name: str`
  - `avatar_url: str | None`
  - `masked_email: str` (local part: first char + `•••`, keep domain — `jo•••@example.com`; single-char local → `•••@domain`)
- **Never** returns full email.

### Invite by user_id

Extend `POST /orgs/{org_id}/invitations`. Request accepts **either**:
- `email: str` (existing path — invite an outsider by address), **or**
- `user_id: UUID` (new — invite a suggested existing user).

Exactly one of the two is required (Pydantic validation; 422 if both/neither). When `user_id` is given:
- Resolve the user server-side; use their email internally for the invitation row (so the token/accept machinery is unchanged).
- 404 if `user_id` does not exist.
- Same 409 on duplicate pending invite; same rate limit on invite creation.
- The invite-creation **response** for the `user_id` path returns `masked_email`, not the full address (so the immediate select→invite action never reveals it).

**On the pending-invitations list (`OrgInvitationResponse`):** leave it unchanged — it keeps showing full `email` as today. Rationale and residual risk: masking only the search endpoint is enough to defeat silent harvest. Creating an invitation is a *loud, consented* action — it emails the invitee and writes a notification — and is rate-limited + audited. An attacker cannot quietly turn invite-by-id into a scraper: every resolved email costs one invite that alerts the victim. So we accept that an admin who deliberately invites a masked colleague will subsequently see that address in their own org's pending list. No migration, no `OrgInvitationResponse` change, existing admin UI (which shows `invitation.email`) is preserved. The privacy guarantee that matters — *typeahead search alone cannot harvest addresses* — holds.

## Frontend

Invite form email field becomes a typeahead (`components/modules/organizations`):

- Type ≥ 3 chars → debounced (~250ms) call to member-search.
- Dropdown: each row = avatar + display name + masked email. Keyboard navigable (arrow/enter/esc), 44px touch targets, 375px.
- Select a suggestion → invite sent with `{ user_id }`.
- Type a full new email + submit (no suggestion selected) → invite sent with `{ email }` (outsider path).
- Loading + empty ("No matching members") + error states.

## OpenAPI

Add `GET /orgs/{org_id}/member-search` + `MemberSearchResult`, and the `user_id` variant on the invite-create request (+ `masked_email` on the invite-create response only), to `contracts/openapi.yaml`; regenerate the client. OpenAPI-first.

## Error handling

| Case | Handling |
|------|----------|
| Non-admin caller | 403 + WARNING |
| `q` < 3 chars | 200 empty (not an error) |
| Rate limit exceeded | 429 |
| Invite: both/neither of email+user_id | 422 |
| Invite: unknown user_id | 404 |
| Invite: duplicate pending | 409 |

## Logging

`module="organizations"`: `org_member_searched` (INFO, caller id, org id, query length only — never raw query or emails), `org_member_invited` (existing). Never log emails or the query string.

## Tests (TDD RED→GREEN per behavior)

**Unit (service):**
- search: `q` < 3 → empty; prefix match on email and on display_name; cap at 10; excludes existing members; excludes already-invited; masking format (multi-char + single-char local part); RBAC 403 for non-admin.
- invite-by-user_id: resolves email and creates invitation; unknown user_id → 404; both email+user_id → 422; neither → 422; duplicate pending → 409.
- invite-by-user_id create response returns `masked_email`, not the full address.

**Integration (endpoints):**
- member-search: admin 200; member/non-member 403; over-rate-limit 429.
- invite: user_id happy path; 422 validation; 409 dup.

**Frontend (vitest + RTL):**
- typeahead: ≥3 chars triggers search, shows masked suggestions; select → invite called with user_id; manual full email → invite called with email; empty + error states.

## Build order

Backend member-search + invite-by-user_id + OpenAPI → regenerate client → frontend typeahead. Backend-before-frontend.
