"""Admin organization detail read endpoints.

Thin routes behind ``require_role("admin")`` for the Decision 1 admin org
detail page. Reads need no step-up; the verification panel signs document
links and audits each view. Logic lives in ``org_detail_service``.

Maps to: organizations end-to-end design §Decision 1 and §Slice D.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import DatabaseSession, require_role
from app.modules.admin import org_detail_service as service
from app.modules.admin.org_detail_schemas import (
    AdminOrgAttestationsResponse,
    AdminOrgAuditResponse,
    AdminOrgFinancialsResponse,
    AdminOrgFrameworksResponse,
    AdminOrgMembersResponse,
    AdminOrgOverviewResponse,
    AdminOrgVerificationResponse,
)
from app.modules.auth.models import User

router = APIRouter(prefix="/admin/orgs", tags=["Admin Organizations"])

PlatformAdmin = Annotated[User, Depends(require_role("admin"))]


@router.get(
    "/{org_id}/detail",
    response_model=AdminOrgOverviewResponse,
    summary="Organization overview (platform admin)",
    description=(
        "Identity, business verification state, suspension and closure records "
        "with the acting user, capabilities, member count, and owners."
    ),
)
async def admin_org_overview(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> AdminOrgOverviewResponse:
    """Return the overview panel for one organization."""
    del admin
    return await service.get_overview(db, org_id=org_id)


@router.get(
    "/{org_id}/members",
    response_model=AdminOrgMembersResponse,
    summary="Organization members (platform admin)",
    description="Members with roles and teams, and the pending invitation count.",
)
async def admin_org_members(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> AdminOrgMembersResponse:
    """Return the members panel for one organization."""
    del admin
    return await service.get_members(db, org_id=org_id)


@router.get(
    "/{org_id}/verification",
    response_model=AdminOrgVerificationResponse,
    summary="Organization verification record (platform admin)",
    description=(
        "Legal profile, KYB verdict, and incorporation/tax documents as "
        "300-second presigned download links. Every call is audited."
    ),
)
async def admin_org_verification(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> AdminOrgVerificationResponse:
    """Return the verification panel, signing and auditing document access."""
    return await service.get_verification(db, org_id=org_id, admin_id=admin.id)


@router.get(
    "/{org_id}/financials",
    response_model=AdminOrgFinancialsResponse,
    summary="Organization financial summary (platform admin)",
    description=(
        "Balances, payout and purchase summaries, and the ten most recent "
        "payouts and transactions. No payout account details."
    ),
)
async def admin_org_financials(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> AdminOrgFinancialsResponse:
    """Return the financials panel for one organization."""
    del admin
    return await service.get_financials(db, org_id=org_id)


@router.get(
    "/{org_id}/frameworks",
    response_model=AdminOrgFrameworksResponse,
    summary="Organization frameworks and licenses (platform admin)",
    description="Frameworks the org sells and Licenses it holds with grant counts.",
)
async def admin_org_frameworks(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> AdminOrgFrameworksResponse:
    """Return the frameworks panel for one organization."""
    del admin
    return await service.get_frameworks(db, org_id=org_id)


@router.get(
    "/{org_id}/attestations",
    response_model=AdminOrgAttestationsResponse,
    summary="Organization in-flight attestations (platform admin)",
    description="Attestations the org is performing that are not yet finished.",
)
async def admin_org_attestations(
    org_id: UUID, admin: PlatformAdmin, db: DatabaseSession
) -> AdminOrgAttestationsResponse:
    """Return the attestations panel for one organization."""
    del admin
    return await service.get_attestations(db, org_id=org_id)


@router.get(
    "/{org_id}/audit",
    response_model=AdminOrgAuditResponse,
    summary="Organization audit trail (platform admin)",
    description=(
        "Audit events targeting the org or tagged with its id, newest first, paginated."
    ),
)
async def admin_org_audit(
    org_id: UUID,
    admin: PlatformAdmin,
    db: DatabaseSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AdminOrgAuditResponse:
    """Return one page of the organization's audit trail."""
    del admin
    return await service.get_audit(db, org_id=org_id, page=page, page_size=page_size)
