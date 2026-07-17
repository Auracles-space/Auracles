"""Integration tests for the org attestation offer + staffing endpoints.

Covers the accept-and-staff, decline, reassign, and org queue routes under
/v1/orgs/{org_id}, including RBAC (401 anonymous, 403 plain member) and the
member-scoped queue. Enforces the matching API surface of
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
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.security import create_access_token, hash_password
from app.modules.attestation.models import Attestation, AttestationOffer
from app.modules.auth.models import User, UserRole
from app.modules.organizations.models import (
    Organization,
    OrgAttestorProfile,
    OrgCapability,
    OrgInvitation,
    OrgMember,
    OrgMemberNda,
)
from app.shared.models.audit_log import AuditLog

pytestmark = pytest.mark.asyncio

NDA_VERSION = get_settings().org_member_nda_version


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure attestation + org tables exist."""
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture
async def clean_state() -> AsyncIterator[None]:
    """Reset org attestation rows between tests."""
    await engine.dispose()

    async def cleanup() -> None:
        """Delete rows in FK order between tests."""
        async with async_session_factory() as session:
            from app.modules.frameworks.models import Framework

            await session.execute(delete(AuditLog))
            await session.execute(delete(AttestationOffer))
            await session.execute(delete(Attestation))
            await session.execute(delete(Framework))
            await session.execute(delete(OrgAttestorProfile))
            await session.execute(delete(OrgMemberNda))
            await session.execute(delete(OrgCapability))
            await session.execute(delete(OrgInvitation))
            await session.execute(delete(OrgMember))
            await session.execute(delete(Organization))
            await session.execute(delete(UserRole))
            await session.execute(delete(User))
            await session.commit()

    await cleanup()
    try:
        yield
    finally:
        await cleanup()


def auth(user_id: UUID) -> dict[str, str]:
    """Build an Authorization header for the given user."""
    return {"Authorization": f"Bearer {create_access_token(user_id, [])}"}


async def _new_user(prefix: str) -> UUID:
    """Create a verified user; return its id."""
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


async def _attestor_org() -> tuple[UUID, UUID, UUID]:
    """Create an active attestor org. Return (org_id, owner_user, owner_member)."""
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
            member = OrgMember(org_id=org.id, user_id=owner_id, role="owner")
            session.add(member)
            await session.flush()
            session.add(
                OrgCapability(org_id=org.id, capability="attestor", status="active")
            )
            session.add(OrgMemberNda(member_id=member.id, nda_version=NDA_VERSION))
            session.add(
                OrgAttestorProfile(
                    org_id=org.id,
                    specializations=["tax"],
                    jurisdictions=["US"],
                    sectors=[],
                    functions=[],
                    active=True,
                    coi_signed_at=now,
                    coi_expires_at=now + timedelta(days=365),
                    approved_at=now,
                )
            )
            return org.id, owner_id, member.id


async def _add_member(
    org_id: UUID, *, role: str = "member", sign_nda: bool = True
) -> tuple[UUID, UUID]:
    """Add a member to an org. Return (member_id, user_id)."""
    user_id = await _new_user("member")
    async with async_session_factory() as session:
        async with session.begin():
            member = OrgMember(org_id=org_id, user_id=user_id, role=role)
            session.add(member)
            await session.flush()
            if sign_nda:
                session.add(OrgMemberNda(member_id=member.id, nda_version=NDA_VERSION))
            return member.id, user_id


async def _offered_attestation(org_id: UUID) -> tuple[UUID, UUID]:
    """Create an offered attestation + org offer. Return (attestation_id, offer_id)."""
    requestor = await _new_user("req")
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="contributor",
                target_id=uuid4(),
                requestor_id=requestor,
                status="offered",
                review_type="quality",
                fee_amount=Decimal("500.00"),
                currency="USD",
                requested_specializations=["tax"],
                requested_jurisdictions=["US"],
            )
            session.add(attestation)
            await session.flush()
            offer = AttestationOffer(
                attestation_id=attestation.id,
                org_id=org_id,
                cohort_index=0,
                status="offered",
                offered_at=now,
                expires_at=now + timedelta(hours=48),
            )
            session.add(offer)
            await session.flush()
            return attestation.id, offer.id


async def _offered_framework_attestation(
    org_id: UUID, *, title: str
) -> tuple[UUID, UUID]:
    """Create an offered attestation targeting a framework. Return (attn, offer)."""
    from app.modules.frameworks.models import Framework

    contributor = await _new_user("contrib")
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            framework = Framework(
                contributor_id=contributor,
                title=title,
                description="A framework under review.",
                category="operations",
                price=Decimal("100.00"),
                license_types=["single_user"],
            )
            session.add(framework)
            await session.flush()
            attestation = Attestation(
                target_type="framework",
                target_id=framework.id,
                requestor_id=contributor,
                status="offered",
                review_type="quality",
                fee_amount=Decimal("500.00"),
                currency="USD",
                requested_specializations=["tax"],
                requested_jurisdictions=["US"],
            )
            session.add(attestation)
            await session.flush()
            offer = AttestationOffer(
                attestation_id=attestation.id,
                org_id=org_id,
                cohort_index=0,
                status="offered",
                offered_at=now,
                expires_at=now + timedelta(hours=48),
            )
            session.add(offer)
            await session.flush()
            return attestation.id, offer.id


async def test_offer_preview_includes_framework_title(
    client: AsyncClient, migrated_database: None, clean_state: None
) -> None:
    """A framework offer previews the framework title; contributor targets are null."""
    org_id, owner_user, _ = await _attestor_org()
    await _offered_framework_attestation(org_id, title="Revenue Ops Playbook")
    await _offered_attestation(org_id)  # contributor target -> null title

    res = await client.get(
        f"/v1/orgs/{org_id}/attestation-offers", headers=auth(owner_user)
    )
    assert res.status_code == 200
    offers = res.json()["offers"]
    titles = {o["target_type"]: o["target_title"] for o in offers}
    assert titles["framework"] == "Revenue Ops Playbook"
    assert titles["contributor"] is None


async def test_orgs_mine_reports_action_counts(
    client: AsyncClient, migrated_database: None, clean_state: None
) -> None:
    """/orgs/mine returns per-org offer, queue, and invitation counts for admins."""
    org_id, owner_user, _ = await _attestor_org()
    # One open framework offer -> offers = 1.
    await _offered_framework_attestation(org_id, title="Ops Playbook")
    # One in-flight assigned attestation -> queue = 1.
    async with async_session_factory() as session:
        async with session.begin():
            requestor = await _new_user("q-req")
            session.add(
                Attestation(
                    target_type="contributor",
                    target_id=uuid4(),
                    requestor_id=requestor,
                    attestor_org_id=org_id,
                    status="accepted",
                    review_type="quality",
                    fee_amount=Decimal("500.00"),
                    currency="USD",
                    requested_specializations=["tax"],
                    requested_jurisdictions=["US"],
                )
            )
            # One pending invitation -> invitations = 1.
            session.add(
                OrgInvitation(
                    org_id=org_id,
                    email="invitee@auracles.space",
                    role="member",
                    invited_by=owner_user,
                    status="pending",
                    token_hash="hash",
                    expires_at=datetime.now(UTC) + timedelta(days=7),
                )
            )

    res = await client.get("/v1/orgs/mine", headers=auth(owner_user))
    assert res.status_code == 200
    org = next(o for o in res.json()["organizations"] if o["org"]["id"] == str(org_id))
    assert org["counts"] == {"offers": 1, "queue": 1, "invitations": 1}


async def test_orgs_mine_counts_zero_for_plain_member(
    client: AsyncClient, migrated_database: None, clean_state: None
) -> None:
    """A plain member sees all-zero counts even when offers exist."""
    org_id, _, _ = await _attestor_org()
    await _offered_framework_attestation(org_id, title="Ops Playbook")
    _, member_user = await _add_member(org_id)

    res = await client.get("/v1/orgs/mine", headers=auth(member_user))
    assert res.status_code == 200
    org = next(o for o in res.json()["organizations"] if o["org"]["id"] == str(org_id))
    assert org["counts"] == {"offers": 0, "queue": 0, "invitations": 0}


async def test_offers_endpoint_requires_admin(
    client: AsyncClient, migrated_database: None, clean_state: None
) -> None:
    """The offers list rejects anonymous (401) and plain-member (403) callers."""
    org_id, _, _ = await _attestor_org()
    _, member_user = await _add_member(org_id)
    url = f"/v1/orgs/{org_id}/attestation-offers"
    assert (await client.get(url)).status_code == 401
    assert (await client.get(url, headers=auth(member_user))).status_code == 403


async def test_accept_and_staff_happy_path(
    client: AsyncClient, migrated_database: None, clean_state: None
) -> None:
    """Owner accepts an offer and staffs a member; the attestation is assigned."""
    org_id, owner_user, _ = await _attestor_org()
    member_id, _ = await _add_member(org_id)
    attestation_id, offer_id = await _offered_attestation(org_id)

    response = await client.post(
        f"/v1/orgs/{org_id}/attestation-offers/{offer_id}/accept",
        headers=auth(owner_user),
        json={"reviewing_member_id": str(member_id)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["reviewing_member_id"] == str(member_id)

    async with async_session_factory() as session:
        attestation = await session.get(Attestation, attestation_id)
        assert attestation is not None
        assert attestation.attestor_org_id == org_id


async def test_accept_rejects_plain_member(
    client: AsyncClient, migrated_database: None, clean_state: None
) -> None:
    """A plain member cannot accept an offer (403)."""
    org_id, _, _ = await _attestor_org()
    member_id, member_user = await _add_member(org_id)
    _, offer_id = await _offered_attestation(org_id)

    response = await client.post(
        f"/v1/orgs/{org_id}/attestation-offers/{offer_id}/accept",
        headers=auth(member_user),
        json={"reviewing_member_id": str(member_id)},
    )
    assert response.status_code == 403


async def test_accept_offer_of_another_org_404(
    client: AsyncClient, migrated_database: None, clean_state: None
) -> None:
    """Accepting an offer that belongs to another org returns 404."""
    org_id, owner_user, _ = await _attestor_org()
    member_id, _ = await _add_member(org_id)
    other_org, _, _ = await _attestor_org()
    _, other_offer_id = await _offered_attestation(other_org)

    response = await client.post(
        f"/v1/orgs/{org_id}/attestation-offers/{other_offer_id}/accept",
        headers=auth(owner_user),
        json={"reviewing_member_id": str(member_id)},
    )
    assert response.status_code == 404


async def test_queue_shows_friendly_labels(
    client: AsyncClient, migrated_database: None, clean_state: None
) -> None:
    """The org queue exposes framework title, review type, and reviewer name."""
    org_id, owner_user, _ = await _attestor_org()
    member_id, _ = await _add_member(org_id)
    _, offer_id = await _offered_framework_attestation(org_id, title="Ops Playbook")

    accept = await client.post(
        f"/v1/orgs/{org_id}/attestation-offers/{offer_id}/accept",
        headers=auth(owner_user),
        json={"reviewing_member_id": str(member_id)},
    )
    assert accept.status_code == 200

    res = await client.get(
        f"/v1/orgs/{org_id}/attestations", headers=auth(owner_user)
    )
    assert res.status_code == 200
    item = res.json()["attestations"][0]
    assert item["target_title"] == "Ops Playbook"
    assert item["review_type"] == "quality"
    assert item["reviewing_member_name"] == "member"


async def test_decline_endpoint(
    client: AsyncClient, migrated_database: None, clean_state: None
) -> None:
    """Owner declines an offer; the offer is marked declined."""
    org_id, owner_user, _ = await _attestor_org()
    _, offer_id = await _offered_attestation(org_id)

    response = await client.post(
        f"/v1/orgs/{org_id}/attestation-offers/{offer_id}/decline",
        headers=auth(owner_user),
    )
    assert response.status_code == 200

    async with async_session_factory() as session:
        offer = await session.get(AttestationOffer, offer_id)
        assert offer is not None
        assert offer.status == "declined"


async def test_reassign_endpoint_before_start(
    client: AsyncClient, migrated_database: None, clean_state: None
) -> None:
    """Owner reassigns the reviewing member before review starts."""
    org_id, owner_user, _ = await _attestor_org()
    first_member, _ = await _add_member(org_id)
    second_member, _ = await _add_member(org_id)
    attestation_id, offer_id = await _offered_attestation(org_id)
    await client.post(
        f"/v1/orgs/{org_id}/attestation-offers/{offer_id}/accept",
        headers=auth(owner_user),
        json={"reviewing_member_id": str(first_member)},
    )

    response = await client.post(
        f"/v1/orgs/{org_id}/attestations/{attestation_id}/reassign",
        headers=auth(owner_user),
        json={"reviewing_member_id": str(second_member)},
    )
    assert response.status_code == 200
    assert response.json()["reviewing_member_id"] == str(second_member)


async def test_org_queue_scopes_by_role(
    client: AsyncClient, migrated_database: None, clean_state: None
) -> None:
    """Owner sees all org attestations; a plain member sees only their own."""
    org_id, owner_user, _ = await _attestor_org()
    member_id, member_user = await _add_member(org_id)
    other_member, _ = await _add_member(org_id)
    # Two accepted attestations, one staffed on each member.
    a1, offer1 = await _offered_attestation(org_id)
    a2, offer2 = await _offered_attestation(org_id)
    await client.post(
        f"/v1/orgs/{org_id}/attestation-offers/{offer1}/accept",
        headers=auth(owner_user),
        json={"reviewing_member_id": str(member_id)},
    )
    await client.post(
        f"/v1/orgs/{org_id}/attestation-offers/{offer2}/accept",
        headers=auth(owner_user),
        json={"reviewing_member_id": str(other_member)},
    )

    owner_view = await client.get(
        f"/v1/orgs/{org_id}/attestations", headers=auth(owner_user)
    )
    member_view = await client.get(
        f"/v1/orgs/{org_id}/attestations", headers=auth(member_user)
    )

    assert owner_view.status_code == 200
    assert {row["id"] for row in owner_view.json()["attestations"]} == {
        str(a1),
        str(a2),
    }
    assert member_view.status_code == 200
    assert {row["id"] for row in member_view.json()["attestations"]} == {str(a1)}
