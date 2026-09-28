"""Integration tests for the admin Framework detail endpoint.

The moderation queue tells an admin that a Framework is held, but a held
Framework is not published, so it appears in no other admin surface. These
tests cover the read-only detail view that lets an admin judge the hold.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import (
    Artifact,
    ArtifactPiiAudit,
    ArtifactRarityAudit,
)
from app.shared.models.audit_log import AuditLog


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for the given user and roles."""
    return {
        "Authorization": f"Bearer {create_access_token(user_id=user_id, roles=roles)}"
    }


async def _create_user(
    session: AsyncSession,
    *,
    email: str,
    roles: list[str],
    created_at: datetime,
) -> User:
    """Create a verified user with approved roles."""
    user = User(
        email=email,
        password_hash=hash_password("CorrectHorse9"),
        display_name=email.split("@")[0],
        email_verified=True,
        kyc_status="verified",
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(user)
    await session.flush()
    for role in roles:
        session.add(
            UserRole(
                user_id=user.id,
                role=role,
                approved_at=created_at,
                created_at=created_at,
            )
        )
    await session.flush()
    return user


async def _cleanup() -> None:
    """Delete detail-test rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(ArtifactPiiAudit))
        await session.execute(delete(ArtifactRarityAudit))
        await session.execute(delete(Artifact))
        await session.execute(delete(Framework))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()


async def _seed_held_framework(now: datetime) -> dict[str, UUID]:
    """Create one PII-held Framework with two artifacts and return key ids."""
    async with async_session_factory() as session:
        async with session.begin():
            admin = await _create_user(
                session,
                email=f"admin-detail-{uuid4()}@auracles.space",
                roles=["admin"],
                created_at=now - timedelta(days=30),
            )
            contributor = await _create_user(
                session,
                email=f"contributor-detail-{uuid4()}@auracles.space",
                roles=["contributor"],
                created_at=now - timedelta(days=10),
            )
            framework = Framework(
                contributor_id=contributor.id,
                title="Held Onboarding Framework",
                description="Held for PII review.",
                status="pipeline_failed",
                category="operations",
                sector="technology",
                industry="software",
                business_function="operations",
                tags=["held"],
                tags_text="held",
                price=Decimal("150.00"),
                currency="NGN",
                license_types=["single_user"],
                pipeline_failure_reasons={},
                created_at=now - timedelta(days=3),
                updated_at=now - timedelta(hours=1),
            )
            session.add(framework)
            await session.flush()

            held_artifact = Artifact(
                framework_id=framework.id,
                name="onboarding-playbook.pdf",
                file_key="frameworks/held/original.pdf",
                clean_file_key="frameworks/held/redacted.pdf",
                file_size=4096,
                mime_type="application/pdf",
                scan_status="clean",
                processing_status="flagged_pii",
                pii_detected=True,
                pii_review_needed=True,
                metadata_vector={
                    "redaction": {"status": "generated", "accepted": False}
                },
                current_for_framework=True,
                created_at=now - timedelta(hours=2),
            )
            clean_artifact = Artifact(
                framework_id=framework.id,
                name="appendix.pdf",
                file_key="frameworks/held/appendix.pdf",
                file_size=2048,
                mime_type="application/pdf",
                scan_status="clean",
                processing_status="processed",
                current_for_framework=True,
                created_at=now - timedelta(hours=3),
            )
            session.add_all([held_artifact, clean_artifact])
            await session.flush()

            framework.pipeline_failure_reasons = {"pii": [str(held_artifact.id)]}
            session.add(
                ArtifactPiiAudit(
                    artifact_id=held_artifact.id,
                    pii_types_found=["email", "phone_number"],
                    auto_redacted=True,
                    flagged_for_review=True,
                    processed_at=now - timedelta(hours=2),
                )
            )

    return {
        "admin_id": admin.id,
        "contributor_id": contributor.id,
        "framework_id": framework.id,
        "held_artifact_id": held_artifact.id,
    }


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the database schema is current for these tests."""
    backend_dir = Path(__file__).resolve().parents[2]
    sync_engine = create_engine(app.state.settings.sync_database_url)
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "migrations"))
    command.upgrade(config, "head")
    try:
        yield
    finally:
        command.upgrade(config, "head")
        sync_engine.dispose()


async def test_admin_detail_shows_a_held_framework_and_why_it_is_held(
    client: AsyncClient,
    migrated_database: None,
) -> None:
    """A held Framework must be readable by admin with its blocking artifacts.

    The Framework is ``pipeline_failed``, so it is absent from every other
    admin surface; this endpoint is the only place an admin can see it.
    """
    del migrated_database
    now = datetime.now(UTC)
    await engine.dispose()
    await _cleanup()
    try:
        fixture = await _seed_held_framework(now)
        response = await client.get(
            f"/v1/admin/frameworks/{fixture['framework_id']}",
            headers=auth_headers(fixture["admin_id"], ["admin"]),
        )
    finally:
        await _cleanup()
        await engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["framework_id"] == str(fixture["framework_id"])
    assert body["title"] == "Held Onboarding Framework"
    assert body["status"] == "pipeline_failed"
    assert body["currency"] == "NGN"
    assert body["contributor_id"] == str(fixture["contributor_id"])
    assert body["pipeline_failure_reasons"] == {
        "pii": [str(fixture["held_artifact_id"])]
    }

    artifacts = {item["name"]: item for item in body["artifacts"]}
    assert set(artifacts) == {"onboarding-playbook.pdf", "appendix.pdf"}
    held = artifacts["onboarding-playbook.pdf"]
    assert held["processing_status"] == "flagged_pii"
    assert held["pii_review_needed"] is True
    assert held["pii_types_found"] == ["email", "phone_number"]
    assert held["redaction_status"] == "generated"
    assert held["redaction_accepted"] is False
    assert held["blocking"] is True
    assert artifacts["appendix.pdf"]["blocking"] is False
    assert artifacts["appendix.pdf"]["processing_status"] == "processed"

    # Metadata only: the detail view never hands an admin the file.
    assert "file_key" not in held
    assert "clean_file_key" not in held
    assert "download_url" not in held


async def test_admin_detail_returns_404_for_an_unknown_framework(
    client: AsyncClient,
    migrated_database: None,
) -> None:
    """An id that matches no Framework must 404, not leak an empty shell."""
    del migrated_database
    now = datetime.now(UTC)
    await engine.dispose()
    await _cleanup()
    try:
        fixture = await _seed_held_framework(now)
        response = await client.get(
            f"/v1/admin/frameworks/{uuid4()}",
            headers=auth_headers(fixture["admin_id"], ["admin"]),
        )
    finally:
        await _cleanup()
        await engine.dispose()

    assert response.status_code == 404


async def test_admin_detail_refuses_a_non_admin_caller(
    client: AsyncClient,
    migrated_database: None,
) -> None:
    """The Framework's own Contributor must not reach the admin detail view.

    The view carries moderation findings and the audit trail, so it is gated
    on the admin role rather than on ownership.
    """
    del migrated_database
    now = datetime.now(UTC)
    await engine.dispose()
    await _cleanup()
    try:
        fixture = await _seed_held_framework(now)
        response = await client.get(
            f"/v1/admin/frameworks/{fixture['framework_id']}",
            headers=auth_headers(fixture["contributor_id"], ["contributor"]),
        )
        unauthenticated = await client.get(
            f"/v1/admin/frameworks/{fixture['framework_id']}"
        )
    finally:
        await _cleanup()
        await engine.dispose()

    assert response.status_code == 403
    assert unauthenticated.status_code == 401


@pytest.mark.parametrize(
    ("framework_status", "expected_rels"),
    [
        ("pipeline_failed", ["override_rarity_block"]),
        ("published", ["suspend_framework"]),
        ("suspended", ["reinstate_framework"]),
        ("draft", []),
    ],
)
async def test_admin_detail_offers_only_actions_valid_for_the_status(
    client: AsyncClient,
    migrated_database: None,
    framework_status: str,
    expected_rels: list[str],
) -> None:
    """Action links must mirror what the admin router will actually accept.

    Offering a reinstate on a published Framework, or a suspend on a held one,
    would put a button in the UI that can only fail.
    """
    del migrated_database
    now = datetime.now(UTC)
    await engine.dispose()
    await _cleanup()
    try:
        fixture = await _seed_held_framework(now)
        async with async_session_factory() as session:
            async with session.begin():
                framework = await session.get(Framework, fixture["framework_id"])
                assert framework is not None
                framework.status = framework_status
        response = await client.get(
            f"/v1/admin/frameworks/{fixture['framework_id']}",
            headers=auth_headers(fixture["admin_id"], ["admin"]),
        )
    finally:
        await _cleanup()
        await engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert [link["rel"] for link in body["action_links"]] == expected_rels
    assert all(link["actor_role"] == "admin" for link in body["action_links"])


async def test_admin_detail_audits_the_view_and_returns_the_framework_timeline(
    client: AsyncClient,
    migrated_database: None,
) -> None:
    """Reading a Framework must be audited, and prior audit rows returned.

    The timeline is how an admin sees who held the Framework and when, which
    is the question the moderation queue cannot answer.
    """
    del migrated_database
    now = datetime.now(UTC)
    await engine.dispose()
    await _cleanup()
    try:
        fixture = await _seed_held_framework(now)
        async with async_session_factory() as session:
            async with session.begin():
                session.add(
                    AuditLog(
                        actor_id=fixture["contributor_id"],
                        action="framework_submitted",
                        target_type="framework",
                        target_id=fixture["framework_id"],
                        metadata_={"version": "1.0.0"},
                        created_at=now - timedelta(days=3),
                    )
                )
        response = await client.get(
            f"/v1/admin/frameworks/{fixture['framework_id']}",
            headers=auth_headers(fixture["admin_id"], ["admin"]),
        )
        async with async_session_factory() as session:
            views = (
                (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.action == "admin_framework_viewed"
                        )
                    )
                )
                .scalars()
                .all()
            )
            view_actor_ids = [entry.actor_id for entry in views]
            view_targets = [entry.target_id for entry in views]
    finally:
        await _cleanup()
        await engine.dispose()

    assert response.status_code == 200
    assert view_actor_ids == [fixture["admin_id"]]
    assert view_targets == [fixture["framework_id"]]

    timeline = response.json()["timeline"]
    submitted = [
        entry for entry in timeline if entry["action"] == "framework_submitted"
    ]
    assert len(submitted) == 1
    assert submitted[0]["actor_id"] == str(fixture["contributor_id"])
    assert submitted[0]["metadata"] == {"version": "1.0.0"}
