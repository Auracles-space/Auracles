# Org Invitation Inbox + Dead-Link Fix (Slice A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give an invitee an in-app "Pending invitations" inbox at `/settings/organizations` (list + Accept/Decline without the email token), fix the dead `/settings/organizations` notification link, and make sure a freshly-registered invitee notices the invite.

**Architecture:** Add a token-free "invitations I received" read + id-based accept/decline to the existing `org-invitations` router (the token path stays untouched; shared post-resolution logic is extracted so both paths are DRY). Register-time reconciliation writes the `org_invitation_received` notification for invitees who had no account at invite time. A new client page renders the inbox; a global toast + settings-nav badge surface the count.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, Alembic (no migration needed here), pytest / httpx AsyncClient; Next.js 15 App Router, Tailwind, vitest + React Testing Library, hey-api generated client.

## Global Constraints

- Backend-before-frontend; OpenAPI-first: update `contracts/openapi.yaml`, then regenerate the client (`cd frontend && npm run generate:api`).
- TDD RED→GREEN per behavior. One test → one implementation → repeat. Never write implementation before its failing test.
- No `Co-Authored-By` trailer on commits. Work directly on `main` (do not create a branch).
- Test DB is `auracles_test`. Backend tests: `cd backend && uv run pytest <path> -v`. Full lint before done: `cd backend && uv run ruff check . && uv run mypy app`; `cd frontend && npx tsc --noEmit && npx eslint <files>`.
- Loguru only, never `print`. Response models explicit; never return ORM objects. Pydantic on every input.
- Mobile-first, 44px touch targets, verified at 375px for every new component.
- Money/escrow untouched by this slice.
- Route ordering: the new literal `/received...` routes MUST be registered **before** the existing `/{token}` routes on `invitation_router`, or Starlette will match `received` as a `{token}` value.

---

### Task 1: Backend — list "invitations I received" endpoint

**Files:**
- Modify: `backend/app/modules/organizations/schemas.py` (add `MyInvitationResponse`, `MyInvitationsResponse` after `OrgInvitationPreviewResponse`, ~line 401)
- Modify: `backend/app/modules/organizations/service.py` (add `list_received_invitations`)
- Modify: `backend/app/modules/organizations/router.py` (add `GET /org-invitations/received` **above** the `/{token}` route at line 1207)
- Modify: `contracts/openapi.yaml` (regenerate)
- Test: `backend/tests/integration/test_org_invitation_inbox.py` (new)

**Interfaces:**
- Produces:
  - `MyInvitationResponse{ id: UUID, org: OrganizationResponse, role: str, invited_by_name: str | None, created_at: datetime }`
  - `MyInvitationsResponse{ invitations: list[MyInvitationResponse] }`
  - `service.list_received_invitations(db: AsyncSession, *, user: User) -> MyInvitationsResponse`
  - Route `GET /v1/org-invitations/received` → `MyInvitationsResponse`, operationId `list_received_invitations`.

- [ ] **Step 1: Write the failing test**

Look at `backend/tests/integration/test_organizations_endpoints.py` for fixture patterns (authed client, factory usage). Create `backend/tests/integration/test_org_invitation_inbox.py`:

```python
"""Integration tests for the invitee invitation inbox (Slice A).

Covers listing invitations addressed to the authenticated user and the
id-based accept/decline endpoints. Maps to the org-invitation-inbox design.
"""
import pytest


@pytest.mark.asyncio
async def test_received_lists_only_my_pending_invitations(
    authed_client, other_user_org_with_invite
):
    """GET /org-invitations/received returns pending invites for my email only.

    The invite's email must match the caller; other emails, non-pending
    invites, and dead orgs are excluded, and no token is ever leaked.
    """
    client, me = authed_client  # me.email matches the seeded invite
    resp = await client.get("/v1/org-invitations/received")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["invitations"]) == 1
    inv = body["invitations"][0]
    assert inv["role"] == "member"
    assert inv["org"]["name"] == "Meridian"
    assert "token" not in inv and "token_hash" not in inv
    assert set(inv.keys()) == {"id", "org", "role", "invited_by_name", "created_at"}


@pytest.mark.asyncio
async def test_received_requires_auth(client):
    """Unauthenticated caller gets 401."""
    resp = await client.get("/v1/org-invitations/received")
    assert resp.status_code == 401
```

Build the `other_user_org_with_invite` fixture in this file (or `conftest`): create an org owned by user B, create a `pending` `OrgInvitation` whose `email == me.email` with `role="member"`, org name "Meridian", plus one non-matching invite (different email) and one `accepted` invite to prove filtering. Reuse existing factories in `backend/tests/factories/` — inspect them first; if an invitation factory is absent, insert rows directly with the ORM in the fixture.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_org_invitation_inbox.py -v`
Expected: FAIL — 404 (route missing).

- [ ] **Step 3: Add the schemas**

In `schemas.py`, after `OrgInvitationPreviewResponse` (line ~401). `OrganizationResponse` is already defined in this file with a computed `logo_url`, so reuse it:

```python
class MyInvitationResponse(BaseModel):
    """A pending invitation addressed to the authenticated user.

    Token-free: the invitee acts on it by id via the /received endpoints,
    never by the raw token (which is not retrievable — only its hash is stored).
    """

    id: UUID
    org: OrganizationResponse
    role: str
    invited_by_name: str | None
    created_at: datetime


class MyInvitationsResponse(BaseModel):
    """List wrapper for invitations addressed to the current user."""

    invitations: list[MyInvitationResponse]
```

- [ ] **Step 4: Add the service function**

In `service.py`. Confirm `func`, `select`, `datetime`, `UTC`, `User`, `Organization`, `OrgInvitation`, `OrganizationResponse` are already imported (they are used elsewhere in the file). Add:

```python
async def list_received_invitations(
    db: AsyncSession,
    *,
    user: User,
) -> MyInvitationsResponse:
    """List live pending invitations addressed to the authenticated user.

    Matches on the caller's email (case-insensitive), only for active orgs and
    non-expired pending invites. Never exposes the invitation token.

    Args:
        db: Async database session.
        user: The authenticated invitee.

    Returns:
        The invitations addressed to this user, newest first.
    """
    rows = (
        await db.execute(
            select(OrgInvitation, Organization, User.display_name)
            .join(Organization, Organization.id == OrgInvitation.org_id)
            .join(User, User.id == OrgInvitation.invited_by, isouter=True)
            .where(
                OrgInvitation.status == "pending",
                func.lower(OrgInvitation.email) == user.email.lower(),
                Organization.deactivated_at.is_(None),
                Organization.suspended_at.is_(None),
                OrgInvitation.expires_at > datetime.now(UTC),
            )
            .order_by(OrgInvitation.created_at.desc())
        )
    ).all()

    return MyInvitationsResponse(
        invitations=[
            MyInvitationResponse(
                id=invitation.id,
                org=OrganizationResponse.model_validate(organization),
                role=invitation.role,
                invited_by_name=inviter_name,
                created_at=invitation.created_at,
            )
            for invitation, organization, inviter_name in rows
        ]
    )
```

Add `MyInvitationResponse`, `MyInvitationsResponse` to the schema imports at the top of `service.py` (find the existing `from app.modules.organizations.schemas import (...)` block and add both names).

- [ ] **Step 5: Add the route (ABOVE the `/{token}` route)**

In `router.py`, immediately after `invitation_router = APIRouter(...)` (line 1204) and **before** `@invitation_router.get("/{token}")` (line 1207):

```python
@invitation_router.get(
    "/received",
    response_model=MyInvitationsResponse,
    operation_id="list_received_invitations",
    summary="List invitations addressed to me",
    description=(
        "List live pending invitations sent to the authenticated user's "
        "email. Token-free; the invitee accepts or declines by invitation id."
    ),
)
async def list_received_invitations(
    user: CurrentUser,
    db: DatabaseSession,
) -> MyInvitationsResponse:
    """List the authenticated user's pending invitations."""
    return await service.list_received_invitations(db=db, user=user)
```

Add `MyInvitationsResponse` to the schema imports at the top of `router.py`.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/integration/test_org_invitation_inbox.py -v`
Expected: PASS (both tests).

- [ ] **Step 7: Regenerate the OpenAPI contract**

Run from `backend/` (dumps the live spec with default yaml wrap width to keep the diff minimal):

```bash
cd backend && uv run python -c "
import yaml
from app.main import app
with open('../contracts/openapi.yaml', 'w') as f:
    yaml.safe_dump(app.openapi(), f, sort_keys=False, allow_unicode=True)
"
```

Verify: `git -C .. diff --stat contracts/openapi.yaml` shows additions only for the `received` path + `MyInvitationResponse`/`MyInvitationsResponse` schemas. If the diff is a large rewrap, `git checkout contracts/openapi.yaml` and re-run (width mismatch — the command above uses the default width already).

- [ ] **Step 8: Commit**

```bash
cd /Users/a0000/projects/auracles
git add backend/app/modules/organizations/schemas.py backend/app/modules/organizations/service.py backend/app/modules/organizations/router.py backend/tests/integration/test_org_invitation_inbox.py contracts/openapi.yaml
git commit -m "Add token-free received-invitations list endpoint"
```

---

### Task 2: Backend — id-based accept / decline + shared finalize refactor

**Files:**
- Modify: `backend/app/modules/organizations/service.py` (extract `_finalize_accept`, `_finalize_decline`, `_get_live_invitation_by_id`; add `accept_invitation_by_id`, `decline_invitation_by_id`; refactor token `accept_invitation`/`decline_invitation` to call the shared finalizers)
- Modify: `backend/app/modules/organizations/router.py` (add `/received/{invitation_id}/accept` + `/decline`, **above** the `/{token}` routes)
- Modify: `contracts/openapi.yaml` (regenerate)
- Test: `backend/tests/integration/test_org_invitation_inbox.py` (extend), `backend/tests/unit/modules/test_organizations_service.py` (regression on token path if present)

**Interfaces:**
- Consumes: `list_received_invitations` (Task 1), existing `accept_invitation`/`decline_invitation` bodies.
- Produces:
  - `service.accept_invitation_by_id(db, *, user: User, invitation_id: UUID) -> MyOrganizationResponse`
  - `service.decline_invitation_by_id(db, *, user: User, invitation_id: UUID) -> None`
  - Routes `POST /v1/org-invitations/received/{invitation_id}/accept` (→ `MyOrganizationResponse`, operationId `accept_received_invitation`), `.../decline` (→ 204, operationId `decline_received_invitation`).
  - Internal helpers `_finalize_accept(db, *, user, invitation, organization) -> MyOrganizationResponse`, `_finalize_decline(db, *, user, invitation, organization) -> None`, `_get_live_invitation_by_id(db, *, invitation_id) -> tuple[OrgInvitation, Organization]`.

- [ ] **Step 1: Write the failing tests**

Extend `backend/tests/integration/test_org_invitation_inbox.py`:

```python
@pytest.mark.asyncio
async def test_accept_by_id_creates_membership(authed_client, other_user_org_with_invite):
    """POST /received/{id}/accept joins the org and clears the invite."""
    client, me = authed_client
    inv_id = (await client.get("/v1/org-invitations/received")).json()["invitations"][0]["id"]
    resp = await client.post(f"/v1/org-invitations/received/{inv_id}/accept")
    assert resp.status_code == 200
    assert resp.json()["role"] == "member"
    # Invite no longer pending.
    assert (await client.get("/v1/org-invitations/received")).json()["invitations"] == []


@pytest.mark.asyncio
async def test_accept_by_id_rejects_email_mismatch(authed_client_other, other_user_org_with_invite):
    """A logged-in user whose email does not match the invite gets 403."""
    client, _ = authed_client_other  # different email than the invite target
    # Resolve the invite id via a direct query fixture value.
    inv_id = other_user_org_with_invite["invitation_id"]
    resp = await client.post(f"/v1/org-invitations/received/{inv_id}/accept")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_accept_by_id_duplicate_is_409(authed_client, other_user_org_with_invite):
    """Accepting an already-accepted invite returns 409, never 500."""
    client, _ = authed_client
    inv_id = other_user_org_with_invite["invitation_id"]
    assert (await client.post(f"/v1/org-invitations/received/{inv_id}/accept")).status_code == 200
    assert (await client.post(f"/v1/org-invitations/received/{inv_id}/accept")).status_code == 409


@pytest.mark.asyncio
async def test_decline_by_id_marks_declined(authed_client, other_user_org_with_invite):
    """POST /received/{id}/decline removes the invite from my inbox."""
    client, _ = authed_client
    inv_id = other_user_org_with_invite["invitation_id"]
    assert (await client.post(f"/v1/org-invitations/received/{inv_id}/decline")).status_code == 204
    assert (await client.get("/v1/org-invitations/received")).json()["invitations"] == []
```

Extend the `other_user_org_with_invite` fixture to return a dict including `invitation_id`, and add an `authed_client_other` fixture (a second authenticated user with a non-matching email). Follow existing multi-user fixture patterns in `backend/tests/`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/integration/test_org_invitation_inbox.py -v`
Expected: the 4 new tests FAIL with 404 (routes missing).

- [ ] **Step 3: Extract the shared finalizers and refactor the token path**

In `service.py`, add `_get_live_invitation_by_id`, `_finalize_accept`, `_finalize_decline`. Move the existing lock+transaction+member+audit+notify body out of `accept_invitation` (lines 1215–1287) into `_finalize_accept`, and the decline body (lines 1321–1347) into `_finalize_decline`. Both finalizers take the already-resolved `(invitation, organization)` and the `user`; the caller is responsible for the email-match check. Keep behavior byte-for-byte identical.

```python
async def _get_live_invitation_by_id(
    db: AsyncSession,
    *,
    invitation_id: UUID,
) -> tuple[OrgInvitation, Organization]:
    """Resolve a pending invitation and its active org by id.

    Mirrors _get_live_invitation but keys on the invitation id (the invitee
    already knows it from their inbox) instead of the raw token.

    Raises:
        HTTPException(404): Unknown id or dead org.
        HTTPException(409): Non-pending status.
        HTTPException(410): Pending but expired.
    """
    invitation = await db.scalar(
        select(OrgInvitation).where(OrgInvitation.id == invitation_id)
    )
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found.")
    if invitation.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invitation is not available.")
    organization = await db.scalar(
        select(Organization).where(
            Organization.id == invitation.org_id,
            Organization.deactivated_at.is_(None),
            Organization.suspended_at.is_(None),
        )
    )
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation is not available.")
    if invitation.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invitation has expired.")
    return invitation, organization


async def _finalize_accept(
    db: AsyncSession,
    *,
    user: User,
    invitation: OrgInvitation,
    organization: Organization,
) -> MyOrganizationResponse:
    """Accept a resolved, email-matched invitation. Caller checked the email.

    Locks the invitation, creates the membership, audits, notifies the inviter,
    and returns the new membership in MyOrganizationResponse shape.
    """
    invitation_id = invitation.id
    invited_role = invitation.role
    invited_by = invitation.invited_by
    org_id = organization.id
    org_name = organization.name
    user_id = user.id
    user_display_name = user.display_name

    if db.in_transaction():
        await db.rollback()

    try:
        async with db.begin():
            locked_invitation = await db.scalar(
                select(OrgInvitation).where(OrgInvitation.id == invitation_id).with_for_update()
            )
            if locked_invitation is None or locked_invitation.status != "pending":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invitation is not available.")
            locked_invitation.status = "accepted"
            locked_invitation.responded_at = datetime.now(UTC)

            member = OrgMember(org_id=org_id, user_id=user_id, role=invited_role)
            db.add(member)
            await write_audit(
                db=db,
                actor_id=user_id,
                action="org_member_joined",
                target_type="organization",
                target_id=org_id,
                metadata={"role": invited_role},
            )
            await create_notification(
                db=db,
                user_id=invited_by,
                notification_type="org_invitation_accepted",
                title=f"{user_display_name} joined {org_name}",
                body=f"{user_display_name} accepted the invitation to join {org_name}.",
                link="/settings/organizations",
                payload={"org_id": str(org_id)},
                dedupe_key=f"org-invite-accepted:{invitation_id}",
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already a member of this organization.",
        ) from exc

    await sync_derived_roles(db, user_id=user_id)

    capabilities: dict[str, str] = {}
    cap_rows = (await db.scalars(select(OrgCapability).where(OrgCapability.org_id == org_id))).all()
    for cap in cap_rows:
        capabilities[cap.capability] = cap.status

    org_obj = await db.scalar(select(Organization).where(Organization.id == org_id))
    if org_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    return MyOrganizationResponse(
        org=OrganizationResponse.model_validate(org_obj),
        role=invited_role,
        capabilities=capabilities,
        nda_required=capabilities.get("attestor") in ("pending", "active"),
    )


async def _finalize_decline(
    db: AsyncSession,
    *,
    user: User,
    invitation: OrgInvitation,
    organization: Organization,
) -> None:
    """Decline a resolved, email-matched invitation. Caller checked the email."""
    invitation_id = invitation.id
    invited_by = invitation.invited_by
    org_id = organization.id
    org_name = organization.name
    user_display_name = user.display_name

    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        locked_invitation = await db.scalar(
            select(OrgInvitation).where(OrgInvitation.id == invitation_id).with_for_update()
        )
        if locked_invitation is None or locked_invitation.status != "pending":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invitation is not available.")
        locked_invitation.status = "declined"
        locked_invitation.responded_at = datetime.now(UTC)

        await create_notification(
            db=db,
            user_id=invited_by,
            notification_type="org_invitation_declined",
            title=f"{user_display_name} declined the invitation",
            body=f"{user_display_name} declined the invitation to join {org_name}.",
            link="/settings/organizations",
            payload={"org_id": str(org_id)},
            dedupe_key=f"org-invite-declined:{invitation_id}",
        )
```

Now shrink the token functions to resolve + email-check + delegate:

```python
async def accept_invitation(db: AsyncSession, *, user: User, token: str) -> MyOrganizationResponse:
    """Accept an invitation via its raw token (email-link path)."""
    invitation, organization = await _get_live_invitation(db, token=token)
    if user.email.lower() != invitation.email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This invitation was sent to a different email address.")
    return await _finalize_accept(db, user=user, invitation=invitation, organization=organization)


async def decline_invitation(db: AsyncSession, *, user: User, token: str) -> None:
    """Decline an invitation via its raw token (email-link path)."""
    invitation, organization = await _get_live_invitation(db, token=token)
    if user.email.lower() != invitation.email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This invitation was sent to a different email address.")
    await _finalize_decline(db, user=user, invitation=invitation, organization=organization)
```

- [ ] **Step 4: Add the id-based service functions**

```python
async def accept_invitation_by_id(db: AsyncSession, *, user: User, invitation_id: UUID) -> MyOrganizationResponse:
    """Accept an invitation the invitee found in their in-app inbox."""
    invitation, organization = await _get_live_invitation_by_id(db, invitation_id=invitation_id)
    if user.email.lower() != invitation.email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This invitation was sent to a different email address.")
    return await _finalize_accept(db, user=user, invitation=invitation, organization=organization)


async def decline_invitation_by_id(db: AsyncSession, *, user: User, invitation_id: UUID) -> None:
    """Decline an invitation the invitee found in their in-app inbox."""
    invitation, organization = await _get_live_invitation_by_id(db, invitation_id=invitation_id)
    if user.email.lower() != invitation.email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This invitation was sent to a different email address.")
    await _finalize_decline(db, user=user, invitation=invitation, organization=organization)
```

- [ ] **Step 5: Add the routes (ABOVE `/{token}`)**

In `router.py`, directly after the `GET /received` route from Task 1 (still above `/{token}`):

```python
@invitation_router.post(
    "/received/{invitation_id}/accept",
    response_model=MyOrganizationResponse,
    operation_id="accept_received_invitation",
    summary="Accept an invitation from my inbox",
    description="Accept a pending invitation by id. The caller's email must match the invitation.",
)
async def accept_received_invitation(
    invitation_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
) -> MyOrganizationResponse:
    """Accept an invitation addressed to the authenticated user by id."""
    return await service.accept_invitation_by_id(db=db, user=user, invitation_id=invitation_id)


@invitation_router.post(
    "/received/{invitation_id}/decline",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="decline_received_invitation",
    summary="Decline an invitation from my inbox",
    description="Decline a pending invitation by id. The caller's email must match the invitation.",
)
async def decline_received_invitation(
    invitation_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
) -> None:
    """Decline an invitation addressed to the authenticated user by id."""
    await service.decline_invitation_by_id(db=db, user=user, invitation_id=invitation_id)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/integration/test_org_invitation_inbox.py -v`
Expected: all tests PASS.

Then run the existing token-path tests to prove the refactor is behavior-preserving:
Run: `cd backend && uv run pytest tests/ -k "invitation" -v`
Expected: PASS.

- [ ] **Step 7: Regenerate OpenAPI**

Same command as Task 1 Step 7. Verify the diff adds only the two `received/.../accept|decline` paths.

- [ ] **Step 8: Commit**

```bash
cd /Users/a0000/projects/auracles
git add backend/app/modules/organizations/service.py backend/app/modules/organizations/router.py backend/tests/integration/test_org_invitation_inbox.py contracts/openapi.yaml
git commit -m "Add id-based invitation accept/decline with shared finalize path"
```

---

### Task 3: Backend — register-time notification reconciliation

**Files:**
- Modify: `backend/app/modules/auth/service.py` (`register_user`, inside the `async with db.begin()` block, after `db.flush()`)
- Test: `backend/tests/unit/modules/test_auth_service.py` (or a new `test_auth_register_reconcile.py` if the former is large)

**Interfaces:**
- Consumes: existing `create_notification`, `OrgInvitation` model.
- Produces: no new public symbols; a new user with a matching pending invite gets an `org_invitation_received` notification (dedupe_key `org-invitation-received:{invitation.id}`).

- [ ] **Step 1: Write the failing test**

In `backend/tests/unit/modules/` add `test_auth_register_reconcile.py`:

```python
"""Register-time reconciliation of pending org invitations (Slice A)."""
import pytest
from sqlalchemy import select

from app.modules.notifications.models import Notification


@pytest.mark.asyncio
async def test_register_creates_notification_for_pending_invite(db, redis, make_pending_invite):
    """Registering with an email that has a pending invite writes a notification."""
    email = "newbie@example.com"
    await make_pending_invite(email=email)  # inserts a pending OrgInvitation to `email`
    from app.modules.auth import service as auth_service
    from app.modules.auth.schemas import RegisterRequest

    await auth_service.register_user(
        db, redis,
        RegisterRequest(email=email, password="Str0ng!passw0rd", display_name="Newbie", roles=["operator"]),
    )
    notes = (await db.execute(select(Notification).where(Notification.type == "org_invitation_received"))).scalars().all()
    assert len(notes) == 1


@pytest.mark.asyncio
async def test_register_without_invite_creates_no_notification(db, redis):
    """No pending invite → no org_invitation_received notification."""
    from app.modules.auth import service as auth_service
    from app.modules.auth.schemas import RegisterRequest

    await auth_service.register_user(
        db, redis,
        RegisterRequest(email="solo@example.com", password="Str0ng!passw0rd", display_name="Solo", roles=["operator"]),
    )
    notes = (await db.execute(select(Notification).where(Notification.type == "org_invitation_received"))).scalars().all()
    assert notes == []
```

Add a `make_pending_invite` fixture (create an org + a `pending` `OrgInvitation` with the given email; reuse the fixture from Task 1 if shared via conftest). Match the exact `RegisterRequest` field names/validators — inspect `app/modules/auth/schemas.py` first and adjust the password to satisfy its policy.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/modules/test_auth_register_reconcile.py -v`
Expected: FAIL — first test finds 0 notifications.

- [ ] **Step 3: Implement reconciliation in `register_user`**

In `app/modules/auth/service.py`, inside `register_user`'s `async with db.begin():` block, after the roles loop and before/after `write_audit` (still inside the transaction). Add imports at top: `from app.modules.organizations.models import OrgInvitation` and `from app.modules.notifications.service import create_notification` (verify no circular import — if one occurs, import inside the function body). Then:

```python
            # Reconcile any invitations addressed to this email so the invitee
            # sees them in-app immediately after registering. dedupe_key makes
            # this idempotent with the invite-time notification for existing users.
            pending_invites = (
                await db.scalars(
                    select(OrgInvitation).where(
                        func.lower(OrgInvitation.email) == email,
                        OrgInvitation.status == "pending",
                    )
                )
            ).all()
            for invite in pending_invites:
                await create_notification(
                    db=db,
                    user_id=user.id,
                    notification_type="org_invitation_received",
                    title="You have a pending organization invitation",
                    body="An organization invited you to join. Review it in your settings.",
                    link="/settings/organizations",
                    payload={"org_id": str(invite.org_id)},
                    dedupe_key=f"org-invitation-received:{invite.id}",
                )
```

Confirm `select` and `func` are imported in this file (add if missing).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/modules/test_auth_register_reconcile.py -v`
Expected: PASS.

Run the existing auth suite to ensure registration still works:
Run: `cd backend && uv run pytest tests/ -k "register" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/a0000/projects/auracles
git add backend/app/modules/auth/service.py backend/tests/unit/modules/test_auth_register_reconcile.py
git commit -m "Reconcile pending org invitations into notifications at registration"
```

---

### Task 4: Frontend — regenerate client + `/settings/organizations` inbox page

**Files:**
- Regenerate: `frontend/src/lib/generated/*` (via `npm run generate:api`)
- Create: `frontend/src/app/(auth)/settings/organizations/page.tsx`
- Create: `frontend/src/components/modules/settings/organizations-panel.tsx`
- Modify: `frontend/src/components/modules/settings/settings-workspace-shell.tsx` (add the nav link)
- Test: `frontend/tests/unit/components/settings/organizations-panel.test.tsx` (new)

**Interfaces:**
- Consumes generated client fns (names derive from the operationIds set in Tasks 1–2; after regen, confirm exact names in `src/lib/generated/sdk.gen.ts`):
  - `listReceivedInvitationsV1OrgInvitationsReceivedGet`
  - `acceptReceivedInvitationV1OrgInvitationsReceivedInvitationIdAcceptPost`
  - `declineReceivedInvitationV1OrgInvitationsReceivedInvitationIdDeclinePost`
  - `listMyOrganizationsV1OrgsMineGet` (existing)
- Produces: `OrganizationsPanel` component; a `/settings/organizations` route.

- [ ] **Step 1: Regenerate the client**

Run: `cd frontend && npm run generate:api`
Then confirm the three new fn names: `grep -oE "export const (listReceivedInvitations|acceptReceivedInvitation|declineReceivedInvitation)[A-Za-z0-9]*" src/lib/generated/sdk.gen.ts`. Use whatever names it prints in the steps below.

- [ ] **Step 2: Write the failing component test**

Study `frontend/src/components/modules/organizations/organization-logo-uploader.tsx`'s test for the mock pattern (`vi.mock("@/lib/generated/sdk.gen", ...)`, `vi.mock("@/lib/auth/form-client", ...)`). Create `frontend/tests/unit/components/settings/organizations-panel.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationsPanel } from "@/components/modules/settings/organizations-panel";
import {
  listReceivedInvitationsV1OrgInvitationsReceivedGet,
  acceptReceivedInvitationV1OrgInvitationsReceivedInvitationIdAcceptPost,
  listMyOrganizationsV1OrgsMineGet,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }) }));
vi.mock("@/lib/generated/sdk.gen", () => ({
  listReceivedInvitationsV1OrgInvitationsReceivedGet: vi.fn(),
  acceptReceivedInvitationV1OrgInvitationsReceivedInvitationIdAcceptPost: vi.fn(),
  declineReceivedInvitationV1OrgInvitationsReceivedInvitationIdDeclinePost: vi.fn(),
  listMyOrganizationsV1OrgsMineGet: vi.fn(),
}));

const ok = <T,>(data: T) => ({ data, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("OrganizationsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(ok({ organizations: [] }) as never);
  });

  it("renders a pending invitation and accepts it", async () => {
    vi.mocked(listReceivedInvitationsV1OrgInvitationsReceivedGet).mockResolvedValue(
      ok({ invitations: [{ id: "inv-1", role: "member", invited_by_name: "Ada", created_at: "2026-07-13T00:00:00Z", org: { id: "o1", name: "Meridian", slug: "meridian", logo_url: null } }] }) as never,
    );
    vi.mocked(acceptReceivedInvitationV1OrgInvitationsReceivedInvitationIdAcceptPost).mockResolvedValue(ok({ role: "member" }) as never);

    render(<OrganizationsPanel />);
    await waitFor(() => expect(screen.getByText("Meridian")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /accept/i }));
    await waitFor(() =>
      expect(acceptReceivedInvitationV1OrgInvitationsReceivedInvitationIdAcceptPost).toHaveBeenCalledWith(
        expect.objectContaining({ path: { invitation_id: "inv-1" } }),
      ),
    );
  });

  it("shows an empty state when there are no invitations", async () => {
    vi.mocked(listReceivedInvitationsV1OrgInvitationsReceivedGet).mockResolvedValue(ok({ invitations: [] }) as never);
    render(<OrganizationsPanel />);
    await waitFor(() => expect(screen.getByText(/no pending invitations/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run tests/unit/components/settings/organizations-panel.test.tsx`
Expected: FAIL — module `organizations-panel` not found.

- [ ] **Step 4: Implement the panel**

Create `frontend/src/components/modules/settings/organizations-panel.tsx`. Follow the data-loading + toast pattern from `organization-profile.tsx` and `notification-preferences-panel.tsx`. Mobile-first card stack; Accept/Decline buttons min-h-11 (44px). Include: "My organizations" section (from `listMyOrganizationsV1OrgsMineGet`, link each to `/dashboard/organizations/{id}`), "Pending invitations" section (rows with org name/logo, role, invited-by, Accept/Decline). On accept success: remove the row and toast; on decline success: remove the row. Empty state text "No pending invitations." Use `configureBrowserClient()` + `getAccessTokenHeaders()` before each call, exactly as the uploader does. Provide a real JSDoc file header per the docs standard.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run tests/unit/components/settings/organizations-panel.test.tsx`
Expected: PASS.

- [ ] **Step 6: Add the route page + nav link**

Create `frontend/src/app/(auth)/settings/organizations/page.tsx` mirroring `settings/notifications/page.tsx` (header block + `<OrganizationsPanel />`, `mx-auto max-w-4xl space-y-6`). File-level JSDoc.

In `settings-workspace-shell.tsx`, add to `settingsLinks` (place after the "Notifications" entry):

```tsx
  {
    href: "/settings/organizations",
    label: "Organizations",
    getSummary: () => "Your organizations and pending invitations.",
  },
```

- [ ] **Step 7: Typecheck + lint**

Run: `cd frontend && npx tsc --noEmit && npx eslint src/components/modules/settings/organizations-panel.tsx "src/app/(auth)/settings/organizations/page.tsx" src/components/modules/settings/settings-workspace-shell.tsx tests/unit/components/settings/organizations-panel.test.tsx`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
cd /Users/a0000/projects/auracles
git add frontend/src/lib/generated frontend/src/app/"(auth)"/settings/organizations frontend/src/components/modules/settings/organizations-panel.tsx frontend/src/components/modules/settings/settings-workspace-shell.tsx frontend/tests/unit/components/settings/organizations-panel.test.tsx
git commit -m "Add settings organizations inbox page and nav link"
```

---

### Task 5: Frontend — pending-invite badge + one-time login toast

**Files:**
- Create: `frontend/src/components/modules/settings/pending-invitations-toast.tsx`
- Modify: `frontend/src/components/modules/layout/authenticated-app-shell.tsx` (mount the toast component)
- Modify: `frontend/src/components/modules/settings/settings-workspace-shell.tsx` (badge count on the Organizations link)
- Test: `frontend/tests/unit/components/settings/pending-invitations-toast.test.tsx` (new)

**Interfaces:**
- Consumes: `listReceivedInvitationsV1OrgInvitationsReceivedGet`, `useToast()`.
- Produces: `PendingInvitationsToast` (renders nothing; fires a one-time toast). The toast dedupe key is `localStorage["pending-invites-seen"]` = the sorted invitation ids joined by `,`.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/components/settings/pending-invitations-toast.test.tsx`:

```tsx
import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PendingInvitationsToast } from "@/components/modules/settings/pending-invitations-toast";
import { listReceivedInvitationsV1OrgInvitationsReceivedGet } from "@/lib/generated/sdk.gen";

const toastSuccess = vi.fn();
vi.mock("@/components/ui/toast", () => ({ useToast: () => ({ success: toastSuccess, error: vi.fn() }) }));
vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({ listReceivedInvitationsV1OrgInvitationsReceivedGet: vi.fn() }));

const ok = <T,>(data: T) => ({ data, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("PendingInvitationsToast", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("toasts once when there are pending invitations", async () => {
    vi.mocked(listReceivedInvitationsV1OrgInvitationsReceivedGet).mockResolvedValue(
      ok({ invitations: [{ id: "a" }, { id: "b" }] }) as never,
    );
    render(<PendingInvitationsToast />);
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledTimes(1));
    // Second mount with the same set does not re-toast.
    render(<PendingInvitationsToast />);
    await new Promise((r) => setTimeout(r, 0));
    expect(toastSuccess).toHaveBeenCalledTimes(1);
  });

  it("does not toast when there are none", async () => {
    vi.mocked(listReceivedInvitationsV1OrgInvitationsReceivedGet).mockResolvedValue(ok({ invitations: [] }) as never);
    render(<PendingInvitationsToast />);
    await new Promise((r) => setTimeout(r, 0));
    expect(toastSuccess).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run tests/unit/components/settings/pending-invitations-toast.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the toast component**

Create `frontend/src/components/modules/settings/pending-invitations-toast.tsx` (client component). On mount: `configureBrowserClient()`, fetch received invitations; compute `key = invitations.map(i => i.id).sort().join(",")`; if `invitations.length > 0` and `localStorage.getItem("pending-invites-seen") !== key`, call `toast.success(\`You have ${n} pending invitation${n===1?"":"s"} — review them in Settings › Organizations.\`)` and `localStorage.setItem("pending-invites-seen", key)`. Render `null`. Swallow fetch errors silently (discoverability is best-effort; never block the shell). File-level JSDoc.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run tests/unit/components/settings/pending-invitations-toast.test.tsx`
Expected: PASS.

- [ ] **Step 5: Mount the toast + add the nav badge**

In `authenticated-app-shell.tsx`, render `<PendingInvitationsToast />` once inside the shell (near the top of the returned tree, alongside existing global children). Confirm the shell is a client component (`"use client"`); if not, mount the toast from a client child that already exists.

In `settings-workspace-shell.tsx`, fetch the received-invitation count on mount (client `useEffect`) and render a count badge on the "Organizations" link label when `> 0`. Reuse the badge styling pattern from `components/ui/tabs.tsx` (the `count` badge span). Keep it purely additive — the link still works with no badge when count is 0.

- [ ] **Step 6: Typecheck + lint**

Run: `cd frontend && npx tsc --noEmit && npx eslint src/components/modules/settings/pending-invitations-toast.tsx src/components/modules/layout/authenticated-app-shell.tsx src/components/modules/settings/settings-workspace-shell.tsx tests/unit/components/settings/pending-invitations-toast.test.tsx`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
cd /Users/a0000/projects/auracles
git add frontend/src/components/modules/settings/pending-invitations-toast.tsx frontend/src/components/modules/layout/authenticated-app-shell.tsx frontend/src/components/modules/settings/settings-workspace-shell.tsx frontend/tests/unit/components/settings/pending-invitations-toast.test.tsx
git commit -m "Surface pending invitations via login toast and settings badge"
```

---

## Final verification (after all tasks)

- [ ] Backend: `cd backend && uv run ruff check . && uv run mypy app` — clean.
- [ ] Backend: `cd backend && uv run pytest tests/ -k "invitation or register" -v` — green.
- [ ] Frontend: `cd frontend && npx tsc --noEmit && npx eslint .` — clean.
- [ ] Frontend: `cd frontend && npx vitest run tests/unit/components/settings` — green.
- [ ] Manual (localhost): create an org as user A, invite user B's email; as B, log in → see the toast + settings badge → open `/settings/organizations` → Accept → land in the org; re-open inbox → invite gone. Repeat with Decline. Confirm the old notification link (`/settings/organizations`) now resolves.
- [ ] Manual: invite an unregistered email, register that email, confirm the `org_invitation_received` notification and the inbox entry both appear.

## Notes / self-review

- **Spec coverage:** list-received (Task 1), id accept/decline + shared finalize refactor (Task 2), register reconciliation (Task 3), `/settings/organizations` inbox + dead-link fix + nav (Task 4), badge + one-time toast (Task 5). All spec sections mapped.
- **Route-collision guard** is called out in Global Constraints and both backend tasks: `/received...` literal routes must precede `/{token}`.
- **DRY:** token and id paths share `_finalize_accept`/`_finalize_decline`; the refactor is behavior-preserving and covered by the existing token tests re-run in Task 2 Step 6.
- **Type consistency:** generated fn names derive from the operationIds (`list_received_invitations`, `accept_received_invitation`, `decline_received_invitation`); Task 4 Step 1 re-confirms the exact strings post-regen before use.
