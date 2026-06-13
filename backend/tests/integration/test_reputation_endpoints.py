"""Integration tests for the public + gated reputation read API (Phase 5e).

Exercises ``/v1/reputation/*`` and the admin recompute trigger over HTTP:
framework/contributor reads are public, operator reads are gated to the
operator themselves, an in-deal contributor, or an admin, and the recompute
endpoint requires an admin with verified 2FA.

Maps to: BR-ATT-005, full-spec section 3234 (reputation visibility).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.auth.models import User, UserRole
from app.modules.frameworks.models import Framework
from app.modules.projects.models import Project, Proposal
from app.modules.reputation.models import ReputationScore
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis double for the TOTP rate-limit guard used by sensitive admin ops."""

    def __init__(self) -> None:
        """Create empty in-memory counter state."""
        self.counters: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        """Return a stored counter value as a string, if present."""
        return None if key not in self.counters else str(self.counters[key])

    async def incr(self, key: str) -> int:
        """Increment and return a counter."""
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """Record a TTL for a key."""
        self.ttls[key] = seconds

    async def delete(self, *keys: str) -> int:
        """Delete stored counters."""
        removed = 0
        for key in keys:
            removed += int(key in self.counters)
            self.counters.pop(key, None)
            self.ttls.pop(key, None)
        return removed


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure reputation + source tables exist for the endpoint tests."""
    sync_engine = create_engine(app.state.settings.sync_database_url)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


@pytest.fixture
async def reputation_api_context() -> AsyncIterator[FakeRedis]:
    """Reset reputation/project/auth rows and install a Redis double."""
    fake_redis = FakeRedis()
    await engine.dispose()

    async def cleanup() -> None:
        async with async_session_factory() as session:
            await session.execute(delete(ReputationScore))
            await session.execute(delete(AuditLog))
            await session.execute(delete(Proposal))
            await session.execute(delete(Project))
            await session.execute(delete(Framework))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield fake_redis
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await cleanup()
        await engine.dispose()


async def _create_user(
    email: str,
    roles: list[str],
    *,
    totp_secret: str | None = None,
) -> UUID:
    """Create one verified user with the given roles; return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                kyc_status="verified",
                totp_enabled=totp_secret is not None,
                totp_secret=(
                    encrypt_totp_secret(totp_secret)
                    if totp_secret is not None
                    else None
                ),
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


async def _create_framework(contributor_id: UUID) -> UUID:
    """Create one published framework owned by ``contributor_id``."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                id=uuid4(),
                contributor_id=contributor_id,
                title="Reputation API Framework",
                description="Framework used by reputation API tests.",
                version="1.0.0",
                status="published",
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
                published_at=datetime.now(UTC),
            )
            session.add(framework)
        return framework.id


async def _seed_score(
    subject_type: str,
    subject_id: UUID,
    *,
    score: str | None,
    is_provisional: bool,
    components: dict[str, Any],
) -> None:
    """Insert one reputation score row directly."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                ReputationScore(
                    id=uuid4(),
                    subject_type=subject_type,
                    subject_id=subject_id,
                    score=Decimal(score) if score is not None else None,
                    components=components,
                    is_provisional=is_provisional,
                    last_calculated_at=datetime.now(UTC),
                )
            )


async def _create_deal(operator_id: UUID, contributor_id: UUID) -> None:
    """Create an open project by ``operator_id`` with a pending proposal."""
    async with async_session_factory() as session:
        async with session.begin():
            project = Project(
                id=uuid4(),
                operator_id=operator_id,
                title="Deal Project",
                description="Project for reputation gating test.",
                category="advisory",
                required_deliverables=[{"name": "report"}],
                budget_min=Decimal("1000.00"),
                budget_max=Decimal("5000.00"),
                currency="USD",
                status="open",
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
            session.add(project)
            await session.flush()
            session.add(
                Proposal(
                    id=uuid4(),
                    project_id=project.id,
                    contributor_id=contributor_id,
                    scope="Deliver the report.",
                    budget=Decimal("3000.00"),
                    currency="USD",
                    timeline_days=14,
                    deliverables=[{"name": "report"}],
                    status="pending",
                )
            )


async def _create_open_project(operator_id: UUID) -> UUID:
    """Create one open project owned by ``operator_id`` and return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            project = Project(
                id=uuid4(),
                operator_id=operator_id,
                title="Open Project",
                description="Open project for operator reputation surface test.",
                category="advisory",
                required_deliverables=[{"name": "report"}],
                budget_min=Decimal("1000.00"),
                budget_max=Decimal("5000.00"),
                currency="USD",
                status="open",
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
            session.add(project)
        return project.id


def _auth(user_id: UUID, roles: list[str]) -> dict[str, str]:
    """Build bearer auth headers for a test user."""
    token = create_access_token(user_id=user_id, roles=roles)
    return {"Authorization": f"Bearer {token}"}


_COMPONENTS = {
    "reviews": {"value": "0.9000", "label": "strong"},
    "attestations": {"value": "0.5000", "label": "moderate"},
    "adoption": {"value": "0.2000", "label": "weak"},
    "completion": {"value": "0.5000", "label": "moderate"},
    "recency": {"value": "0.5000", "label": "moderate"},
}


@pytest.mark.asyncio
async def test_framework_reputation_public_returns_labels_only(
    client: AsyncClient,
    migrated_database: None,
    reputation_api_context: FakeRedis,
) -> None:
    """Public framework read returns the score + factor labels, never raw values."""
    contributor_id = await _create_user("rep-fw-owner@example.com", ["contributor"])
    framework_id = await _create_framework(contributor_id)
    await _seed_score(
        "framework",
        framework_id,
        score="78.50",
        is_provisional=False,
        components=_COMPONENTS,
    )

    response = await client.get(f"/v1/reputation/framework/{framework_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["score"] == "78.50"
    assert body["is_provisional"] is False
    factor_names = {f["factor"] for f in body["factors"]}
    # Zero-weight launch factors (completion/recency) are not surfaced.
    assert factor_names == {"reviews", "attestations", "adoption"}
    for factor in body["factors"]:
        assert set(factor.keys()) == {"factor", "label"}
        assert factor["label"] in {"strong", "moderate", "weak"}


@pytest.mark.asyncio
async def test_framework_reputation_uncomputed_returns_provisional(
    client: AsyncClient,
    migrated_database: None,
    reputation_api_context: FakeRedis,
) -> None:
    """A framework with no score row reads as provisional with no factors."""
    contributor_id = await _create_user("rep-fw-new@example.com", ["contributor"])
    framework_id = await _create_framework(contributor_id)

    response = await client.get(f"/v1/reputation/framework/{framework_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["score"] is None
    assert body["is_provisional"] is True
    assert body["factors"] == []


@pytest.mark.asyncio
async def test_framework_reputation_unknown_subject_returns_404(
    client: AsyncClient,
    migrated_database: None,
    reputation_api_context: FakeRedis,
) -> None:
    """Reading reputation for a non-existent framework returns 404."""
    response = await client.get(f"/v1/reputation/framework/{uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_operator_reputation_visibility_gating(
    client: AsyncClient,
    migrated_database: None,
    reputation_api_context: FakeRedis,
) -> None:
    """Operator score is visible to self, in-deal contributor, admin; else 403."""
    operator_id = await _create_user("rep-operator@example.com", ["operator"])
    in_deal_id = await _create_user("rep-indeal@example.com", ["contributor"])
    stranger_id = await _create_user("rep-stranger@example.com", ["contributor"])
    admin_id = await _create_user("rep-admin@example.com", ["admin"])
    await _create_deal(operator_id, in_deal_id)
    await _seed_score(
        "operator",
        operator_id,
        score="64.00",
        is_provisional=False,
        components={"purchase_activity": {"value": "0.8000", "label": "strong"}},
    )

    path = f"/v1/reputation/operator/{operator_id}"
    self_resp = await client.get(path, headers=_auth(operator_id, ["operator"]))
    deal_resp = await client.get(path, headers=_auth(in_deal_id, ["contributor"]))
    admin_resp = await client.get(path, headers=_auth(admin_id, ["admin"]))
    stranger_resp = await client.get(
        path, headers=_auth(stranger_id, ["contributor"])
    )
    anon_resp = await client.get(path)

    assert self_resp.status_code == 200
    assert deal_resp.status_code == 200
    assert admin_resp.status_code == 200
    assert stranger_resp.status_code == 403
    assert anon_resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_recompute_requires_admin(
    client: AsyncClient,
    migrated_database: None,
    reputation_api_context: FakeRedis,
) -> None:
    """A non-admin cannot trigger a reputation recompute."""
    contributor_id = await _create_user("rep-noadmin@example.com", ["contributor"])
    framework_id = await _create_framework(contributor_id)

    response = await client.post(
        "/v1/admin/reputation/recompute",
        headers=_auth(contributor_id, ["contributor"]),
        json={
            "subject_type": "framework",
            "subject_id": str(framework_id),
            "reason": "manual refresh",
            "totp_code": "000000",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_recompute_queues_with_valid_2fa(
    client: AsyncClient,
    migrated_database: None,
    reputation_api_context: FakeRedis,
) -> None:
    """An admin with valid 2FA queues a single-subject recompute (202)."""
    secret = pyotp.random_base32()
    admin_id = await _create_user(
        "rep-admin2fa@example.com", ["admin"], totp_secret=secret
    )
    contributor_id = await _create_user("rep-subject@example.com", ["contributor"])
    framework_id = await _create_framework(contributor_id)

    dispatched: list[tuple[str, str]] = []

    from app.workers.tasks import reputation as reputation_tasks

    def _fake_delay(subject_type: str, subject_id: str) -> None:
        dispatched.append((subject_type, subject_id))

    original_delay = reputation_tasks.recompute_subject_task.delay
    reputation_tasks.recompute_subject_task.delay = _fake_delay  # type: ignore[method-assign]
    try:
        response = await client.post(
            "/v1/admin/reputation/recompute",
            headers=_auth(admin_id, ["admin"]),
            json={
                "subject_type": "framework",
                "subject_id": str(framework_id),
                "reason": "manual refresh",
                "totp_code": pyotp.TOTP(secret).now(),
            },
        )
    finally:
        reputation_tasks.recompute_subject_task.delay = original_delay  # type: ignore[method-assign]

    assert response.status_code == 202
    assert dispatched == [("framework", str(framework_id))]


@pytest.mark.asyncio
async def test_explore_framework_card_includes_reputation(
    client: AsyncClient,
    migrated_database: None,
    reputation_api_context: FakeRedis,
) -> None:
    """The public Explore catalog embeds a framework's reputation summary."""
    contributor_id = await _create_user("rep-card-owner@example.com", ["contributor"])
    framework_id = await _create_framework(contributor_id)
    await _seed_score(
        "framework",
        framework_id,
        score="81.00",
        is_provisional=False,
        components=_COMPONENTS,
    )

    response = await client.get("/v1/explore/frameworks")

    assert response.status_code == 200
    card = next(
        item for item in response.json()["items"] if item["id"] == str(framework_id)
    )
    assert card["reputation"] is not None
    assert card["reputation"]["score"] == "81.00"
    assert card["reputation"]["is_provisional"] is False
    factor_names = {f["factor"] for f in card["reputation"]["factors"]}
    assert factor_names == {"reviews", "attestations", "adoption"}


@pytest.mark.asyncio
async def test_contributor_profile_includes_reputation(
    client: AsyncClient,
    migrated_database: None,
    reputation_api_context: FakeRedis,
) -> None:
    """The public contributor profile embeds the contributor's reputation."""
    contributor_id = await _create_user("rep-prof-owner@example.com", ["contributor"])
    await _create_framework(contributor_id)
    await _seed_score(
        "contributor",
        contributor_id,
        score="72.00",
        is_provisional=False,
        components={"verification": {"value": "1.0000", "label": "strong"}},
    )

    response = await client.get(f"/v1/explore/contributors/{contributor_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["reputation"] is not None
    assert body["reputation"]["score"] == "72.00"


@pytest.mark.asyncio
async def test_provisional_framework_card_hides_numeric_score(
    client: AsyncClient,
    migrated_database: None,
    reputation_api_context: FakeRedis,
) -> None:
    """A provisional framework reads as "New": score suppressed on the card."""
    contributor_id = await _create_user("rep-card-new@example.com", ["contributor"])
    framework_id = await _create_framework(contributor_id)
    await _seed_score(
        "framework",
        framework_id,
        score="50.00",
        is_provisional=True,
        components=_COMPONENTS,
    )

    response = await client.get("/v1/explore/frameworks")

    card = next(
        item for item in response.json()["items"] if item["id"] == str(framework_id)
    )
    assert card["reputation"]["score"] is None
    assert card["reputation"]["is_provisional"] is True


@pytest.mark.asyncio
async def test_operator_reputation_on_project_for_contributor_not_operator(
    client: AsyncClient,
    migrated_database: None,
    reputation_api_context: FakeRedis,
) -> None:
    """Operator reputation rides the Project detail for a contributor, not self."""
    operator_id = await _create_user("rep-proj-operator@example.com", ["operator"])
    contributor_id = await _create_user("rep-proj-bidder@example.com", ["contributor"])
    project_id = await _create_open_project(operator_id)
    await _seed_score(
        "operator",
        operator_id,
        score="66.00",
        is_provisional=False,
        components={"purchase_activity": {"value": "0.9000", "label": "strong"}},
    )

    path = f"/v1/projects/{project_id}"
    contributor_resp = await client.get(
        path, headers=_auth(contributor_id, ["contributor"])
    )
    operator_resp = await client.get(path, headers=_auth(operator_id, ["operator"]))

    assert contributor_resp.status_code == 200
    assert contributor_resp.json()["operator_reputation"] is not None
    assert contributor_resp.json()["operator_reputation"]["score"] == "66.00"
    assert operator_resp.status_code == 200
    assert operator_resp.json()["operator_reputation"] is None
