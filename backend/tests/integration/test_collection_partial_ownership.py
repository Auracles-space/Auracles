"""Buying a bundle when you already own part of it.

QA hit "Collection is already fully licensed" on a two-member bundle while
holding a licence for only one member, and then found only that one member in
their Library. Those two observations cannot both follow from the code as read,
so this reproduces the state exactly rather than reasoning about it further.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.core.database import async_session_factory, engine
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import User, UserRole
from app.modules.collections.models import CollectionFramework, FrameworkCollection
from app.modules.frameworks.models import Framework, License


@pytest.fixture(autouse=True)
async def _pools() -> AsyncIterator[None]:
    """Drop process-wide pools around each test in this module."""
    await engine.dispose()
    get_redis.cache_clear()
    yield
    get_redis.cache_clear()


async def _seed_owning_one_of_two() -> dict[str, Any]:
    """Create a two-member bundle where the buyer already licenses one member."""
    async with async_session_factory() as session:
        async with session.begin():
            seller = User(
                email=f"bundle-seller-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Bundle Seller",
                email_verified=True,
            )
            buyer = User(
                email=f"bundle-buyer-{uuid4().hex[:8]}@auracles.space",
                password_hash=hash_password("CorrectHorse9"),
                display_name="Bundle Buyer",
                email_verified=True,
                kyc_status="verified",
            )
            session.add_all([seller, buyer])
            await session.flush()
            session.add_all(
                [
                    UserRole(
                        user_id=seller.id,
                        role="contributor",
                        approved_at=datetime.now(UTC),
                    ),
                    UserRole(
                        user_id=buyer.id,
                        role="operator",
                        approved_at=datetime.now(UTC),
                    ),
                ]
            )
            framework_ids: list[UUID] = []
            for index, price in enumerate((Decimal("4000.00"), Decimal("60000.00"))):
                framework = Framework(
                    contributor_id=seller.id,
                    title=f"Bundle Member {index}",
                    description="Member of a partially owned bundle.",
                    status="published",
                    category="operations",
                    sector="technology",
                    industry="software",
                    business_function="revenue_operations",
                    tags=["bundle"],
                    tags_text="bundle",
                    price=price,
                    currency="USD",
                    license_types=["single_user"],
                    published_at=datetime.now(UTC),
                )
                session.add(framework)
                await session.flush()
                framework_ids.append(framework.id)

            collection = FrameworkCollection(
                contributor_id=seller.id,
                title="Partially Owned Bundle",
                description="Two members, one of them already licensed.",
                bundle_price=Decimal("50000.00"),
                currency="USD",
                status="published",
            )
            session.add(collection)
            await session.flush()
            for framework_id in framework_ids:
                session.add(
                    CollectionFramework(
                        collection_id=collection.id, framework_id=framework_id
                    )
                )

            # The buyer already owns the FIRST member, and only that one.
            session.add(
                License(
                    framework_id=framework_ids[0],
                    operator_id=buyer.id,
                    license_type="single_user",
                    version_at_grant="1.0.0",
                    status="active",
                    granted_at=datetime.now(UTC),
                )
            )
            return {
                "buyer_id": buyer.id,
                "collection_id": collection.id,
                "owned_framework_id": framework_ids[0],
                "unowned_framework_id": framework_ids[1],
            }


def _auth(user_id: UUID) -> dict[str, str]:
    """Bearer headers for one operator."""
    token = create_access_token(user_id=user_id, roles=["operator"])
    return {"Authorization": f"Bearer {token}"}


async def test_partially_owned_bundle_is_still_purchasable(
    client: AsyncClient,
) -> None:
    """Owning one member of two must not read as owning the bundle.

    The 409 is reserved for a buyer who already holds every member; firing it
    at partial ownership sells them nothing and tells them they own something
    they do not.
    """
    seeded = await _seed_owning_one_of_two()

    response = await client.post(
        f"/v1/financials/collections/{seeded['collection_id']}/purchase",
        headers=_auth(seeded["buyer_id"]),
        json={"license_type": "single_user", "country": "US"},
    )

    assert response.status_code != 409, response.text


async def test_the_library_lists_every_active_licence(
    client: AsyncClient,
) -> None:
    """A licence the bundle check counts must also appear in the Library.

    QA saw the two disagree: the purchase said every member was licensed while
    the Library showed one. Whatever ownership means, both surfaces have to
    answer the same way or a buyer is told they own something they cannot open.
    """
    seeded = await _seed_owning_one_of_two()

    library = await client.get(
        "/v1/library", headers=_auth(seeded["buyer_id"])
    )

    assert library.status_code == 200, library.text
    listed = {item["framework_id"] for item in library.json()["items"]}
    assert str(seeded["owned_framework_id"]) in listed
    assert str(seeded["unowned_framework_id"]) not in listed
