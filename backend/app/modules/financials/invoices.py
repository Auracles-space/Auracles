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
from app.modules.auth.models import User
from app.modules.financials.models import Transaction
from app.modules.frameworks.models import Framework
from app.modules.frameworks.ownership import resolve_framework_seller
from app.modules.invoicing import service as invoicing_service
from app.modules.invoicing.models import Invoice
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


async def resolve_org_billing_email(db: AsyncSession, org: Organization) -> str:
    """Resolve the invoice buyer email for an org, falling back to its owner.

    Raises:
        ValueError: The org has neither a billing email nor a creator on file.
    """
    if org.billing_email:
        return org.billing_email
    owner = await db.get(User, org.created_by)
    if owner is None:
        raise ValueError("Organization has no billing contact.")
    return owner.email


async def issue_purchase_invoice_for_transaction(
    db: AsyncSession,
    *,
    transaction: Transaction,
) -> Invoice:
    """Idempotently issue the sales invoice for one Framework purchase.

    One buyer-resolution implementation for every issuance path — the buyer's
    own invoice request, the org billing endpoint, and settlement-time
    issuance in the purchase webhook. Individual purchases bill the paying
    Operator; org purchases bill the organization at its billing email
    (falling back to the org owner).

    Args:
        db: Session inside the caller's transaction.
        transaction: A Framework purchase (`ref_type == "framework"`).

    Raises:
        ValueError: The transaction is not a Framework purchase, its
            Framework or payer no longer resolves, or the org has no billing
            contact.
    """
    if transaction.ref_type != "framework" or transaction.ref_id is None:
        raise ValueError("Invoice issuance requires a Framework purchase.")
    framework = await db.get(Framework, transaction.ref_id)
    if framework is None:
        raise ValueError("Framework not found for purchase invoice.")

    if transaction.payer_org_id is not None:
        organization = await db.get(Organization, transaction.payer_org_id)
        if organization is None:
            raise ValueError("Paying organization not found.")
        buyer_name = organization.name
        buyer_email = await resolve_org_billing_email(db, organization)
    else:
        payer = await db.get(User, transaction.payer_id)
        if payer is None:
            raise ValueError("Paying user not found for purchase invoice.")
        buyer_name = payer.display_name
        buyer_email = payer.email

    return await invoicing_service.issue_invoice(
        db,
        doc_type=invoicing_service.DOC_SALES_INVOICE,
        series=invoicing_service.SERIES_SALES,
        source_ref_type="transaction",
        source_ref_id=transaction.id,
        currency=transaction.currency,
        subtotal=transaction.amount,
        seller=await framework_invoice_seller_identity(db, framework=framework),
        buyer_name=buyer_name,
        buyer_email=buyer_email,
    )
