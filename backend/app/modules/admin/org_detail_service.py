"""Service layer for the admin organization detail page.

Read-only aggregation behind the Decision 1 admin org detail panels:
overview, members, verification documents, financials, frameworks and
licenses, in-flight attestations, and the org audit trail. Authorization is
enforced by the router's ``require_role("admin")`` dependency; this layer only
assembles minimum-necessary views. The single write is the audit row recorded
whenever KYB document links are signed.

Maps to: organizations end-to-end design §Decision 1 and §Slice D.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.admin.org_detail_schemas import (
    AdminOrgAttestationCounts,
    AdminOrgAttestationItem,
    AdminOrgAttestationsResponse,
    AdminOrgAuditItem,
    AdminOrgAuditResponse,
    AdminOrgCapabilityItem,
    AdminOrgDocumentLink,
    AdminOrgFinancialsResponse,
    AdminOrgFrameworkItem,
    AdminOrgFrameworksResponse,
    AdminOrgLicenseItem,
    AdminOrgMemberItem,
    AdminOrgMembersResponse,
    AdminOrgOverviewResponse,
    AdminOrgOwnerItem,
    AdminOrgPayoutItem,
    AdminOrgPayoutsSummary,
    AdminOrgPurchasesSummary,
    AdminOrgTeamRef,
    AdminOrgTransactionItem,
    AdminOrgUserRef,
    AdminOrgVerificationResponse,
)
from app.modules.attestation.models import (
    FINISHED_ATTESTATION_STATUSES,
    Attestation,
)
from app.modules.auth.models import User
from app.modules.financials.models import Payout, PayoutAccount, Transaction
from app.modules.financials.service import get_org_earnings
from app.modules.frameworks.models import Framework, License, LicenseGrant
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgInvitation,
    OrgLegalProfile,
    OrgMember,
    OrgTeam,
    OrgTeamMember,
)
from app.shared.models.audit_log import AuditLog

# Admin document links are deliberately shorter-lived than the 900s attestor
# review links: the detail page re-signs on every open (spec §Security).
KYB_DOCUMENT_TTL_SECONDS = 300
RECENT_ROWS_LIMIT = 10

# S3 keys are minted as ``{uuid4}-{file_name}``: 36 uuid chars plus a hyphen.
_UUID_KEY_PREFIX_LEN = 37


async def _require_org(db: AsyncSession, org_id: UUID) -> Organization:
    """Load an organization or raise 404."""
    organization = await db.get(Organization, org_id)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found.",
        )
    return organization


async def _user_refs(
    db: AsyncSession, user_ids: Iterable[UUID | None]
) -> dict[UUID, AdminOrgUserRef]:
    """Resolve user ids to display-name references in one query."""
    wanted = {user_id for user_id in user_ids if user_id is not None}
    if not wanted:
        return {}
    rows = await db.execute(
        select(User.id, User.display_name).where(User.id.in_(wanted))
    )
    return {
        row.id: AdminOrgUserRef(id=row.id, display_name=row.display_name)
        for row in rows
    }


def _file_name_from_key(key: str) -> str:
    """Return only the original file name from an S3 key, never the path."""
    segment = key.rsplit("/", 1)[-1]
    if len(segment) > _UUID_KEY_PREFIX_LEN and segment[_UUID_KEY_PREFIX_LEN - 1] == "-":
        return segment[_UUID_KEY_PREFIX_LEN:]
    return segment


async def get_overview(db: AsyncSession, *, org_id: UUID) -> AdminOrgOverviewResponse:
    """Return the org's identity, KYB, lifecycle state, capabilities, and owners.

    Args:
        db: Async session.
        org_id: Organization to describe.

    Returns:
        The overview panel.

    Raises:
        HTTPException(404): If the organization does not exist.
    """
    organization = await _require_org(db, org_id)
    profile = await db.scalar(
        select(OrgLegalProfile).where(OrgLegalProfile.org_id == org_id)
    )
    capabilities = (
        await db.scalars(
            select(OrgCapability)
            .where(OrgCapability.org_id == org_id)
            .order_by(OrgCapability.capability)
        )
    ).all()
    member_count = await db.scalar(
        select(func.count()).select_from(OrgMember).where(OrgMember.org_id == org_id)
    )
    owner_rows = await db.execute(
        select(OrgMember.id, OrgMember.user_id, User.display_name, User.email)
        .join(User, User.id == OrgMember.user_id)
        .where(OrgMember.org_id == org_id, OrgMember.role == "owner")
        .order_by(OrgMember.joined_at)
    )
    refs = await _user_refs(
        db, [organization.suspended_by, organization.deactivated_by]
    )
    return AdminOrgOverviewResponse(
        id=organization.id,
        slug=organization.slug,
        name=organization.name,
        country=organization.country,
        website=organization.website,
        description=organization.description,
        created_at=organization.created_at,
        kyb_status=profile.kyb_status if profile else "unverified",
        kyb_submitted_at=profile.kyb_submitted_at if profile else None,
        kyb_verified_at=profile.kyb_verified_at if profile else None,
        legal_name=profile.legal_name if profile else None,
        registration_number=profile.registration_number if profile else None,
        suspended_at=organization.suspended_at,
        suspension_reason=organization.suspension_reason,
        suspended_by=refs.get(organization.suspended_by)
        if organization.suspended_by
        else None,
        deactivated_at=organization.deactivated_at,
        deactivation_reason=organization.deactivation_reason,
        deactivated_by=refs.get(organization.deactivated_by)
        if organization.deactivated_by
        else None,
        capabilities=[
            AdminOrgCapabilityItem(
                capability=row.capability,
                status=row.status,
                status_reason=row.status_reason,
            )
            for row in capabilities
        ],
        member_count=member_count or 0,
        owners=[
            AdminOrgOwnerItem(
                member_id=row.id,
                user_id=row.user_id,
                display_name=row.display_name,
                email=row.email,
            )
            for row in owner_rows
        ],
    )


async def get_members(db: AsyncSession, *, org_id: UUID) -> AdminOrgMembersResponse:
    """Return every member with role and teams, plus pending invitation count.

    Raises:
        HTTPException(404): If the organization does not exist.
    """
    await _require_org(db, org_id)
    member_rows = (
        await db.execute(
            select(
                OrgMember.id,
                OrgMember.user_id,
                OrgMember.role,
                OrgMember.joined_at,
                User.display_name,
                User.email,
            )
            .join(User, User.id == OrgMember.user_id)
            .where(OrgMember.org_id == org_id)
            .order_by(OrgMember.joined_at, OrgMember.id)
        )
    ).all()
    team_rows = await db.execute(
        select(OrgTeamMember.member_id, OrgTeam.id, OrgTeam.name)
        .join(OrgTeam, OrgTeam.id == OrgTeamMember.team_id)
        .where(OrgTeam.org_id == org_id)
        .order_by(OrgTeam.name)
    )
    teams_by_member: dict[UUID, list[AdminOrgTeamRef]] = {}
    for row in team_rows:
        teams_by_member.setdefault(row.member_id, []).append(
            AdminOrgTeamRef(id=row.id, name=row.name)
        )
    pending = await db.scalar(
        select(func.count())
        .select_from(OrgInvitation)
        .where(OrgInvitation.org_id == org_id, OrgInvitation.status == "pending")
    )
    return AdminOrgMembersResponse(
        members=[
            AdminOrgMemberItem(
                member_id=row.id,
                user_id=row.user_id,
                display_name=row.display_name,
                email=row.email,
                role=row.role,
                joined_at=row.joined_at,
                teams=teams_by_member.get(row.id, []),
            )
            for row in member_rows
        ],
        pending_invitation_count=pending or 0,
    )


async def get_verification(
    db: AsyncSession, *, org_id: UUID, admin_id: UUID
) -> AdminOrgVerificationResponse:
    """Return the legal profile with presigned KYB document links, audited.

    Incorporation and tax documents live in the private artifacts bucket, so
    they are delivered only as 300-second presigned GET URLs. Raw S3 keys are
    never returned; only the original file name is. Every call writes one
    ``org_kyb_documents_viewed`` audit row, even when there are no documents,
    because the admin still looked.

    Args:
        db: Async session.
        org_id: Organization whose verification record to open.
        admin_id: Platform admin requesting the links (audit actor).

    Returns:
        The verification panel.

    Raises:
        HTTPException(404): If the organization does not exist.
    """
    await _require_org(db, org_id)
    profile = await db.scalar(
        select(OrgLegalProfile).where(OrgLegalProfile.org_id == org_id)
    )
    bucket = get_settings().s3_artifacts_bucket

    def _link(kind: str, key: str) -> AdminOrgDocumentLink:
        """Sign one key, or return a null URL when the upload never landed."""
        file_name = _file_name_from_key(key)
        if not s3.storage.object_exists(bucket, key):
            return AdminOrgDocumentLink(
                kind=kind, file_name=file_name, download_url=None
            )
        return AdminOrgDocumentLink(
            kind=kind,
            file_name=file_name,
            download_url=s3.storage.presigned_get(
                bucket, key, KYB_DOCUMENT_TTL_SECONDS, download_name=file_name
            ),
        )

    documents: list[AdminOrgDocumentLink] = []
    if profile is not None:
        documents.extend(
            _link("incorporation", key) for key in profile.incorporation_doc_keys
        )
        if profile.tax_document_key:
            documents.append(_link("tax", profile.tax_document_key))

    await write_audit(
        db=db,
        actor_id=admin_id,
        action="org_kyb_documents_viewed",
        target_type="organization",
        target_id=org_id,
        metadata={"org_id": str(org_id), "document_count": len(documents)},
    )
    await db.commit()
    logger.bind(
        module="admin",
        action="view_org_kyb_documents",
        user_id=admin_id,
        org_id=org_id,
    ).info("org_kyb_documents_viewed", document_count=len(documents))

    return AdminOrgVerificationResponse(
        legal_name=profile.legal_name if profile else None,
        registration_number=profile.registration_number if profile else None,
        address=profile.address if profile else None,
        kyb_status=profile.kyb_status if profile else "unverified",
        kyb_submitted_at=profile.kyb_submitted_at if profile else None,
        kyb_verified_at=profile.kyb_verified_at if profile else None,
        kyb_review_notes=profile.kyb_review_notes if profile else None,
        tax_document_type=profile.tax_document_type if profile else None,
        documents=documents,
    )


async def get_financials(
    db: AsyncSession, *, org_id: UUID
) -> AdminOrgFinancialsResponse:
    """Return balances, payout and purchase summaries, and recent ledger rows.

    Balances come from the same ledger read the org's own earnings endpoint
    uses. Payout rows expose the provider name only — never the payout account.

    Raises:
        HTTPException(404): If the organization does not exist.
    """
    await _require_org(db, org_id)
    earnings = await get_org_earnings(db, org_id=org_id)

    payout_summary = (
        await db.execute(
            select(
                func.count()
                .filter(Payout.status.in_(("pending", "processing")))
                .label("pending_count"),
                func.coalesce(
                    func.sum(Payout.amount).filter(Payout.status == "completed"), 0
                ).label("completed_total"),
                func.max(Payout.initiated_at).label("last_payout_at"),
            ).where(Payout.org_id == org_id)
        )
    ).one()
    purchase_summary = (
        await db.execute(
            select(
                func.count()
                .filter(Transaction.status == "completed")
                .label("completed_count"),
                func.count()
                .filter(Transaction.status == "failed")
                .label("failed_count"),
                func.coalesce(
                    func.sum(Transaction.amount).filter(
                        Transaction.status == "completed"
                    ),
                    0,
                ).label("total_spent"),
            ).where(
                Transaction.payer_org_id == org_id,
                Transaction.transaction_type == "purchase",
            )
        )
    ).one()
    payout_rows = await db.execute(
        select(Payout, PayoutAccount.provider)
        .outerjoin(PayoutAccount, PayoutAccount.id == Payout.payout_account_id)
        .where(Payout.org_id == org_id)
        .order_by(Payout.initiated_at.desc())
        .limit(RECENT_ROWS_LIMIT)
    )
    transactions = (
        await db.scalars(
            select(Transaction)
            .where(
                or_(
                    Transaction.payer_org_id == org_id,
                    Transaction.payee_org_id == org_id,
                )
            )
            .order_by(Transaction.created_at.desc())
            .limit(RECENT_ROWS_LIMIT)
        )
    ).all()
    return AdminOrgFinancialsResponse(
        currency=earnings.currency,
        available_balance=earnings.available_balance,
        pending_balance=earnings.pending_clearance,
        payouts_summary=AdminOrgPayoutsSummary(
            pending_count=payout_summary.pending_count,
            completed_total=payout_summary.completed_total,
            last_payout_at=payout_summary.last_payout_at,
        ),
        purchases_summary=AdminOrgPurchasesSummary(
            completed_count=purchase_summary.completed_count,
            failed_count=purchase_summary.failed_count,
            total_spent=purchase_summary.total_spent,
        ),
        recent_payouts=[
            AdminOrgPayoutItem(
                payout_id=payout.id,
                amount=payout.amount,
                currency=payout.currency,
                status=payout.status,
                provider=provider,
                initiated_at=payout.initiated_at,
                completed_at=payout.completed_at,
            )
            for payout, provider in payout_rows.tuples()
        ],
        recent_transactions=[
            AdminOrgTransactionItem(
                transaction_id=row.id,
                transaction_type=row.transaction_type,
                status=row.status,
                amount=row.amount,
                currency=row.currency,
                created_at=row.created_at,
            )
            for row in transactions
        ],
    )


async def get_frameworks(
    db: AsyncSession, *, org_id: UUID
) -> AdminOrgFrameworksResponse:
    """Return Frameworks the org sells and Licenses it holds.

    Raises:
        HTTPException(404): If the organization does not exist.
    """
    await _require_org(db, org_id)
    frameworks = (
        await db.scalars(
            select(Framework)
            .where(Framework.contributor_org_id == org_id)
            .order_by(Framework.created_at.desc())
        )
    ).all()
    grant_counts = (
        select(LicenseGrant.license_id, func.count().label("grant_count"))
        .group_by(LicenseGrant.license_id)
        .subquery()
    )
    license_rows = await db.execute(
        select(
            License.id,
            License.framework_id,
            Framework.title,
            License.status,
            License.license_type,
            License.created_at,
            func.coalesce(grant_counts.c.grant_count, 0).label("grant_count"),
        )
        .join(Framework, Framework.id == License.framework_id)
        .outerjoin(grant_counts, grant_counts.c.license_id == License.id)
        .where(License.licensee_org_id == org_id)
        .order_by(License.created_at.desc())
    )
    return AdminOrgFrameworksResponse(
        frameworks=[
            AdminOrgFrameworkItem(
                id=row.id, title=row.title, status=row.status, created_at=row.created_at
            )
            for row in frameworks
        ],
        licenses=[
            AdminOrgLicenseItem(
                license_id=row.id,
                framework_id=row.framework_id,
                framework_title=row.title,
                status=row.status,
                license_type=row.license_type,
                created_at=row.created_at,
                grant_count=row.grant_count,
            )
            for row in license_rows
        ],
    )


async def get_attestations(
    db: AsyncSession, *, org_id: UUID
) -> AdminOrgAttestationsResponse:
    """Return the org's in-flight Attestations and in-flight/finished counts.

    Target titles are resolved in batch for framework targets (Framework
    title) and person targets (user display name); other targets get null.

    Raises:
        HTTPException(404): If the organization does not exist.
    """
    await _require_org(db, org_id)
    counts = (
        await db.execute(
            select(
                func.count()
                .filter(Attestation.status.not_in(FINISHED_ATTESTATION_STATUSES))
                .label("in_flight"),
                func.count()
                .filter(Attestation.status.in_(FINISHED_ATTESTATION_STATUSES))
                .label("completed"),
            ).where(Attestation.attestor_org_id == org_id)
        )
    ).one()
    attestations = (
        await db.scalars(
            select(Attestation)
            .where(
                Attestation.attestor_org_id == org_id,
                Attestation.status.not_in(FINISHED_ATTESTATION_STATUSES),
            )
            .order_by(Attestation.created_at.desc())
        )
    ).all()

    framework_ids = {a.target_id for a in attestations if a.target_type == "framework"}
    person_ids = {
        a.target_id
        for a in attestations
        if a.target_type in ("contributor", "operator")
    }
    framework_titles: dict[UUID, str] = {}
    if framework_ids:
        framework_titles = {
            row.id: row.title
            for row in await db.execute(
                select(Framework.id, Framework.title).where(
                    Framework.id.in_(framework_ids)
                )
            )
        }
    person_refs = await _user_refs(db, person_ids)
    member_ids = {a.reviewing_member_id for a in attestations if a.reviewing_member_id}
    member_names: dict[UUID, str] = {}
    if member_ids:
        member_names = {
            row.id: row.display_name
            for row in await db.execute(
                select(OrgMember.id, User.display_name)
                .join(User, User.id == OrgMember.user_id)
                .where(OrgMember.id.in_(member_ids))
            )
        }

    def _target_title(attestation: Attestation) -> str | None:
        """Resolve a human title for the attestation target when cheap."""
        if attestation.target_type == "framework":
            return framework_titles.get(attestation.target_id)
        ref = person_refs.get(attestation.target_id)
        return ref.display_name if ref else None

    return AdminOrgAttestationsResponse(
        attestations=[
            AdminOrgAttestationItem(
                id=attestation.id,
                status=attestation.status,
                target_title=_target_title(attestation),
                reviewing_member_display_name=member_names.get(
                    attestation.reviewing_member_id
                )
                if attestation.reviewing_member_id
                else None,
                completion_due_at=attestation.completion_due_at,
                created_at=attestation.created_at,
            )
            for attestation in attestations
        ],
        counts=AdminOrgAttestationCounts(
            in_flight=counts.in_flight, completed=counts.completed
        ),
    )


async def get_audit(
    db: AsyncSession, *, org_id: UUID, page: int, page_size: int
) -> AdminOrgAuditResponse:
    """Return a page of audit events about the org, newest first.

    An event is about the org when it targets the org directly or carries the
    org's id in ``metadata.org_id`` (events targeting members, applications,
    or documents that belong to it). Actor names resolve in one query.

    Raises:
        HTTPException(404): If the organization does not exist.
    """
    await _require_org(db, org_id)
    relevant = or_(
        AuditLog.target_id == org_id,
        AuditLog.metadata_["org_id"].astext == str(org_id),
    )
    total = await db.scalar(select(func.count()).select_from(AuditLog).where(relevant))
    rows = (
        await db.scalars(
            select(AuditLog)
            .where(relevant)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    actors = await _user_refs(db, [row.actor_id for row in rows])
    return AdminOrgAuditResponse(
        items=[
            AdminOrgAuditItem(
                log_id=row.id,
                actor=actors.get(row.actor_id) if row.actor_id else None,
                action=row.action,
                target_type=row.target_type,
                target_id=row.target_id,
                metadata=row.metadata_,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total or 0,
        page=page,
        page_size=page_size,
    )
