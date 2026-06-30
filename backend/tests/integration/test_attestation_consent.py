"""Owner-consent endpoint coverage for operator-initiated attestations."""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.core.database import async_session_factory
from app.modules.attestation.models import Attestation
from tests.integration import test_attestation_requests as request_tests

pytest_plugins = ("tests.integration.test_attestation_requests",)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pending_consent_attestation() -> AsyncIterator[dict[str, UUID | str]]:
    """Seed one operator-initiated framework request awaiting owner consent."""
    owner_id = await request_tests.create_user(
        "consent-owner@auracles.space", ["contributor"]
    )
    operator_id = await request_tests.create_user(
        "consent-operator@auracles.space", ["operator"]
    )
    framework_id = await request_tests._create_framework(owner_id, "published")

    async with async_session_factory() as session:
        async with session.begin():
            attestation = Attestation(
                target_type="framework",
                target_id=framework_id,
                requestor_id=operator_id,
                status="pending_owner_consent",
                review_type="quality",
                brief=request_tests._FRAMEWORK_BRIEF,
                requested_specializations=["operations"],
                requested_jurisdictions=["US"],
                fee_amount=Decimal("500.00"),
                currency="USD",
            )
            session.add(attestation)
            await session.flush()
            seeded = {
                "attestation_id": attestation.id,
                "owner_id": owner_id,
                "operator_id": operator_id,
            }

    yield seeded


async def test_owner_approve_moves_to_pending_fee(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: object,
    pending_consent_attestation: dict[str, UUID | str],
) -> None:
    """The framework owner approving consent advances the request to pending_fee."""
    del migrated_database, attestation_context
    response = await client.post(
        f"/v1/attestations/{pending_consent_attestation['attestation_id']}/consent",
        headers=request_tests.auth_headers(
            pending_consent_attestation["owner_id"],  # type: ignore[arg-type]
            ["contributor"],
        ),
        json={"decision": "approve"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pending_fee"


async def test_owner_decline_cancels(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: object,
    pending_consent_attestation: dict[str, UUID | str],
) -> None:
    """The framework owner declining consent cancels the request."""
    del migrated_database, attestation_context
    response = await client.post(
        f"/v1/attestations/{pending_consent_attestation['attestation_id']}/consent",
        headers=request_tests.auth_headers(
            pending_consent_attestation["owner_id"],  # type: ignore[arg-type]
            ["contributor"],
        ),
        json={"decision": "decline"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


async def test_non_owner_consent_is_not_found(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: object,
    pending_consent_attestation: dict[str, UUID | str],
) -> None:
    """A non-owner caller gets 404 with no attestation existence leak."""
    del migrated_database, attestation_context
    response = await client.post(
        f"/v1/attestations/{pending_consent_attestation['attestation_id']}/consent",
        headers=request_tests.auth_headers(
            pending_consent_attestation["operator_id"],  # type: ignore[arg-type]
            ["operator"],
        ),
        json={"decision": "approve"},
    )

    assert response.status_code == 404


async def test_consent_wrong_status_conflicts(
    client: AsyncClient,
    migrated_database: None,
    attestation_context: object,
    pending_consent_attestation: dict[str, UUID | str],
) -> None:
    """Consent on an attestation outside pending_owner_consent returns 409."""
    del migrated_database, attestation_context
    async with async_session_factory() as session:
        async with session.begin():
            attestation = await session.get(
                Attestation,
                pending_consent_attestation["attestation_id"],  # type: ignore[arg-type]
            )
            assert attestation is not None
            attestation.status = "matching"

    response = await client.post(
        f"/v1/attestations/{pending_consent_attestation['attestation_id']}/consent",
        headers=request_tests.auth_headers(
            pending_consent_attestation["owner_id"],  # type: ignore[arg-type]
            ["contributor"],
        ),
        json={"decision": "approve"},
    )

    assert response.status_code == 409
