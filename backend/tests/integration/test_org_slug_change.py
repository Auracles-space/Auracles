"""Integration tests for organization slug changes (Decision 5).

Covers ``slug_service.change_org_slug`` and ``slug_service.resolve_public_slug``
against the real database, plus the ``org_slug_history`` migration round trip.
Spec: docs/superpowers/specs/2026-09-14-organizations-end-to-end-design.md
§Slug change.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import create_engine, inspect, select, text, update
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.modules.auth.models import User
from app.modules.organizations import service as org_service
from app.modules.organizations import slug_service
from app.modules.organizations.models import Organization, OrgSlugHistory
from app.modules.organizations.schemas import (
    OrganizationCreateRequest,
    OrgSlugChangeRequest,
)
from app.shared.models.audit_log import AuditLog
from tests.integration.test_org_admin_endpoints import record_owner_notifications
from tests.integration.test_organizations_endpoints import (
    add_member,
    clean_orgs,
    create_org,
    create_user,
    migrated_database,
)

pytestmark = pytest.mark.asyncio

__all__ = ["clean_orgs", "migrated_database"]

PRIOR_HEAD = "2026_09_14_0105"


async def _owned_org(client: AsyncClient, prefix: str) -> tuple[UUID, UUID, str]:
    """Create an org through the API; return (owner_id, org_id, slug)."""
    owner_id = await create_user(f"{prefix}-owner")
    org = await create_org(client, create_access_token(owner_id, []), prefix)
    return owner_id, UUID(str(org["id"])), str(org["slug"])


async def _change(org_id: UUID, actor: UUID, new_slug: str) -> Organization:
    """Run ``change_org_slug`` in a fresh session."""
    async with async_session_factory() as session:
        return await slug_service.change_org_slug(
            session, org_id=org_id, actor_user_id=actor, new_slug=new_slug
        )


async def _expect_error(org_id: UUID, actor: UUID, new_slug: str) -> HTTPException:
    """Run ``change_org_slug`` expecting an HTTPException and return it."""
    with pytest.raises(HTTPException) as caught:
        await _change(org_id, actor, new_slug)
    return caught.value


async def _history(org_id: UUID) -> list[str]:
    """Return the slugs recorded in history for ``org_id``."""
    async with async_session_factory() as session:
        rows = await session.scalars(
            select(OrgSlugHistory.slug).where(OrgSlugHistory.org_id == org_id)
        )
        return sorted(rows.all())


def _fresh_slug(prefix: str) -> str:
    """Return a unique valid slug."""
    return f"{prefix}-{uuid4().hex[:6]}"


async def test_owner_changes_slug_records_history_and_audit(
    client: AsyncClient,
    clean_orgs: None,
    migrated_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An owner's change moves the old slug to history and audits {from, to}.

    The acting owner is never notified about their own change.
    """
    recorder = record_owner_notifications(monkeypatch)
    owner_id, org_id, old_slug = await _owned_org(client, "renameorg")
    new_slug = _fresh_slug("renamed")

    org = await _change(org_id, owner_id, new_slug)

    assert org.slug == new_slug
    assert await _history(org_id) == [old_slug]
    async with async_session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.action == "org_slug_changed", AuditLog.target_id == org_id
            )
        )
    assert audit is not None
    assert audit.actor_id == owner_id
    assert audit.metadata_ == {"from": old_slug, "to": new_slug}
    assert [
        c for c in recorder.sent if c["notification_type"] == "org_slug_changed"
    ] == []


async def test_slug_change_notifies_other_owners_not_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every owner except the actor hears the new address and the redirect.

    The schema currently allows one owner per org, so the recipient rule is
    exercised on the notifier directly with a second owner id.
    """
    recorder = record_owner_notifications(monkeypatch)
    actor, other, org_id = uuid4(), uuid4(), uuid4()

    slug_service.notify_org_slug_changed(
        [actor, other],
        actor_user_id=actor,
        org_id=org_id,
        old_slug="old-name",
        new_slug="new-name",
    )

    assert [c["user_id"] for c in recorder.sent] == [str(other)]
    sent = recorder.sent[0]
    assert sent["notification_type"] == "org_slug_changed"
    assert sent["title"] == "Public profile address changed"
    assert "/orgs/new-name" in str(sent["body"])
    assert "/orgs/old-name" in str(sent["body"])
    assert "redirect" in str(sent["body"])
    assert sent["link"] == f"/dashboard/organizations/{org_id}"


async def test_non_owner_admin_is_forbidden(
    client: AsyncClient, clean_orgs: None, migrated_database: None
) -> None:
    """An org admin who is not an owner cannot change the slug (403)."""
    _owner_id, org_id, slug = await _owned_org(client, "adminorg")
    admin_id = await create_user("org-admin")
    await add_member(str(org_id), admin_id, "admin")

    error = await _expect_error(org_id, admin_id, _fresh_slug("hijack"))

    assert error.status_code == 403
    assert await _history(org_id) == []
    async with async_session_factory() as session:
        assert (
            await session.scalar(
                select(Organization.slug).where(Organization.id == org_id)
            )
            == slug
        )


async def test_unknown_deactivated_and_suspended_orgs_are_refused(
    client: AsyncClient, clean_orgs: None, migrated_database: None
) -> None:
    """Unknown or closed orgs are 404; a suspended org is 409."""
    owner_id, org_id, _slug = await _owned_org(client, "stateorg")

    assert (await _expect_error(uuid4(), owner_id, _fresh_slug("x"))).status_code == 404

    async with async_session_factory() as session, session.begin():
        await session.execute(
            update(Organization)
            .where(Organization.id == org_id)
            .values(suspended_at=datetime.now(UTC))
        )
    suspended = await _expect_error(org_id, owner_id, _fresh_slug("x"))
    assert suspended.status_code == 409
    assert suspended.detail == "A suspended organization cannot change its slug."

    async with async_session_factory() as session, session.begin():
        await session.execute(
            update(Organization)
            .where(Organization.id == org_id)
            .values(suspended_at=None, deactivated_at=datetime.now(UTC))
        )
    assert (await _expect_error(org_id, owner_id, _fresh_slug("x"))).status_code == 404


async def test_unchanged_slug_is_422(
    client: AsyncClient, clean_orgs: None, migrated_database: None
) -> None:
    """Submitting the current slug is a validation error, not a no-op write."""
    owner_id, org_id, slug = await _owned_org(client, "sameorg")

    error = await _expect_error(org_id, owner_id, slug)

    assert error.status_code == 422
    assert error.detail == "That is already this organization's slug."


async def test_slug_taken_by_another_org_is_409(
    client: AsyncClient, clean_orgs: None, migrated_database: None
) -> None:
    """Another organization's current slug cannot be taken."""
    owner_id, org_id, _slug = await _owned_org(client, "firstorg")
    _other_owner, _other_org, other_slug = await _owned_org(client, "secondorg")

    error = await _expect_error(org_id, owner_id, other_slug)

    assert error.status_code == 409
    assert error.detail == "That slug is taken."


async def test_slug_in_another_orgs_history_is_409(
    client: AsyncClient, clean_orgs: None, migrated_database: None
) -> None:
    """A slug another org used before stays reserved to that org."""
    owner_a, org_a, old_a = await _owned_org(client, "reservedorg")
    owner_b, org_b, _old_b = await _owned_org(client, "claimerorg")
    await _change(org_a, owner_a, _fresh_slug("moved"))

    error = await _expect_error(org_b, owner_b, old_a)

    assert error.status_code == 409
    assert error.detail == "That slug is taken."


async def test_owner_reclaims_own_old_slug(
    client: AsyncClient, clean_orgs: None, migrated_database: None
) -> None:
    """Moving back to an org's own previous slug succeeds and frees that row."""
    owner_id, org_id, original = await _owned_org(client, "reclaimorg")
    interim = _fresh_slug("interim")
    await _change(org_id, owner_id, interim)

    org = await _change(org_id, owner_id, original)

    assert org.slug == original
    assert await _history(org_id) == [interim]


async def test_resolve_public_slug(
    client: AsyncClient, clean_orgs: None, migrated_database: None
) -> None:
    """Current and historical slugs resolve to the canonical slug.

    Unknown slugs and suspended organizations resolve to None.
    """
    owner_id, org_id, old_slug = await _owned_org(client, "resolveorg")
    new_slug = _fresh_slug("resolved")
    await _change(org_id, owner_id, new_slug)

    async with async_session_factory() as session:
        current = await slug_service.resolve_public_slug(session, new_slug)
        historical = await slug_service.resolve_public_slug(session, old_slug)
        unknown = await slug_service.resolve_public_slug(session, _fresh_slug("nope"))
    assert current is not None and historical is not None
    assert current[0].id == org_id and current[1] == new_slug
    assert historical[0].id == org_id and historical[1] == new_slug
    assert unknown is None

    async with async_session_factory() as session, session.begin():
        await session.execute(
            update(Organization)
            .where(Organization.id == org_id)
            .values(suspended_at=datetime.now(UTC))
        )
    async with async_session_factory() as session:
        assert await slug_service.resolve_public_slug(session, new_slug) is None
        assert await slug_service.resolve_public_slug(session, old_slug) is None


async def test_slug_change_request_matches_creation_rules() -> None:
    """The change schema normalizes and bounds slugs like org creation does."""
    assert OrgSlugChangeRequest(slug="Acme-Labs").slug == "acme-labs"
    for bad in ("ab", "a" * 81, "acme labs", "acme_labs", " acme-labs "):
        with pytest.raises(ValueError):
            OrgSlugChangeRequest(slug=bad)


async def test_migration_downgrade_purges_label_and_upgrade_restores(
    clean_orgs: None,
) -> None:
    """Downgrade drops the table and purges label rows; upgrade restores it."""
    user_id = await create_user("slug-migration")
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")
    command.upgrade(alembic_config, "head")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO notifications (user_id, type, title, body) "
                    "VALUES (:user_id, 'org_slug_changed', 't', 'b')"
                ),
                {"user_id": user_id},
            )
        command.downgrade(alembic_config, PRIOR_HEAD)
        assert "org_slug_history" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            remaining = connection.scalar(
                text(
                    "SELECT count(*) FROM notifications "
                    "WHERE type::text = 'org_slug_changed'"
                )
            )
        assert remaining == 0
    finally:
        command.upgrade(alembic_config, "head")
    try:
        assert "org_slug_history" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            labels = connection.scalars(
                text("SELECT unnest(enum_range(NULL::notification_type_enum))::text")
            ).all()
        assert "org_slug_changed" in labels
    finally:
        engine.dispose()


async def _hold_slug_lock_then_reserve(
    slug: str, holder_org_id: UUID, release: asyncio.Event
) -> None:
    """Take the slug lock, reserve ``slug`` in history, commit on ``release``.

    Stands in for a concurrent slug change that has passed its check but not
    yet committed: its history row is invisible to other transactions.
    """
    async with async_session_factory() as session:
        async with session.begin():
            await slug_service.lock_slug(session, slug)
            session.add(OrgSlugHistory(org_id=holder_org_id, slug=slug))
            await session.flush()
            await release.wait()


async def _assert_waits_then_conflicts(
    slug: str, holder_org_id: UUID, contender: object
) -> None:
    """Run ``contender`` while the lock is held; it must wait, then 409."""
    release = asyncio.Event()
    holder = asyncio.create_task(
        _hold_slug_lock_then_reserve(slug, holder_org_id, release)
    )
    await asyncio.sleep(0.2)
    contender_task = asyncio.ensure_future(contender)  # type: ignore[arg-type]
    await asyncio.sleep(0.3)
    assert not contender_task.done(), "contender did not wait for the slug lock"

    release.set()
    await holder
    with pytest.raises(HTTPException) as caught:
        await contender_task
    assert caught.value.status_code == 409


async def test_lock_slug_blocks_a_second_transaction_on_the_same_slug(
    clean_orgs: None, migrated_database: None
) -> None:
    """A held slug lock blocks another transaction on the same normalized slug.

    ``lock_timeout`` turns the wait into an observable error; a different slug
    is not blocked, and case/whitespace variants share one key.
    """
    slug = _fresh_slug("locked")
    async with async_session_factory() as holder:
        async with holder.begin():
            await slug_service.lock_slug(holder, slug)

            async with async_session_factory() as contender:
                async with contender.begin():
                    await contender.execute(text("SET LOCAL lock_timeout = '200ms'"))
                    await slug_service.lock_slug(contender, _fresh_slug("other"))
                    with pytest.raises(DBAPIError):
                        await slug_service.lock_slug(contender, f"  {slug.upper()} ")


async def test_create_org_waits_for_a_concurrent_slug_claim(
    client: AsyncClient, clean_orgs: None, migrated_database: None
) -> None:
    """Organization creation serializes on the slug lock (Decision 5 race).

    Without the lock, creation would read history before the concurrent
    change commits and claim the same slug. With it, creation waits for the
    holder to commit, then sees the reserved slug and returns 409.
    """
    _owner, holder_org_id, _ = await _owned_org(client, "holderorg")
    creator_id = await create_user("racecreator")
    async with async_session_factory() as session:
        creator = await session.get(User, creator_id)
    assert creator is not None
    slug = _fresh_slug("contested")

    async def create() -> None:
        async with async_session_factory() as session:
            await org_service.create_organization(
                db=session,
                user=creator,
                payload=OrganizationCreateRequest(
                    slug=slug, name="Race Creator", country="NG"
                ),
            )

    await _assert_waits_then_conflicts(slug, holder_org_id, create())


async def test_change_org_slug_waits_for_a_concurrent_slug_claim(
    client: AsyncClient, clean_orgs: None, migrated_database: None
) -> None:
    """Slug changes serialize on the lock for the NEW slug (Decision 5 race).

    Without the lock, the change would read history before the concurrent
    claim commits and take the same slug. With it, the change waits, then
    sees the reserved slug and returns 409.
    """
    _holder_owner, holder_org_id, _ = await _owned_org(client, "holdertwo")
    owner_id, org_id, _ = await _owned_org(client, "changer")
    slug = _fresh_slug("contested")

    await _assert_waits_then_conflicts(
        slug, holder_org_id, _change(org_id, owner_id, slug)
    )
