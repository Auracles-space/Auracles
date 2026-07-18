"""Unit tests for organization-scoped Framework service behavior."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.frameworks import service
from app.modules.frameworks.models import Framework, FrameworkVersion, Review
from app.modules.frameworks.models_artifact import Artifact
from app.modules.frameworks.ownership import FrameworkOwner
from app.modules.frameworks.schemas import FrameworkCreate
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for org framework service tests."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        command.upgrade(alembic_config, "head")
        sync_engine.dispose()


@pytest.fixture
async def org_framework_state() -> AsyncIterator[None]:
    """Reset framework and organization rows around each unit test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete framework rows before clearing shared identity state."""
        async with async_session_factory() as session:
            await session.execute(delete(Review))
            await session.execute(delete(Artifact))
            await session.execute(delete(FrameworkVersion))
            await session.execute(delete(Framework))
            await session.execute(delete(AuditLog))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await clear_identity_state_async(session)
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()
        await engine.dispose()


async def _create_user(prefix: str) -> User:
    """Create and return one verified user for org framework tests."""
    email = f"{prefix}-{uuid4().hex[:8]}@auracles.space"
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status="verified",
            )
            session.add(user)
            await session.flush()
            await session.refresh(user)
            return user


async def _create_org_member(user: User, *, role: str = "member") -> tuple[UUID, UUID]:
    """Create an organization membership row and return org/member ids."""
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"org-{uuid4().hex[:8]}",
                name="Org Framework Test Org",
                country="GB",
                created_by=user.id,
            )
            session.add(org)
            await session.flush()
            member = OrgMember(org_id=org.id, user_id=user.id, role=role)
            session.add(member)
            await session.flush()
            return org.id, member.id


async def _set_contributor_capability(org_id: UUID, *, status: str) -> None:
    """Persist one contributor capability row for an organization."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(
                    org_id=org_id,
                    capability="contributor",
                    status=status,
                )
            )


async def _create_framework(
    *,
    contributor_id: UUID | None,
    contributor_org_id: UUID | None,
    authoring_member_id: UUID | None,
    status: str = "draft",
) -> Framework:
    """Create and return one Framework row for org service tests."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                contributor_org_id=contributor_org_id,
                authoring_member_id=authoring_member_id,
                title="Owned Framework",
                description="A framework row for ownership tests.",
                category="framework",
                sector="financial_services",
                industry="fund_management",
                business_function="risk_management",
                tags=["ownership"],
                tags_text="ownership",
                jurisdiction="GB",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price="499.00",
                currency="USD",
                license_types=["single_user"],
                commercial_rights="Internal commercial use allowed.",
                usage_restrictions="No resale.",
                status=status,
            )
            session.add(framework)
            await session.flush()
            await session.refresh(framework)
            return framework


async def _create_artifact(framework_id: UUID) -> Artifact:
    """Create one current artifact for a Framework."""
    async with async_session_factory() as session:
        async with session.begin():
            artifact = Artifact(
                framework_id=framework_id,
                name="artifact.pdf",
                file_key=f"frameworks/{framework_id}/artifact.pdf",
                file_size=2048,
                mime_type="application/pdf",
                scan_status="clean",
                processing_status="processed",
                pii_detected=False,
                pii_review_needed=False,
                current_for_framework=True,
            )
            session.add(artifact)
            await session.flush()
            await session.refresh(artifact)
            return artifact


def _framework_payload() -> FrameworkCreate:
    """Return a valid Framework create payload for service tests."""
    return FrameworkCreate.model_validate(
        {
            "title": "Org Authored Framework",
            "description": "A contributor framework authored under an org.",
            "category": "framework",
            "sector": "financial_services",
            "industry": "fund_management",
            "function": "risk_management",
            "tags": ["org", "governance"],
            "jurisdiction": "GB",
            "complexity": 3,
            "org_size": "mid_market",
            "lifecycle_stage": "scale",
            "pricing": {
                "price": "499.00",
                "currency": "USD",
                "license_types": ["single_user"],
                "commercial_rights": "Internal commercial use allowed.",
                "usage_restrictions": "No resale.",
            },
        }
    )


@pytest.mark.asyncio
async def test_org_create_stamps_org_and_authoring_member(
    migrated_database: None,
    org_framework_state: None,
) -> None:
    """Creating a Framework for an org stamps org ownership and member provenance."""
    del migrated_database, org_framework_state
    author = await _create_user("org-framework-author")
    org_id, member_id = await _create_org_member(author)

    async with async_session_factory() as session:
        response = await service.create_framework(
            db=session,
            owner=FrameworkOwner(
                actor_id=author.id,
                user_id=None,
                org_id=org_id,
                authoring_member_id=member_id,
                can_manage_live_state=False,
            ),
            payload=_framework_payload(),
        )

    async with async_session_factory() as session:
        framework = await session.get(Framework, response.id)

    assert framework is not None
    assert framework.contributor_id is None
    assert framework.contributor_org_id == org_id
    assert framework.authoring_member_id == member_id


@pytest.mark.asyncio
async def test_list_artifacts_for_owner_returns_org_framework_artifacts(
    migrated_database: None,
    org_framework_state: None,
) -> None:
    """Owner-aware artifact listing returns current org Framework artifacts."""
    del migrated_database, org_framework_state
    author = await _create_user("org-artifact-list-author")
    org_id, member_id = await _create_org_member(author)
    framework = await _create_framework(
        contributor_id=None,
        contributor_org_id=org_id,
        authoring_member_id=member_id,
    )
    artifact = await _create_artifact(framework.id)

    async with async_session_factory() as session:
        artifacts = await service.list_artifacts_for_owner(
            db=session,
            owner=FrameworkOwner(
                actor_id=author.id,
                user_id=None,
                org_id=org_id,
                authoring_member_id=member_id,
                can_manage_live_state=True,
            ),
            framework_id=framework.id,
        )

    assert [response.id for response in artifacts] == [artifact.id]


@pytest.mark.asyncio
async def test_org_member_cannot_publish_org_framework(
    migrated_database: None,
    org_framework_state: None,
) -> None:
    """Publishing an org-owned Framework requires live-state permission."""
    del migrated_database, org_framework_state
    author = await _create_user("org-framework-member")
    org_id, member_id = await _create_org_member(author)
    framework = await _create_framework(
        contributor_id=None,
        contributor_org_id=org_id,
        authoring_member_id=member_id,
        status="pipeline_passed",
    )

    async with async_session_factory() as session:
        with pytest.raises(Exception) as exc_info:
            await service.publish_framework(
                db=session,
                owner=FrameworkOwner(
                    actor_id=author.id,
                    user_id=None,
                    org_id=org_id,
                    authoring_member_id=member_id,
                    can_manage_live_state=False,
                ),
                framework_id=framework.id,
            )

    assert getattr(exc_info.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_publish_rejects_suspended_contributor_capability(
    migrated_database: None,
    org_framework_state: None,
) -> None:
    """Publishing is blocked when the org contributor capability is not active."""
    del migrated_database, org_framework_state
    author = await _create_user("org-framework-admin")
    org_id, member_id = await _create_org_member(author, role="admin")
    await _set_contributor_capability(org_id, status="suspended")
    framework = await _create_framework(
        contributor_id=None,
        contributor_org_id=org_id,
        authoring_member_id=member_id,
        status="pipeline_passed",
    )

    async with async_session_factory() as session:
        with pytest.raises(Exception) as exc_info:
            await service.publish_framework(
                db=session,
                owner=FrameworkOwner(
                    actor_id=author.id,
                    user_id=None,
                    org_id=org_id,
                    authoring_member_id=member_id,
                    can_manage_live_state=True,
                ),
                framework_id=framework.id,
            )

    assert getattr(exc_info.value, "status_code", None) == 403
    assert getattr(exc_info.value, "detail", None) == {
        "error_code": "capability_suspended"
    }


@pytest.mark.asyncio
async def test_org_admin_can_publish_org_framework(
    migrated_database: None,
    org_framework_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An org admin with active capability can publish an org-owned Framework."""
    del migrated_database, org_framework_state
    author = await _create_user("org-framework-admin")
    org_id, member_id = await _create_org_member(author, role="admin")
    await _set_contributor_capability(org_id, status="active")
    framework = await _create_framework(
        contributor_id=None,
        contributor_org_id=org_id,
        authoring_member_id=member_id,
        status="pipeline_passed",
    )
    await _create_artifact(framework.id)

    async def _noop_pipeline(*args: object, **kwargs: object) -> None:
        return None

    async def _false_file_missing(*args: object, **kwargs: object) -> bool:
        return False

    async def _noop_snapshot(*args: object, **kwargs: object) -> None:
        return None

    async def _noop_index(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(service, "evaluate_framework_pipeline", _noop_pipeline)
    monkeypatch.setattr(service, "current_artifact_file_missing", _false_file_missing)
    monkeypatch.setattr(service, "_ensure_published_version_snapshot", _noop_snapshot)
    monkeypatch.setattr(service, "index_framework_artifacts", _noop_index)

    async with async_session_factory() as session:
        response = await service.publish_framework(
            db=session,
            owner=FrameworkOwner(
                actor_id=author.id,
                user_id=None,
                org_id=org_id,
                authoring_member_id=member_id,
                can_manage_live_state=True,
            ),
            framework_id=framework.id,
        )

    assert response.status == "published"
    async with async_session_factory() as session:
        published = await session.get(Framework, framework.id)

    assert published is not None
    assert published.status == "published"
