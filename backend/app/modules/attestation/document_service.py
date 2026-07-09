"""Attestation invoice-document delivery services.

Resolves settled attestation billing documents through the shared invoicing
ledger and delivers them lazily via private S3 redirects. Tax invoices are for
the requestor; earnings statements are for the attestor.

Maps to: FR-FIN-003 and FR-FIN-004.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.attestation.dependencies import attestor_actor
from app.modules.attestation.models import Attestation
from app.modules.auth.models import User, UserRole
from app.modules.financials import invoices as financials_invoices
from app.modules.financials.models import PlatformConfig, Transaction
from app.modules.financials.service import INVOICE_URL_TTL_SECONDS
from app.modules.invoicing import service as invoicing_service
from app.modules.invoicing.annual import annual_summary_key
from app.modules.organizations.models import (
    Organization,
    OrgMember,
)
from app.workers.tasks.invoicing import generate_invoice_document


async def _load_settled_attestation(
    db: AsyncSession,
    attestation_id: UUID,
) -> Attestation:
    """Return one closed attestation or raise a typed HTTP error."""
    attestation = await db.scalar(
        select(Attestation).where(Attestation.id == attestation_id)
    )
    if attestation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation not found.",
        )
    if attestation.status != "closed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invoice is only available for settled attestations.",
        )
    return attestation


async def _is_admin(db: AsyncSession, user: User) -> bool:
    """Return whether the caller has an approved admin role row."""
    return (
        await db.scalar(
            select(UserRole.id).where(
                UserRole.user_id == user.id,
                UserRole.role == "admin",
                UserRole.approved_at.is_not(None),
            )
        )
        is not None
    )


async def _attestation_fee_transaction(
    db: AsyncSession,
    attestation_id: UUID,
) -> Transaction:
    """Load the fee transaction backing one attestation request."""
    transaction = await db.scalar(
        select(Transaction).where(
            Transaction.transaction_type == "attestation_fee",
            Transaction.ref_type == "attestation",
            Transaction.ref_id == attestation_id,
        )
    )
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestation fee transaction not found.",
        )
    return transaction


async def _deliver_invoice(invoice_id: UUID, key: str) -> Response:
    """Return a presigned redirect or queue document generation."""
    settings = get_settings()
    if s3.storage.object_exists(settings.s3_reports_bucket, key):
        document_url = s3.storage.presigned_get(
            settings.s3_reports_bucket,
            key,
            INVOICE_URL_TTL_SECONDS,
        )
        return RedirectResponse(url=document_url, status_code=status.HTTP_302_FOUND)

    generate_invoice_document.delay(str(invoice_id))
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
        content={"invoice_id": str(invoice_id), "status": "generating"},
    )


async def get_tax_invoice(
    db: AsyncSession,
    *,
    attestation_id: UUID,
    user: User,
) -> Response:
    """Deliver the requestor's tax invoice for one settled attestation.

    Args:
        db: Async database session.
        attestation_id: Attestation being invoiced.
        user: Authenticated caller.

    Returns:
        A redirect to the private PDF if ready, else a 202 enqueue response.

    Raises:
        HTTPException: If the attestation is missing, unsettled, or forbidden.
    """
    attestation = await _load_settled_attestation(db, attestation_id)
    is_admin = await _is_admin(db, user)
    if user.id != attestation.requestor_id and not is_admin:
        logger.bind(
            module="attestation",
            action="attestation_tax_invoice_denied",
            user_id=user.id,
            attestation_id=attestation_id,
        ).warning("access_denied")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not permitted.",
        )

    transaction = await _attestation_fee_transaction(db, attestation_id)
    requestor = await db.get(User, attestation.requestor_id)
    if requestor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Requestor not found.",
        )
    if attestation.attestor_org_id is not None:
        seller = await financials_invoices.org_invoice_seller_identity(
            db,
            org_id=attestation.attestor_org_id,
        )
    else:
        settings = get_settings()
        seller = invoicing_service.seller_identity(settings)
    invoice = await invoicing_service.issue_invoice(
        db,
        doc_type=invoicing_service.DOC_SALES_INVOICE,
        series=invoicing_service.SERIES_SALES,
        source_ref_type="attestation",
        source_ref_id=attestation.id,
        currency=transaction.currency,
        subtotal=transaction.amount,
        seller=seller,
        buyer_name=requestor.display_name,
        buyer_email=requestor.email,
    )

    if is_admin and user.id != attestation.requestor_id:
        await write_audit(
            db=db,
            actor_id=user.id,
            action="attestation_invoice_admin_accessed",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"invoice_id": str(invoice.id)},
        )

    await db.commit()

    return await _deliver_invoice(invoice.id, invoice.s3_key)


async def _earnings_buyer_identity(
    db: AsyncSession, attestation: Attestation
) -> tuple[str, str]:
    """Resolve the earnings-statement buyer name and email for one attestation.

    Attestations bill to the attestor organization's legal name (falling back to
    the org name) and the org owner's email — orgs carry no billing email of
    their own. The reviewing member's identity is never used as the buyer:
    earnings settle to the org, not the individual reviewer.

    Raises:
        HTTPException(404): No attestor identity can be resolved.
    """
    org = await db.get(Organization, attestation.attestor_org_id)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestor not found.",
        )
    owner_email = await db.scalar(
        select(User.email)
        .join(OrgMember, OrgMember.user_id == User.id)
        .where(OrgMember.org_id == org.id, OrgMember.role == "owner")
        .limit(1)
    )
    if owner_email is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attestor not found.",
        )
    seller = await financials_invoices.org_invoice_seller_identity(db, org_id=org.id)
    return seller.name, owner_email


async def get_earnings_statement(
    db: AsyncSession,
    *,
    attestation_id: UUID,
    user: User,
) -> Response:
    """Deliver the attestor earnings statement for one settled attestation.

    Args:
        db: Async database session.
        attestation_id: Attestation being settled.
        user: Authenticated caller.

    Returns:
        A redirect to the private PDF if ready, else a 202 enqueue response.

    Raises:
        HTTPException: If the attestation is missing, unsettled, or forbidden.
    """
    attestation = await _load_settled_attestation(db, attestation_id)
    is_admin = await _is_admin(db, user)
    actor = await attestor_actor(db, attestation=attestation, user_id=user.id)
    if not (actor.is_reviewing_member or actor.is_org_manager) and not is_admin:
        logger.bind(
            module="attestation",
            action="attestation_earnings_statement_denied",
            user_id=user.id,
            attestation_id=attestation_id,
        ).warning("access_denied")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not permitted.",
        )

    transaction = await _attestation_fee_transaction(db, attestation_id)
    buyer_name, buyer_email = await _earnings_buyer_identity(db, attestation)

    commission_rate = await _attestation_commission_rate(db)
    net_amount = (transaction.amount * (Decimal("1") - commission_rate)).quantize(
        Decimal("0.01")
    )
    settings = get_settings()
    invoice = await invoicing_service.issue_invoice(
        db,
        doc_type=invoicing_service.DOC_EARNINGS_STATEMENT,
        series=invoicing_service.SERIES_EARNINGS,
        source_ref_type="attestation",
        source_ref_id=attestation.id,
        currency=transaction.currency,
        subtotal=transaction.amount,
        seller=invoicing_service.seller_identity(settings),
        buyer_name=buyer_name,
        buyer_email=buyer_email,
        commission_rate=commission_rate,
        net_amount=net_amount,
    )

    if is_admin and not (actor.is_reviewing_member or actor.is_org_manager):
        await write_audit(
            db=db,
            actor_id=user.id,
            action="attestation_earnings_statement_admin_accessed",
            target_type="attestation",
            target_id=attestation.id,
            metadata={"invoice_id": str(invoice.id)},
        )

    await db.commit()

    return await _deliver_invoice(invoice.id, invoice.s3_key)


async def _attestation_commission_rate(db: AsyncSession) -> Decimal:
    """Return the configured attestation commission rate."""
    value = await db.scalar(
        select(PlatformConfig.value).where(
            PlatformConfig.key == "attestation_commission_rate"
        )
    )
    if value is None:
        return Decimal("0.10")
    return Decimal(value)


async def get_annual_summary(
    db: AsyncSession,
    *,
    user: User,
    year: int,
) -> Response:
    """Deliver an approved attestor's annual earnings summary PDF."""
    del db
    settings = get_settings()
    key = annual_summary_key(user.id, year)
    if not s3.storage.object_exists(settings.s3_reports_bucket, key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No earnings summary for that year.",
        )
    document_url = s3.storage.presigned_get(
        settings.s3_reports_bucket,
        key,
        INVOICE_URL_TTL_SECONDS,
    )
    return RedirectResponse(url=document_url, status_code=status.HTTP_302_FOUND)
