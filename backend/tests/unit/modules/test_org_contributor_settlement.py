"""Unit tests for org contributor settlement and shared legal identity.

Starts with the money-path re-point: published Framework purchases should
credit the organization beneficiary when the seller is org-owned, while the
existing individual contributor path remains unchanged.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, select

from app.core.database import async_session_factory, engine
from app.core.security import encrypt_totp_secret, hash_password
from app.main import app
from app.modules.auth.models import User
from app.modules.financials import escrow_service
from app.modules.financials import invoices as financials_invoices
from app.modules.financials import service as financials_service
from app.modules.financials.models import Escrow, Payout, PayoutAccount, Transaction
from app.modules.financials.schemas import PayoutRequest, PurchaseRequest
from app.modules.frameworks.models import Framework, License
from app.modules.organizations import legal_profile_service
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgLegalProfile,
    OrgMember,
)
from app.modules.projects.models import Milestone, Project, Proposal
from app.shared.models.audit_log import AuditLog
from tests.support.db_cleanup import clear_identity_state_async

BACKEND_DIR = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.asyncio


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the current schema exists for org contributor settlement tests."""
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
async def settlement_state() -> AsyncIterator[None]:
    """Reset settlement rows around each org contributor settlement test."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete settlement rows before shared identity cleanup."""
        async with async_session_factory() as session:
            await session.execute(delete(AuditLog))
            await session.execute(delete(License))
            await session.execute(delete(Payout))
            await session.execute(delete(PayoutAccount))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(Framework))
            await session.execute(delete(Milestone))
            await session.execute(delete(Project))
            await session.execute(delete(Proposal))
            await session.execute(delete(OrgLegalProfile))
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


async def _create_user(
    prefix: str,
    *,
    stripe_customer_id: str | None = None,
    totp_secret: str | None = None,
) -> User:
    """Create and return one verified user for settlement tests."""
    email = f"{prefix}-{uuid4().hex[:8]}@auracles.space"
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=email,
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
                stripe_customer_id=stripe_customer_id,
                totp_enabled=totp_secret is not None,
                totp_secret=(
                    encrypt_totp_secret(totp_secret)
                    if totp_secret is not None
                    else None
                ),
            )
            session.add(user)
            await session.flush()
            await session.refresh(user)
            return user


async def _create_org(owner_id: UUID) -> Organization:
    """Create and return one organization with an owner membership."""
    async with async_session_factory() as session:
        async with session.begin():
            organization = Organization(
                slug=f"settlement-org-{uuid4().hex[:8]}",
                name="Settlement Org",
                country="US",
                created_by=owner_id,
            )
            session.add(organization)
            await session.flush()
            session.add(
                OrgMember(org_id=organization.id, user_id=owner_id, role="owner")
            )
            await session.refresh(organization)
            return organization


async def _create_published_framework(
    *,
    contributor_id: UUID | None,
    contributor_org_id: UUID | None,
) -> UUID:
    """Create and return one published Framework owned by a user or org."""
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor_id,
                contributor_org_id=contributor_org_id,
                title="Revenue Operations Playbook",
                description="A practical operating system for revenue teams.",
                status="published",
                category="operations",
                sector="technology",
                industry="software",
                business_function="revenue_operations",
                tags=["revenue", "operations"],
                price=Decimal("149.00"),
                currency="USD",
                license_types=["single_user", "team"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            return framework.id


async def _create_project(operator_id: UUID) -> Project:
    """Create and return one Project ready for accepted-Proposal settlement."""
    async with async_session_factory() as session:
        async with session.begin():
            project = Project(
                operator_id=operator_id,
                title="Org Delivery Project",
                description="A project used to test org settlement.",
                category="operations",
                required_deliverables=[
                    {"name": "Playbook", "description": "Implementation guide"}
                ],
                budget_min=Decimal("1000.00"),
                budget_max=Decimal("2000.00"),
                currency="USD",
                expires_at=datetime.now(UTC),
                status="assigned",
            )
            session.add(project)
            await session.flush()
            await session.refresh(project)
            return project


async def _seed_org_milestone_escrow(
    *,
    operator_id: UUID,
    org_id: UUID,
) -> tuple[UUID, UUID]:
    """Seed a held milestone escrow for an accepted org-owned Proposal."""
    async with async_session_factory() as session:
        async with session.begin():
            project = Project(
                operator_id=operator_id,
                title="Org Delivery Project",
                description="A project used to test org settlement.",
                category="operations",
                required_deliverables=[
                    {"name": "Playbook", "description": "Implementation guide"}
                ],
                budget_min=Decimal("1000.00"),
                budget_max=Decimal("2000.00"),
                currency="USD",
                expires_at=datetime.now(UTC),
                status="assigned",
            )
            session.add(project)
            await session.flush()
            proposal = Proposal(
                project_id=project.id,
                contributor_id=None,
                contributor_org_id=org_id,
                scope="Deliver the operating model and rollout plan.",
                budget=Decimal("1500.00"),
                currency="USD",
                timeline_days=21,
                deliverables=[
                    {"name": "Operating model", "description": "Documented model"}
                ],
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
                description="Initial milestone.",
                budget=Decimal("1000.00"),
                currency="USD",
                status="funded",
            )
            session.add(milestone)
            await session.flush()
            transaction = Transaction(
                payer_id=operator_id,
                payee_id=None,
                payee_org_id=None,
                amount=Decimal("1000.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("1000.00"),
                transaction_type="milestone",
                status="completed",
                provider="stripe",
                provider_ref="pi_milestone_org",
                ref_id=milestone.id,
                ref_type="project_milestone",
            )
            session.add(transaction)
            await session.flush()
            escrow = Escrow(
                ref_id=milestone.id,
                ref_type="project_milestone",
                amount=Decimal("1000.00"),
                currency="USD",
                status="held",
                release_conditions={},
                transaction_id=transaction.id,
            )
            session.add(escrow)
            await session.flush()
            return escrow.id, transaction.id


class _FakeRedis:
    """Async Redis double supporting TOTP-sensitive payout checks."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        if key in self.values:
            return self.values[key]
        if key in self.counters:
            return str(self.counters[key])
        return None

    async def incr(self, key: str) -> int:
        self.counters[key] = int(await self.get(key) or "0") + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        self.ttls[key] = seconds

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            removed += int(key in self.values or key in self.counters)
            self.values.pop(key, None)
            self.counters.pop(key, None)
            self.ttls.pop(key, None)
        return removed


async def _seed_contributor_org_financials(
    *,
    org_id: UUID,
    owner_id: UUID,
    include_tax_document: bool,
) -> UUID:
    """Seed contributor-capability org payout prerequisites and earnings."""
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgCapability(
                    org_id=org_id,
                    capability="contributor",
                    status="active",
                )
            )
            session.add(
                OrgLegalProfile(
                    org_id=org_id,
                    legal_name="Settlement Org LLC",
                    registration_number="RC-123456",
                    address={"country": "US", "city": "New York"},
                    tax_document_type="w9" if include_tax_document else None,
                    tax_document_key=(
                        "org-legal-profiles/tax-doc.pdf"
                        if include_tax_document
                        else None
                    ),
                )
            )
            payout_account = PayoutAccount(
                org_id=org_id,
                provider="stripe",
                provider_account_id="acct_settlement",
                provider_account_lookup_hash="acct_settlement_hash",
                account_type="express",
                is_default=True,
                verified_at=datetime.now(UTC),
            )
            session.add(payout_account)
            transaction = Transaction(
                payer_id=owner_id,
                payee_id=None,
                payee_org_id=org_id,
                amount=Decimal("1000.00"),
                currency="USD",
                platform_commission=Decimal("0.00"),
                net_amount=Decimal("1000.00"),
                transaction_type="purchase",
                status="completed",
                provider="stripe",
                provider_ref="pi_contributor_org_purchase",
                ref_id=uuid4(),
                ref_type="framework",
                created_at=datetime.now(UTC) - timedelta(hours=72),
            )
            session.add(transaction)
            await session.flush()
            return payout_account.id


@pytest.mark.asyncio
async def test_create_framework_purchase_credits_org_beneficiary(
    migrated_database: None,
    settlement_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An org-owned Framework purchase must credit ``payee_org_id`` only."""
    del migrated_database, settlement_state
    operator = await _create_user("operator", stripe_customer_id="cus_operator")
    owner = await _create_user("org-owner")
    organization = await _create_org(owner.id)
    framework_id = await _create_published_framework(
        contributor_id=None,
        contributor_org_id=organization.id,
    )

    async def fake_create_payment_intent(**_: object) -> SimpleNamespace:
        """Return a fake PaymentIntent so the local transaction persists."""
        return SimpleNamespace(id="pi_org_purchase", client_secret="secret_org")

    monkeypatch.setattr(
        financials_service.stripe,
        "create_payment_intent",
        fake_create_payment_intent,
    )

    async with async_session_factory() as session:
        response = await financials_service.create_framework_purchase(
            session,
            operator,
            framework_id=framework_id,
            payload=PurchaseRequest(license_type="single_user"),
        )

    async with async_session_factory() as session:
        transaction = await session.scalar(
            select(Transaction).where(Transaction.id == response.transaction_id)
        )

    assert transaction is not None
    assert transaction.payee_org_id == organization.id
    assert transaction.payee_id is None


@pytest.mark.asyncio
async def test_create_framework_purchase_keeps_individual_beneficiary(
    migrated_database: None,
    settlement_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user-owned Framework purchase must keep the existing ``payee_id`` path."""
    del migrated_database, settlement_state
    operator = await _create_user("operator", stripe_customer_id="cus_operator")
    contributor = await _create_user("contributor")
    framework_id = await _create_published_framework(
        contributor_id=contributor.id,
        contributor_org_id=None,
    )

    async def fake_create_payment_intent(**_: object) -> SimpleNamespace:
        """Return a fake PaymentIntent so the local transaction persists."""
        return SimpleNamespace(id="pi_user_purchase", client_secret="secret_user")

    monkeypatch.setattr(
        financials_service.stripe,
        "create_payment_intent",
        fake_create_payment_intent,
    )

    async with async_session_factory() as session:
        response = await financials_service.create_framework_purchase(
            session,
            operator,
            framework_id=framework_id,
            payload=PurchaseRequest(license_type="single_user"),
        )

    async with async_session_factory() as session:
        transaction = await session.scalar(
            select(Transaction).where(Transaction.id == response.transaction_id)
        )

    assert transaction is not None
    assert transaction.payee_id == contributor.id
    assert transaction.payee_org_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("suspend", [True, False])
async def test_create_framework_purchase_blocks_inactive_org_seller(
    migrated_database: None,
    settlement_state: None,
    monkeypatch: pytest.MonkeyPatch,
    suspend: bool,
) -> None:
    """Purchasing an org-owned Framework must 404 once the org is inactive.

    Mirrors the individual-seller suspension guard: an admin trust action
    (suspension) or owner deactivation must stop new sales settling to the
    organization, matching catalog visibility.
    """
    del migrated_database, settlement_state
    operator = await _create_user("operator", stripe_customer_id="cus_operator")
    owner = await _create_user("org-owner")
    organization = await _create_org(owner.id)
    framework_id = await _create_published_framework(
        contributor_id=None,
        contributor_org_id=organization.id,
    )

    async def fail_create_payment_intent(**_: object) -> SimpleNamespace:
        """Fail loudly if checkout reaches the provider for an inactive seller."""
        raise AssertionError("Stripe must not be called for an inactive org seller.")

    monkeypatch.setattr(
        financials_service.stripe,
        "create_payment_intent",
        fail_create_payment_intent,
    )

    async with async_session_factory() as session:
        async with session.begin():
            org_row = await session.get(Organization, organization.id)
            assert org_row is not None
            if suspend:
                org_row.suspended_at = datetime.now(UTC)
            else:
                org_row.deactivated_at = datetime.now(UTC)

    with pytest.raises(HTTPException) as exc_info:
        async with async_session_factory() as session:
            await financials_service.create_framework_purchase(
                session,
                operator,
                framework_id=framework_id,
                payload=PurchaseRequest(license_type="single_user"),
            )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_release_project_escrow_credits_org_beneficiary(
    migrated_database: None,
    settlement_state: None,
) -> None:
    """Releasing an org-owned Milestone escrow must credit ``payee_org_id`` only."""
    del migrated_database, settlement_state
    operator = await _create_user("operator")
    owner = await _create_user("org-owner")
    organization = await _create_org(owner.id)
    escrow_id, transaction_id = await _seed_org_milestone_escrow(
        operator_id=operator.id,
        org_id=organization.id,
    )

    async with async_session_factory() as session:
        await escrow_service.release(
            session,
            escrow_id=escrow_id,
            actor_id=operator.id,
            reason="deliverable_approved",
        )
        await session.commit()

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, transaction_id)
        escrow = await session.get(Escrow, escrow_id)

    assert transaction is not None
    assert transaction.payee_org_id == organization.id
    assert transaction.payee_id is None
    assert escrow is not None
    assert escrow.status == "released"


@pytest.mark.asyncio
async def test_request_org_payout_allows_active_contributor_org_with_tax_document(
    migrated_database: None,
    settlement_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active contributor org can request payout with tax doc and account."""
    del migrated_database, settlement_state
    fake_task = SimpleNamespace(dispatched=[])

    def _delay(payout_id: str) -> None:
        fake_task.dispatched.append(payout_id)

    fake_task.delay = _delay
    monkeypatch.setattr(financials_service, "process_payout", fake_task, raising=False)

    owner_secret = pyotp.random_base32()
    owner = await _create_user("org-owner", totp_secret=owner_secret)
    organization = await _create_org(owner.id)
    payout_account_id = await _seed_contributor_org_financials(
        org_id=organization.id,
        owner_id=owner.id,
        include_tax_document=True,
    )

    async with async_session_factory() as session:
        payout = await financials_service.request_org_payout(
            session,
            _FakeRedis(),
            org_id=organization.id,
            actor=owner,
            payload=PayoutRequest(
                amount=Decimal("100.00"),
                currency="USD",
                payout_account_id=payout_account_id,
                totp_code=pyotp.TOTP(owner_secret).now(),
            ),
        )

    assert payout.net_amount == Decimal("100.00")
    async with async_session_factory() as session:
        payout_row = await session.scalar(select(Payout))

    assert payout_row is not None
    assert payout_row.org_id == organization.id
    assert payout_row.contributor_id is None
    assert fake_task.dispatched == [str(payout_row.id)]


@pytest.mark.asyncio
async def test_request_org_payout_blocks_contributor_org_without_tax_document(
    migrated_database: None,
    settlement_state: None,
) -> None:
    """A contributor org without a tax document cannot request payout."""
    del migrated_database, settlement_state
    owner_secret = pyotp.random_base32()
    owner = await _create_user("org-owner", totp_secret=owner_secret)
    organization = await _create_org(owner.id)
    payout_account_id = await _seed_contributor_org_financials(
        org_id=organization.id,
        owner_id=owner.id,
        include_tax_document=False,
    )

    async with async_session_factory() as session:
        with pytest.raises(Exception) as excinfo:
            await financials_service.request_org_payout(
                session,
                _FakeRedis(),
                org_id=organization.id,
                actor=owner,
                payload=PayoutRequest(
                    amount=Decimal("100.00"),
                    currency="USD",
                    payout_account_id=payout_account_id,
                    totp_code=pyotp.TOTP(owner_secret).now(),
                ),
            )

    assert getattr(excinfo.value, "status_code", None) == 403


@pytest.mark.asyncio
async def test_upsert_legal_profile_requires_valid_totp_and_persists_profile(
    migrated_database: None,
    settlement_state: None,
) -> None:
    """Upserting the shared legal profile must require TOTP and persist values."""
    del migrated_database, settlement_state
    owner_secret = pyotp.random_base32()
    owner = await _create_user("org-owner", totp_secret=owner_secret)
    organization = await _create_org(owner.id)

    async with async_session_factory() as session:
        profile = await legal_profile_service.upsert_legal_profile(
            session,
            _FakeRedis(),
            org_id=organization.id,
            actor_id=owner.id,
            totp_code=pyotp.TOTP(owner_secret).now(),
            legal_name="Settlement Org LLC",
            registration_number="RC-123456",
            address={"country": "US", "city": "New York"},
        )
        await session.commit()

    assert profile.legal_name == "Settlement Org LLC"
    assert profile.registration_number == "RC-123456"

    async with async_session_factory() as session:
        persisted = await session.scalar(
            select(OrgLegalProfile).where(OrgLegalProfile.org_id == organization.id)
        )

    assert persisted is not None
    assert persisted.address == {"country": "US", "city": "New York"}


@pytest.mark.asyncio
async def test_framework_sale_invoice_uses_shared_org_legal_name(
    migrated_database: None,
    settlement_state: None,
) -> None:
    """Org-backed Framework invoices must render the shared legal name."""
    del migrated_database, settlement_state
    owner = await _create_user("org-owner")
    organization = await _create_org(owner.id)
    framework_id = await _create_published_framework(
        contributor_id=None,
        contributor_org_id=organization.id,
    )

    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgLegalProfile(
                    org_id=organization.id,
                    legal_name="Shared Legal Name LLC",
                    registration_number="RC-123456",
                    address={"country": "US", "city": "New York"},
                )
            )

    async with async_session_factory() as session:
        framework = await session.get(Framework, framework_id)
        assert framework is not None
        seller = await financials_invoices.framework_invoice_seller_identity(
            session,
            framework=framework,
        )

    assert seller.name == "Shared Legal Name LLC"


@pytest.mark.asyncio
async def test_attestor_invoice_identity_uses_shared_org_legal_name(
    migrated_database: None,
    settlement_state: None,
) -> None:
    """Attestor invoicing must read the shared legal profile after the re-point."""
    del migrated_database, settlement_state
    owner = await _create_user("org-owner")
    organization = await _create_org(owner.id)

    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgLegalProfile(
                    org_id=organization.id,
                    legal_name="Shared Attestor Legal Name LLC",
                    registration_number="RC-987654",
                    address={"country": "US", "city": "Chicago"},
                )
            )

    async with async_session_factory() as session:
        seller = await financials_invoices.org_invoice_seller_identity(
            session,
            org_id=organization.id,
        )

    assert seller.name == "Shared Attestor Legal Name LLC"
