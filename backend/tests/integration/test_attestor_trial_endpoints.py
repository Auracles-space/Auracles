"""Integration tests for the nominee calibration-trial endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.main import app
from app.modules.attestation import rubrics
from app.modules.attestation.models import (
    AttestationRubricDimension,
    AttestorTrial,
    AttestorTrialAnswerKey,
    AttestorTrialRubricScore,
)
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.frameworks.models_artifact import Artifact
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgMember,
)

pytestmark = pytest.mark.asyncio


class FakeRedis:
    """Redis test double for endpoints that do not use Redis directly."""

    def __init__(self) -> None:
        """Create empty in-memory Redis-like state."""
        self.values: dict[str, str] = {}
        self.counters: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored string or counter value."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def set(
        self, key: str, value: str, ex: int | None = None, nx: bool = False
    ) -> bool:
        """Store a string value, optionally respecting NX semantics."""
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Store a string value with a TTL (test double ignores expiry)."""
        del seconds
        self.values[key] = value

    async def incr(self, key: str) -> int:
        """Increment and return a counter value."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """No-op TTL assignment for the test double."""
        del key, seconds

    async def delete(self, *keys: str) -> int:
        """Delete string and counter keys."""
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.counters)
            self.values.pop(key, None)
            self.counters.pop(key, None)
        return removed

    async def ttl(self, key: str) -> int:
        """Return the no-expiry sentinel."""
        del key
        return -1


class FakeStorage:
    """S3 storage test double for nominee trial artifact URLs."""

    def presigned_get(
        self,
        bucket: str,
        key: str,
        expires_in: int,
        *,
        download_name: str | None = None,
    ) -> str:
        """Return a deterministic fake presigned URL."""
        return f"https://storage.test/{bucket}/{key}?exp={expires_in}"


@dataclass(frozen=True)
class SeededTrialHttpContext:
    """HTTP fixture state for nominee trial endpoint tests."""

    org_id: UUID
    nominee_headers: dict[str, str]
    other_member_headers: dict[str, str]


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
async def seeded_trial_http(
    migrated_database: None,
) -> AsyncIterator[SeededTrialHttpContext]:
    """Seed one assigned calibration trial plus nominee and other-member auth."""
    from app.integrations import s3

    del migrated_database
    await engine.dispose()
    fake_redis = FakeRedis()
    fake_storage = FakeStorage()

    async def cleanup() -> None:
        """Delete rows touched by the nominee trial endpoint tests."""
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(delete(AttestorTrialRubricScore))
                await session.execute(delete(AttestorTrialAnswerKey))
                await session.execute(delete(AttestorTrial))
                await session.execute(delete(Artifact))
                await session.execute(delete(OrgAttestorApplication))
                await session.execute(delete(OrgMember))
                await session.execute(delete(Organization))
                await session.execute(delete(Framework))
                await session.execute(delete(User))

    async def create_user(prefix: str) -> User:
        """Create one verified user row for the test org."""
        async with async_session_factory() as session:
            async with session.begin():
                user = User(
                    email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
                    password_hash=hash_password("CorrectHorse9"),
                    display_name=prefix,
                    email_verified=True,
                    kyc_status="verified",
                )
                session.add(user)
                await session.flush()
                await session.refresh(user)
                return user

    await cleanup()
    original_storage = s3.storage
    s3.storage = fake_storage
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        nominee_user = await create_user("trial-nominee")
        other_user = await create_user("trial-other")

        async with async_session_factory() as session:
            async with session.begin():
                org = Organization(
                    slug=f"trial-http-{uuid4().hex[:8]}",
                    name="Trial HTTP Org",
                    country="US",
                    created_by=nominee_user.id,
                )
                session.add(org)
                await session.flush()
                nominee_member = OrgMember(
                    org_id=org.id,
                    user_id=nominee_user.id,
                    role="owner",
                )
                other_member = OrgMember(
                    org_id=org.id,
                    user_id=other_user.id,
                    role="member",
                )
                session.add_all([nominee_member, other_member])
                await session.flush()

                application = OrgAttestorApplication(
                    org_id=org.id,
                    status="submitted",
                    specializations=[],
                    sectors=["private_equity"],
                    functions=["compliance"],
                    jurisdictions=["united_states"],
                    credentials_summary="Two decades of PE compliance experience.",
                    sample_work={},
                    professional_references="Jane Roe, MD.",
                    trial_member_id=nominee_member.id,
                )
                session.add(application)
                await session.flush()

                dimensions = (
                    await session.scalars(
                        select(AttestationRubricDimension)
                        .where(
                            AttestationRubricDimension.review_type == "quality",
                            AttestationRubricDimension.version
                            == rubrics.RUBRIC_VERSION,
                        )
                        .order_by(AttestationRubricDimension.display_order.asc())
                    )
                ).all()
                assert len(dimensions) >= 2

                framework = Framework(
                    id=uuid4(),
                    contributor_id=nominee_user.id,
                    title="Calibration Fixture",
                    description="Calibration framework fixture.",
                    version="1.0.0",
                    status="published",
                    is_calibration=True,
                    calibration_review_type="quality",
                    category="framework",
                    sector="financial_services",
                    industry="fund_management",
                    business_function="risk_management",
                    tags=["risk"],
                    tags_text="risk",
                    jurisdiction="us",
                    complexity=3,
                    org_size="mid_market",
                    lifecycle_stage="scale",
                    price=Decimal("499.00"),
                    currency="USD",
                    license_types=["single_user"],
                )
                session.add(framework)
                await session.flush()

                session.add(
                    Artifact(
                        framework_id=framework.id,
                        name="fixture.pdf",
                        file_key=f"frameworks/{framework.id}/fixture.pdf",
                        file_size=2048,
                        mime_type="application/pdf",
                        scan_status="clean",
                        processing_status="processed",
                    )
                )
                for dimension in dimensions:
                    session.add(
                        AttestorTrialAnswerKey(
                            framework_id=framework.id,
                            dimension_id=dimension.id,
                            expected_score=4,
                            tolerance=0,
                        )
                    )
                session.add(
                    AttestorTrial(
                        org_application_id=application.id,
                        org_id=org.id,
                        member_id=nominee_member.id,
                        seeded_framework_id=framework.id,
                        status="assigned",
                        attempt=1,
                    )
                )

        yield SeededTrialHttpContext(
            org_id=org.id,
            nominee_headers={
                "Authorization": f"Bearer {create_access_token(nominee_user.id, [])}"
            },
            other_member_headers={
                "Authorization": f"Bearer {create_access_token(other_user.id, [])}"
            },
        )
    finally:
        s3.storage = original_storage
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def test_nominee_can_load_and_submit(
    client,
    seeded_trial_http: SeededTrialHttpContext,
) -> None:
    """The nominated member loads the trial and submits a full rubric."""
    response = await client.get(
        f"/v1/orgs/{seeded_trial_http.org_id}/attestor-trial",
        headers=seeded_trial_http.nominee_headers,
    )
    assert response.status_code == 200
    dimensions = response.json()["dimensions"]

    submit = await client.post(
        f"/v1/orgs/{seeded_trial_http.org_id}/attestor-trial/submit",
        headers=seeded_trial_http.nominee_headers,
        json={
            "scores": [
                {"dimension_id": dimension["dimension_id"], "score": 4}
                for dimension in dimensions
            ]
        },
    )
    assert submit.status_code == 200
    assert submit.json()["status"] == "submitted"


async def test_non_nominee_member_forbidden(
    client,
    seeded_trial_http: SeededTrialHttpContext,
) -> None:
    """A different org member gets 403 on the member trial endpoint."""
    response = await client.get(
        f"/v1/orgs/{seeded_trial_http.org_id}/attestor-trial",
        headers=seeded_trial_http.other_member_headers,
    )
    assert response.status_code == 403
