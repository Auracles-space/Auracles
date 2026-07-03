"""Integration tests for the admin moderation queue endpoint.

These tests exercise the public admin HTTP contract for aggregating rarity,
near-duplicate, and PII review signals into one paginated moderation queue.
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


def auth_headers(user_id: UUID) -> dict[str, str]:
    """Create bearer auth headers for an admin user."""
    token = create_access_token(user_id=user_id, roles=["admin"])
    return {"Authorization": f"Bearer {token}"}


async def _create_user(
    session: AsyncSession,
    *,
    email: str,
    roles: list[str],
    created_at: datetime,
) -> User:
    """Create a verified user with approved roles for moderation tests."""
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


async def _cleanup_admin_moderation_queue_state() -> None:
    """Delete moderation-queue test rows in foreign-key-safe order."""
    async with async_session_factory() as session:
        await session.execute(delete(AuditLog))
        await session.execute(delete(ArtifactPiiAudit))
        await session.execute(delete(ArtifactRarityAudit))
        await session.execute(delete(Artifact))
        await session.execute(delete(Framework))
        await session.execute(delete(UserRole))
        await session.execute(delete(User))
        await session.commit()


async def _seed_moderation_queue_fixture(now: datetime) -> dict[str, UUID]:
    """Create one mixed moderation queue fixture and return key identifiers."""
    async with async_session_factory() as session:
        async with session.begin():
            admin = await _create_user(
                session,
                email=f"admin-moderation-{uuid4()}@auracles.space",
                roles=["admin"],
                created_at=now - timedelta(days=30),
            )
            contributor = await _create_user(
                session,
                email=f"contributor-moderation-{uuid4()}@auracles.space",
                roles=["contributor"],
                created_at=now - timedelta(days=10),
            )

            blocked_framework = Framework(
                contributor_id=contributor.id,
                title="Blocked Similarity Framework",
                description="Near-duplicate moderation fixture.",
                status="pipeline_failed",
                category="operations",
                sector="technology",
                industry="software",
                business_function="operations",
                tags=["blocked"],
                tags_text="blocked",
                price=Decimal("120.00"),
                currency="USD",
                license_types=["single_user"],
                pipeline_failure_reasons={},
                created_at=now - timedelta(days=5),
                updated_at=now - timedelta(hours=2),
            )
            rarity_framework = Framework(
                contributor_id=contributor.id,
                title="Low Rarity Framework",
                description="Low-rarity moderation fixture.",
                status="pipeline_failed",
                category="operations",
                sector="technology",
                industry="software",
                business_function="operations",
                tags=["rarity"],
                tags_text="rarity",
                price=Decimal("130.00"),
                currency="USD",
                license_types=["single_user"],
                pipeline_failure_reasons={},
                created_at=now - timedelta(days=4),
                updated_at=now - timedelta(hours=3),
            )
            pii_framework = Framework(
                contributor_id=contributor.id,
                title="PII Framework",
                description="PII moderation fixture.",
                status="pipeline_failed",
                category="operations",
                sector="technology",
                industry="software",
                business_function="operations",
                tags=["pii"],
                tags_text="pii",
                price=Decimal("140.00"),
                currency="USD",
                license_types=["single_user"],
                pipeline_failure_reasons={},
                created_at=now - timedelta(days=3),
                updated_at=now - timedelta(hours=1),
            )
            session.add_all([blocked_framework, rarity_framework, pii_framework])
            await session.flush()

            blocked_artifact = Artifact(
                framework_id=blocked_framework.id,
                name="blocked-playbook.pdf",
                file_key="frameworks/blocked/original.pdf",
                file_size=1024,
                mime_type="application/pdf",
                scan_status="clean",
                processing_status="flagged_rarity",
                metadata_vector={"near_duplicate_blocked": True},
                current_for_framework=True,
                created_at=now - timedelta(hours=2),
            )
            rarity_artifact = Artifact(
                framework_id=rarity_framework.id,
                name="low-rarity-playbook.pdf",
                file_key="frameworks/rarity/original.pdf",
                file_size=2048,
                mime_type="application/pdf",
                scan_status="clean",
                processing_status="flagged_rarity",
                current_for_framework=True,
                created_at=now - timedelta(hours=3),
            )
            pii_artifact = Artifact(
                framework_id=pii_framework.id,
                name="pii-playbook.pdf",
                file_key="frameworks/pii/original.pdf",
                clean_file_key="frameworks/pii/redacted.pdf",
                file_size=4096,
                mime_type="application/pdf",
                scan_status="clean",
                processing_status="flagged_pii",
                pii_detected=True,
                pii_review_needed=True,
                metadata_vector={
                    "redaction": {
                        "status": "generated",
                        "accepted": False,
                        "original_file_key": "frameworks/pii/original.pdf",
                    }
                },
                current_for_framework=True,
                created_at=now - timedelta(hours=1),
            )
            session.add_all([blocked_artifact, rarity_artifact, pii_artifact])
            await session.flush()

            blocked_framework.pipeline_failure_reasons = {
                "internal_rarity": [str(blocked_artifact.id)]
            }

            session.add_all(
                [
                    ArtifactRarityAudit(
                        artifact_id=blocked_artifact.id,
                        internal_jaccard=Decimal("0.9500"),
                        blended_score=Decimal("0.1200"),
                        external_phrases_queried=["blocked phrase"],
                        external_hit_counts=[1],
                        created_at=now - timedelta(hours=2),
                    ),
                    ArtifactRarityAudit(
                        artifact_id=rarity_artifact.id,
                        internal_jaccard=Decimal("0.5200"),
                        blended_score=Decimal("0.3100"),
                        external_phrases_queried=["rare phrase"],
                        external_hit_counts=[3],
                        created_at=now - timedelta(hours=3),
                    ),
                    ArtifactPiiAudit(
                        artifact_id=pii_artifact.id,
                        pii_types_found=["email", "phone_number"],
                        auto_redacted=True,
                        flagged_for_review=True,
                        processed_at=now - timedelta(hours=1),
                    ),
                ]
            )

    return {
        "admin_id": admin.id,
        "blocked_artifact_id": blocked_artifact.id,
        "rarity_artifact_id": rarity_artifact.id,
    }


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the database schema is current for moderation queue tests."""
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


async def test_admin_moderation_queue_aggregates_all_signal_types(
    client: AsyncClient,
    migrated_database: None,
) -> None:
    """Admin queue must aggregate rarity, near-duplicate, and PII rows together."""
    del migrated_database
    now = datetime.now(UTC)
    await engine.dispose()
    await _cleanup_admin_moderation_queue_state()
    try:
        fixture = await _seed_moderation_queue_fixture(now)

        response = await client.get(
            "/v1/admin/moderation/queue",
            headers=auth_headers(fixture["admin_id"]),
        )

        async with async_session_factory() as audit_session:
            audits = (
                (
                    await audit_session.execute(
                        select(AuditLog)
                        .where(AuditLog.action == "moderation_queue_viewed")
                        .order_by(AuditLog.created_at)
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await _cleanup_admin_moderation_queue_state()
        await engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert [item["queue_type"] for item in body["items"]] == [
        "pii_review",
        "near_duplicate_block",
        "rarity_review",
        "rarity_review",
    ]

    pii_row = body["items"][0]
    assert pii_row["framework_title"] == "PII Framework"
    assert pii_row["artifact_name"] == "pii-playbook.pdf"
    assert pii_row["details"]["pii_types_found"] == ["email", "phone_number"]
    assert pii_row["details"]["redaction_status"] == "generated"
    expected_accept_redaction_path = (
        f"/v1/frameworks/{pii_row['framework_id']}/artifacts/"
        f"{pii_row['artifact_id']}/accept-redaction"
    )
    expected_resolve_pii_path = (
        f"/v1/frameworks/{pii_row['framework_id']}/artifacts/"
        f"{pii_row['artifact_id']}/resolve-pii-review"
    )
    assert pii_row["action_links"] == [
        {
            "rel": "accept_redaction",
            "method": "POST",
            "path": expected_accept_redaction_path,
            "actor_role": "contributor",
        },
        {
            "rel": "resolve_pii_review",
            "method": "POST",
            "path": expected_resolve_pii_path,
            "actor_role": "contributor",
        },
    ]

    near_duplicate_row = body["items"][1]
    assert near_duplicate_row["framework_title"] == "Blocked Similarity Framework"
    assert near_duplicate_row["artifact_id"] == str(fixture["blocked_artifact_id"])
    assert near_duplicate_row["details"]["blocked_artifact_ids"] == [
        str(fixture["blocked_artifact_id"])
    ]
    assert near_duplicate_row["details"]["internal_jaccard"] == "0.9500"
    expected_override_path = (
        f"/v1/admin/frameworks/{near_duplicate_row['framework_id']}/"
        "rarity-block/override"
    )
    assert near_duplicate_row["action_links"] == [
        {
            "rel": "override_rarity_block",
            "method": "POST",
            "path": expected_override_path,
            "actor_role": "admin",
        }
    ]

    blocked_rarity_row = body["items"][2]
    assert blocked_rarity_row["framework_title"] == "Blocked Similarity Framework"
    assert blocked_rarity_row["artifact_id"] == str(fixture["blocked_artifact_id"])
    assert blocked_rarity_row["details"]["internal_jaccard"] == "0.9500"

    plain_rarity_row = body["items"][3]
    assert plain_rarity_row["framework_title"] == "Low Rarity Framework"
    assert plain_rarity_row["artifact_id"] == str(fixture["rarity_artifact_id"])
    assert plain_rarity_row["details"]["internal_jaccard"] == "0.5200"
    assert plain_rarity_row["details"]["external_phrases_queried"] == ["rare phrase"]

    assert len(audits) == 1
    assert audits[0].target_type == "moderation_queue"
    assert audits[0].metadata_ == {
        "type": "all",
        "page": 1,
        "page_size": 20,
        "returned_count": 4,
        "total": 4,
    }


async def test_admin_moderation_queue_filters_and_paginates_by_type(
    client: AsyncClient,
    migrated_database: None,
) -> None:
    """Queue type filtering and pagination must preserve total counts and audit."""
    del migrated_database
    now = datetime.now(UTC)
    await engine.dispose()
    await _cleanup_admin_moderation_queue_state()
    try:
        fixture = await _seed_moderation_queue_fixture(now)

        response = await client.get(
            "/v1/admin/moderation/queue",
            params={"type": "rarity_review", "page": 2, "page_size": 1},
            headers=auth_headers(fixture["admin_id"]),
        )

        async with async_session_factory() as audit_session:
            audit = await audit_session.scalar(
                select(AuditLog)
                .where(AuditLog.action == "moderation_queue_viewed")
                .order_by(AuditLog.created_at.desc())
            )
    finally:
        await _cleanup_admin_moderation_queue_state()
        await engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["page"] == 2
    assert body["page_size"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["queue_type"] == "rarity_review"
    assert body["items"][0]["framework_title"] == "Low Rarity Framework"
    assert audit is not None
    assert audit.metadata_ == {
        "type": "rarity_review",
        "page": 2,
        "page_size": 1,
        "returned_count": 1,
        "total": 2,
    }
