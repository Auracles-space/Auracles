# Org Invite Typeahead + Enumeration Guard (Slice B+C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an org admin type into the invite form and pick from suggested existing users, built so the search cannot be turned into an email-harvest tool.

**Architecture:** A new admin-only, rate-limited, audited `GET /orgs/{org_id}/member-search` returns capped, masked-email suggestions (prefix match on email/display_name, excluding current members and already-invited users). The invite endpoint gains a `user_id` path so picking a suggestion invites by id — the server resolves the email and the admin never sees the full address. The manual "type any email" path is untouched.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, pytest / httpx AsyncClient; Next.js 15, Tailwind, vitest + React Testing Library, hey-api generated client.

## Global Constraints

- Backend-before-frontend; OpenAPI-first: update `contracts/openapi.yaml` (regen command in Task 1 Step 7), then `cd frontend && npm run generate:api`.
- TDD RED→GREEN per behavior. One test → one implementation → repeat.
- No `Co-Authored-By` trailer. Work on `main` (do not branch unless the human says so). NOTE: Slice A ships on branch `org-invitation-inbox`; this slice assumes Slice A is merged (it reuses `OrgInvitationCreateRequest`, the invite route, and the inbox). Confirm Slice A is merged before starting.
- Security (non-negotiable, this is the whole point of the slice): search is **admin-only** (RBAC dependency `OrgAdmin`), **min 3 chars**, **cap 10**, **rate-limited**, **audited**, returns **masked emails only**, and picking a suggestion invites **by user_id** (email resolved server-side). Never log emails or the raw query string — log query *length* only.
- Loguru only. Pydantic on every input. Response models explicit. Every write in a transaction.
- Mobile-first, 44px touch targets, verified at 375px.
- Test DB `auracles_test`. Backend: `cd backend && uv run pytest <path> -v`; lint `uv run ruff check . && uv run mypy app`. Frontend: `npx tsc --noEmit && npx eslint <files> && npx vitest run <path>`.

---

### Task 1: Backend — admin-only member-search endpoint

**Files:**
- Modify: `backend/app/modules/organizations/schemas.py` (add `MemberSearchResult`, `MemberSearchResponse`)
- Modify: `backend/app/modules/organizations/service.py` (add `_mask_email`, `search_members`, a new `MEMBER_SEARCH_RATE_LIMITER`)
- Modify: `backend/app/modules/organizations/router.py` (add `GET /{org_id}/member-search`)
- Modify: `contracts/openapi.yaml` (regenerate)
- Test: `backend/tests/integration/test_org_member_search.py` (new)

**Interfaces:**
- Produces:
  - `MemberSearchResult{ user_id: UUID, display_name: str, avatar_url: str | None, masked_email: str }`
  - `MemberSearchResponse{ results: list[MemberSearchResult] }`
  - `service.search_members(db, redis, *, context: OrgContext, q: str) -> MemberSearchResponse`
  - `service._mask_email(email: str) -> str`
  - Route `GET /v1/orgs/{org_id}/member-search?q=<str>` → `MemberSearchResponse`, operationId `search_org_members`, dependency `OrgAdmin`.

- [ ] **Step 1: Write the failing tests**

Inspect `backend/tests/integration/test_organizations_endpoints.py` for the admin-authed client fixtures and factories. Create `backend/tests/integration/test_org_member_search.py`:

```python
"""Integration tests for admin-only invite member-search (Slice B+C).

Covers the enumeration guard: min length, masking, exclusions, RBAC.
"""
import pytest


@pytest.mark.asyncio
async def test_search_returns_masked_matches_for_admin(admin_client, org, seed_users):
    """>=3 char prefix returns matching users with masked emails, capped."""
    client, _ = admin_client
    # seed_users created e.g. "joanna@example.com" (display "Joanna Reed")
    resp = await client.get(f"/v1/orgs/{org.id}/member-search", params={"q": "joa"})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) >= 1
    hit = results[0]
    assert hit["masked_email"] == "j•••@example.com"
    assert "email" not in hit  # full address never returned
    assert set(hit.keys()) == {"user_id", "display_name", "avatar_url", "masked_email"}


@pytest.mark.asyncio
async def test_search_under_three_chars_is_empty(admin_client, org):
    """A query shorter than 3 chars returns an empty list, not an error."""
    client, _ = admin_client
    resp = await client.get(f"/v1/orgs/{org.id}/member-search", params={"q": "jo"})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


@pytest.mark.asyncio
async def test_search_excludes_members_and_invited(admin_client, org, seed_users):
    """Existing members and already-invited users are excluded from results."""
    client, admin = admin_client
    # seed_users includes one user already a member and one already invited to `org`.
    resp = await client.get(f"/v1/orgs/{org.id}/member-search", params={"q": "exc"})
    emails = [r["masked_email"] for r in resp.json()["results"]]
    assert "e•••@member.com" not in emails
    assert "e•••@invited.com" not in emails


@pytest.mark.asyncio
async def test_search_requires_admin(member_client, org):
    """A plain member (non-admin) cannot search: 403."""
    client, _ = member_client
    resp = await client.get(f"/v1/orgs/{org.id}/member-search", params={"q": "joa"})
    assert resp.status_code == 403
```

Build fixtures (`seed_users`, `admin_client`, `member_client`, `org`) reusing existing org/user factories. `seed_users` inserts: a matchable user `joanna@example.com`/"Joanna Reed"; a user already a member of `org` with email `exc...@member.com`; a user with a pending `OrgInvitation` to `org` at `exc...@invited.com`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/integration/test_org_member_search.py -v`
Expected: FAIL — 404 (route missing).

- [ ] **Step 3: Add the schemas**

In `schemas.py`, after `OrgInvitationsResponse` (~line 392):

```python
class MemberSearchResult(BaseModel):
    """One invite typeahead suggestion. Email is always masked."""

    user_id: UUID
    display_name: str
    avatar_url: str | None
    masked_email: str


class MemberSearchResponse(BaseModel):
    """Capped list of invite typeahead suggestions."""

    results: list[MemberSearchResult]
```

- [ ] **Step 4: Add the mask helper + rate limiter + service**

In `service.py`. Near the existing `INVITE_RATE_LIMITER` (line 68) add:

```python
# Per-caller limiter for the invite typeahead: bounds enumeration sweeps.
MEMBER_SEARCH_RATE_LIMITER = RateLimiter(
    namespace="org_member_search", limit=30, window=60
)
```

Confirm `or_`, `exists`, `cast` are importable (`from sqlalchemy import or_, exists` at top — add if missing; `cast` from `typing` is already used). Add `MemberSearchResult`, `MemberSearchResponse` to the schema import block. Then:

```python
def _mask_email(email: str) -> str:
    """Mask an email for display: keep the first local char and the domain.

    ``joanna@example.com`` -> ``j•••@example.com``; a single-char local part
    yields ``•••@example.com``. Never exposes the full address.
    """
    local, _, domain = email.partition("@")
    prefix = local[:1] if len(local) > 1 else ""
    return f"{prefix}•••@{domain}"


async def search_members(
    db: AsyncSession,
    redis: Redis,
    *,
    context: OrgContext,
    q: str,
) -> MemberSearchResponse:
    """Admin-only invite typeahead over existing users.

    Prefix-matches email or display name (case-insensitive), excludes users
    already in the org or already invited, caps at 10, and returns masked
    emails. Rate-limited and audited to bound enumeration.

    Args:
        db: Async database session.
        redis: Redis client for the per-caller rate limiter.
        context: Resolved org/admin context (RBAC-gated at the router).
        q: Raw query string from the caller.

    Returns:
        Up to 10 masked suggestions; empty when q has fewer than 3 chars.

    Raises:
        HTTPException(429): The caller exceeded the search rate window.
    """
    org_id = context.org.id
    actor_id = context.user.id
    await MEMBER_SEARCH_RATE_LIMITER.check(cast(RedisCounter, redis), str(actor_id))

    cleaned = q.strip()
    if len(cleaned) < 3:
        return MemberSearchResponse(results=[])

    # Escape LIKE wildcards in user input, then prefix-match.
    escaped = cleaned.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"{escaped}%"

    member_subq = select(OrgMember.user_id).where(OrgMember.org_id == org_id)
    invited_exists = (
        select(OrgInvitation.id)
        .where(
            OrgInvitation.org_id == org_id,
            OrgInvitation.status == "pending",
            func.lower(OrgInvitation.email) == func.lower(User.email),
        )
        .exists()
    )
    rows = (
        await db.execute(
            select(User.id, User.display_name, User.avatar_url, User.email)
            .where(
                or_(
                    func.lower(User.email).like(pattern, escape="\\"),
                    func.lower(User.display_name).like(pattern, escape="\\"),
                ),
                User.id.notin_(member_subq),
                ~invited_exists,
            )
            .order_by(User.display_name)
            .limit(10)
        )
    ).all()

    await write_audit(
        db=db,
        actor_id=actor_id,
        action="org_member_searched",
        target_type="organization",
        target_id=org_id,
        metadata={"query_length": len(cleaned)},
    )

    return MemberSearchResponse(
        results=[
            MemberSearchResult(
                user_id=user_id,
                display_name=display_name,
                avatar_url=avatar_url,
                masked_email=_mask_email(email),
            )
            for user_id, display_name, avatar_url, email in rows
        ]
    )
```

Note: `write_audit` here runs outside an explicit `db.begin()`; follow the pattern used by other read-with-audit paths in this module (if `write_audit` requires an open transaction, wrap the audit in `async with db.begin():` after building `rows`). Verify against an existing audited read in `service.py` and match it.

- [ ] **Step 5: Add the route**

In `router.py`, near the other `/{org_id}/...` admin routes (e.g. after the invitations block ~line 712). Import `MemberSearchResponse` in the schema import block.

```python
@router.get(
    "/{org_id}/member-search",
    response_model=MemberSearchResponse,
    operation_id="search_org_members",
    summary="Search existing users to invite",
    description=(
        "Admin-only invite typeahead. Prefix-matches existing users by email "
        "or name (min 3 chars, capped, rate-limited); returns masked emails "
        "only. Pick a result and invite by user id."
    ),
)
async def search_org_members(
    org_id: UUID,
    q: str,
    context: OrgAdmin,
    db: DatabaseSession,
    redis: RedisClient,
) -> MemberSearchResponse:
    """Return masked invite suggestions for an org admin."""
    del org_id
    return await service.search_members(db=db, redis=redis, context=context, q=q)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/integration/test_org_member_search.py -v`
Expected: all PASS.

- [ ] **Step 7: Regenerate OpenAPI**

```bash
cd backend && uv run python -c "
import yaml
from app.main import app
with open('../contracts/openapi.yaml', 'w') as f:
    yaml.safe_dump(app.openapi(), f, sort_keys=False, allow_unicode=True)
"
```
Verify `git -C .. diff --stat contracts/openapi.yaml` adds only the `member-search` path + the two schemas.

- [ ] **Step 8: Commit**

```bash
cd /Users/a0000/projects/auracles
git add backend/app/modules/organizations/schemas.py backend/app/modules/organizations/service.py backend/app/modules/organizations/router.py backend/tests/integration/test_org_member_search.py contracts/openapi.yaml
git commit -m "Add admin-only invite member-search with enumeration guard"
```

---

### Task 2: Backend — invite by user_id (email resolved server-side)

**Files:**
- Modify: `backend/app/modules/organizations/schemas.py` (`OrgInvitationCreateRequest`: email optional + `user_id` + exactly-one validator)
- Modify: `backend/app/modules/organizations/service.py` (`create_invitation`: resolve `user_id` → email; mask the returned email on the user_id path)
- Modify: `contracts/openapi.yaml` (regenerate)
- Test: `backend/tests/integration/test_org_member_search.py` (extend) or a new `test_org_invite_by_id.py`

**Interfaces:**
- Consumes: `_mask_email` (Task 1), existing `create_invitation` body.
- Produces: `OrgInvitationCreateRequest{ email: EmailStr | None, user_id: UUID | None, role: Literal["admin","member"] }` with an exactly-one-of validator; `create_invitation` accepts either.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_invite_by_user_id_masks_email(admin_client, org, seed_users):
    """Inviting by user_id creates the invite and returns a masked email."""
    client, _ = admin_client
    hit = (await client.get(f"/v1/orgs/{org.id}/member-search", params={"q": "joa"})).json()["results"][0]
    resp = await client.post(
        f"/v1/orgs/{org.id}/invitations",
        json={"user_id": hit["user_id"], "role": "member"},
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "j•••@example.com"


@pytest.mark.asyncio
async def test_invite_requires_exactly_one_target(admin_client, org, seed_users):
    """Both email and user_id, or neither, is a 422."""
    client, _ = admin_client
    both = await client.post(f"/v1/orgs/{org.id}/invitations", json={"email": "a@b.com", "user_id": "00000000-0000-0000-0000-000000000000", "role": "member"})
    assert both.status_code == 422
    neither = await client.post(f"/v1/orgs/{org.id}/invitations", json={"role": "member"})
    assert neither.status_code == 422


@pytest.mark.asyncio
async def test_invite_unknown_user_id_is_404(admin_client, org):
    """Inviting a non-existent user_id returns 404."""
    client, _ = admin_client
    resp = await client.post(f"/v1/orgs/{org.id}/invitations", json={"user_id": "00000000-0000-0000-0000-000000000000", "role": "member"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_invite_by_email_still_returns_full_email(admin_client, org):
    """The manual email path is unchanged: full email echoed back."""
    client, _ = admin_client
    resp = await client.post(f"/v1/orgs/{org.id}/invitations", json={"email": "outsider@example.com", "role": "member"})
    assert resp.status_code == 201
    assert resp.json()["email"] == "outsider@example.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/integration/test_org_member_search.py -k "invite" -v`
Expected: FAIL (422 not raised / user_id unsupported).

- [ ] **Step 3: Update the request schema**

In `schemas.py`, replace `OrgInvitationCreateRequest`:

```python
class OrgInvitationCreateRequest(BaseModel):
    """Admin request to invite either an email address or an existing user."""

    email: EmailStr | None = None
    user_id: UUID | None = None
    role: Literal["admin", "member"]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr | None) -> str | None:
        """Lowercase invitation emails for unique matching."""
        return str(value).strip().lower() if value is not None else None

    @model_validator(mode="after")
    def exactly_one_target(self) -> "OrgInvitationCreateRequest":
        """Require exactly one of email or user_id."""
        if (self.email is None) == (self.user_id is None):
            raise ValueError("Provide exactly one of email or user_id.")
        return self
```

Ensure `model_validator` is imported from `pydantic` at the top of `schemas.py`.

- [ ] **Step 4: Update `create_invitation`**

In `service.py`, at the start of `create_invitation` (after extracting `org_id`/`actor_id`), resolve the target email. Replace the current `email = payload.email` usage:

```python
    invited_via_user_id = payload.user_id is not None
    if invited_via_user_id:
        target_user = await db.scalar(select(User).where(User.id == payload.user_id))
        if target_user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        email = target_user.email.lower()
    else:
        # payload.email is guaranteed non-None by the schema validator.
        email = payload.email  # type: ignore[assignment]
```

Then, at the return (`response = OrgInvitationResponse.model_validate(invitation)` ~line 1011), mask the echoed email when invited by id:

```python
            response = OrgInvitationResponse.model_validate(invitation)
            if invited_via_user_id:
                response.email = _mask_email(email)
```

The rest (rate limit, member-exists check, invitation insert, audit, notification, email send) is unchanged — it already keys on the resolved `email`. The `send_org_invitation.delay(email, ...)` still sends to the real address (server-side; never returned to the caller).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/integration/test_org_member_search.py -v`
Expected: all PASS.

Regression — the existing invite tests (email path) still pass:
Run: `cd backend && uv run pytest tests/ -k "invitation" -v`
Expected: PASS.

- [ ] **Step 6: Regenerate OpenAPI**

Same command as Task 1 Step 7. Verify the diff updates only `OrgInvitationCreateRequest` (email now nullable + `user_id` added).

- [ ] **Step 7: Commit**

```bash
cd /Users/a0000/projects/auracles
git add backend/app/modules/organizations/schemas.py backend/app/modules/organizations/service.py backend/tests/integration/test_org_member_search.py contracts/openapi.yaml
git commit -m "Support inviting an existing user by id with masked echo"
```

---

### Task 3: Frontend — invite typeahead

**Files:**
- Regenerate: `frontend/src/lib/generated/*` (`npm run generate:api`)
- Create: `frontend/src/components/modules/organizations/invite-member-typeahead.tsx`
- Modify: `frontend/src/components/modules/organizations/organization-invitations.tsx` (use the typeahead in the invite form; submit by `user_id` or `email`)
- Test: `frontend/tests/unit/components/organizations/invite-member-typeahead.test.tsx` (new)

**Interfaces:**
- Consumes generated fns (confirm exact names post-regen in `sdk.gen.ts`): `searchOrgMembers` (operationId `search_org_members`), and the existing invite-create fn (`createInvitationV1OrgsOrgIdInvitationsPost`) whose request now accepts `user_id`.
- Produces: `InviteMemberTypeahead({ orgId, disabled, onSelect, onEmailChange, value })` — a combobox that emits either a selected `user_id` (via `onSelect`) or the raw typed email (via `onEmailChange`).

- [ ] **Step 1: Regenerate the client**

Run: `cd frontend && npm run generate:api`
Confirm: `grep -oE "export const searchOrgMembers[A-Za-z0-9]*" src/lib/generated/sdk.gen.ts` and that `OrgInvitationCreateRequest` in `types.gen.ts` now has optional `email` + `user_id`.

- [ ] **Step 2: Write the failing test**

Model the mocks on `organization-logo-uploader.test.tsx`. Create `frontend/tests/unit/components/organizations/invite-member-typeahead.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InviteMemberTypeahead } from "@/components/modules/organizations/invite-member-typeahead";
import { searchOrgMembers } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ searchOrgMembers: vi.fn() }));

const ok = <T,>(data: T) => ({ data, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("InviteMemberTypeahead", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows masked suggestions after 3 chars and emits user_id on select", async () => {
    vi.mocked(searchOrgMembers).mockResolvedValue(
      ok({ results: [{ user_id: "u1", display_name: "Joanna Reed", avatar_url: null, masked_email: "j•••@example.com" }] }) as never,
    );
    const onSelect = vi.fn();
    const onEmailChange = vi.fn();
    render(<InviteMemberTypeahead orgId="o1" value="" onSelect={onSelect} onEmailChange={onEmailChange} />);

    fireEvent.change(screen.getByLabelText(/invite by email/i), { target: { value: "joa" } });

    await waitFor(() => expect(screen.getByText("Joanna Reed")).toBeInTheDocument());
    expect(screen.getByText("j•••@example.com")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Joanna Reed"));
    expect(onSelect).toHaveBeenCalledWith("u1");
  });

  it("does not search below 3 chars", async () => {
    render(<InviteMemberTypeahead orgId="o1" value="" onSelect={vi.fn()} onEmailChange={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/invite by email/i), { target: { value: "jo" } });
    await new Promise((r) => setTimeout(r, 300));
    expect(searchOrgMembers).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run tests/unit/components/organizations/invite-member-typeahead.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement the typeahead**

Create `invite-member-typeahead.tsx` (client component). A labeled text input ("Invite by email"): on change, call `onEmailChange(value)` (so the parent keeps the raw email for the manual path) and, when `value.trim().length >= 3`, debounce ~250ms then call `searchOrgMembers({ path: { org_id: orgId }, query: { q: value }, headers: getAccessTokenHeaders() })` after `configureBrowserClient()`. Render a dropdown of results (avatar or initial + `display_name` + `masked_email`), keyboard-navigable (Arrow/Enter/Escape), 44px rows, closes on select/blur/escape. On select: call `onSelect(user_id)` and set the input to the display name (visual only). Loading + "No matching members" + silent error states. File-level JSDoc per the docs standard.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run tests/unit/components/organizations/invite-member-typeahead.test.tsx`
Expected: PASS.

- [ ] **Step 6: Wire it into the invite form**

Read `frontend/src/components/modules/organizations/organization-invitations.tsx` (invite form at lines ~141-181). Replace the plain email `<Input>` with `<InviteMemberTypeahead>`. Add state `selectedUserId: string | null`; `onSelect` sets it (and clears any typed email), `onEmailChange` sets `inviteEmail` and clears `selectedUserId`. In `handleInvite` build the body conditionally:

```tsx
const body: OrgInvitationCreateRequest = selectedUserId
  ? { user_id: selectedUserId, role: inviteRole }
  : { email: inviteEmail, role: inviteRole };
```

Reset both `inviteEmail` and `selectedUserId` on success. Keep the existing role select, error display, and submit button. The manual email path (type a full new address, no suggestion selected) still works.

- [ ] **Step 7: Typecheck + lint**

Run: `cd frontend && npx tsc --noEmit && npx eslint src/components/modules/organizations/invite-member-typeahead.tsx src/components/modules/organizations/organization-invitations.tsx tests/unit/components/organizations/invite-member-typeahead.test.tsx`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
cd /Users/a0000/projects/auracles
git add frontend/src/lib/generated frontend/src/components/modules/organizations/invite-member-typeahead.tsx frontend/src/components/modules/organizations/organization-invitations.tsx frontend/tests/unit/components/organizations/invite-member-typeahead.test.tsx
git commit -m "Add invite typeahead using masked member search"
```

---

## Final verification (after all tasks)

- [ ] Backend: `cd backend && uv run ruff check . && uv run mypy app` — clean.
- [ ] Backend: `cd backend && uv run pytest tests/ -k "member_search or invitation" -v` — green.
- [ ] Frontend: `cd frontend && npx tsc --noEmit && npx eslint . && npx vitest run tests/unit/components/organizations` — clean/green.
- [ ] Manual (localhost, org admin): open invite form, type ≥3 chars of a colleague's name/email → masked suggestions appear; pick one → invite sent (they get the email/notification); confirm the network response for the create call shows the **masked** email, and the search response never contains a full address. Type a full outsider email with no selection → invite still sends by email. Type 2 chars → no request fires. As a non-admin member, confirm the search endpoint 403s.

## Self-review notes

- **Spec coverage:** member-search + guard (Task 1), invite-by-user_id + masked echo (Task 2), typeahead UI (Task 3). All spec sections mapped.
- **Enumeration guard** is enforced server-side only (client cannot be trusted): admin RBAC, min-3, cap-10, rate-limit, audit, masked emails, invite-by-id. The plan never relies on the frontend for any of these.
- **Residual risk (documented in spec):** the pending-invitations *list* still shows full emails, and inviting is a loud, rate-limited, audited action — accepted trade-off. The create-by-id response is masked as a cheap extra guard.
- **Type consistency:** `search_org_members` operationId → generated `searchOrgMembers`; `OrgInvitationCreateRequest` gains `user_id` used identically in Task 2 (backend) and Task 3 (frontend body).
- **LIKE-injection:** user input is escaped (`\`, `%`, `_`) with `escape="\\"` before prefix matching.
