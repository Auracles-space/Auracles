"""Unit test: version bump folds artifact source binding forward.

`create_new_version` clones a non-inherited current Artifact into the new
draft version. Connector-bound artifacts (google_drive, etc.) must carry
their source columns into the clone, otherwise re-sync/re-bind breaks the
moment a Contributor bumps the Framework's version.

Maps to: Connectors Phase C, Task 7.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine
from app.modules.auth.models import User
from app.modules.frameworks import service
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from app.modules.frameworks.ownership import FrameworkOwner
from app.modules.frameworks.schemas import FrameworkVersionCreate
from app.modules.integrations.models import OAuthConnection
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


async def _cleanup_version_bump_rows() -> None:
    """Truncate the tables this suite touches, order-independently."""
    async with async_session_factory() as session:
        await session.execute(
            text(
                "TRUNCATE TABLE "
                f"{AuditLog.__tablename__}, {Artifact.__tablename__}, "
                f"{Framework.__tablename__}, {OAuthConnection.__tablename__}, "
                f"{User.__tablename__} RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()


@pytest.fixture
async def version_bump_ctx(
    migrated_database: None,
) -> AsyncIterator[tuple[AsyncSession, User, Framework, Artifact]]:
    """Seed a published Framework with one current google_drive Artifact."""
    await engine.dispose()
    await _cleanup_version_bump_rows()

    session = async_session_factory()
    contributor = User(
        email="version-bump-owner@auracles.space",
        display_name="Version Bump Owner",
        email_verified=True,
        password_hash=None,
    )
    framework = Framework(
        contributor_id=uuid4(),
        title="Versionable Framework",
        description="Published framework for version-bump source-binding tests.",
        category="framework",
        sector="financial_services",
        industry="fund_management",
        business_function="risk_management",
        tags=["versioning"],
        tags_text="versioning",
        jurisdiction="us",
        complexity=3,
        org_size="mid_market",
        lifecycle_stage="scale",
        price=Decimal("499.00"),
        currency="USD",
        license_types=["single_user"],
        commercial_rights="Internal commercial use allowed.",
        usage_restrictions="No resale.",
        status="published",
        version="1.0.0",
    )
    connection = OAuthConnection(
        user_id=uuid4(),
        provider="google_drive",
        scopes="https://www.googleapis.com/auth/drive.readonly",
        status="active",
    )
    artifact = Artifact(
        framework_id=uuid4(),
        name="brief.pdf",
        file_key="frameworks/fw/artifacts/art.pdf",
        file_size=13,
        mime_type="application/pdf",
        scan_status="clean",
        processing_status="processed",
        current_for_framework=True,
        content_sha256="ORIG-HASH",
        source_kind="google_drive",
        source_external_id="file-orig",
        source_connection_id=uuid4(),
        source_last_synced_at=datetime(2026, 7, 8, tzinfo=UTC),
        source_synced_revision="REV-ORIG",
    )

    async with session.begin():
        session.add(contributor)
        await session.flush()
        framework.contributor_id = contributor.id
        session.add(framework)
        await session.flush()
        connection.user_id = contributor.id
        session.add(connection)
        await session.flush()
        artifact.framework_id = framework.id
        artifact.source_connection_id = connection.id
        session.add(artifact)
        await session.flush()

    yield session, contributor, framework, artifact

    await session.close()
    await _cleanup_version_bump_rows()
    await engine.dispose()


async def test_version_bump_folds_source_binding_into_clone(
    monkeypatch: pytest.MonkeyPatch,
    version_bump_ctx: tuple[AsyncSession, User, Framework, Artifact],
) -> None:
    """The cloned current Artifact keeps the predecessor's source binding.

    Without folding the source columns forward, the clone reverts to the
    "upload" default and re-sync/re-bind silently breaks after a version
    bump.
    """
    db, contributor, framework, artifact = version_bump_ctx
    original_connection_id = artifact.source_connection_id

    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(s3_artifacts_bucket="bucket"),
    )
    monkeypatch.setattr(
        service.s3.storage, "copy_object", lambda *args, **kwargs: None
    )

    owner = FrameworkOwner(
        actor_id=contributor.id,
        user_id=contributor.id,
        org_id=None,
        authoring_member_id=None,
        can_manage_live_state=True,
    )
    payload = FrameworkVersionCreate(
        change_type="improvement",
        change_log="Refresh the sourced artifact.",
        artifact_inheritance={artifact.id: False},
    )

    await service.create_new_version(db, owner, framework.id, payload)

    new_clone = await db.scalar(
        select(Artifact).where(
            Artifact.framework_id == framework.id,
            Artifact.current_for_framework.is_(True),
        )
    )
    assert new_clone is not None
    assert new_clone.id != artifact.id
    assert new_clone.source_kind == "google_drive"
    assert new_clone.source_external_id == "file-orig"
    assert new_clone.source_connection_id == original_connection_id
    assert new_clone.source_synced_revision == "REV-ORIG"
    assert new_clone.content_sha256 == "ORIG-HASH"

    retired = await db.get(Artifact, UUID(str(artifact.id)))
    assert retired is not None
    assert retired.current_for_framework is False
