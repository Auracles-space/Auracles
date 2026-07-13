"""Integration tests for per-organization Framework purchase pricing.

Verifies that org Framework purchases snapshot the resolved tier amount into
`transactions.amount`, rather than always charging the base Framework price.
Maps to docs/superpowers/specs/2026-07-13-per-org-framework-pricing-design.md.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.database import async_session_factory
from app.modules.financials import service as financials_service
from app.modules.financials.models import Transaction
from app.modules.financials.schemas import PurchaseRequest
from tests.unit.modules.test_org_framework_purchase import (
    _activate_operator_capability,
    _create_framework,
    _create_org,
    _create_user,
    _patch_payment_intent,
)
from tests.unit.modules.test_org_framework_purchase import (
    migrated_database as _migrated_database_fixture,
)
from tests.unit.modules.test_org_framework_purchase import (
    org_purchase_state as _org_purchase_state_fixture,
)

migrated_database = _migrated_database_fixture
org_purchase_state = _org_purchase_state_fixture


@pytest.fixture
async def org_pricing_state(
    migrated_database: None,
    org_purchase_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> SimpleNamespace:
    """Create an org purchase setup with an explicit org tier price."""
    del migrated_database, org_purchase_state
    contributor = await _create_user("org-pricing-contributor")
    owner = await _create_user("org-pricing-owner")
    org = await _create_org(owner)
    await _activate_operator_capability(org.id, owner.id)
    framework = await _create_framework(
        contributor_id=contributor.id,
        contributor_org_id=None,
        price=Decimal("250.00"),
        license_types=["single_user", "organizational"],
    )
    framework.org_price = Decimal("900.00")
    async with async_session_factory() as session:
        async with session.begin():
            stored_framework = await session.get(type(framework), framework.id)
            assert stored_framework is not None
            stored_framework.org_price = Decimal("900.00")
    payment_calls = _patch_payment_intent(monkeypatch)
    return SimpleNamespace(
        db=async_session_factory(),
        org_id=org.id,
        actor=owner,
        framework_id=framework.id,
        payment_calls=payment_calls,
    )


@pytest.fixture
async def org_pricing_state_reuse(
    migrated_database: None,
    org_purchase_state: None,
    monkeypatch: pytest.MonkeyPatch,
) -> SimpleNamespace:
    """Create an org purchase setup where the org tier reuses the base price."""
    del migrated_database, org_purchase_state
    contributor = await _create_user("org-pricing-reuse-contributor")
    owner = await _create_user("org-pricing-reuse-owner")
    org = await _create_org(owner)
    await _activate_operator_capability(org.id, owner.id)
    framework = await _create_framework(
        contributor_id=contributor.id,
        contributor_org_id=None,
        price=Decimal("250.00"),
        license_types=["single_user", "organizational"],
    )
    payment_calls = _patch_payment_intent(monkeypatch)
    return SimpleNamespace(
        db=async_session_factory(),
        org_id=org.id,
        actor=owner,
        framework_id=framework.id,
        payment_calls=payment_calls,
    )


@pytest.mark.asyncio
async def test_org_purchase_charges_org_price(
    org_pricing_state: SimpleNamespace,
) -> None:
    """An org buying the organizational tier is charged org_price, not base."""
    async with org_pricing_state.db as session:
        response = await financials_service.create_org_framework_purchase(
            session,
            org_id=org_pricing_state.org_id,
            actor=org_pricing_state.actor,
            framework_id=org_pricing_state.framework_id,
            payload=PurchaseRequest(license_type="organizational"),
        )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, response.transaction_id)

    assert transaction is not None
    assert transaction.amount == Decimal("900.00")


@pytest.mark.asyncio
async def test_org_purchase_reuse_charges_base_price(
    org_pricing_state_reuse: SimpleNamespace,
) -> None:
    """An org tier with NULL org_price is charged the base price."""
    async with org_pricing_state_reuse.db as session:
        response = await financials_service.create_org_framework_purchase(
            session,
            org_id=org_pricing_state_reuse.org_id,
            actor=org_pricing_state_reuse.actor,
            framework_id=org_pricing_state_reuse.framework_id,
            payload=PurchaseRequest(license_type="organizational"),
        )

    async with async_session_factory() as session:
        transaction = await session.get(Transaction, response.transaction_id)

    assert transaction is not None
    assert transaction.amount == Decimal("250.00")
