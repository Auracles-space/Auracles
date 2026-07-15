"""Calibration fixtures must never leak into public framework surfaces.

Enforces the calibration-fixture leak guard across public Explore reads and
framework attestation-target selection.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.attestation.models import Attestation
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio


class FakeRedis:
    """Redis test double for Explore routes that expect a client."""

    async def incr(self, key: str) -> int:
        """Return a stable counter value for unused rate-limit paths."""
        del key
        return 1

    async def expire(self, key: str, seconds: int) -> bool:
        """Pretend key expiry succeeded."""
        del key, seconds
        return True


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the test database is upgraded to the current head."""
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
async def clean_state(migrated_database: None) -> AsyncIterator[dict[str, Any]]:
    """Reset public-framework rows and install the Explore Redis double."""
    del migrated_database
    fake_redis = FakeRedis()
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows touched by the calibration leak-guard test."""
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(delete(Attestation))
                await session.execute(delete(Framework))
                await session.execute(delete(AuditLog))
                await session.execute(delete(UserRole))
                await session.execute(delete(User))

    await cleanup()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield {"redis": fake_redis}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def _create_user(email: str, roles: list[str]) -> UUID:
    """Create one verified user with approved role rows."""
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


async def _create_framework(
    contributor_id: UUID,
    *,
    title: str,
    is_calibration: bool,
) -> UUID:
    """Create one published framework with or without the calibration flag."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                id=uuid4(),
                contributor_id=contributor_id,
                title=title,
                description=f"{title} implementation playbook.",
                version="1.0.0",
                status="published",
                is_calibration=is_calibration,
                calibration_review_type="quality" if is_calibration else None,
                category="framework",
                sector="financial_services",
                industry="fund_management",
                business_function="risk_management",
                tags=["risk", "governance"],
                tags_text="risk governance",
                jurisdiction="us",
                complexity=3,
                org_size="mid_market",
                lifecycle_stage="scale",
                price=Decimal("499.00"),
                currency="USD",
                license_types=["single_user"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            return framework.id


def _auth_headers(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Create bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


async def test_calibration_framework_hidden_from_public_surfaces_and_attestation_target(
    client,
    clean_state: dict[str, Any],
) -> None:
    """Calibration fixtures stay out of Explore/profile and attestation requests."""
    del clean_state
    contributor_id = await _create_user(
        f"fixture-owner-{uuid4().hex[:8]}@auracles.space",
        ["contributor"],
    )
    operator_id = await _create_user(
        f"operator-{uuid4().hex[:8]}@auracles.space",
        ["operator"],
    )
    visible_framework_id = await _create_framework(
        contributor_id,
        title="Visible Framework",
        is_calibration=False,
    )
    calibration_framework_id = await _create_framework(
        contributor_id,
        title="Calibration Fixture",
        is_calibration=True,
    )

    catalog_response = await client.get("/v1/explore/frameworks")
    assert catalog_response.status_code == 200
    catalog_ids = {UUID(item["id"]) for item in catalog_response.json()["items"]}
    assert visible_framework_id in catalog_ids
    assert calibration_framework_id not in catalog_ids

    profile_response = await client.get(f"/v1/explore/contributors/{contributor_id}")
    assert profile_response.status_code == 200
    profile_body = profile_response.json()
    assert profile_body["published_framework_count"] == 1
    profile_ids = {UUID(item["id"]) for item in profile_body["published_frameworks"]}
    assert visible_framework_id in profile_ids
    assert calibration_framework_id not in profile_ids

    normal_request = await client.post(
        "/v1/attestations",
        headers=_auth_headers(operator_id, ["operator"]),
        json={
            "target_type": "framework",
            "target_id": str(visible_framework_id),
            "review_type": "quality",
            "brief": {
                "what_it_does": "Standardises KYC onboarding",
                "use_case": "Compliance team at a mid-size fund",
                "jurisdiction": "US",
                "focus_areas": "AML completeness",
                "desired_outcome": "Compliance sign-off badge",
            },
            "requested_specializations": ["compliance"],
            "requested_jurisdictions": ["US"],
        },
    )
    assert normal_request.status_code == 201
    assert normal_request.json()["status"] == "pending_owner_consent"

    calibration_request = await client.post(
        "/v1/attestations",
        headers=_auth_headers(operator_id, ["operator"]),
        json={
            "target_type": "framework",
            "target_id": str(calibration_framework_id),
            "review_type": "quality",
            "brief": {
                "what_it_does": "Standardises KYC onboarding",
                "use_case": "Compliance team at a mid-size fund",
                "jurisdiction": "US",
                "focus_areas": "AML completeness",
                "desired_outcome": "Compliance sign-off badge",
            },
            "requested_specializations": ["compliance"],
            "requested_jurisdictions": ["US"],
        },
    )
    assert calibration_request.status_code == 404
