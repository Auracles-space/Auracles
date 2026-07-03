"""Integration tests for Phase 5c GDPR account-deletion flows and scrub worker."""

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
from sqlalchemy import create_engine, delete, or_, select

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, encrypt_totp_secret, hash_password
from app.main import app
from app.modules.attestation.models import (
    Attestation,
    AttestationDispute,
    AttestationOffer,
)
from app.modules.auth import service as auth_service
from app.modules.auth.models import (
    KycDocument,
    OAuthAccount,
    User,
    UserBackupCode,
    UserRole,
)
from app.modules.developer.models import (
    ApiKey,
    DeveloperAccount,
    DeveloperApplication,
    PartnerPayout,
)
from app.modules.financials.models import (
    Escrow,
    Payout,
    PayoutAccount,
    PlatformConfig,
    Transaction,
)
from app.modules.gdpr.models import AccountDeletionRequest
from app.modules.gdpr.schemas import AccountDeletionBlockedReason
from app.modules.projects.models import Dispute, Milestone, Project, Proposal
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import gdpr_beat


class FakeRedis:
    """Redis test double for GDPR account-deletion security checks."""

    def __init__(self) -> None:
        """Create empty string, set, and counter state."""
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
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
        """Delete string, set, and counter keys."""
        removed = 0
        for key in keys:
            removed += int(
                key in self.values or key in self.counters or key in self.sets
            )
            self.values.pop(key, None)
            self.sets.pop(key, None)
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

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """Store a string value with a TTL."""
        self.values[key] = value
        self.ttls[key] = seconds

    async def sadd(self, key: str, *members: str) -> int:
        """Add one or more members to a set."""
        bucket = self.sets.setdefault(key, set())
        before = len(bucket)
        bucket.update(str(member) for member in members)
        return len(bucket) - before

    async def smembers(self, key: str) -> set[str]:
        """Return the members stored for one set key."""
        return set(self.sets.get(key, set()))

    async def srem(self, key: str, *members: str) -> int:
        """Remove one or more members from a set."""
        bucket = self.sets.get(key)
        if bucket is None:
            return 0
        removed = 0
        for member in members:
            if member in bucket:
                bucket.remove(member)
                removed += 1
        if not bucket:
            self.sets.pop(key, None)
        return removed


class FakeS3Storage:
    """S3 test double that captures KYC document deletions."""

    def __init__(self) -> None:
        """Create empty deletion storage."""
        self.deleted_objects: list[tuple[str, str]] = []

    def delete_object(self, bucket: str, key: str) -> None:
        """Record a private object deletion request."""
        self.deleted_objects.append((bucket, key))


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
async def account_deletion_test_context(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[dict[str, Any]]:
    """Reset GDPR/account state and install Redis overrides."""
    fake_redis = FakeRedis()
    fake_s3 = FakeS3Storage()

    async def reset_database() -> None:
        """Remove account-deletion test data while preserving config rows."""
        await engine.dispose()
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(delete(AccountDeletionRequest))
                await session.execute(delete(AuditLog))
                await session.execute(delete(ApiKey))
                await session.execute(delete(PartnerPayout))
                await session.execute(delete(DeveloperAccount))
                await session.execute(delete(DeveloperApplication))
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
                config = await session.get(
                    PlatformConfig,
                    "account_deletion_grace_days",
                )
                if config is None:
                    session.add(
                        PlatformConfig(
                            key="account_deletion_grace_days",
                            value="14",
                        )
                    )
                else:
                    config.value = "14"

    await reset_database()

    app.dependency_overrides[get_redis] = lambda: fake_redis
    monkeypatch.setattr(gdpr_beat.s3, "storage", fake_s3)
    try:
        yield {"redis": fake_redis, "s3": fake_s3}
    finally:
        app.dependency_overrides.pop(get_redis, None)
        await reset_database()


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


async def seed_scrub_state(
    *,
    user_id: UUID,
    redis: FakeRedis,
) -> dict[str, Any]:
    """Create durable state that the anonymisation worker must scrub or retain."""
    old_email = "scrub-me@auracles.space"
    refresh_token = "refresh-token-for-deletion"
    family_id = "family-for-deletion"
    original_password_hash: str | None = None
    async with async_session_factory() as session:
        async with session.begin():
            user = await session.get(User, user_id, with_for_update=True)
            assert user is not None
            original_password_hash = user.password_hash
            user.email = old_email
            user.display_name = "Scrub Me"
            user.avatar_url = "https://cdn.auracles.space/avatar.png"
            user.bio = "Detailed personal bio"
            user.location = "Lagos"
            user.website = "https://scrub-me.example"
            user.stripe_customer_id = "cus_delete_me"
            user.kyc_status = "verified"

            session.add(
                OAuthAccount(
                    user_id=user_id,
                    provider="google",
                    provider_id="google-user-1",
                )
            )
            session.add(
                UserBackupCode(
                    user_id=user_id,
                    code_hash=auth_service._backup_code_hash("backup-code-1"),  # noqa: SLF001
                )
            )
            session.add(
                KycDocument(
                    user_id=user_id,
                    doc_type="passport",
                    s3_key="kyc/delete-me/passport.pdf",
                    mime_type="application/pdf",
                    file_size=2048,
                    status="verified",
                )
            )

            developer_application = DeveloperApplication(
                user_id=user_id,
                company_name="Delete Me Labs",
                use_case="Partner API access",
                status="approved",
                reviewed_at=datetime.now(UTC),
            )
            session.add(developer_application)
            await session.flush()
            developer_account = DeveloperAccount(
                user_id=user_id,
                application_id=developer_application.id,
                company_name="Delete Me Labs",
                status="active",
            )
            session.add(developer_account)
            await session.flush()
            session.add(
                ApiKey(
                    developer_account_id=developer_account.id,
                    name="Primary key",
                    key_prefix="ak_delete123",
                    key_hash="deadbeef" * 8,
                    scopes=["catalog:read"],
                    status="active",
                )
            )

            payout_account = PayoutAccount(
                user_id=user_id,
                provider="stripe",
                provider_account_id="acct_live_delete_me",
                provider_account_lookup_hash="lookup-hash-delete-me",
                account_type="standard",
                is_default=True,
                verified_at=datetime.now(UTC),
            )
            session.add(payout_account)

            session.add(
                AuditLog(
                    actor_id=user_id,
                    action="account_email_change_requested",
                    target_type="user",
                    target_id=user_id,
                    metadata_={
                        "new_email": old_email,
                        "uploaded_filename": "passport.pdf",
                        "provider_ref": "pi_123456",
                        "raw_url": "https://files.auracles.space/private",
                        "safe": "retained",
                        "summary": "Escalate with counterparty@example.com before release",
                        "note": f"Contact {old_email} before release",
                    },
                    ip_address="127.0.0.1",
                    user_agent="Deletion test browser",
                )
            )

            deletion_request = AccountDeletionRequest(
                user_id=user_id,
                status="scheduled",
                blocked_reasons=[],
                scheduled_for=datetime.now(UTC) - timedelta(hours=2),
                requested_at=datetime.now(UTC) - timedelta(days=14),
            )
            session.add(deletion_request)

    await auth_service._store_refresh_token(  # noqa: SLF001
        redis=redis,
        token=refresh_token,
        user_id=user_id,
        family_id=family_id,
        ip="127.0.0.1",
        ua="Deletion test browser",
        totp_verified=True,
    )
    return {
        "old_email": old_email,
        "original_password_hash": original_password_hash,
        "refresh_session_id": auth_service.refresh_session_id(refresh_token),
    }


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


async def seed_partner_payout_state(user_id: UUID) -> None:
    """Create one pending Partner payout that must block GDPR deletion."""
    async with async_session_factory() as session:
        async with session.begin():
            application = DeveloperApplication(
                user_id=user_id,
                company_name="GDPR Partner Payout Co.",
                use_case="Partner commission payout blocking test.",
                status="approved",
                reviewed_at=datetime.now(UTC),
            )
            session.add(application)
            await session.flush()

            account = DeveloperAccount(
                user_id=user_id,
                application_id=application.id,
                company_name=application.company_name,
            )
            session.add(account)

            payout_account = PayoutAccount(
                user_id=user_id,
                provider="stripe",
                provider_account_id="acct_gdpr_partner_block",
                provider_account_lookup_hash="lookup-gdpr-partner-block",
                account_type="express",
                is_default=True,
                verified_at=datetime.now(UTC),
            )
            session.add(payout_account)
            await session.flush()

            session.add(
                PartnerPayout(
                    developer_account_id=account.id,
                    payout_account_id=payout_account.id,
                    amount=Decimal("55.00"),
                    currency="USD",
                    status="pending",
                )
            )


async def clear_blocking_state(user_id: UUID) -> None:
    """Move seeded deletion blockers into terminal states for one user.

    This helper simulates the post-resolution state after the user has closed
    active work, payouts, disputes, escrows, and attestations.
    """
    async with async_session_factory() as session:
        async with session.begin():
            payouts = list(
                (
                    await session.execute(
                        select(Payout).where(Payout.contributor_id == user_id)
                    )
                ).scalars()
            )
            for payout in payouts:
                payout.status = "completed"

            projects = list(
                (
                    await session.execute(
                        select(Project).where(Project.operator_id == user_id)
                    )
                ).scalars()
            )
            for project in projects:
                project.status = "closed"
                project.closed_at = datetime.now(UTC)

            disputes = list(
                (
                    await session.execute(
                        select(Dispute)
                        .join(Project, Project.id == Dispute.project_id)
                        .where(Project.operator_id == user_id)
                    )
                ).scalars()
            )
            for dispute in disputes:
                dispute.status = "resolved"
                dispute.resolution_type = "release"
                dispute.resolved_at = datetime.now(UTC)

            escrows = list(
                (
                    await session.execute(
                        select(Escrow)
                        .join(Milestone, Milestone.id == Escrow.ref_id)
                        .join(Project, Project.id == Milestone.project_id)
                        .where(
                            Escrow.ref_type == "project_milestone",
                            Project.operator_id == user_id,
                        )
                    )
                ).scalars()
            )
            for escrow in escrows:
                escrow.status = "released"

            attestations = list(
                (
                    await session.execute(
                        select(Attestation).where(
                            or_(
                                Attestation.requestor_id == user_id,
                                Attestation.attestor_id == user_id,
                            )
                        )
                    )
                ).scalars()
            )
            for attestation in attestations:
                attestation.status = "cancelled"


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


async def test_request_account_deletion_passwordless_account_skips_password(
    client: AsyncClient,
    migrated_database: None,
    account_deletion_test_context: dict[str, Any],
) -> None:
    """A passwordless (Google) account schedules deletion without a password.

    The grace period is the safety net; no password is demanded of an account
    that has none. TOTP would still apply if the account had enabled it.
    """
    del account_deletion_test_context
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email="google-delete@auracles.space",
                password_hash=None,
                display_name="Google Delete",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserRole(
                    user_id=user.id, role="operator", approved_at=datetime.now(UTC)
                )
            )
        user_id = user.id

    created = await client.post(
        "/v1/gdpr/account-deletion",
        headers=auth_headers(user_id),
        json={},
    )

    assert created.status_code == 202
    assert created.json()["status"] == "scheduled"


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
    assert {reason["code"] for reason in response.json()["blocked_reasons"]} == {
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


async def test_request_account_deletion_blocks_when_partner_payout_is_pending(
    client: AsyncClient,
    migrated_database: None,
    account_deletion_test_context: dict[str, Any],
) -> None:
    """Pending Partner payouts block GDPR deletion for Developer users."""
    del migrated_database, account_deletion_test_context
    user_id, _secret = await create_verified_user(
        "partner-payout-block@auracles.space",
        roles=["developer"],
    )
    await seed_partner_payout_state(user_id)

    response = await client.post(
        "/v1/gdpr/account-deletion",
        headers=auth_headers(user_id, ["developer"]),
        json={"password": "CorrectHorse9", "totp_code": None},
    )

    assert response.status_code == 409
    assert response.json()["status"] == "blocked"
    assert {reason["code"] for reason in response.json()["blocked_reasons"]} == {
        "pending_payout"
    }


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


async def test_blocked_deletion_can_be_re_requested_after_obligations_clear(
    client: AsyncClient,
    migrated_database: None,
    account_deletion_test_context: dict[str, Any],
) -> None:
    """A blocked user can schedule and cancel deletion after clearing blockers."""
    del migrated_database, account_deletion_test_context
    user_id, _secret = await create_verified_user(
        "delete-retry@auracles.space",
        roles=["operator", "contributor"],
    )
    await seed_blocking_state(user_id)

    blocked = await client.post(
        "/v1/gdpr/account-deletion",
        headers=auth_headers(user_id, ["operator", "contributor"]),
        json={"password": "CorrectHorse9", "totp_code": None},
    )

    await clear_blocking_state(user_id)

    scheduled = await client.post(
        "/v1/gdpr/account-deletion",
        headers=auth_headers(user_id, ["operator", "contributor"]),
        json={"password": "CorrectHorse9", "totp_code": None},
    )
    cancelled = await client.post(
        "/v1/gdpr/account-deletion/cancel",
        headers=auth_headers(user_id, ["operator", "contributor"]),
    )

    async with async_session_factory() as session:
        requests = list(
            (
                await session.execute(
                    select(AccountDeletionRequest)
                    .where(AccountDeletionRequest.user_id == user_id)
                    .order_by(AccountDeletionRequest.requested_at.asc())
                )
            ).scalars()
        )

    assert blocked.status_code == 409
    assert blocked.json()["status"] == "blocked"
    assert scheduled.status_code == 202
    assert scheduled.json()["status"] == "scheduled"
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert [request.status for request in requests] == ["blocked", "cancelled"]


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


async def test_process_account_deletions_scrubs_due_scheduled_user_state(
    migrated_database: None,
    account_deletion_test_context: dict[str, Any],
) -> None:
    """The hourly worker anonymises a due scheduled request and revokes access."""
    del migrated_database
    user_id, _secret = await create_verified_user(
        "worker-delete@auracles.space",
        roles=["operator", "developer"],
        enable_totp=True,
    )
    seeded = await seed_scrub_state(
        user_id=user_id,
        redis=account_deletion_test_context["redis"],
    )

    result = await gdpr_beat._process_account_deletions_impl(
        redis=account_deletion_test_context["redis"]
    )

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        request = await session.scalar(
            select(AccountDeletionRequest).where(
                AccountDeletionRequest.user_id == user_id
            )
        )
        kyc_documents = list(
            (
                await session.execute(
                    select(KycDocument).where(KycDocument.user_id == user_id)
                )
            ).scalars()
        )
        oauth_accounts = list(
            (
                await session.execute(
                    select(OAuthAccount).where(OAuthAccount.user_id == user_id)
                )
            ).scalars()
        )
        backup_codes = list(
            (
                await session.execute(
                    select(UserBackupCode).where(UserBackupCode.user_id == user_id)
                )
            ).scalars()
        )
        payout_account = await session.scalar(
            select(PayoutAccount).where(PayoutAccount.user_id == user_id)
        )
        api_key = await session.scalar(
            select(ApiKey).where(ApiKey.key_prefix == "ak_delete123")
        )
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.actor_id == user_id,
                AuditLog.action == "account_email_change_requested",
            )
        )
        completion_audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.actor_id == user_id,
                AuditLog.action == "account_deletion_completed",
            )
        )

    assert result == {"processed_count": 1, "skipped_count": 0}
    assert user is not None
    assert user.email == f"deleted+{user_id}@tombstone.invalid"
    assert user.password_hash != seeded["original_password_hash"]
    assert user.display_name == "Deleted user"
    assert user.avatar_url is None
    assert user.bio is None
    assert user.location is None
    assert user.website is None
    assert user.stripe_customer_id is None
    assert user.kyc_status == "unverified"
    assert user.email_verified is False
    assert user.totp_secret is None
    assert user.totp_enabled is False
    assert user.deactivated_at is not None
    assert request is not None
    assert request.status == "completed"
    assert request.completed_at is not None
    assert request.blocked_reasons == []
    assert kyc_documents == []
    assert oauth_accounts == []
    assert backup_codes == []
    assert payout_account is not None
    assert payout_account.deleted_at is not None
    assert payout_account.is_default is False
    assert payout_account.provider_account_id != "acct_live_delete_me"
    assert payout_account.provider_account_lookup_hash != "lookup-hash-delete-me"
    assert api_key is not None
    assert api_key.status == "revoked"
    assert api_key.revoked_at is not None
    assert audit is not None
    assert audit.metadata_ == {"safe": "retained"}
    assert audit.ip_address is None
    assert audit.user_agent is None
    assert completion_audit is not None
    assert account_deletion_test_context["s3"].deleted_objects == [
        (
            app.state.settings.s3_artifacts_bucket,
            "kyc/delete-me/passport.pdf",
        )
    ]
    assert (
        await account_deletion_test_context["redis"].get(
            f"refresh:{seeded['refresh_session_id']}"
        )
        is None
    )
    assert (
        await account_deletion_test_context["redis"].smembers(f"refresh_user:{user_id}")
        == set()
    )


async def test_process_account_deletions_skips_due_requests_with_live_obligations(
    migrated_database: None,
    account_deletion_test_context: dict[str, Any],
) -> None:
    """The hourly worker re-checks obligations before completing deletion."""
    del migrated_database
    user_id, _secret = await create_verified_user(
        "worker-blocked@auracles.space",
        roles=["operator", "contributor"],
    )
    await seed_blocking_state(user_id)
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                AccountDeletionRequest(
                    user_id=user_id,
                    status="scheduled",
                    blocked_reasons=[],
                    scheduled_for=datetime.now(UTC) - timedelta(hours=1),
                    requested_at=datetime.now(UTC) - timedelta(days=14),
                )
            )

    result = await gdpr_beat._process_account_deletions_impl(
        redis=account_deletion_test_context["redis"]
    )

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        request = await session.scalar(
            select(AccountDeletionRequest).where(
                AccountDeletionRequest.user_id == user_id
            )
        )
        completion_audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.actor_id == user_id,
                AuditLog.action == "account_deletion_completed",
            )
        )

    assert result == {"processed_count": 0, "skipped_count": 1}
    assert user is not None
    assert user.deactivated_at is None
    assert user.email == "worker-blocked@auracles.space"
    assert request is not None
    assert request.status == "scheduled"
    assert {reason["code"] for reason in (request.blocked_reasons or [])} == {
        "held_escrow",
        "pending_payout",
        "open_dispute",
        "in_progress_project",
        "active_attestation",
    }
    assert request.completed_at is None
    assert completion_audit is None


async def test_process_account_deletions_defers_side_effects_until_final_recheck(
    migrated_database: None,
    account_deletion_test_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Late blockers must prevent pre-commit KYC deletion and session revocation."""
    del migrated_database
    user_id, _secret = await create_verified_user(
        "worker-race@auracles.space",
        roles=["operator", "developer"],
        enable_totp=True,
    )
    seeded = await seed_scrub_state(
        user_id=user_id,
        redis=account_deletion_test_context["redis"],
    )
    reasons_by_call = [
        [],
        [
            AccountDeletionBlockedReason(
                code="pending_payout",
                message=(
                    "Wait for pending payouts to settle before requesting "
                    "account deletion."
                ),
                count=1,
            )
        ],
    ]

    async def fake_collect_blocked_reasons(
        *,
        db: Any,
        user_id: UUID,
    ) -> list[AccountDeletionBlockedReason]:
        """Simulate a blocker appearing between the two Beat checks."""
        del db, user_id
        return reasons_by_call.pop(0) if reasons_by_call else []

    monkeypatch.setattr(
        gdpr_beat.deletion_service,
        "collect_blocked_reasons",
        fake_collect_blocked_reasons,
    )

    result = await gdpr_beat._process_account_deletions_impl(
        redis=account_deletion_test_context["redis"]
    )

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        request = await session.scalar(
            select(AccountDeletionRequest).where(
                AccountDeletionRequest.user_id == user_id
            )
        )
        kyc_documents = list(
            (
                await session.execute(
                    select(KycDocument).where(KycDocument.user_id == user_id)
                )
            ).scalars()
        )

    assert result == {"processed_count": 0, "skipped_count": 1}
    assert user is not None
    assert user.deactivated_at is None
    assert request is not None
    assert request.status == "scheduled"
    assert {reason["code"] for reason in (request.blocked_reasons or [])} == {
        "pending_payout"
    }
    assert len(kyc_documents) == 1
    assert account_deletion_test_context["s3"].deleted_objects == []
    assert (
        await account_deletion_test_context["redis"].get(
            f"refresh:{seeded['refresh_session_id']}"
        )
        is not None
    )
