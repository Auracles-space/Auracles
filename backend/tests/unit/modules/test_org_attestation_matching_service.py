"""Unit tests for org-based attestation matching and accept-and-staff.

Covers the re-pointed AMM engine: ranking only orgs with an active attestor
capability, self-review CoI exclusions (requestor-member org, target-owner-member
org), accept-and-staff member validations, reviewing-member reassignment, the
member-removal blocker, and org CoI reminders. Enforces the matching section of
docs/superpowers/specs/2026-07-04-org-attestor-design.md.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, select

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.modules.attestation import matching_service
from app.modules.attestation.models import (
    Attestation,
    AttestationOffer,
)
from app.modules.auth.models import User, UserRole
from app.modules.financials.models import Escrow, PlatformConfig, Transaction
from app.modules.frameworks.models import Framework
from app.modules.organizations.dependencies import OrgContext
from app.modules.organizations.models import (
    Organization,
    OrgAttestorProfile,
    OrgCapability,
    OrgMember,
    OrgMemberNda,
)
from app.modules.organizations.service import remove_member
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio

NDA_VERSION = get_settings().org_member_nda_version


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure the schema is at alembic head for matching tests."""
    sync_engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    command.upgrade(Config("alembic.ini"), "head")
    try:
        yield
    finally:
        sync_engine.dispose()


async def _reset() -> None:
    """Delete matching rows in FK-safe order plus identity."""
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(delete(AuditLog))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(Attestation))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgMemberNda))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(Escrow))
            await session.execute(delete(Transaction))
            await session.execute(delete(PlatformConfig))
            await session.execute(delete(Framework))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))


@pytest.fixture
async def clean_state(migrated_database: None) -> AsyncIterator[None]:
    """Reset matching state before and after each test."""
    del migrated_database
    await engine.dispose()
    await _reset()
    try:
        yield
    finally:
        await _reset()
        await engine.dispose()


@pytest.fixture
async def db_session(clean_state: None) -> AsyncIterator:
    """Provide an async session for matching service calls."""
    del clean_state
    async with async_session_factory() as session:
        yield session


async def _new_user(prefix: str) -> UUID:
    """Create one verified user; return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            user = User(
                email=f"{prefix}-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name=prefix,
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            return user.id


async def _attestor_org(
    *,
    capability_status: str = "active",
    profile_active: bool = True,
    specializations: list[str] | None = None,
    jurisdictions: list[str] | None = None,
    functions: list[str] | None = None,
    coi_declarations: list[dict[str, object]] | None = None,
    coi_valid: bool = True,
    approved_at: datetime | None = None,
) -> tuple[UUID, UUID]:
    """Create an attestor org with capability + profile + owner. Return (org, owner)."""
    owner_id = await _new_user("owner")
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            org = Organization(
                slug=f"org-{uuid4().hex[:6]}",
                name="Attestor Org",
                country="US",
                created_by=owner_id,
            )
            session.add(org)
            await session.flush()
            session.add(OrgMember(org_id=org.id, user_id=owner_id, role="owner"))
            session.add(
                OrgCapability(
                    org_id=org.id,
                    capability="attestor",
                    status=capability_status,
                    activated_at=now,
                )
            )
            session.add(
                OrgAttestorProfile(
                    org_id=org.id,
                    specializations=specializations or ["tax"],
                    jurisdictions=jurisdictions or ["US"],
                    sectors=[],
                    functions=functions or [],
                    active=profile_active,
                    coi_declarations=coi_declarations or [],
                    coi_signed_at=now if coi_valid else None,
                    coi_expires_at=(
                        now + timedelta(days=365) if coi_valid else now
                    ),
                    approved_at=approved_at or now,
                )
            )
            return org.id, owner_id


async def _add_member(
    org_id: UUID,
    *,
    role: str = "member",
    sign_nda: bool = True,
) -> tuple[UUID, UUID]:
    """Add a member (optionally NDA-signed) to an org. Return (member_id, user_id)."""
    user_id = await _new_user("member")
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=org_id, user_id=user_id, role=role)
            session.add(member)
            await session.flush()
            if sign_nda:
                session.add(
                    OrgMemberNda(member_id=member.id, nda_version=NDA_VERSION)
                )
            return member.id, user_id


async def _owner_member_id(org_id: UUID) -> UUID:
    """Return the owner's membership id, NDA-signed for assignability."""
    async with async_session_factory() as session:
        async with session.begin():
            member = await session.scalar(
                select(OrgMember).where(
                    OrgMember.org_id == org_id, OrgMember.role == "owner"
                )
            )
            assert member is not None
            existing = await session.scalar(
                select(OrgMemberNda).where(OrgMemberNda.member_id == member.id)
            )
            if existing is None:
                session.add(
                    OrgMemberNda(member_id=member.id, nda_version=NDA_VERSION)
                )
            return member.id


async def _make_attestation(
    requestor_id: UUID,
    *,
    target_id: UUID,
    target_type: str = "contributor",
    specializations: list[str] | None = None,
    jurisdictions: list[str] | None = None,
    status_value: str = "matching",
) -> UUID:
    """Create one attestation request; return its id."""
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type=target_type,
                target_id=target_id,
                requestor_id=requestor_id,
                status=status_value,
                review_type="quality",
                fee_amount=Decimal("500.00"),
                currency="USD",
                requested_specializations=specializations or ["tax"],
                requested_jurisdictions=jurisdictions or ["US"],
            )
            session.add(attestation)
            await session.flush()
            return attestation.id


async def _make_offer(
    attestation_id: UUID,
    org_id: UUID,
    *,
    status_value: str = "offered",
    expires_at: datetime | None = None,
) -> UUID:
    """Create one cohort offer for an org; return its id."""
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            offer = AttestationOffer(
                attestation_id=attestation_id,
                org_id=org_id,
                cohort_index=0,
                status=status_value,
                offered_at=now,
                expires_at=expires_at or now + timedelta(hours=48),
            )
            session.add(offer)
            await session.flush()
            return offer.id


async def test_cohort_ranks_only_active_capability_orgs(db_session) -> None:
    """Ranking includes active-capability orgs and excludes pending ones."""
    requestor = await _new_user("req")
    active_org, _ = await _attestor_org(capability_status="active")
    pending_org, _ = await _attestor_org(capability_status="pending")
    attestation = await _load_attestation(
        db_session, await _make_attestation(requestor, target_id=uuid4())
    )

    ranked = await matching_service._rank_eligible_attestors(
        db_session,
        attestation=attestation,
        excluded_ids=set(),
        limit=10,
        now=datetime.now(UTC),
    )

    org_ids = {candidate.org_id for candidate in ranked}
    assert active_org in org_ids
    assert pending_org not in org_ids


async def test_suspended_capability_org_excluded(db_session) -> None:
    """An org whose attestor capability is suspended is not ranked."""
    requestor = await _new_user("req")
    active_org, _ = await _attestor_org(capability_status="active")
    suspended_org, _ = await _attestor_org(capability_status="suspended")
    attestation = await _load_attestation(
        db_session, await _make_attestation(requestor, target_id=uuid4())
    )

    ranked = await matching_service._rank_eligible_attestors(
        db_session,
        attestation=attestation,
        excluded_ids=set(),
        limit=10,
        now=datetime.now(UTC),
    )

    org_ids = {candidate.org_id for candidate in ranked}
    assert active_org in org_ids
    assert suspended_org not in org_ids


async def test_requestor_member_org_excluded(db_session) -> None:
    """An org where the requestor is a member is excluded (self-review guard)."""
    clean_org, _ = await _attestor_org()
    conflicted_org, _ = await _attestor_org()
    requestor = await _new_user("req")
    # The requestor is also a member of the conflicted org.
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                OrgMember(org_id=conflicted_org, user_id=requestor, role="member")
            )
    attestation = await _load_attestation(
        db_session, await _make_attestation(requestor, target_id=uuid4())
    )

    excluded = await matching_service._excluded_org_ids(db_session, attestation)
    ranked = await matching_service._rank_eligible_attestors(
        db_session,
        attestation=attestation,
        excluded_ids=excluded,
        limit=10,
        now=datetime.now(UTC),
    )

    org_ids = {candidate.org_id for candidate in ranked}
    assert clean_org in org_ids
    assert conflicted_org not in org_ids


async def test_target_owner_member_org_excluded(db_session) -> None:
    """An org whose member owns the target framework is excluded."""
    clean_org, _ = await _attestor_org()
    conflicted_org, _ = await _attestor_org()
    requestor = await _new_user("req")
    owner = await _new_user("fwowner")
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=owner,
                title="Owned Framework",
                description="Framework owned by a conflicted org member.",
                status="published",
                category="compliance",
                tags=["test"],
                price=Decimal("1.00"),
                license_types=["single_user"],
                published_at=datetime.now(UTC),
            )
            session.add(framework)
            await session.flush()
            framework_id = framework.id
            session.add(
                OrgMember(org_id=conflicted_org, user_id=owner, role="member")
            )
    attestation = await _load_attestation(
        db_session,
        await _make_attestation(
            requestor, target_id=framework_id, target_type="framework"
        ),
    )

    excluded = await matching_service._excluded_org_ids(db_session, attestation)
    ranked = await matching_service._rank_eligible_attestors(
        db_session,
        attestation=attestation,
        excluded_ids=excluded,
        limit=10,
        now=datetime.now(UTC),
    )

    org_ids = {candidate.org_id for candidate in ranked}
    assert clean_org in org_ids
    assert conflicted_org not in org_ids


async def test_expired_coi_org_excluded(db_session) -> None:
    """An org whose CoI declaration has lapsed is not ranked."""
    requestor = await _new_user("req")
    valid_org, _ = await _attestor_org(coi_valid=True)
    expired_org, _ = await _attestor_org(coi_valid=False)
    attestation = await _load_attestation(
        db_session, await _make_attestation(requestor, target_id=uuid4())
    )

    ranked = await matching_service._rank_eligible_attestors(
        db_session,
        attestation=attestation,
        excluded_ids=set(),
        limit=10,
        now=datetime.now(UTC),
    )

    org_ids = {candidate.org_id for candidate in ranked}
    assert valid_org in org_ids
    assert expired_org not in org_ids


async def test_coi_declaration_subject_conflict_org_excluded(db_session) -> None:
    """An org whose CoI declaration names the target is excluded (subject screen)."""
    requestor = await _new_user("req")
    target_owner = await _new_user("target")
    clean_org, _ = await _attestor_org()
    conflicted_org, _ = await _attestor_org(
        coi_declarations=[
            {
                "entity": "Linked Target",
                "entity_type": "firm",
                "relationship": "financial",
                "within_24mo": True,
                "subject_id": str(target_owner),
                "subject_kind": "user",
            }
        ],
    )
    attestation = await _load_attestation(
        db_session,
        await _make_attestation(requestor, target_id=target_owner),
    )

    ranked = await matching_service._rank_eligible_attestors(
        db_session,
        attestation=attestation,
        excluded_ids=set(),
        limit=10,
        now=datetime.now(UTC),
    )

    org_ids = {candidate.org_id for candidate in ranked}
    assert clean_org in org_ids
    assert conflicted_org not in org_ids


async def test_ranking_orders_by_score_then_fifo(db_session) -> None:
    """Function-matching orgs rank first; ties fall back to approval time."""
    requestor = await _new_user("req")
    owner = await _new_user("fwowner")
    base = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=owner,
                title="Scored Framework",
                description="Framework for org score-order tests.",
                status="published",
                category="compliance",
                business_function="compliance",
                tags=["test"],
                price=Decimal("1.00"),
                license_types=["single_user"],
                published_at=base,
            )
            session.add(framework)
            await session.flush()
            framework_id = framework.id

    high_org, _ = await _attestor_org(
        functions=["compliance"], approved_at=base
    )
    low_org, _ = await _attestor_org(approved_at=base)
    older_org, _ = await _attestor_org(approved_at=base - timedelta(days=1))
    attestation = await _load_attestation(
        db_session,
        await _make_attestation(
            requestor, target_id=framework_id, target_type="framework"
        ),
    )

    ranked = await matching_service._rank_eligible_attestors(
        db_session,
        attestation=attestation,
        excluded_ids=set(),
        limit=10,
        now=base,
    )

    order = [candidate.org_id for candidate in ranked]
    assert order[0] == high_org
    assert order.index(older_org) < order.index(low_org)


async def test_reputation_lifts_tied_org(db_session) -> None:
    """A higher stored org reputation lifts an otherwise tied org above a peer."""
    from app.modules.reputation.models import ReputationScore

    requestor = await _new_user("req")
    base = datetime.now(UTC)
    high_org, _ = await _attestor_org(specializations=["ml"], approved_at=base)
    low_org, _ = await _attestor_org(specializations=["ml"], approved_at=base)
    attestation = await _load_attestation(
        db_session,
        await _make_attestation(
            requestor, target_id=uuid4(), specializations=["ml"]
        ),
    )
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                ReputationScore(
                    subject_type="attestor",
                    subject_id=high_org,
                    score=Decimal("90.00"),
                    components={},
                    is_provisional=False,
                )
            )

    ranked = await matching_service._rank_eligible_attestors(
        db_session,
        attestation=attestation,
        excluded_ids=set(),
        limit=5,
        now=base,
    )

    order = [candidate.org_id for candidate in ranked]
    assert order.index(high_org) < order.index(low_org)


async def test_accept_sets_org_and_member_never_attestor_id(db_session) -> None:
    """Accept writes attestor_org_id + reviewing_member_id, never attestor_id."""
    requestor = await _new_user("req")
    org_id, owner_id = await _attestor_org()
    member_id, _ = await _add_member(org_id)
    attestation_id = await _make_attestation(
        requestor, target_id=uuid4(), status_value="offered"
    )
    offer_id = await _make_offer(attestation_id, org_id)

    attestation = await matching_service.accept_org_offer(
        db_session,
        offer_id=offer_id,
        org_id=org_id,
        actor_id=owner_id,
        reviewing_member_id=member_id,
    )

    assert attestation.status == "accepted"
    assert attestation.attestor_org_id == org_id
    assert attestation.reviewing_member_id == member_id
    assert attestation.completion_due_at is not None


async def test_accept_grants_staffed_member_the_attestor_role(db_session) -> None:
    """Staffing a plain member on an accepted offer grants the derived attestor role.

    Model A: being assigned to perform an attestation makes the member an
    attestor. The accept path places the staffed member on the org's Attestors
    team so the derived-role sync grants ``attestor``.
    """
    requestor = await _new_user("req")
    org_id, owner_id = await _attestor_org()
    member_id, member_user_id = await _add_member(org_id)
    attestation_id = await _make_attestation(
        requestor, target_id=uuid4(), status_value="offered"
    )
    offer_id = await _make_offer(attestation_id, org_id)

    await matching_service.accept_org_offer(
        db_session,
        offer_id=offer_id,
        org_id=org_id,
        actor_id=owner_id,
        reviewing_member_id=member_id,
    )

    async with async_session_factory() as session:
        role = await session.scalar(
            select(UserRole).where(
                UserRole.user_id == member_user_id,
                UserRole.role == "attestor",
                UserRole.source == "derived",
            )
        )
    assert role is not None


async def test_accept_unsigned_member_rejected(db_session) -> None:
    """Accept with an NDA-unsigned member raises 422 nda_required."""
    requestor = await _new_user("req")
    org_id, owner_id = await _attestor_org()
    member_id, _ = await _add_member(org_id, sign_nda=False)
    attestation_id = await _make_attestation(
        requestor, target_id=uuid4(), status_value="offered"
    )
    offer_id = await _make_offer(attestation_id, org_id)

    with pytest.raises(HTTPException) as exc:
        await matching_service.accept_org_offer(
            db_session,
            offer_id=offer_id,
            org_id=org_id,
            actor_id=owner_id,
            reviewing_member_id=member_id,
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["error_code"] == "nda_required"


async def test_accept_non_member_rejected(db_session) -> None:
    """Accept naming a member of another org raises 404."""
    requestor = await _new_user("req")
    org_id, owner_id = await _attestor_org()
    other_org, _ = await _attestor_org()
    stranger_member_id, _ = await _add_member(other_org)
    attestation_id = await _make_attestation(
        requestor, target_id=uuid4(), status_value="offered"
    )
    offer_id = await _make_offer(attestation_id, org_id)

    with pytest.raises(HTTPException) as exc:
        await matching_service.accept_org_offer(
            db_session,
            offer_id=offer_id,
            org_id=org_id,
            actor_id=owner_id,
            reviewing_member_id=stranger_member_id,
        )
    assert exc.value.status_code == 404


async def test_accept_member_at_capacity_rejected(db_session) -> None:
    """Accept with a member already at the concurrency cap raises 422."""
    requestor = await _new_user("req")
    org_id, owner_id = await _attestor_org()
    member_id, _ = await _add_member(org_id)
    async with async_session_factory() as session:
        async with session.begin():
            session.add(PlatformConfig(key="attestation_concurrency_cap", value="1"))
            # One active assignment already staffed on this member.
            busy = Attestation(
                target_type="contributor",
                target_id=uuid4(),
                requestor_id=requestor,
                attestor_org_id=org_id,
                reviewing_member_id=member_id,
                status="accepted",
                review_type="quality",
                fee_amount=Decimal("500.00"),
                currency="USD",
                requested_specializations=["tax"],
                requested_jurisdictions=["US"],
            )
            session.add(busy)
    attestation_id = await _make_attestation(
        requestor, target_id=uuid4(), status_value="offered"
    )
    offer_id = await _make_offer(attestation_id, org_id)

    with pytest.raises(HTTPException) as exc:
        await matching_service.accept_org_offer(
            db_session,
            offer_id=offer_id,
            org_id=org_id,
            actor_id=owner_id,
            reviewing_member_id=member_id,
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["error_code"] == "member_at_capacity"


async def test_accept_under_suspended_capability_rejected(db_session) -> None:
    """Accept while the org attestor capability is suspended raises 403."""
    requestor = await _new_user("req")
    org_id, owner_id = await _attestor_org(capability_status="suspended")
    member_id, _ = await _add_member(org_id)
    attestation_id = await _make_attestation(
        requestor, target_id=uuid4(), status_value="offered"
    )
    offer_id = await _make_offer(attestation_id, org_id)

    with pytest.raises(HTTPException) as exc:
        await matching_service.accept_org_offer(
            db_session,
            offer_id=offer_id,
            org_id=org_id,
            actor_id=owner_id,
            reviewing_member_id=member_id,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["error_code"] == "capability_suspended"


async def test_reassign_before_start_ok_after_start_conflicts(db_session) -> None:
    """Reassign is allowed before review starts and 409 after."""
    requestor = await _new_user("req")
    org_id, owner_id = await _attestor_org()
    first_member, _ = await _add_member(org_id)
    second_member, _ = await _add_member(org_id)
    attestation_id = await _make_attestation(
        requestor, target_id=uuid4(), status_value="offered"
    )
    offer_id = await _make_offer(attestation_id, org_id)
    await matching_service.accept_org_offer(
        db_session,
        offer_id=offer_id,
        org_id=org_id,
        actor_id=owner_id,
        reviewing_member_id=first_member,
    )

    reassigned = await matching_service.reassign_reviewing_member(
        db_session,
        attestation_id=attestation_id,
        org_id=org_id,
        actor_id=owner_id,
        reviewing_member_id=second_member,
    )
    assert reassigned.reviewing_member_id == second_member

    async with async_session_factory() as session:
        async with session.begin():
            row = await session.get(Attestation, attestation_id)
            assert row is not None
            row.review_started_at = datetime.now(UTC)

    with pytest.raises(HTTPException) as exc:
        await matching_service.reassign_reviewing_member(
            db_session,
            attestation_id=attestation_id,
            org_id=org_id,
            actor_id=owner_id,
            reviewing_member_id=first_member,
        )
    assert exc.value.status_code == 409


async def test_remove_member_blocks_started_review_and_nulls_unstarted(
    db_session,
) -> None:
    """A started review blocks removal; an unstarted one is unstaffed."""
    org_id, owner_id = await _attestor_org()
    started_member, started_user = await _add_member(org_id)
    unstarted_member, unstarted_user = await _add_member(org_id)
    requestor = await _new_user("req")
    async with async_session_factory() as session:
        async with session.begin():
            session.add(
                Attestation(
                    target_type="contributor",
                    target_id=uuid4(),
                    requestor_id=requestor,
                    attestor_org_id=org_id,
                    reviewing_member_id=started_member,
                    status="in_review",
                    review_type="quality",
                    review_started_at=datetime.now(UTC),
                    fee_amount=Decimal("500.00"),
                    currency="USD",
                    requested_specializations=["tax"],
                    requested_jurisdictions=["US"],
                )
            )
            unstarted = Attestation(
                target_type="contributor",
                target_id=uuid4(),
                requestor_id=requestor,
                attestor_org_id=org_id,
                reviewing_member_id=unstarted_member,
                status="accepted",
                review_type="quality",
                fee_amount=Decimal("500.00"),
                currency="USD",
                requested_specializations=["tax"],
                requested_jurisdictions=["US"],
            )
            session.add(unstarted)
            await session.flush()
            unstarted_id = unstarted.id

    owner_ctx = await _org_context(org_id, owner_id)

    with pytest.raises(HTTPException) as exc:
        await remove_member(db_session, context=owner_ctx, member_id=started_member)
    assert exc.value.status_code == 409

    await remove_member(db_session, context=owner_ctx, member_id=unstarted_member)
    async with async_session_factory() as session:
        row = await session.get(Attestation, unstarted_id)
        assert row is not None
        assert row.reviewing_member_id is None


async def test_coi_reminder_targets_org_managers(db_session) -> None:
    """CoI reminders read OrgAttestorProfile fields and notify owner + admins."""
    org_id, owner_id = await _attestor_org()
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            profile = await session.scalar(
                select(OrgAttestorProfile).where(
                    OrgAttestorProfile.org_id == org_id
                )
            )
            assert profile is not None
            profile.coi_expires_at = now + timedelta(days=10)
            profile.coi_reminder_sent_at = None

    sent = await matching_service.send_coi_resign_reminders(db_session, now=now)
    assert sent == 1


async def _load_attestation(db_session, attestation_id: UUID) -> Attestation:
    """Load an attestation into the test session."""
    attestation = await db_session.get(Attestation, attestation_id)
    assert attestation is not None
    return attestation


async def _org_context(org_id: UUID, owner_id: UUID) -> OrgContext:
    """Build an OrgContext for the org owner (remove_member RBAC input)."""
    async with async_session_factory() as session:
        org = await session.get(Organization, org_id)
        user = await session.get(User, owner_id)
        member = await session.scalar(
            select(OrgMember).where(
                OrgMember.org_id == org_id, OrgMember.user_id == owner_id
            )
        )
        assert org is not None and user is not None and member is not None
        return OrgContext(org=org, member=member, user=user)
