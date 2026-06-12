"""Integration tests for Phase 5c Slice 5 GDPR account-deletion flows."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import (
    Escrow,
    Payout,
    PayoutAccount,
    PlatformConfig,
    Transaction,
)
from app.modules.gdpr.models import AccountDeletionRequest
from app.modules.projects.models import Dispute, Milestone, Project, Proposal
from app.shared.models.audit_log import AuditLog


class FakeRedis:
    """Redis test double for GDPR account-deletion security checks."""

    def __init__(self) -> None:
        """Create empty string and counter state."""
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.counters: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        """Return a string or counter value."""
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def delete(self, *keys: str) -> int:
        """Delete string and counter keys."""
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.counters)
            self.values.pop(key, None)
            self.counters.pop(key, None)
            self.ttls.pop(key, None)
        return removed

    async def incr(self, key: str) -> int:
        """Increment a counter and return it."""
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        """Record a TTL for a key."""
        self.ttls[key] = seconds

    async def ttl(self, key: str) -> int:
        """Return a TTL or Redis' no-expiry sentinel."""
        return self.ttls.get(key, -1)


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure GDPR account-deletion tables exist."""
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
async def account_deletion_test_context() -> AsyncIterator[dict[str, Any]]:
    """Reset GDPR/account state and install Redis overrides."""
    fake_redis = FakeRedis()
    await engine.dispose()
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AccountDeletionRequest))
            await session.execute(delete(AuditLog))
            await session.execute(delete(AttestationDispute))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(Attestation))
            await session.execute(delete(Payout))
            await session.execute(delete(PayoutAccount))
            await session.execute(delete(Dispute))
            await session.execute(delete(Milestone))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(Proposal))
            await session.execute(delete(Project))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            config = await session.get(PlatformConfig, "account_deletion_grace_days")
            if config is None:
                session.add(
                    PlatformConfig(
                        key="account_deletion_grace_days",
                        value="14",
                    )
                )
            else:
                config.value = "14"

    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield {"redis": fake_redis}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await engine.dispose()


async def create_verified_user(
    email: str,
    *,
    roles: list[str] | None = None,
    enable_totp: bool = False,
) -> tuple[UUID, str | None]:
    """Create a verified user and optional TOTP secret for GDPR tests."""
    secret = pyotp.random_base32() if enable_totp else None
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=email.split("@")[0],
                email_verified=True,
                totp_enabled=enable_totp,
                totp_secret=encrypt_totp_secret(secret) if secret else None,
            )
            session.add(user)
            await session.flush()
            for role in roles or ["operator"]:
                session.add(
                    UserRole(
                        user_id=user.id,
                        role=role,
                        approved_at=datetime.now(UTC),
                    )
                )
        return user.id, secret


def auth_headers(user_id: UUID, roles: list[str] | None = None) -> dict[str, str]:
    """Create bearer auth headers for one GDPR account-deletion test user."""
    token = create_access_token(user_id=user_id, roles=roles or ["operator"])
    return {"Authorization": f"Bearer {token}"}


async def seed_blocking_state(user_id: UUID) -> None:
    """Create one instance of every Slice 5 deletion-blocking obligation."""
    counterpart_id, _secret = await create_verified_user(
        f"counterparty-{uuid4()}@auracles.space",
        roles=["contributor", "attestor", "operator"],
    )
    async with async_session_factory() as session:
        async with session.begin():
            project = Project(
                operator_id=user_id,
                title="Blocking project",
                description="Project still in progress.",
                category="operations",
                required_deliverables=[{"name": "Playbook"}],
                budget_min=Decimal("500.00"),
                budget_max=Decimal("750.00"),
                currency="USD",
                status="disputed",
                milestone_plan_status="finalized",
                expires_at=datetime.now(UTC),
            )
            session.add(project)
            await session.flush()
            proposal = Proposal(
                project_id=project.id,
                contributor_id=counterpart_id,
                scope="Delivery scope",
                budget=Decimal("700.00"),
                currency="USD",
                timeline_days=14,
                deliverables=[{"name": "Playbook"}],
                status="accepted",
                accepted_at=datetime.now(UTC),
            )
            session.add(proposal)
            await session.flush()
            project.accepted_proposal_id = proposal.id

            milestone = Milestone(
                project_id=project.id,
                sequence=1,
                name="Milestone 1",
                description="Work in progress",
                budget=Decimal("700.00"),
                currency="USD",
                status="funded",
            )
            session.add(milestone)
            await session.flush()
            milestone_transaction = Transaction(
                payer_id=user_id,
                payee_id=counterpart_id,
                amount=Decimal("700.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("700.00"),
                transaction_type="milestone",
                status="completed",
                provider="stripe",
                provider_ref=f"pi_{uuid4().hex[:8]}",
                ref_id=milestone.id,
                ref_type="project_milestone",
            )
            session.add(milestone_transaction)
            await session.flush()
            escrow = Escrow(
                ref_id=milestone.id,
                ref_type="project_milestone",
                amount=Decimal("700.00"),
                currency="USD",
                status="held",
                release_conditions={"kind": "milestone"},
                transaction_id=milestone_transaction.id,
            )
            session.add(escrow)
            await session.flush()
            milestone.escrow_id = escrow.id

            dispute = Dispute(
                project_id=project.id,
                milestone_id=milestone.id,
                raised_by=user_id,
                reason="Still disputed",
                status="open",
            )
            session.add(dispute)

            payout_account = PayoutAccount(
                user_id=user_id,
                provider="stripe",
                provider_account_id="acct_blocking",
                provider_account_lookup_hash="blocking-hash",
                account_type="standard",
                verified_at=datetime.now(UTC),
            )
            session.add(payout_account)
            await session.flush()
            payout = Payout(
                contributor_id=user_id,
                payout_account_id=payout_account.id,
                amount=Decimal("100.00"),
                currency="USD",
                commission_deducted=Decimal("5.00"),
                net_amount=Decimal("95.00"),
                status="pending",
            )
            session.add(payout)

            attestation = Attestation(
                target_type="operator",
                target_id=user_id,
                requestor_id=user_id,
                attestor_id=counterpart_id,
                status="accepted",
                fee_amount=Decimal("300.00"),
                currency="USD",
                accepted_at=datetime.now(UTC),
            )
            session.add(attestation)


async def test_request_account_deletion_schedules_cooling_off_and_status_reads_it(
    client: AsyncClient,
    migrated_database: None,
    account_deletion_test_context: dict[str, Any],
) -> None:
    """A valid password-confirmed request schedules GDPR deletion."""
    del migrated_database, account_deletion_test_context
    user_id, _secret = await create_verified_user("delete-me@auracles.space")

    created = await client.post(
        "/v1/gdpr/account-deletion",
        headers=auth_headers(user_id),
        json={"password": "CorrectHorse9", "totp_code": None},
    )
    listed = await client.get(
        "/v1/gdpr/account-deletion",
        headers=auth_headers(user_id),
    )

    async with async_session_factory() as session:
        request = await session.scalar(
            select(AccountDeletionRequest).where(
                AccountDeletionRequest.user_id == user_id
            )
        )
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.actor_id == user_id,
                AuditLog.action == "account_deletion_requested",
            )
        )

    assert created.status_code == 202
    assert created.json()["status"] == "scheduled"
    assert created.json()["blocked_reasons"] == []
    assert created.json()["scheduled_for"] is not None
    assert listed.status_code == 200
    assert listed.json()["status"] == "scheduled"
    assert request is not None
    assert request.status == "scheduled"
    assert request.scheduled_for is not None
    assert audit is not None


async def test_get_account_deletion_status_returns_empty_state_without_request(
    client: AsyncClient,
    migrated_database: None,
    account_deletion_test_context: dict[str, Any],
) -> None:
    """Status returns an empty state before any deletion request exists."""
    del migrated_database, account_deletion_test_context
    user_id, _secret = await create_verified_user("delete-status@auracles.space")

    response = await client.get(
        "/v1/gdpr/account-deletion",
        headers=auth_headers(user_id),
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": None,
        "status": None,
        "blocked_reasons": [],
        "scheduled_for": None,
        "requested_at": None,
        "completed_at": None,
    }


async def test_request_account_deletion_blocks_when_unsettled_obligations_exist(
    client: AsyncClient,
    migrated_database: None,
    account_deletion_test_context: dict[str, Any],
) -> None:
    """Deletion is blocked when any Slice 5 obligation still exists."""
    del migrated_database, account_deletion_test_context
    user_id, _secret = await create_verified_user(
        "blocked-delete@auracles.space",
        roles=["operator", "contributor"],
    )
    await seed_blocking_state(user_id)

    response = await client.post(
        "/v1/gdpr/account-deletion",
        headers=auth_headers(user_id, ["operator", "contributor"]),
        json={"password": "CorrectHorse9", "totp_code": None},
    )

    async with async_session_factory() as session:
        request = await session.scalar(
            select(AccountDeletionRequest)
            .where(AccountDeletionRequest.user_id == user_id)
            .order_by(AccountDeletionRequest.requested_at.desc())
        )
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.actor_id == user_id,
                AuditLog.action == "account_deletion_blocked",
            )
        )

    assert response.status_code == 409
    assert response.json()["status"] == "blocked"
    assert {
        reason["code"] for reason in response.json()["blocked_reasons"]
    } == {
        "held_escrow",
        "pending_payout",
        "open_dispute",
        "in_progress_project",
        "active_attestation",
    }
    assert request is not None
    assert request.status == "blocked"
    assert audit is not None


async def test_request_account_deletion_requires_totp_when_enabled(
    client: AsyncClient,
    migrated_database: None,
    account_deletion_test_context: dict[str, Any],
) -> None:
    """TOTP-enabled users must confirm deletion requests with a 2FA code."""
    del migrated_database, account_deletion_test_context
    user_id, _secret = await create_verified_user(
        "delete-totp@auracles.space",
        enable_totp=True,
    )

    response = await client.post(
        "/v1/gdpr/account-deletion",
        headers=auth_headers(user_id),
        json={"password": "CorrectHorse9", "totp_code": None},
    )

    assert response.status_code == 403
    assert (
        response.json()["detail"]
        == "Confirm with your authenticator app before continuing."
    )


async def test_cancel_account_deletion_marks_scheduled_request_cancelled(
    client: AsyncClient,
    migrated_database: None,
    account_deletion_test_context: dict[str, Any],
) -> None:
    """Scheduled deletion requests remain cancellable during cooling-off."""
    del migrated_database, account_deletion_test_context
    user_id, _secret = await create_verified_user("delete-cancel@auracles.space")

    created = await client.post(
        "/v1/gdpr/account-deletion",
        headers=auth_headers(user_id),
        json={"password": "CorrectHorse9", "totp_code": None},
    )
    cancelled = await client.post(
        "/v1/gdpr/account-deletion/cancel",
        headers=auth_headers(user_id),
    )
    listed = await client.get(
        "/v1/gdpr/account-deletion",
        headers=auth_headers(user_id),
    )

    async with async_session_factory() as session:
        request = await session.scalar(
            select(AccountDeletionRequest)
            .where(AccountDeletionRequest.user_id == user_id)
            .order_by(AccountDeletionRequest.requested_at.desc())
        )
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.actor_id == user_id,
                AuditLog.action == "account_deletion_cancelled",
            )
        )

    assert created.status_code == 202
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert listed.status_code == 200
    assert listed.json()["status"] == "cancelled"
    assert request is not None
    assert request.status == "cancelled"
    assert audit is not None


async def test_legacy_settings_deactivate_endpoint_is_removed(
    client: AsyncClient,
    migrated_database: None,
    account_deletion_test_context: dict[str, Any],
) -> None:
    """The old settings deactivation endpoint is retired in favor of GDPR deletion."""
    del migrated_database, account_deletion_test_context
    user_id, _secret = await create_verified_user("legacy-delete@auracles.space")

    response = await client.post(
        "/v1/settings/account/deactivate",
        headers=auth_headers(user_id),
        json={"password": "CorrectHorse9"},
    )

    assert response.status_code == 404
