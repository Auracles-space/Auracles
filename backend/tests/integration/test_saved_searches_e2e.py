"""End-to-end saved-search alert integration tests.

These tests connect the public saved-search API, Framework publish flow, Celery
Beat dispatcher, digest email queue, and in-app notification API so Phase 5b-2
has one regression check across the full alert lifecycle.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select, update

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Payout, PayoutAccount, Transaction
from app.modules.frameworks.models import (
    Framework,
    FrameworkVersion,
    FrameworkVersionArtifact,
    License,
    Review,
)
from app.modules.frameworks.models_artifact import (
    Artifact,
    ArtifactDownload,
    ArtifactPiiAudit,
    ArtifactRarityAudit,
)
from app.modules.notifications.models import Notification
from app.modules.saved_searches.models import (
    SavedSearch,
    SavedSearchAlertDelivery,
)
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import saved_searches_beat


class FakeRedis:
    """Minimal Redis dependency override for authenticated routes."""


class FakeArtifactStorage:
    """S3 storage double for Framework artifact upload and publish checks."""

    def __init__(self) -> None:
        """Create empty fake object state."""
        self.existing_keys: set[str] = set()

    def presigned_post(
        self,
        bucket: str,
        key: str,
        mime_type: str,
        max_size: int,
        expires_in: int,
    ) -> dict[str, Any]:
        """Return a deterministic presigned POST payload."""
        del bucket, mime_type, max_size, expires_in
        self.existing_keys.add(key)
        return {
            "fields": {"key": key},
            "url": "https://s3.test/upload",
        }

    def object_exists(self, bucket: str, key: str) -> bool:
        """Return whether the fake S3 object exists."""
        del bucket
        return key in self.existing_keys


class FakeDigestEmailTask:
    """Celery-task-shaped double for saved-search digest email dispatch."""

    def __init__(self) -> None:
        """Create empty delayed-call storage."""
        self.calls: list[dict[str, Any]] = []

    def delay(self, **kwargs: Any) -> None:
        """Record a queued digest email call."""
        self.calls.append(kwargs)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure every table used by the saved-search E2E path exists."""
    sync_engine = create_engine(
        app.state.settings.sync_database_url,
        pool_pre_ping=True,
    )
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        command.upgrade(Config("alembic.ini"), "head")
        sync_engine.dispose()


@pytest.fixture
async def saved_search_e2e_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset marketplace rows and patch external dispatchers for E2E tests."""
    from app.integrations import s3

    fake_storage = FakeArtifactStorage()
    fake_digest_task = FakeDigestEmailTask()
    indexed_frameworks: list[str] = []
    await engine.dispose()

    async def fake_index_framework_artifacts(framework_id: UUID) -> None:
        """Record MinHash indexing requests without touching Redis."""
        indexed_frameworks.append(str(framework_id))

    async def cleanup() -> None:
        """Delete rows in dependency order for isolated E2E assertions."""
        async with async_session_factory() as session:
            await session.execute(update(Framework).values(preview_artifact_id=None))
            await session.execute(delete(AuditLog))
            await session.execute(delete(Notification))
            await session.execute(delete(SavedSearchAlertDelivery))
            await session.execute(delete(SavedSearch))
            await session.execute(delete(Review))
            await session.execute(delete(ArtifactDownload))
            await session.execute(delete(License))
            await session.execute(delete(Payout))
            await session.execute(delete(PayoutAccount))
            await session.execute(delete(Transaction))
            await session.execute(delete(ArtifactRarityAudit))
            await session.execute(delete(ArtifactPiiAudit))
            await session.execute(delete(FrameworkVersionArtifact))
            await session.execute(delete(FrameworkVersion))
            await session.execute(delete(Artifact))
            await session.execute(delete(Framework))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    original_storage = s3.storage
    s3.storage = fake_storage
    monkeypatch.setattr(
        "app.modules.frameworks.service.index_framework_artifacts",
        fake_index_framework_artifacts,
        raising=False,
    )
    monkeypatch.setattr(
        saved_searches_beat,
        "send_saved_search_alert_email",
        fake_digest_task,
        raising=False,
    )
    try:
        yield {
            "digest_task": fake_digest_task,
            "indexed_frameworks": indexed_frameworks,
            "storage": fake_storage,
        }
    finally:
        s3.storage = original_storage
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def create_user_with_roles(email: str, roles: list[str]) -> UUID:
    """Create an email-verified user with approved roles."""
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
            for role in roles:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role=role,
                        approved_at=datetime.now(UTC),
                    )
                )
        return user.id


def auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


def framework_payload() -> dict[str, Any]:
    """Return a Framework payload matching the saved-search filters."""
    return {
        "category": "playbook",
        "complexity": 3,
        "description": "A risk governance implementation package.",
        "function": "risk_management",
        "industry": "fund_management",
        "jurisdiction": "us",
        "lifecycle_stage": "scale",
        "org_size": "mid_market",
        "pricing": {
            "commercial_rights": "Internal commercial use allowed.",
            "currency": "USD",
            "license_types": ["single_user", "team"],
            "price": "450.00",
            "usage_restrictions": "No resale.",
        },
        "sector": "financial_services",
        "tags": ["risk", "governance"],
        "title": "Risk Control Playbook",
    }


async def mark_artifact_pipeline_passed(framework_id: str, artifact_id: str) -> None:
    """Persist artifact pipeline fields that are normally set by workers."""
    async with async_session_factory() as session:
        artifact = await session.get(Artifact, UUID(artifact_id))
        framework = await session.get(Framework, UUID(framework_id))
        assert artifact is not None
        assert framework is not None
        artifact.scan_status = "clean"
        artifact.processing_status = "processed"
        artifact.pii_detected = False
        artifact.pii_review_needed = False
        artifact.internal_rarity = Decimal("1.0000")
        artifact.external_rarity = Decimal("1.0000")
        artifact.rarity_score = Decimal("1.0000")
        framework.pipeline_failure_reasons = {}
        session.add(
            ArtifactRarityAudit(
                artifact_id=artifact.id,
                blended_score=Decimal("1.0000"),
                external_hit_counts=[],
                external_phrases_queried=[],
                internal_jaccard=Decimal("0.0000"),
            )
        )
        await session.commit()


def run_saved_search_beat() -> dict[str, int]:
    """Run the Celery task wrapper in a worker-like thread."""
    return saved_searches_beat.dispatch_saved_search_alerts.apply().get()


async def test_saved_search_alert_flow_sends_digest_and_in_app_once(
    client: AsyncClient,
    migrated_database: None,
    saved_search_e2e_context: dict[str, Any],
) -> None:
    """Save filters, publish a match, dispatch Beat, and prevent duplicates."""
    operator_id = await create_user_with_roles(
        "saved-e2e-operator@auracles.space",
        ["operator"],
    )
    contributor_id = await create_user_with_roles(
        "saved-e2e-contributor@auracles.space",
        ["contributor"],
    )
    saved = await client.post(
        "/v1/saved-searches",
        json={
            "alert_enabled": True,
            "filters": {
                "category": "playbook",
                "function": "risk_management",
                "q": "risk",
                "sort": "newest",
            },
            "name": "Risk playbooks",
        },
        headers=auth_headers(operator_id, ["operator"]),
    )

    created = await client.post(
        "/v1/frameworks",
        json=framework_payload(),
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    framework_id = created.json()["id"]
    upload = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/upload-url",
        json={
            "file_size": 2048,
            "filename": "risk-playbook.pdf",
            "mime_type": "application/pdf",
        },
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    artifact_id = upload.json()["artifact_id"]
    confirmed = await client.post(
        f"/v1/frameworks/{framework_id}/artifacts/confirm",
        json={"artifact_id": artifact_id},
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    await mark_artifact_pipeline_passed(framework_id, artifact_id)
    submitted = await client.post(
        f"/v1/frameworks/{framework_id}/submit",
        headers=auth_headers(contributor_id, ["contributor"]),
    )
    published = await client.post(
        f"/v1/frameworks/{framework_id}/publish",
        headers=auth_headers(contributor_id, ["contributor"]),
    )

    # The test exercises API calls and a Celery wrapper in one process. Dispose
    # the shared async engine before crossing event loops so asyncpg connections
    # are never reused by a different loop than the one that opened them.
    await engine.dispose()
    first_dispatch = await asyncio.to_thread(run_saved_search_beat)
    await engine.dispose()
    notifications = await client.get(
        "/v1/notifications",
        headers=auth_headers(operator_id, ["operator"]),
    )
    await engine.dispose()
    second_dispatch = await asyncio.to_thread(run_saved_search_beat)
    await engine.dispose()

    assert saved.status_code == 201
    assert created.status_code == 201
    assert upload.status_code == 200
    assert confirmed.status_code == 200
    assert submitted.status_code == 200
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert first_dispatch == {"processed_count": 1, "sent_count": 1, "match_count": 1}
    assert second_dispatch == {"processed_count": 1, "sent_count": 0, "match_count": 0}
    assert notifications.status_code == 200
    assert notifications.json()["unread_count"] == 1
    assert notifications.json()["notifications"][0]["type"] == "saved_search_alert"
    assert notifications.json()["notifications"][0]["payload"]["matches"] == [
        {
            "framework_id": framework_id,
            "link": f"/explore/{framework_id}",
            "title": "Risk Control Playbook",
        }
    ]
    assert saved_search_e2e_context["digest_task"].calls == [
        {
            "email": "saved-e2e-operator@auracles.space",
            "link": f"/settings/saved-searches/{saved.json()['id']}",
            "matches": [
                {
                    "framework_id": framework_id,
                    "link": f"/explore/{framework_id}",
                    "title": "Risk Control Playbook",
                }
            ],
            "saved_search_name": "Risk playbooks",
        }
    ]
    assert saved_search_e2e_context["indexed_frameworks"] == [framework_id]

    async with async_session_factory() as session:
        deliveries = (
            await session.execute(select(SavedSearchAlertDelivery))
        ).scalars().all()
        notification_rows = (
            await session.execute(select(Notification))
        ).scalars().all()

    assert len(deliveries) == 1
    assert len(notification_rows) == 1
