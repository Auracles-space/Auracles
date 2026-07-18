# Org Contributor Framework Management UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give org members full-parity Framework management UI under the organization identity, built by extracting the existing personal Contributor Framework components into shared, seller-identity-parameterized components, and enforce the team-scoped capability grant on org authoring endpoints.

**Architecture:** Backend adds a grant-enforcing dependency (`require_org_capability_grant`), two missing org endpoints (list-artifacts, relist), and a caller-scoped `grants` field on the my-orgs payload. Frontend introduces a `FrameworkApi` adapter built from a serializable `FrameworkSeller` descriptor; existing client components are refactored to receive the descriptor and build the adapter internally (one code path for personal + org); new org routes and a nav tab surface the feature.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, pytest/pytest-asyncio (backend); Next.js 15 App Router, TypeScript, vitest + @testing-library/react, hey-api generated SDK (frontend).

## Global Constraints

- Work on `main`, no branches. Never create a branch without asking.
- Commit messages end at the last meaningful line — **no `Co-Authored-By` trailer**.
- TDD RED→GREEN per behavior. One test → one implementation. No horizontal slicing.
- OpenAPI-first: when an endpoint contract changes, update `contracts/openapi.yaml`, then regenerate the frontend client with `npm run generate:api` (run from `frontend/`).
- Backend commands run from `backend/` and use `uv` (e.g. `cd backend && uv run pytest ...`).
- Full-repo lint/type before claiming a task clean: `cd backend && uv run ruff check . && uv run mypy app`; `cd frontend && npx tsc --noEmit && npx eslint .`.
- Backend is authoritative for all gating; UI gating is convenience only.
- Mobile-first, 44px min touch targets, verify at 375px for any new UI.
- Authoring authority: create/edit/submit/list/get/artifact-upload/confirm are **grant-gated** (owner/admin OR contributor-capability team member). publish/unpublish/relist/pricing/version remain **admin/owner** only.

---

## File Structure

**Backend**
- Modify `backend/app/modules/organizations/dependencies.py` — add `require_org_capability_grant`.
- Modify `backend/app/modules/frameworks/router.py` — swap authoring endpoints to the grant dependency; add org list-artifacts + org relist endpoints.
- Modify `backend/app/modules/frameworks/service.py` — add `list_artifacts_for_owner`, `relist_framework_for_owner`.
- Modify `backend/app/modules/organizations/service.py` — add `caller_capability_grants`.
- Modify `backend/app/modules/organizations/schemas.py` — add `grants` to `MyOrganizationResponse`.
- Modify `backend/app/modules/organizations/router.py` — populate `grants` in `/orgs/mine`.
- Modify `contracts/openapi.yaml` — new endpoints + `grants` field.

**Frontend**
- Create `frontend/src/lib/frameworks/framework-api.ts` — `FrameworkSeller`, `FrameworkApi`, `frameworkApiFor`.
- Modify `frontend/src/components/modules/frameworks/*` — accept `seller` (and `canManageLiveState`/`pricingInline` where relevant), build adapter internally.
- Create `frontend/src/app/(auth)/dashboard/organizations/[orgId]/frameworks/{page,new/page,[id]/page}.tsx`.
- Modify `frontend/src/components/modules/organizations/organization-shell.tsx` — Frameworks tab.
- Regenerate `frontend/src/lib/generated/*`.

---

## Task 1: Backend — `require_org_capability_grant` dependency + apply to authoring endpoints

**Files:**
- Modify: `backend/app/modules/organizations/dependencies.py`
- Modify: `backend/app/modules/frameworks/router.py`
- Test: `backend/tests/unit/modules/test_org_capability_grant_dependency.py` (create)
- Test: `backend/tests/integration/test_org_frameworks.py` (add cases; create if absent)

**Interfaces:**
- Consumes: `OrgContext`, `_load_org_context`, `_deny`, `_ROLE_RANK` (dependencies.py); `OrgTeam`, `OrgTeamMember`, `OrgTeamCapability` (organizations/models.py).
- Produces: `require_org_capability_grant(capability: str) -> Callable[..., OrgContext]` — FastAPI dependency returning `OrgContext`, drop-in for `require_org_role("member")` on org-framework authoring endpoints.

- [ ] **Step 1: Write the failing unit tests**

Create `backend/tests/unit/modules/test_org_capability_grant_dependency.py`. Use the org/member/team factory helpers already in the unit suite (inspect `backend/tests/unit/modules/test_org_*` for helpers that create an org, a member with a role, a capability row, a team + team-capability + team-member). Cover every branch:

```python
"""Unit tests for require_org_capability_grant.

Enforces the team-scoped capability model on org-scoped actions: a caller holds
a capability grant only as owner/admin, or as a member of a team with the
capability enabled, and only while the org capability is active.
"""
import pytest
from fastapi import HTTPException

from app.modules.organizations.dependencies import require_org_capability_grant


async def _run(dep, *, org_id, db, user):
    """Invoke the dependency's inner checker directly."""
    return await dep(org_id=org_id, db=db, user=user)


@pytest.mark.asyncio
async def test_owner_holds_grant(db, org_factory, member_factory, capability_factory):
    """An owner holds any active capability's grant without team membership."""
    org = await org_factory()
    await capability_factory(org_id=org.id, capability="contributor", status="active")
    owner_user = await member_factory(org_id=org.id, role="owner")
    ctx = await _run(require_org_capability_grant("contributor"), org_id=org.id, db=db, user=owner_user)
    assert ctx.org.id == org.id


@pytest.mark.asyncio
async def test_admin_holds_grant(db, org_factory, member_factory, capability_factory):
    """An admin holds an active capability's grant without team membership."""
    org = await org_factory()
    await capability_factory(org_id=org.id, capability="contributor", status="active")
    admin_user = await member_factory(org_id=org.id, role="admin")
    ctx = await _run(require_org_capability_grant("contributor"), org_id=org.id, db=db, user=admin_user)
    assert ctx.member.role == "admin"


@pytest.mark.asyncio
async def test_team_member_holds_grant(db, org_factory, member_factory, capability_factory, team_factory):
    """A plain member on a contributor-capability team holds the grant."""
    org = await org_factory()
    await capability_factory(org_id=org.id, capability="contributor", status="active")
    user, member_id = await member_factory(org_id=org.id, role="member", return_member_id=True)
    await team_factory(org_id=org.id, capability="contributor", member_ids=[member_id])
    ctx = await _run(require_org_capability_grant("contributor"), org_id=org.id, db=db, user=user)
    assert ctx.member.id == member_id


@pytest.mark.asyncio
async def test_plain_member_without_team_denied(db, org_factory, member_factory, capability_factory):
    """A plain member not on any contributor team is denied (403 grant_required)."""
    org = await org_factory()
    await capability_factory(org_id=org.id, capability="contributor", status="active")
    user = await member_factory(org_id=org.id, role="member")
    with pytest.raises(HTTPException) as exc:
        await _run(require_org_capability_grant("contributor"), org_id=org.id, db=db, user=user)
    assert exc.value.status_code == 403
    assert exc.value.detail["error_code"] == "capability_grant_required"


@pytest.mark.asyncio
async def test_inactive_capability_denied(db, org_factory, member_factory, capability_factory):
    """An owner is denied when the org capability is not active (403 capability_required)."""
    org = await org_factory()
    await capability_factory(org_id=org.id, capability="contributor", status="disabled")
    user = await member_factory(org_id=org.id, role="owner")
    with pytest.raises(HTTPException) as exc:
        await _run(require_org_capability_grant("contributor"), org_id=org.id, db=db, user=user)
    assert exc.value.status_code == 403
    assert exc.value.detail["error_code"] == "capability_required"
```

> Adapt fixture names to the ones already in the suite. If there is no `team_factory` attaching a capability + member, add a local helper in the test module that inserts `OrgTeam`, `OrgTeamCapability(team_id, capability)`, and `OrgTeamMember(team_id, member_id)` directly.

- [ ] **Step 2: Run the tests, verify they fail**

Run: `cd backend && uv run pytest tests/unit/modules/test_org_capability_grant_dependency.py -v`
Expected: FAIL — `ImportError: cannot import name 'require_org_capability_grant'`.

- [ ] **Step 3: Implement the dependency**

In `backend/app/modules/organizations/dependencies.py`, extend the model import:

```python
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgMember,
    OrgTeam,
    OrgTeamCapability,
    OrgTeamMember,
)
```

Append after `require_org_capability`:

```python
def require_org_capability_grant(capability: str) -> Callable[..., object]:
    """Build a dependency enforcing the caller's team-scoped capability grant.

    A caller holds the grant only when the organization capability is active and
    the caller is either an owner/admin or a member of a team with the matching
    capability enabled. This is the org-scoped enforcement of the team-scoped
    capability model; ``require_org_capability`` alone checks only that the org
    capability is active, not the caller's per-member grant.

    Args:
        capability: Capability slug (e.g. ``"contributor"``).

    Returns:
        A dependency returning :class:`OrgContext` when the grant holds.
    """

    async def checker(
        org_id: UUID,
        db: DatabaseSession,
        user: Annotated[User, Depends(get_current_user)],
    ) -> OrgContext:
        """Return org context when the caller holds the capability grant."""
        organization, membership = await _load_org_context(db, org_id, user)
        if membership is None:
            await _deny(db, user, org_id, {"required_capability": capability})
        assert membership is not None

        if organization.suspended_at is not None:
            await _deny(
                db, user, org_id, {"reason": "org_suspended"}, error_code="org_suspended"
            )

        active = await db.scalar(
            select(OrgCapability).where(
                OrgCapability.org_id == org_id,
                OrgCapability.capability == capability,
                OrgCapability.status == "active",
            )
        )
        if active is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error_code": "capability_required", "capability": capability},
            )

        if membership.role in ("owner", "admin"):
            return OrgContext(org=organization, member=membership, user=user)

        team_grant = await db.scalar(
            select(OrgTeamMember.member_id)
            .join(OrgTeam, OrgTeam.id == OrgTeamMember.team_id)
            .join(
                OrgTeamCapability,
                (OrgTeamCapability.team_id == OrgTeam.id)
                & (OrgTeamCapability.capability == capability),
            )
            .where(
                OrgTeamMember.member_id == membership.id,
                OrgTeam.org_id == org_id,
            )
            .limit(1)
        )
        if team_grant is not None:
            return OrgContext(org=organization, member=membership, user=user)

        await _deny(
            db,
            user,
            org_id,
            {"required_capability": capability, "member_role": membership.role},
            error_code="capability_grant_required",
        )
        raise AssertionError("unreachable")  # _deny always raises

    return checker
```

> `_deny` writes an `access_denied` audit row and raises 403 with the given `error_code`; the trailing `raise` satisfies the type checker.

- [ ] **Step 4: Run the unit tests, verify they pass**

Run: `cd backend && uv run pytest tests/unit/modules/test_org_capability_grant_dependency.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Swap the authoring endpoints to the grant dependency**

In `backend/app/modules/frameworks/router.py`, import the new dependency:

```python
from app.modules.organizations.dependencies import (
    OrgContext,
    require_org_capability,
    require_org_capability_grant,
    require_org_role,
)
```

Add a context alias near line 63:

```python
OrgContributorContext = Annotated[OrgContext, Depends(require_org_capability_grant("contributor"))]
```

For each of these org endpoints, replace the `context: OrgMemberContext` parameter with `context: OrgContributorContext`, and **remove** the now-redundant `_: Annotated[None, Depends(require_org_capability("contributor"))]` line (the grant dependency already checks the capability):
- `create_org_framework`
- `list_org_frameworks`
- `get_org_framework`
- `update_org_framework`
- `submit_org_framework`
- `create_org_artifact_upload_url` (org artifact upload-url endpoint)
- `confirm_org_artifact_upload` (org confirm endpoint)

Leave `OrgAdminContext` endpoints (`update_org_framework_pricing`, `unpublish_org_framework`, `publish_org_framework`, org start-version) unchanged.

- [ ] **Step 6: Write the failing integration test for authoring gating**

In `backend/tests/integration/test_org_frameworks.py` (create if absent; follow the existing org integration test style in `backend/tests/integration/`), add:

```python
async def test_contributor_team_member_can_create_org_framework(client, org_with_contributor_team):
    """A plain member on a contributor-capability team may create an org Framework."""
    org, member_token = org_with_contributor_team
    resp = await client.post(
        f"/v1/orgs/{org.id}/frameworks",
        json=_valid_framework_body(),
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp.status_code == 201


async def test_plain_member_cannot_create_org_framework(client, org_with_plain_member):
    """A member not on any contributor team is denied (403) when authoring."""
    org, member_token = org_with_plain_member
    resp = await client.post(
        f"/v1/orgs/{org.id}/frameworks",
        json=_valid_framework_body(),
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "capability_grant_required"
```

> Use org/token fixtures already present in the integration suite; `_valid_framework_body()` mirrors the personal create-framework test body in `backend/tests/integration/test_frameworks*.py`.

- [ ] **Step 7: Run integration tests, verify pass**

Run: `cd backend && uv run pytest tests/integration/test_org_frameworks.py -v`
Expected: PASS.

- [ ] **Step 8: Lint/type + commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/organizations/dependencies.py backend/app/modules/frameworks/router.py backend/tests/unit/modules/test_org_capability_grant_dependency.py backend/tests/integration/test_org_frameworks.py
git commit -m "Enforce team-scoped contributor grant on org framework authoring"
```

---

## Task 2: Backend — org list-artifacts endpoint

The org framework editor needs to list an org-owned Framework's artifacts. The personal `GET /v1/frameworks/{id}/artifacts` is scoped to `ContributorUser` ownership and cannot serve org-owned frameworks (null `contributor_id`).

**Files:**
- Modify: `backend/app/modules/frameworks/service.py`
- Modify: `backend/app/modules/frameworks/router.py`
- Modify: `contracts/openapi.yaml`
- Test: `backend/tests/unit/modules/test_frameworks_service.py` (add)
- Test: `backend/tests/integration/test_org_frameworks.py` (add)

**Interfaces:**
- Consumes: `FrameworkOwner`, `_load_owned_framework_by_owner`, `_artifact_to_response`, `Artifact` (service.py); `_org_owner`, `OrgContributorContext` (Task 1).
- Produces: `list_artifacts_for_owner(db, owner: FrameworkOwner, framework_id: UUID) -> list[ArtifactResponse]`; endpoint `GET /v1/orgs/{org_id}/frameworks/{framework_id}/artifacts` → `list[ArtifactResponse]`. Record the generated SDK fn name after Task 5 regen.

- [ ] **Step 1: Write the failing service test**

In `backend/tests/unit/modules/test_frameworks_service.py`:

```python
async def test_list_artifacts_for_owner_returns_org_framework_artifacts(db, org_framework_with_artifact):
    """list_artifacts_for_owner returns current artifacts for an org-owned Framework."""
    from app.modules.frameworks import service
    from app.modules.frameworks.ownership import FrameworkOwner

    framework, artifact, org_id, member_id = org_framework_with_artifact
    owner = FrameworkOwner(
        actor_id=member_id, user_id=None, org_id=org_id,
        authoring_member_id=member_id, can_manage_live_state=True,
    )
    result = await service.list_artifacts_for_owner(db=db, owner=owner, framework_id=framework.id)
    assert [a.id for a in result] == [artifact.id]
```

> Build `org_framework_with_artifact` from the factories already used by framework service tests (an org-owned `Framework` with `contributor_org_id` set + one `Artifact` with `current_for_framework=True`). Reuse an existing fixture if one matches.

- [ ] **Step 2: Run it, verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_frameworks_service.py -k list_artifacts_for_owner -v`
Expected: FAIL — `AttributeError: ... 'list_artifacts_for_owner'`.

- [ ] **Step 3: Implement the service function**

In `backend/app/modules/frameworks/service.py`, add next to `list_artifacts`:

```python
async def list_artifacts_for_owner(
    db: AsyncSession,
    owner: FrameworkOwner,
    framework_id: UUID,
) -> list[ArtifactResponse]:
    """Return current Artifacts for a Framework owned by the given owner context.

    Owner-aware counterpart to :func:`list_artifacts`, resolving ownership
    through :class:`FrameworkOwner` so organization-owned Frameworks are served.
    """
    framework = await _load_owned_framework_by_owner(db, owner, framework_id)
    artifacts = (
        (
            await db.execute(
                select(Artifact)
                .where(
                    Artifact.framework_id == framework.id,
                    Artifact.current_for_framework.is_(True),
                )
                .order_by(Artifact.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [_artifact_to_response(artifact) for artifact in artifacts]
```

- [ ] **Step 4: Run the service test, verify pass**

Run: `cd backend && uv run pytest tests/unit/modules/test_frameworks_service.py -k list_artifacts_for_owner -v`
Expected: PASS.

- [ ] **Step 5: Write the failing endpoint tests**

In `backend/tests/integration/test_org_frameworks.py`:

```python
async def test_org_list_artifacts_endpoint(client, org_framework_with_artifact_and_token):
    """GET org framework artifacts returns the org Framework's current artifacts."""
    org, framework_id, artifact_id, member_token = org_framework_with_artifact_and_token
    resp = await client.get(
        f"/v1/orgs/{org.id}/frameworks/{framework_id}/artifacts",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp.status_code == 200
    assert [a["id"] for a in resp.json()] == [str(artifact_id)]


async def test_org_list_artifacts_denied_for_plain_member(client, org_with_plain_member_and_framework):
    """A member without the contributor grant cannot list org Framework artifacts."""
    org, framework_id, member_token = org_with_plain_member_and_framework
    resp = await client.get(
        f"/v1/orgs/{org.id}/frameworks/{framework_id}/artifacts",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp.status_code == 403
```

- [ ] **Step 6: Run it, verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_org_frameworks.py -k org_list_artifacts -v`
Expected: FAIL — 404 (route missing).

- [ ] **Step 7: Implement the endpoint**

In `backend/app/modules/frameworks/router.py`, add to `org_router` (near the other org artifact endpoints):

```python
@org_router.get(
    "/{framework_id}/artifacts",
    response_model=list[ArtifactResponse],
    summary="List organization Framework artifacts",
    description=(
        "List current Artifacts attached to an organization-owned Framework for "
        "an organization member holding the contributor capability grant."
    ),
)
async def list_org_framework_artifacts(
    org_id: UUID,
    framework_id: UUID,
    context: OrgContributorContext,
    db: DatabaseSession,
) -> list[ArtifactResponse]:
    """List Artifacts for one organization-owned Framework."""
    del org_id
    return await service.list_artifacts_for_owner(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
    )
```

> Confirm `ArtifactResponse` is imported in the router (used by personal artifact endpoints).

- [ ] **Step 8: Run endpoint tests, verify pass**

Run: `cd backend && uv run pytest tests/integration/test_org_frameworks.py -k org_list_artifacts -v`
Expected: PASS.

- [ ] **Step 9: Update OpenAPI**

In `contracts/openapi.yaml`, add `GET /v1/orgs/{org_id}/frameworks/{framework_id}/artifacts` mirroring the personal `GET /v1/frameworks/{framework_id}/artifacts` operation: `ArtifactResponse` array response, `org_id` + `framework_id` path params, 403 response, stable `operationId: list_org_framework_artifacts`.

- [ ] **Step 10: Lint/type + commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/frameworks/service.py backend/app/modules/frameworks/router.py contracts/openapi.yaml backend/tests/unit/modules/test_frameworks_service.py backend/tests/integration/test_org_frameworks.py
git commit -m "Add org framework list-artifacts endpoint"
```

---

## Task 3: Backend — org relist endpoint

Org has publish + unpublish but no relist; org `publish` requires `pipeline_passed`, so a delisted org Framework cannot return to the catalog. Add an owner-aware relist (admin/owner — relisting is a commercial act, matching publish/unpublish).

**Files:**
- Modify: `backend/app/modules/frameworks/service.py`
- Modify: `backend/app/modules/frameworks/router.py`
- Modify: `contracts/openapi.yaml`
- Test: `backend/tests/unit/modules/test_frameworks_service.py` (add)
- Test: `backend/tests/integration/test_org_frameworks.py` (add)

**Interfaces:**
- Consumes: `FrameworkOwner`, `_load_owned_framework_by_owner`, `current_artifacts_block_publish`, `current_artifact_file_missing`, `index_framework_artifacts`, `framework_to_response`, `write_audit` (service.py); `_org_owner`, `OrgAdminContext` (router.py).
- Produces: `relist_framework_for_owner(db, owner: FrameworkOwner, framework_id: UUID) -> FrameworkResponse`; endpoint `POST /v1/orgs/{org_id}/frameworks/{framework_id}/relist` → `FrameworkResponse`. Record the generated SDK fn name after Task 5.

- [ ] **Step 1: Write the failing service test**

In `backend/tests/unit/modules/test_frameworks_service.py`:

```python
async def test_relist_framework_for_owner_republishes_delisted_org_framework(db, org_delisted_framework):
    """relist_framework_for_owner flips a delisted org Framework back to published."""
    from app.modules.frameworks import service
    from app.modules.frameworks.ownership import FrameworkOwner

    framework, org_id, member_id = org_delisted_framework  # status == "unpublished", clean artifacts
    owner = FrameworkOwner(
        actor_id=member_id, user_id=None, org_id=org_id,
        authoring_member_id=member_id, can_manage_live_state=True,
    )
    result = await service.relist_framework_for_owner(db=db, owner=owner, framework_id=framework.id)
    assert result.status == "published"
```

> `org_delisted_framework`: an org-owned Framework at status `unpublished` with a current, clean artifact (mirror the setup used by the personal relist test in `test_frameworks_service.py`, but org-owned).

- [ ] **Step 2: Run it, verify it fails**

Run: `cd backend && uv run pytest tests/unit/modules/test_frameworks_service.py -k relist_framework_for_owner -v`
Expected: FAIL — attribute missing.

- [ ] **Step 3: Implement the owner-aware service function + delegate personal**

In `backend/app/modules/frameworks/service.py`, add `relist_framework_for_owner` (owner-aware copy of `relist_framework`, using `_load_owned_framework_by_owner` and `owner.actor_id` for audit/log):

```python
async def relist_framework_for_owner(
    db: AsyncSession,
    owner: FrameworkOwner,
    framework_id: UUID,
) -> FrameworkResponse:
    """Return an owned, delisted Framework to the public catalog (owner-aware).

    Owner-aware counterpart to :func:`relist_framework`. Same trust re-checks
    (PII/virus drift, missing storage) before flipping ``unpublished`` back to
    ``published``; resolves ownership through :class:`FrameworkOwner`.
    """
    framework = await _load_owned_framework_by_owner(db, owner, framework_id)
    if framework.status == "published":
        return framework_to_response(framework)
    if framework.status != "unpublished":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only unpublished Frameworks can be relisted.",
        )
    if await current_artifacts_block_publish(db, framework.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This framework can't be relisted because an artifact failed a "
                "trust check (virus or PII). Start a new version to resolve it."
            ),
        )
    if await current_artifact_file_missing(db, framework.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An artifact file is no longer available in storage. "
                "Re-upload the affected artifact in a new version to relist."
            ),
        )

    framework.status = "published"
    framework.published_at = datetime.now(UTC)
    await write_audit(
        db=db,
        actor_id=owner.actor_id,
        action="framework_relisted",
        target_type="framework",
        target_id=framework.id,
        metadata={"version": framework.version, "org_id": str(owner.org_id) if owner.org_id else None},
    )
    await db.commit()
    try:
        await index_framework_artifacts(framework.id)
    except Exception as exc:
        logger.bind(
            module="frameworks",
            action="index_framework_artifacts",
            user_id=owner.actor_id,
            framework_id=framework.id,
        ).error("artifact_lsh_index_failed", error=str(exc))
    await db.refresh(framework)
    logger.bind(
        module="frameworks",
        action="relist_framework",
        user_id=owner.actor_id,
        framework_id=framework.id,
    ).info("framework_relisted")
    return framework_to_response(framework)
```

> DRY option: after this passes, you MAY refactor the personal `relist_framework(db, contributor, framework_id)` to delegate — build a self `FrameworkOwner(actor_id=contributor.id, user_id=contributor.id, org_id=None, authoring_member_id=None, can_manage_live_state=True)` and call `relist_framework_for_owner`. Only do this if the existing personal relist tests stay green (behavior is identical — `owner.actor_id == contributor.id`). If any personal test asserts on internals that differ, leave `relist_framework` as-is.

- [ ] **Step 4: Run the service test, verify pass**

Run: `cd backend && uv run pytest tests/unit/modules/test_frameworks_service.py -k "relist_framework_for_owner or relist" -v`
Expected: PASS (new test + existing personal relist tests still green).

- [ ] **Step 5: Write the failing endpoint test**

In `backend/tests/integration/test_org_frameworks.py`:

```python
async def test_org_relist_endpoint_admin(client, org_delisted_framework_and_admin_token):
    """An org admin can relist a delisted org Framework."""
    org, framework_id, admin_token = org_delisted_framework_and_admin_token
    resp = await client.post(
        f"/v1/orgs/{org.id}/frameworks/{framework_id}/relist",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "published"


async def test_org_relist_denied_for_non_admin(client, org_delisted_framework_and_member_token):
    """A non-admin member cannot relist an org Framework."""
    org, framework_id, member_token = org_delisted_framework_and_member_token
    resp = await client.post(
        f"/v1/orgs/{org.id}/frameworks/{framework_id}/relist",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp.status_code == 403
```

- [ ] **Step 6: Run it, verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_org_frameworks.py -k org_relist -v`
Expected: FAIL — 404 (route missing).

- [ ] **Step 7: Implement the endpoint**

In `backend/app/modules/frameworks/router.py`, add to `org_router` (near org publish/unpublish):

```python
@org_router.post(
    "/{framework_id}/relist",
    response_model=FrameworkResponse,
    summary="Relist organization Framework",
    description=(
        "Return a delisted organization-owned Framework to the public catalog. "
        "Requires org admin/owner access and an active contributor capability."
    ),
)
async def relist_org_framework(
    org_id: UUID,
    framework_id: UUID,
    context: OrgAdminContext,
    _: Annotated[None, Depends(require_org_capability("contributor"))],
    db: DatabaseSession,
) -> FrameworkResponse:
    """Relist one delisted organization-owned Framework."""
    del org_id
    return await service.relist_framework_for_owner(
        db=db,
        owner=_org_owner(context),
        framework_id=framework_id,
    )
```

> Mirrors the org publish/unpublish endpoints, which pair `OrgAdminContext` with `require_org_capability("contributor")`. Match whichever pattern the existing `unpublish_org_framework` uses (if it does not also gate the capability, drop the `_` dependency to stay consistent).

- [ ] **Step 8: Run endpoint tests, verify pass**

Run: `cd backend && uv run pytest tests/integration/test_org_frameworks.py -k org_relist -v`
Expected: PASS.

- [ ] **Step 9: Update OpenAPI**

In `contracts/openapi.yaml`, add `POST /v1/orgs/{org_id}/frameworks/{framework_id}/relist` mirroring the personal `POST /v1/frameworks/{framework_id}/relist`: `FrameworkResponse` response, both path params, 403/409 responses, stable `operationId: relist_org_framework`.

- [ ] **Step 10: Lint/type + commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/frameworks/service.py backend/app/modules/frameworks/router.py contracts/openapi.yaml backend/tests/unit/modules/test_frameworks_service.py backend/tests/integration/test_org_frameworks.py
git commit -m "Add org framework relist endpoint"
```

---

## Task 4: Backend — caller-scoped `grants` on `MyOrganizationResponse`

**Files:**
- Modify: `backend/app/modules/organizations/schemas.py`
- Modify: `backend/app/modules/organizations/service.py`
- Modify: `backend/app/modules/organizations/router.py`
- Modify: `contracts/openapi.yaml`
- Test: `backend/tests/integration/test_organizations.py` (add — use the org endpoints integration file if named differently)

**Interfaces:**
- Consumes: `OrgTeam`, `OrgTeamMember`, `OrgTeamCapability`, `OrgCapability`, `OrgMember`, `defaultdict`.
- Produces: `caller_capability_grants(db, *, user_id: UUID, org_ids: list[UUID]) -> dict[UUID, set[str]]`; `MyOrganizationResponse.grants: dict[str, bool]`.

- [ ] **Step 1: Write the failing endpoint tests**

```python
async def test_my_orgs_grants_owner(client, org_owner_with_contributor_capability):
    """An owner's my-orgs entry reports the contributor grant as true."""
    org, owner_token = org_owner_with_contributor_capability
    resp = await client.get("/v1/orgs/mine", headers={"Authorization": f"Bearer {owner_token}"})
    entry = next(o for o in resp.json()["organizations"] if o["org"]["id"] == str(org.id))
    assert entry["grants"]["contributor"] is True


async def test_my_orgs_grants_plain_member_false(client, org_plain_member_with_contributor_capability):
    """A plain member (no contributor team) reports the contributor grant as false."""
    org, member_token = org_plain_member_with_contributor_capability
    resp = await client.get("/v1/orgs/mine", headers={"Authorization": f"Bearer {member_token}"})
    entry = next(o for o in resp.json()["organizations"] if o["org"]["id"] == str(org.id))
    assert entry["grants"].get("contributor", False) is False


async def test_my_orgs_grants_team_member_true(client, org_team_member_with_contributor_capability):
    """A member on a contributor-capability team reports the contributor grant true."""
    org, member_token = org_team_member_with_contributor_capability
    resp = await client.get("/v1/orgs/mine", headers={"Authorization": f"Bearer {member_token}"})
    entry = next(o for o in resp.json()["organizations"] if o["org"]["id"] == str(org.id))
    assert entry["grants"]["contributor"] is True
```

- [ ] **Step 2: Run it, verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_organizations.py -k my_orgs_grants -v`
Expected: FAIL — `KeyError: 'grants'`.

- [ ] **Step 3: Add the schema field**

In `backend/app/modules/organizations/schemas.py`, add to `MyOrganizationResponse`:

```python
    # True per capability when the CALLER personally holds that capability's
    # grant (owner/admin, or a member of a team with the capability enabled) AND
    # the org capability is active. Distinct from `capabilities`, the org-level
    # status regardless of caller.
    grants: dict[str, bool] = Field(default_factory=dict)
```

> Confirm `Field` is imported.

- [ ] **Step 4: Implement the service predicate**

In `backend/app/modules/organizations/service.py`:

```python
async def caller_capability_grants(
    db: AsyncSession,
    *,
    user_id: UUID,
    org_ids: list[UUID],
) -> dict[UUID, set[str]]:
    """Return, per org, the active capabilities the caller personally holds.

    A caller holds a capability grant in an org when the org capability is active
    and the caller is either owner/admin (holds every active capability) or a
    member of a team with that capability enabled.
    """
    if not org_ids:
        return {}

    grants: dict[UUID, set[str]] = {org_id: set() for org_id in org_ids}

    active_rows = await db.execute(
        select(OrgCapability.org_id, OrgCapability.capability).where(
            OrgCapability.org_id.in_(org_ids),
            OrgCapability.status == "active",
        )
    )
    active_by_org: dict[UUID, set[str]] = defaultdict(set)
    for org_id, capability in active_rows.all():
        active_by_org[org_id].add(capability)

    member_rows = await db.execute(
        select(OrgMember.org_id, OrgMember.id, OrgMember.role).where(
            OrgMember.user_id == user_id,
            OrgMember.org_id.in_(org_ids),
        )
    )
    memberships = {org_id: (mid, role) for org_id, mid, role in member_rows.all()}

    member_ids = [mid for mid, _role in memberships.values()]
    team_caps_by_member: dict[UUID, set[str]] = defaultdict(set)
    if member_ids:
        team_rows = await db.execute(
            select(OrgTeamMember.member_id, OrgTeamCapability.capability)
            .join(OrgTeam, OrgTeam.id == OrgTeamMember.team_id)
            .join(OrgTeamCapability, OrgTeamCapability.team_id == OrgTeam.id)
            .where(OrgTeamMember.member_id.in_(member_ids))
        )
        for mid, capability in team_rows.all():
            team_caps_by_member[mid].add(capability)

    for org_id in org_ids:
        membership = memberships.get(org_id)
        if membership is None:
            continue
        mid, role = membership
        active = active_by_org.get(org_id, set())
        if role in ("owner", "admin"):
            grants[org_id] = set(active)
        else:
            grants[org_id] = active & team_caps_by_member.get(mid, set())

    return grants
```

> Confirm `OrgTeam`, `OrgTeamMember`, `OrgTeamCapability`, `defaultdict` are imported in this module.

- [ ] **Step 5: Wire it into the router**

In `backend/app/modules/organizations/router.py` `list_my_organizations`, after `counts_by_org`:

```python
    org_ids = [organization.id for organization, _role, _caps in organizations]
    grants_by_org = await service.caller_capability_grants(
        db, user_id=user.id, org_ids=org_ids
    )
```

And in the `MyOrganizationResponse(...)` construction add:

```python
                grants={cap: True for cap in grants_by_org.get(organization.id, set())},
```

- [ ] **Step 6: Run the endpoint tests, verify pass**

Run: `cd backend && uv run pytest tests/integration/test_organizations.py -k my_orgs_grants -v`
Expected: PASS.

- [ ] **Step 7: Update OpenAPI**

In `contracts/openapi.yaml`, add `grants` to `MyOrganizationResponse`: `type: object, additionalProperties: {type: boolean}, default: {}`.

- [ ] **Step 8: Lint/type + commit**

```bash
cd backend && uv run ruff check . && uv run mypy app
git add backend/app/modules/organizations/schemas.py backend/app/modules/organizations/service.py backend/app/modules/organizations/router.py contracts/openapi.yaml backend/tests/integration/test_organizations.py
git commit -m "Expose caller-scoped capability grants on my-organizations"
```

---

## Task 5: Regenerate frontend API client

**Files:**
- Modify: `frontend/src/lib/generated/*` (generated)

- [ ] **Step 1: Regenerate**

Run: `cd frontend && npm run generate:api`

- [ ] **Step 2: Confirm the new symbols exist**

Run: `cd frontend && grep -oE "listOrgFrameworkArtifacts[A-Za-z0-9]*|relistOrgFramework[A-Za-z0-9]*|grants" src/lib/generated/sdk.gen.ts src/lib/generated/types.gen.ts | sort -u`
Expected: an org list-artifacts fn, an org relist fn, and `grants` on the `MyOrganizationResponse` type. Record the exact org list-artifacts and relist fn names — Task 6 uses them.

- [ ] **Step 3: Typecheck + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/lib/generated
git commit -m "Regenerate API client for org framework artifacts, relist, and grants"
```

---

## Task 6: Frontend — `FrameworkApi` adapter

**Files:**
- Create: `frontend/src/lib/frameworks/framework-api.ts`
- Test: `frontend/tests/unit/lib/framework-api.test.ts` (create; match the repo's vitest test location convention — check where other `src/lib` tests live and mirror it)

**Interfaces:**
- Consumes: generated SDK fns (personal + org variants), generated request/response types.
- Produces:
  - `type FrameworkSeller = { kind: "user" } | { kind: "org"; orgId: string }`
  - `interface FrameworkApi` with methods: `list`, `get(id)`, `create(body)`, `update(id, body)`, `updatePricing(id, body)`, `startVersion(id, body)`, `submit(id)`, `publish(id)`, `unpublish(id)`, `relist(id)`, `listArtifacts(id)`, `createArtifactUpload(id, body)`, `confirmArtifact(id, artifactId, body)`.
  - `function frameworkApiFor(seller: FrameworkSeller): FrameworkApi`

**Pricing/relist mapping (important — the two identities diverge):**
- `update` (metadata): personal → `updateFramework`; org → `updateOrgFramework` with the pricing key stripped (the org metadata endpoint takes `FrameworkMetadataUpdate`, no pricing).
- `updatePricing`: personal → `updateFramework({ pricing })` (personal has no separate pricing endpoint; pricing rides the metadata patch); org → `updateOrgFrameworkPricing({ pricing })`.
- `relist`: personal → `relistFramework`; org → the org relist fn from Task 5.

- [ ] **Step 1: Write the failing adapter tests**

Mock the generated SDK module; assert each method calls the right fn with the right shape. Use the exact generated fn names from Task 5.

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import * as sdk from "@/lib/generated/sdk.gen";
import { frameworkApiFor } from "@/lib/frameworks/framework-api";

vi.mock("@/lib/generated/sdk.gen");
beforeEach(() => vi.resetAllMocks());

describe("frameworkApiFor", () => {
  it("org create calls the org SDK fn with org_id in path", async () => {
    (sdk.createOrgFrameworkV1OrgsOrgIdFrameworksPost as any).mockResolvedValue({ data: { id: "f1" } });
    await frameworkApiFor({ kind: "org", orgId: "org-1" }).create({ title: "T" } as any);
    expect(sdk.createOrgFrameworkV1OrgsOrgIdFrameworksPost).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-1" }, body: { title: "T" } }),
    );
  });

  it("org updatePricing calls the org pricing endpoint", async () => {
    (sdk.updateOrgFrameworkPricingV1OrgsOrgIdFrameworksFrameworkIdPricingPatch as any).mockResolvedValue({ data: {} });
    await frameworkApiFor({ kind: "org", orgId: "o1" }).updatePricing("fw", { pricing: {} } as any);
    expect(sdk.updateOrgFrameworkPricingV1OrgsOrgIdFrameworksFrameworkIdPricingPatch).toHaveBeenCalled();
  });

  it("personal updatePricing rides the personal metadata patch", async () => {
    (sdk.updateFrameworkV1FrameworksFrameworkIdPatch as any).mockResolvedValue({ data: {} });
    await frameworkApiFor({ kind: "user" }).updatePricing("fw", { pricing: {} } as any);
    expect(sdk.updateFrameworkV1FrameworksFrameworkIdPatch).toHaveBeenCalledWith(
      expect.objectContaining({ path: { framework_id: "fw" }, body: { pricing: {} } }),
    );
  });

  it("org relist calls the org relist fn with both path params", async () => {
    (sdk.relistOrgFrameworkV1OrgsOrgIdFrameworksFrameworkIdRelistPost as any).mockResolvedValue({ data: {} });
    await frameworkApiFor({ kind: "org", orgId: "o1" }).relist("fw");
    expect(sdk.relistOrgFrameworkV1OrgsOrgIdFrameworksFrameworkIdRelistPost).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "o1", framework_id: "fw" } }),
    );
  });
});
```

- [ ] **Step 2: Run it, verify it fails**

Run: `cd frontend && npx vitest run tests/unit/lib/framework-api.test.ts`
Expected: FAIL — module/`frameworkApiFor` undefined.

- [ ] **Step 3: Implement the adapter**

Create `frontend/src/lib/frameworks/framework-api.ts`. Bind personal + org SDK fns; unwrap `.data`; match the repo's existing SDK result-handling convention (inspect `create-framework-panel.tsx`). Use the exact generated fn + type names from Task 5. Skeleton (replace every `/* … */` and any guessed name with the real generated symbol):

```ts
/**
 * Framework management API adapter.
 *
 * One identity-agnostic surface over the generated SDK. `frameworkApiFor`
 * returns a personal- or org-bound implementation so the same components drive
 * both the personal and organization Framework flows.
 */
import * as sdk from "@/lib/generated/sdk.gen";
import type {
  FrameworkResponse,
  ArtifactResponse,
  FrameworkCreate,
  FrameworkUpdate,
  // …import the exact body/response types used below
} from "@/lib/generated/types.gen";

export type FrameworkSeller = { kind: "user" } | { kind: "org"; orgId: string };

export interface FrameworkApi {
  list(): Promise</* list response type */ unknown>;
  get(id: string): Promise<FrameworkResponse>;
  create(body: FrameworkCreate): Promise<FrameworkResponse>;
  update(id: string, body: FrameworkUpdate): Promise<FrameworkResponse>;
  updatePricing(id: string, body: /* pricing body */ unknown): Promise<FrameworkResponse>;
  startVersion(id: string, body: /* version create */ unknown): Promise<FrameworkResponse>;
  submit(id: string): Promise<FrameworkResponse>;
  publish(id: string): Promise<FrameworkResponse>;
  unpublish(id: string): Promise<FrameworkResponse>;
  relist(id: string): Promise<FrameworkResponse>;
  listArtifacts(id: string): Promise<ArtifactResponse[]>;
  createArtifactUpload(id: string, body: /* upload request */ unknown): Promise</* upload response */ unknown>;
  confirmArtifact(id: string, artifactId: string, body: /* confirm body */ unknown): Promise<ArtifactResponse>;
}

async function unwrap<T>(p: Promise<{ data?: T; error?: unknown }>): Promise<T> {
  const { data, error } = await p;
  if (error || data === undefined) throw error ?? new Error("Request failed");
  return data as T;
}

function personalApi(): FrameworkApi {
  return {
    list: () => unwrap(sdk.listFrameworksV1FrameworksGet({})),
    get: (id) => unwrap(sdk.getFrameworkV1FrameworksFrameworkIdGet({ path: { framework_id: id } })),
    create: (body) => unwrap(sdk.createFrameworkV1FrameworksPost({ body })),
    update: (id, body) => unwrap(sdk.updateFrameworkV1FrameworksFrameworkIdPatch({ path: { framework_id: id }, body })),
    updatePricing: (id, body) => unwrap(sdk.updateFrameworkV1FrameworksFrameworkIdPatch({ path: { framework_id: id }, body })),
    startVersion: (id, body) => unwrap(sdk.createNewVersionV1FrameworksFrameworkIdVersionsPost({ path: { framework_id: id }, body })),
    submit: (id) => unwrap(sdk.submitFrameworkV1FrameworksFrameworkIdSubmitPost({ path: { framework_id: id } })),
    publish: (id) => unwrap(sdk.publishFrameworkV1FrameworksFrameworkIdPublishPost({ path: { framework_id: id } })),
    unpublish: (id) => unwrap(sdk.unpublishFrameworkV1FrameworksFrameworkIdUnpublishPost({ path: { framework_id: id } })),
    relist: (id) => unwrap(sdk.relistFrameworkV1FrameworksFrameworkIdRelistPost({ path: { framework_id: id } })),
    listArtifacts: (id) => unwrap(sdk.listArtifactsV1FrameworksFrameworkIdArtifactsGet({ path: { framework_id: id } })),
    createArtifactUpload: (id, body) => unwrap(sdk.requestArtifactUploadUrlV1FrameworksFrameworkIdArtifactsUploadUrlPost({ path: { framework_id: id }, body })),
    confirmArtifact: (id, artifactId, body) => unwrap(sdk.confirmArtifactUploadV1FrameworksFrameworkIdArtifactsConfirmPost({ path: { framework_id: id }, body })),
  };
}

function orgApi(orgId: string): FrameworkApi {
  const path = { org_id: orgId };
  return {
    list: () => unwrap(sdk.listOrgFrameworksV1OrgsOrgIdFrameworksGet({ path })),
    get: (id) => unwrap(sdk.getOrgFrameworkV1OrgsOrgIdFrameworksFrameworkIdGet({ path: { ...path, framework_id: id } })),
    create: (body) => unwrap(sdk.createOrgFrameworkV1OrgsOrgIdFrameworksPost({ path, body })),
    update: (id, body) => {
      const { pricing: _pricing, ...metadata } = (body ?? {}) as Record<string, unknown>;
      return unwrap(sdk.updateOrgFrameworkV1OrgsOrgIdFrameworksFrameworkIdPatch({ path: { ...path, framework_id: id }, body: metadata }));
    },
    updatePricing: (id, body) => unwrap(sdk.updateOrgFrameworkPricingV1OrgsOrgIdFrameworksFrameworkIdPricingPatch({ path: { ...path, framework_id: id }, body })),
    startVersion: (id, body) => unwrap(sdk.createNewOrgVersionV1OrgsOrgIdFrameworksFrameworkIdVersionPost({ path: { ...path, framework_id: id }, body })),
    submit: (id) => unwrap(sdk.submitOrgFrameworkV1OrgsOrgIdFrameworksFrameworkIdSubmitPost({ path: { ...path, framework_id: id } })),
    publish: (id) => unwrap(sdk.publishOrgFrameworkV1OrgsOrgIdFrameworksFrameworkIdPublishPost({ path: { ...path, framework_id: id } })),
    unpublish: (id) => unwrap(sdk.unpublishOrgFrameworkV1OrgsOrgIdFrameworksFrameworkIdUnpublishPost({ path: { ...path, framework_id: id } })),
    relist: (id) => unwrap(sdk.relistOrgFrameworkV1OrgsOrgIdFrameworksFrameworkIdRelistPost({ path: { ...path, framework_id: id } })),
    listArtifacts: (id) => unwrap(sdk.listOrgFrameworkArtifactsV1OrgsOrgIdFrameworksFrameworkIdArtifactsGet({ path: { ...path, framework_id: id } })),
    createArtifactUpload: (id, body) => unwrap(sdk.requestOrgArtifactUploadUrlV1OrgsOrgIdFrameworksFrameworkIdArtifactsUploadUrlPost({ path: { ...path, framework_id: id }, body })),
    confirmArtifact: (id, artifactId, body) => unwrap(sdk.confirmOrgArtifactUploadV1OrgsOrgIdFrameworksFrameworkIdArtifactsConfirmPost({ path: { ...path, framework_id: id }, body })),
  };
}

/** Return a personal- or org-bound FrameworkApi from a serializable descriptor. */
export function frameworkApiFor(seller: FrameworkSeller): FrameworkApi {
  return seller.kind === "org" ? orgApi(seller.orgId) : personalApi();
}
```

> If the generator names a fn differently than shown, use the generated name (verify each against `sdk.gen.ts`). The `confirmArtifact` `artifactId` arg is part of the interface for symmetry; if the generated confirm body already carries the artifact id, keep the arg but pass it inside `body` per the generated `…Data` type.

- [ ] **Step 4: Run adapter tests, verify pass**

Run: `cd frontend && npx vitest run tests/unit/lib/framework-api.test.ts`
Expected: PASS.

- [ ] **Step 5: Typecheck + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/lib/frameworks/framework-api.ts frontend/tests/unit/lib/framework-api.test.ts
git commit -m "Add FrameworkApi adapter for personal and org sellers"
```

---

## Task 7: Frontend — refactor list + create to the adapter

**Files:**
- Modify: `frontend/src/components/modules/frameworks/framework-list.tsx`
- Modify: `frontend/src/components/modules/frameworks/create-framework-panel.tsx`
- Modify: `frontend/src/app/(auth)/dashboard/frameworks/page.tsx`
- Modify: `frontend/src/app/(auth)/dashboard/frameworks/new/page.tsx`
- Test: existing component tests (keep green) + add a fake-adapter test.

**Interfaces:**
- Consumes: `FrameworkSeller`, `frameworkApiFor` (Task 6).
- Produces: `FrameworkList` and `CreateFrameworkPanel` each accept a required `seller: FrameworkSeller` prop and a `basePath: string` prop (row links / post-create navigation); each builds the adapter via `useMemo(() => frameworkApiFor(seller), [seller.kind, seller.kind === "org" ? seller.orgId : ""])`.

- [ ] **Step 1: Write the failing test (fake adapter)**

Mock `@/lib/frameworks/framework-api` so `frameworkApiFor` returns a fake with `list`/`create` spies. Assert `FrameworkList` renders rows from `api.list()` and `CreateFrameworkPanel` calls `api.create` on submit, driven with `seller={{kind:"user"}}`. Place alongside the existing tests for these components.

- [ ] **Step 2: Run it, verify it fails**

Run: `cd frontend && npx vitest run <new test path>`
Expected: FAIL — components don't accept `seller` / still import SDK directly.

- [ ] **Step 3: Refactor `framework-list.tsx`**

Add `seller: FrameworkSeller` and `basePath: string` props. Replace the direct SDK import/call with:

```tsx
import { frameworkApiFor, type FrameworkSeller } from "@/lib/frameworks/framework-api";
const api = useMemo(() => frameworkApiFor(seller), [seller.kind, seller.kind === "org" ? seller.orgId : ""]);
// replace listFrameworks... with `api.list()`; build row hrefs from `basePath`
```

Keep rendering/markup identical for personal.

- [ ] **Step 4: Refactor `create-framework-panel.tsx`**

Add `seller` + `basePath` props, build `api`, replace `createFramework...` with `api.create(body)`, and route to `${basePath}/${created.id}` on success (no hardcoded `/dashboard/frameworks`).

- [ ] **Step 5: Update personal pages**

`page.tsx`: `<FrameworkList seller={{ kind: "user" }} basePath="/dashboard/frameworks" />`.
`new/page.tsx`: `<CreateFrameworkPanel seller={{ kind: "user" }} basePath="/dashboard/frameworks" />`.

- [ ] **Step 6: Run all framework component tests, verify green**

Run: `cd frontend && npx vitest run src/components/modules/frameworks`
Expected: PASS — personal tests green + new fake-adapter test.

- [ ] **Step 7: Typecheck/lint + commit**

```bash
cd frontend && npx tsc --noEmit && npx eslint src/components/modules/frameworks "src/app/(auth)/dashboard/frameworks"
git add frontend/src/components/modules/frameworks/framework-list.tsx frontend/src/components/modules/frameworks/create-framework-panel.tsx "frontend/src/app/(auth)/dashboard/frameworks/page.tsx" "frontend/src/app/(auth)/dashboard/frameworks/new/page.tsx" <test files>
git commit -m "Refactor framework list and create to the seller adapter"
```

---

## Task 8: Frontend — refactor editor, artifacts, and admin-gated controls

**Files:**
- Modify: `frontend/src/components/modules/frameworks/framework-editor.tsx`
- Modify: `frontend/src/components/modules/frameworks/framework-form.tsx` (pricing-inline flag)
- Modify: `frontend/src/components/modules/frameworks/artifact-uploader.tsx`
- Modify: `frontend/src/components/modules/frameworks/publish-button.tsx`
- Modify: `frontend/src/components/modules/frameworks/version-radios.tsx`
- Modify: `frontend/src/components/modules/frameworks/delist-button.tsx`
- Modify: `frontend/src/components/modules/frameworks/relist-button.tsx`
- Test: existing tests (green) + fake-adapter tests for editor + admin gating + pricing-inline.

**Interfaces:**
- Consumes: `FrameworkSeller`, `frameworkApiFor`, `FrameworkApi`.
- Produces: `FrameworkEditor` accepts `seller: FrameworkSeller`, `canManageLiveState: boolean`, `basePath: string`. It builds the adapter once and passes `api` to the sub-controls. Live-state controls (`PublishButton`, `VersionRadios`, `DelistButton`, `RelistButton`) render **only when `canManageLiveState`**. The metadata form (`framework-form`) takes `pricingInline: boolean` — `true` for personal (pricing edited in-form via `api.update`), `false` for org (pricing hidden from the metadata form). When `!pricingInline` AND `canManageLiveState`, the editor renders a separate pricing control calling `api.updatePricing`.

- [ ] **Step 1: Write the failing tests**

Behaviors: (a) editor drives calls through the adapter (submit → `api.submit`, artifacts → `api.listArtifacts`, metadata → `api.update`); (b) `canManageLiveState={false}` → publish/version/delist/relist NOT in DOM; `true` → present; (c) `pricingInline={false}` → the in-form pricing section is absent and a separate pricing control (calling `api.updatePricing`) is present when `canManageLiveState`. Drive with a fake adapter via the `frameworkApiFor` mock.

- [ ] **Step 2: Run, verify fail**

Run: `cd frontend && npx vitest run src/components/modules/frameworks/framework-editor`
Expected: FAIL — editor lacks the new props; controls/pricing render unconditionally.

- [ ] **Step 3: Refactor `framework-editor.tsx`**

- Add props `seller`, `canManageLiveState`, `basePath`.
- Build `const api = useMemo(() => frameworkApiFor(seller), [seller.kind, seller.kind === "org" ? seller.orgId : ""]);`
- Replace `listFrameworkArtifacts`, `submitFramework`, `updateFramework`, `createFrameworkVersion` calls with `api.listArtifacts(id)`, `api.submit(id)`, `api.update(id, body)`, `api.startVersion(id, body)`.
- Pass `pricingInline={seller.kind === "user"}` to `framework-form`.
- When `seller.kind === "org" && canManageLiveState`, render a pricing control that calls `api.updatePricing(id, { pricing })`.
- Wrap live-state controls in `{canManageLiveState && ( … )}` and pass `api` to `PublishButton`, `VersionRadios`, `DelistButton`, `RelistButton`, `ArtifactUploader`.

- [ ] **Step 4: Refactor the sub-controls + form**

- `publish-button.tsx` → `api.publish`; `delist-button.tsx` → `api.unpublish`; `relist-button.tsx` → `api.relist`; `version-radios.tsx` → `api.startVersion`; `artifact-uploader.tsx` → `api.createArtifactUpload` + `api.confirmArtifact`. Each takes an injected `api: FrameworkApi` prop instead of importing SDK fns.
- `framework-form.tsx` → add `pricingInline: boolean`; render the pricing fields only when true. Personal editor passes `true` (unchanged behavior); org passes `false`.

> Verify each button's current SDK fn and map it to the matching adapter method without changing observable behavior.

- [ ] **Step 5: Run editor + control tests, verify green**

Run: `cd frontend && npx vitest run src/components/modules/frameworks`
Expected: PASS.

- [ ] **Step 6: Update the personal editor page**

`frontend/src/app/(auth)/dashboard/frameworks/[id]/page.tsx`: `<FrameworkEditor seller={{ kind: "user" }} canManageLiveState basePath="/dashboard/frameworks" … />`.

- [ ] **Step 7: Typecheck/lint + commit**

```bash
cd frontend && npx tsc --noEmit && npx eslint src/components/modules/frameworks
git add frontend/src/components/modules/frameworks "frontend/src/app/(auth)/dashboard/frameworks/[id]/page.tsx" <test files>
git commit -m "Refactor framework editor and controls to the seller adapter with live-state and pricing gating"
```

---

## Task 9: Frontend — org framework routes

**Files:**
- Create: `frontend/src/app/(auth)/dashboard/organizations/[orgId]/frameworks/page.tsx`
- Create: `frontend/src/app/(auth)/dashboard/organizations/[orgId]/frameworks/new/page.tsx`
- Create: `frontend/src/app/(auth)/dashboard/organizations/[orgId]/frameworks/[id]/page.tsx`

**Interfaces:**
- Consumes: `FrameworkList`, `CreateFrameworkPanel`, `FrameworkEditor` with the props from Tasks 7–8; the org membership payload for admin resolution.

- [ ] **Step 1: Implement the list page**

```tsx
/** Organization Frameworks list (org contributor identity). */
import { FrameworkList } from "@/components/modules/frameworks/framework-list";

export default async function OrgFrameworksPage({ params }: { params: Promise<{ orgId: string }> }) {
  const { orgId } = await params;
  const basePath = `/dashboard/organizations/${orgId}/frameworks`;
  return (
    <div>
      <div className="mb-6">
        <h2 className="font-heading text-2xl font-bold text-foreground">Frameworks</h2>
        <p className="mt-1 text-sm text-foreground-muted">Frameworks published under this organization.</p>
      </div>
      <FrameworkList seller={{ kind: "org", orgId }} basePath={basePath} />
    </div>
  );
}
```

- [ ] **Step 2: Implement the create page**

Render `<CreateFrameworkPanel seller={{ kind: "org", orgId }} basePath={`/dashboard/organizations/${orgId}/frameworks`} />`.

- [ ] **Step 3: Implement the editor page with admin resolution**

Resolve the caller's role for this org (use the mechanism sibling org pages use — inspect the `[orgId]/operator` or `[orgId]/projects` pages for the established role-fetch pattern). Then:

```tsx
const canManageLiveState = role === "owner" || role === "admin";
const basePath = `/dashboard/organizations/${orgId}/frameworks`;
return <FrameworkEditor seller={{ kind: "org", orgId }} canManageLiveState={canManageLiveState} frameworkId={id} basePath={basePath} />;
```

- [ ] **Step 4: Manual smoke + 375px check**

Dev server: as an org admin, visit `/dashboard/organizations/<orgId>/frameworks`, create a draft, open it, confirm publish/version/pricing/relist controls appear; as a contributor-team plain member confirm those controls are hidden but create/edit/submit work. Verify layout at 375px.

- [ ] **Step 5: Typecheck/lint + commit**

```bash
cd frontend && npx tsc --noEmit && npx eslint "src/app/(auth)/dashboard/organizations"
git add "frontend/src/app/(auth)/dashboard/organizations/[orgId]/frameworks"
git commit -m "Add org framework routes rendering the shared components"
```

---

## Task 10: Frontend — nav tab + grant gating + empty state

**Files:**
- Modify: `frontend/src/components/modules/organizations/organization-shell.tsx`
- Modify: `frontend/src/components/modules/frameworks/framework-list.tsx` (403 empty state)
- Test: `frontend/src/components/modules/organizations/organization-shell.test.tsx`

**Interfaces:**
- Consumes: `myOrg.grants`, `myOrg.role`, `myOrg.capabilities`.

- [ ] **Step 1: Write the failing shell tests**

Add to `organization-shell.test.tsx`:
- contributor active + `grants.contributor === true` (plain member) → "Frameworks" tab present.
- contributor active + `grants.contributor` false/absent + non-admin → no "Frameworks" tab.
- admin + contributor active → "Frameworks" tab present.

- [ ] **Step 2: Run, verify fail**

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-shell.test.tsx`
Expected: FAIL — no Frameworks tab.

- [ ] **Step 3: Add the tab**

In `organization-shell.tsx`, after `contributorActive`:

```tsx
const contributorGrant = myOrg.grants?.["contributor"] === true;
```

Add the tab **outside** the `isAdmin` block (granted plain members must reach it), alongside the other capability tabs:

```tsx
if (contributorActive && (isAdmin || contributorGrant)) {
  tabs.push({ id: "frameworks", label: "Frameworks" });
}
```

- [ ] **Step 4: Add the 403 empty state**

In `framework-list.tsx` (and the editor's load path), when a call returns 403 with `capability_grant_required`, render (via the existing empty-state/error component the module already uses): "You need the Contributor right for this organization. Ask an admin to add you to a team with the Contributor capability." Do not surface a raw error.

- [ ] **Step 5: Run shell tests, verify pass**

Run: `cd frontend && npx vitest run src/components/modules/organizations/organization-shell.test.tsx`
Expected: PASS.

- [ ] **Step 6: Full frontend gate + commit**

```bash
cd frontend && npx tsc --noEmit && npx eslint . && npx vitest run
git add frontend/src/components/modules/organizations/organization-shell.tsx frontend/src/components/modules/frameworks
git commit -m "Add org Frameworks nav tab gated on contributor grant"
```

---

## Final verification

- [ ] Backend: `cd backend && uv run pytest tests/unit/modules/test_org_capability_grant_dependency.py tests/unit/modules/test_frameworks_service.py tests/integration/test_org_frameworks.py -v` all pass; `uv run ruff check . && uv run mypy app` clean.
- [ ] Frontend: `cd frontend && npx vitest run && npx tsc --noEmit && npx eslint .` clean.
- [ ] Personal framework flows unchanged (personal component + relist tests green throughout).
- [ ] Manual: admin creates+publishes an org framework, delists, relists; contributor-team plain member creates+submits but sees no publish/pricing/version/relist controls; plain non-team member sees no Frameworks tab and a 403 empty-state on deep link.
- [ ] All commits on `main`, no `Co-Authored-By` trailer.

## Notes / out of scope (do not build)

- Org framework analytics (reviews) page.
- Operator tab visibility for team-granted operators (separate 15b nav gap).
- Connector import/sync UI for org artifacts — include only if it comes free with the component extraction; otherwise defer.
