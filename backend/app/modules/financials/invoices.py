"""Invoice helpers shared by request services and Celery tasks.

Centralizes seller-identity resolution for invoices. Individual contributor
sales keep the existing platform-issued seller block, while organization-backed
sales and attestor invoices read the org's shared legal profile when present.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.frameworks.models import Framework
from app.modules.frameworks.ownership import resolve_framework_seller
from app.modules.invoicing import service as invoicing_service
from app.modules.organizations.models import (
    Organization,
    OrgAttestorApplication,
    OrgLegalProfile,
)


def purchase_invoice_key(transaction_id: UUID | str) -> str:
    """Return the deterministic private S3 key for a purchase invoice."""
    return f"invoices/purchases/{transaction_id}.pdf"


def _format_address(address: dict[str, object] | None) -> str:
    """Render a compact single-line address for frozen invoice rows."""
    if not address:
        return ""
    return ", ".join(str(value) for value in address.values() if value)


async def org_invoice_seller_identity(
    db: AsyncSession,
    *,
    org_id: UUID,
) -> invoicing_service.SellerIdentity:
    """Return one org invoice seller snapshot from the shared legal profile."""
    organization = await db.get(Organization, org_id)
    if organization is None:
        raise ValueError("Organization not found.")

    profile = await db.scalar(
        select(OrgLegalProfile).where(OrgLegalProfile.org_id == org_id).limit(1)
    )
    if profile is not None:
        return invoicing_service.SellerIdentity(
            name=profile.legal_name,
            tax_id=profile.registration_number or "",
            address=_format_address(profile.address),
        )

    application = await db.scalar(
        select(OrgAttestorApplication)
        .where(
            OrgAttestorApplication.org_id == org_id,
            OrgAttestorApplication.status == "approved",
        )
        .limit(1)
    )
    if application is None:
        return invoicing_service.SellerIdentity(
            name=organization.name,
            tax_id="",
            address="",
        )

    return invoicing_service.SellerIdentity(
        name=application.legal_name or organization.name,
        tax_id=application.registration_number or "",
        address="",
    )


async def framework_invoice_seller_identity(
    db: AsyncSession,
    *,
    framework: Framework,
) -> invoicing_service.SellerIdentity:
    """Return the seller snapshot for one Framework-purchase invoice."""
    seller = resolve_framework_seller(framework)
    if seller.org_id is not None:
        return await org_invoice_seller_identity(db, org_id=seller.org_id)
    return invoicing_service.seller_identity(get_settings())
