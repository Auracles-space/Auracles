"""GDPR data export request and bundle generation service.

Creates owner-scoped export request records, enforces one active generation per
user, and builds deny-by-default JSON bundles for Celery workers.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from fastapi import HTTPException, status
from fastapi.responses import RedirectResponse, Response
from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.rate_limit import RateLimiter, RedisCounter
from app.integrations import s3
from app.modules.attestation.models import (
    Attestation,
    Credential,
)
from app.modules.auth.models import User, UserRole
from app.modules.developer.models import (
    ApiKey,
    DeveloperAccount,
    DeveloperApplication,
    PartnerCommission,
    PartnerPayout,
    PartnerWebhook,
)
from app.modules.financials.models import (
    Payout,
    PayoutAccount,
    Transaction,
)
from app.modules.frameworks.models import Framework, License, Review
from app.modules.gdpr.models import DataExportRequest
from app.modules.gdpr.redaction import redact_metadata
from app.modules.gdpr.schemas import DataExportRequestResponse
from app.modules.integrations.service import export_user_connections
from app.modules.organizations.models import OrgMember, OrgMemberNda
from app.modules.organizations.service import export_user_org_memberships
from app.modules.projects.models import (
    Deliverable,
    Dispute,
    Milestone,
    Project,
    Proposal,
    ProposalAmendment,
)
from app.modules.workspace.models import WorkspaceMessage
from app.shared.models.audit_log import AuditLog
from app.workers.tasks import gdpr_beat

ACTIVE_EXPORT_STATUSES = {"pending", "processing"}
EXPORT_REQUEST_LIMITER = RateLimiter(
    namespace="gdpr_export_request",
    limit=3,
    window=86_400,
)
# Presigned export URLs are cheap to mint but security-sensitive, so cap repeats.
EXPORT_DOWNLOAD_LIMITER = RateLimiter(
    namespace="gdpr_export_download",
    limit=20,
    window=3_600,
)
DATA_EXPORT_DOWNLOAD_URL_TTL_SECONDS = 600
DATA_EXPORT_DOWNLOAD_FILENAME = "auracles-data-export.json"


def _export_response(request: DataExportRequest) -> DataExportRequestResponse:
    """Convert an export request row into its public response shape."""
    return DataExportRequestResponse(
        id=request.id,
        status=request.status,
        requested_at=request.requested_at,
        completed_at=request.completed_at,
        expires_at=request.expires_at,
        failure_reason=request.failure_reason,
    )


def _json_value(value: Any) -> Any:
    """Convert common database scalar values to JSON-safe values."""
    if isinstance(value, UUID | datetime | date):
        return value.isoformat() if not isinstance(value, UUID) else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


async def _collect_profile(db: AsyncSession, user: User) -> dict[str, Any]:
    """Collect profile and role fields explicitly allowed for export."""
    roles = (
        (await db.execute(select(UserRole).where(UserRole.user_id == user.id)))
        .scalars()
        .all()
    )
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
        "bio": user.bio,
        "location": user.location,
        "website": user.website,
        "kyc_status": user.kyc_status,
        "email_verified": user.email_verified,
        "deactivated_at": _json_value(user.deactivated_at),
        "updated_at": _json_value(user.updated_at),
        "roles": [
            {
                "role": role.role,
                "approved_at": _json_value(role.approved_at),
                "created_at": _json_value(role.created_at),
            }
            for role in roles
        ],
    }


async def _collect_financial(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    """Collect financial ledger records without provider secrets or account refs."""
    transactions = (
        (
            await db.execute(
                select(Transaction)
                .where(
                    or_(
                        Transaction.payer_id == user_id,
                        Transaction.payee_id == user_id,
                    )
                )
                .order_by(Transaction.updated_at)
            )
        )
        .scalars()
        .all()
    )
    licenses = (
        (
            await db.execute(
                select(License)
                .where(License.operator_id == user_id)
                .order_by(License.granted_at)
            )
        )
        .scalars()
        .all()
    )
    payouts = (
        (
            await db.execute(
                select(Payout)
                .where(Payout.contributor_id == user_id)
                .order_by(Payout.initiated_at)
            )
        )
        .scalars()
        .all()
    )
    payout_accounts = (
        (
            await db.execute(
                select(PayoutAccount)
                .where(PayoutAccount.user_id == user_id)
                .order_by(PayoutAccount.created_at)
            )
        )
        .scalars()
        .all()
    )
    developer_account = await db.scalar(
        select(DeveloperAccount).where(DeveloperAccount.user_id == user_id)
    )
    partner_commissions: list[PartnerCommission] = []
    if developer_account is not None:
        partner_commissions = list(
            (
                await db.execute(
                    select(PartnerCommission)
                    .where(
                        PartnerCommission.developer_account_id == developer_account.id
                    )
                    .order_by(PartnerCommission.created_at)
                )
            )
            .scalars()
            .all()
        )
    return {
        "transactions": [
            {
                "id": str(row.id),
                "payer_id": str(row.payer_id),
                "payee_id": str(row.payee_id) if row.payee_id else None,
                "amount": _json_value(row.amount),
                "currency": row.currency,
                "platform_commission": _json_value(row.platform_commission),
                "net_amount": _json_value(row.net_amount),
                "type": row.transaction_type,
                "status": row.status,
                "provider": row.provider,
                "ref_id": str(row.ref_id) if row.ref_id else None,
                "ref_type": row.ref_type,
                "updated_at": _json_value(row.updated_at),
            }
            for row in transactions
        ],
        "licenses": [
            {
                "id": str(row.id),
                "framework_id": str(row.framework_id),
                "transaction_id": str(row.transaction_id)
                if row.transaction_id
                else None,
                "source": row.source,
                "type": row.license_type,
                "status": row.status,
                "version_at_grant": row.version_at_grant,
                "granted_at": _json_value(row.granted_at),
                "expires_at": _json_value(row.expires_at),
                "seats_used": row.seats_used,
                "seats_total": row.seats_total,
            }
            for row in licenses
        ],
        "payouts": [
            {
                "id": str(row.id),
                "payout_account_id": str(row.payout_account_id),
                "amount": _json_value(row.amount),
                "currency": row.currency,
                "commission_deducted": _json_value(row.commission_deducted),
                "net_amount": _json_value(row.net_amount),
                "status": row.status,
                "initiated_at": _json_value(row.initiated_at),
                "completed_at": _json_value(row.completed_at),
            }
            for row in payouts
        ],
        "payout_accounts": [
            {
                "id": str(row.id),
                "provider": row.provider,
                "type": row.account_type,
                "is_default": row.is_default,
                "verified_at": _json_value(row.verified_at),
                "deleted_at": _json_value(row.deleted_at),
                "created_at": _json_value(row.created_at),
            }
            for row in payout_accounts
        ],
        "partner_commissions": [
            {
                "id": str(row.id),
                "api_key_id": str(row.api_key_id),
                "transaction_id": str(row.transaction_id),
                "framework_id": str(row.framework_id),
                "sale_amount": _json_value(row.sale_amount),
                "currency": row.currency,
                "tier_at_sale": row.tier_at_sale,
                "tier_rate": _json_value(row.tier_rate),
                "commission_amount": _json_value(row.commission_amount),
                "status": row.status,
                "cleared_at": _json_value(row.cleared_at),
                "payout_id": str(row.payout_id) if row.payout_id else None,
                "created_at": _json_value(row.created_at),
            }
            for row in partner_commissions
        ],
    }


async def _collect_frameworks(db: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    """Collect contributor-authored Framework metadata without artifacts."""
    frameworks = (
        (
            await db.execute(
                select(Framework)
                .where(Framework.contributor_id == user_id)
                .order_by(Framework.updated_at)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(row.id),
            "title": row.title,
            "description": row.description,
            "version": row.version,
            "status": row.status,
            "category": row.category,
            "sector": row.sector,
            "industry": row.industry,
            "function": row.business_function,
            "tags": row.tags,
            "jurisdiction": row.jurisdiction,
            "complexity": row.complexity,
            "org_size": row.org_size,
            "price": _json_value(row.price),
            "currency": row.currency,
            "license_types": row.license_types,
            "published_at": _json_value(row.published_at),
            "updated_at": _json_value(row.updated_at),
        }
        for row in frameworks
    ]


async def _collect_reviews(db: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
    """Collect reviews authored by the user."""
    reviews = (
        (
            await db.execute(
                select(Review)
                .where(Review.operator_id == user_id)
                .order_by(Review.updated_at)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(row.id),
            "framework_id": str(row.framework_id),
            "license_id": str(row.license_id),
            "score": row.score,
            "body": row.body,
            "updated_at": _json_value(row.updated_at),
        }
        for row in reviews
    ]


async def _collect_projects(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    """Collect project records owned by or authored by the user."""
    projects = (
        (
            await db.execute(
                select(Project)
                .where(Project.operator_id == user_id)
                .order_by(Project.updated_at)
            )
        )
        .scalars()
        .all()
    )
    project_ids = [project.id for project in projects]
    milestones: list[Milestone] = []
    if project_ids:
        milestones = list(
            (
                await db.execute(
                    select(Milestone)
                    .where(Milestone.project_id.in_(project_ids))
                    .order_by(Milestone.created_at)
                )
            )
            .scalars()
            .all()
        )
    proposals = (
        (
            await db.execute(
                select(Proposal)
                .where(Proposal.contributor_id == user_id)
                .order_by(Proposal.created_at)
            )
        )
        .scalars()
        .all()
    )
    amendments = (
        (
            await db.execute(
                select(ProposalAmendment)
                .where(
                    or_(
                        ProposalAmendment.proposed_by == user_id,
                        ProposalAmendment.responded_by == user_id,
                    )
                )
                .order_by(ProposalAmendment.created_at)
            )
        )
        .scalars()
        .all()
    )
    deliverables = (
        (
            await db.execute(
                select(Deliverable)
                .where(Deliverable.contributor_id == user_id)
                .order_by(Deliverable.created_at)
            )
        )
        .scalars()
        .all()
    )
    disputes = (
        (
            await db.execute(
                select(Dispute)
                .where(or_(Dispute.raised_by == user_id, Dispute.admin_id == user_id))
                .order_by(Dispute.created_at)
            )
        )
        .scalars()
        .all()
    )
    workspace_messages = (
        (
            await db.execute(
                select(WorkspaceMessage)
                .where(WorkspaceMessage.sender_id == user_id)
                .order_by(WorkspaceMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {
        "projects": [
            {
                "id": str(row.id),
                "title": row.title,
                "description": row.description,
                "category": row.category,
                "required_deliverables": _json_value(row.required_deliverables),
                "budget_min": _json_value(row.budget_min),
                "budget_max": _json_value(row.budget_max),
                "currency": row.currency,
                "deadline": _json_value(row.deadline),
                "status": row.status,
                "created_at": _json_value(row.created_at),
                "updated_at": _json_value(row.updated_at),
            }
            for row in projects
        ],
        "proposals": [
            {
                "id": str(row.id),
                "project_id": str(row.project_id),
                "scope": row.scope,
                "budget": _json_value(row.budget),
                "currency": row.currency,
                "timeline_days": row.timeline_days,
                "deliverables": _json_value(row.deliverables),
                "status": row.status,
                "created_at": _json_value(row.created_at),
            }
            for row in proposals
        ],
        "proposal_amendments": [
            {
                "id": str(row.id),
                "proposal_id": str(row.proposal_id),
                "change_type": row.change_type,
                "before": _json_value(row.before),
                "after": _json_value(row.after),
                "reason": row.reason,
                "status": row.status,
                "created_at": _json_value(row.created_at),
            }
            for row in amendments
        ],
        "milestones": [
            {
                "id": str(row.id),
                "project_id": str(row.project_id),
                "sequence": row.sequence,
                "name": row.name,
                "description": row.description,
                "budget": _json_value(row.budget),
                "currency": row.currency,
                "due_date": _json_value(row.due_date),
                "status": row.status,
                "funded_at": _json_value(row.funded_at),
                "submitted_at": _json_value(row.submitted_at),
                "approved_at": _json_value(row.approved_at),
                "created_at": _json_value(row.created_at),
            }
            for row in milestones
        ],
        "deliverables": [
            {
                "id": str(row.id),
                "milestone_id": str(row.milestone_id),
                "name": row.name,
                "description": row.description,
                "status": row.status,
                "submitted_at": _json_value(row.submitted_at),
                "approved_at": _json_value(row.approved_at),
                "created_at": _json_value(row.created_at),
            }
            for row in deliverables
        ],
        "disputes": [
            {
                "id": str(row.id),
                "project_id": str(row.project_id),
                "milestone_id": str(row.milestone_id),
                "reason": row.reason,
                "status": row.status,
                "resolution_type": row.resolution_type,
                "release_amount": _json_value(row.release_amount),
                "refund_amount": _json_value(row.refund_amount),
                "resolved_at": _json_value(row.resolved_at),
                "created_at": _json_value(row.created_at),
            }
            for row in disputes
        ],
        "workspace_messages": [
            {
                "id": str(row.id),
                "project_id": str(row.project_id),
                "body": row.body,
                "scan_status": row.scan_status,
                "created_at": _json_value(row.created_at),
            }
            for row in workspace_messages
        ],
    }


async def _collect_attestation(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    """Collect attestation records tied to the user.

    Covers the user's own requested attestations, their user-owned credentials,
    NDA signatures, and the ids/dates of attestations they personally staffed as
    an org reviewing member. Org attestor application/profile data is org-owned
    and is not part of a user export.
    """
    credentials = (
        (
            await db.execute(
                select(Credential)
                .where(Credential.user_id == user_id)
                .order_by(Credential.updated_at)
            )
        )
        .scalars()
        .all()
    )
    attestations = (
        (
            await db.execute(
                select(Attestation)
                .where(Attestation.requestor_id == user_id)
                .order_by(Attestation.updated_at)
            )
        )
        .scalars()
        .all()
    )
    nda_signatures = (
        await db.execute(
            select(OrgMemberNda.nda_version, OrgMemberNda.signed_at)
            .join(OrgMember, OrgMember.id == OrgMemberNda.member_id)
            .where(OrgMember.user_id == user_id)
            .order_by(OrgMemberNda.signed_at)
        )
    ).all()
    # Reviewing-member assignment history: attestations this user personally
    # staffed on behalf of an attestor org. Ids and dates only — never the
    # report content, requestor identity, or the org's earnings.
    reviewing_assignments = (
        await db.execute(
            select(
                Attestation.id,
                Attestation.accepted_at,
                Attestation.updated_at,
            )
            .join(OrgMember, OrgMember.id == Attestation.reviewing_member_id)
            .where(OrgMember.user_id == user_id)
            .order_by(Attestation.updated_at)
        )
    ).all()
    return {
        "credentials": [
            {
                "id": str(row.id),
                "title": row.title,
                "issuer": row.issuer,
                "issued_date": _json_value(row.issued_date),
                "expires_date": _json_value(row.expires_date),
                "updated_at": _json_value(row.updated_at),
            }
            for row in credentials
        ],
        "attestations": [
            {
                "id": str(row.id),
                "target_type": row.target_type,
                "target_id": str(row.target_id),
                "requestor_id": str(row.requestor_id),
                "status": row.status,
                "outcome": row.outcome,
                "summary": row.summary,
                "scope": row.scope,
                "updated_at": _json_value(row.updated_at),
            }
            for row in attestations
        ],
        "nda_signatures": [
            {
                "nda_version": nda_version,
                "signed_at": _json_value(signed_at),
            }
            for nda_version, signed_at in nda_signatures
        ],
        "reviewing_member_assignments": [
            {
                "attestation_id": str(attestation_id),
                "accepted_at": _json_value(accepted_at),
                "updated_at": _json_value(updated_at),
            }
            for attestation_id, accepted_at, updated_at in reviewing_assignments
        ],
    }


async def _collect_developer(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    """Collect Developer platform metadata without credentials or secrets."""
    applications = (
        (
            await db.execute(
                select(DeveloperApplication)
                .where(DeveloperApplication.user_id == user_id)
                .order_by(DeveloperApplication.created_at)
            )
        )
        .scalars()
        .all()
    )
    account = await db.scalar(
        select(DeveloperAccount).where(DeveloperAccount.user_id == user_id)
    )
    api_keys: list[ApiKey] = []
    webhooks: list[PartnerWebhook] = []
    payouts: list[PartnerPayout] = []
    if account is not None:
        api_keys = list(
            (
                await db.execute(
                    select(ApiKey)
                    .where(ApiKey.developer_account_id == account.id)
                    .order_by(ApiKey.created_at)
                )
            )
            .scalars()
            .all()
        )
        webhooks = list(
            (
                await db.execute(
                    select(PartnerWebhook)
                    .where(PartnerWebhook.developer_account_id == account.id)
                    .order_by(PartnerWebhook.created_at)
                )
            )
            .scalars()
            .all()
        )
        payouts = list(
            (
                await db.execute(
                    select(PartnerPayout)
                    .where(PartnerPayout.developer_account_id == account.id)
                    .order_by(PartnerPayout.created_at)
                )
            )
            .scalars()
            .all()
        )
    return {
        "applications": [
            {
                "id": str(row.id),
                "company_name": row.company_name,
                "website": row.website,
                "use_case": row.use_case,
                "status": row.status,
                "admin_feedback": row.admin_feedback,
                "created_at": _json_value(row.created_at),
            }
            for row in applications
        ],
        "account": (
            {
                "id": str(account.id),
                "status": account.status,
                "company_name": account.company_name,
                "commission_tier": account.commission_tier,
                "tier_rate": _json_value(account.tier_rate),
                "approved_at": _json_value(account.approved_at),
                "updated_at": _json_value(account.updated_at),
            }
            if account is not None
            else None
        ),
        "api_keys": [
            {
                "id": str(row.id),
                "name": row.name,
                "key_prefix": row.key_prefix,
                "scopes": row.scopes,
                "rate_limit_per_min": row.rate_limit_per_min,
                "status": row.status,
                "expires_at": _json_value(row.expires_at),
                "revoked_at": _json_value(row.revoked_at),
                "last_used_at": _json_value(row.last_used_at),
                "created_at": _json_value(row.created_at),
            }
            for row in api_keys
        ],
        "partner_webhooks": [
            {
                "id": str(row.id),
                "url": row.url,
                "events": row.events,
                "active": row.active,
                "created_at": _json_value(row.created_at),
            }
            for row in webhooks
        ],
        "partner_payouts": [
            {
                "id": str(row.id),
                "payout_account_id": str(row.payout_account_id),
                "amount": _json_value(row.amount),
                "currency": row.currency,
                "status": row.status,
                "initiated_at": _json_value(row.initiated_at),
                "completed_at": _json_value(row.completed_at),
                "created_at": _json_value(row.created_at),
            }
            for row in payouts
        ],
    }


async def _collect_security_audit(
    db: AsyncSession,
    user_id: UUID,
) -> list[dict[str, Any]]:
    """Collect audit rows involving the user with metadata redacted."""
    audit_logs = (
        (
            await db.execute(
                select(AuditLog)
                .where(
                    (AuditLog.actor_id == user_id)
                    | (
                        (AuditLog.target_type == "user")
                        & (AuditLog.target_id == user_id)
                    )
                )
                .order_by(AuditLog.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(row.id),
            "action": row.action,
            "target_type": row.target_type,
            "target_id": str(row.target_id) if row.target_id else None,
            "metadata": _json_value(redact_metadata(row.metadata_)),
            "created_at": _json_value(row.created_at),
        }
        for row in audit_logs
    ]


async def request_data_export(
    *,
    db: AsyncSession,
    redis: Redis,
    user: User,
) -> DataExportRequestResponse:
    """Create a GDPR data export request and enqueue bundle generation."""
    user_id = user.id
    await EXPORT_REQUEST_LIMITER.check(cast(RedisCounter, redis), str(user_id))

    if db.in_transaction():
        await db.rollback()
    try:
        async with db.begin():
            existing = await db.scalar(
                select(DataExportRequest).where(
                    DataExportRequest.user_id == user_id,
                    DataExportRequest.status.in_(ACTIVE_EXPORT_STATUSES),
                )
            )
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A data export is already pending or processing.",
                )

            export_request = DataExportRequest(user_id=user_id, status="pending")
            db.add(export_request)
            await db.flush()
            export_request_id = export_request.id
            await write_audit(
                db=db,
                actor_id=user_id,
                action="gdpr_export_requested",
                target_type="data_export_request",
                target_id=export_request_id,
            )
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A data export is already pending or processing.",
        ) from exc

    gdpr_beat.generate_data_export.delay(str(export_request_id))
    return await get_data_export_status(
        db=db,
        user_id=user_id,
        export_request_id=export_request_id,
    )


async def get_data_export_status(
    *,
    db: AsyncSession,
    user_id: UUID,
    export_request_id: UUID,
) -> DataExportRequestResponse:
    """Return one owner-scoped GDPR export request status."""
    request = await db.scalar(
        select(DataExportRequest).where(
            DataExportRequest.id == export_request_id,
            DataExportRequest.user_id == user_id,
        )
    )
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data export request not found.",
        )
    return _export_response(request)


async def get_latest_data_export_status(
    *,
    db: AsyncSession,
    user_id: UUID,
) -> DataExportRequestResponse:
    """Return the latest owner-scoped GDPR export request status."""
    request = await db.scalar(
        select(DataExportRequest)
        .where(DataExportRequest.user_id == user_id)
        .order_by(DataExportRequest.requested_at.desc())
    )
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data export request not found.",
        )
    return _export_response(request)


async def download_data_export(
    *,
    db: AsyncSession,
    redis: Redis,
    user_id: UUID,
    export_request_id: UUID,
) -> Response:
    """Return an owner-scoped presigned download redirect for a ready export."""
    await EXPORT_DOWNLOAD_LIMITER.check(cast(RedisCounter, redis), str(user_id))
    request = await db.scalar(
        select(DataExportRequest).where(
            DataExportRequest.id == export_request_id,
            DataExportRequest.user_id == user_id,
        )
    )
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data export request not found.",
        )
    if request.status != "ready" or request.bundle_key is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Data export is not ready for download.",
        )
    if request.expires_at is not None and request.expires_at <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Data export has expired.",
        )
    settings = get_settings()
    download_url = s3.storage.presigned_get(
        settings.s3_reports_bucket,
        request.bundle_key,
        DATA_EXPORT_DOWNLOAD_URL_TTL_SECONDS,
        download_name=DATA_EXPORT_DOWNLOAD_FILENAME,
    )
    return RedirectResponse(url=download_url, status_code=status.HTTP_302_FOUND)


async def build_data_export_bundle(
    *,
    db: AsyncSession,
    user_id: UUID,
) -> dict[str, Any]:
    """Build a deny-by-default JSON data export bundle for one user."""
    user = await db.get(User, user_id)
    if user is None:
        raise ValueError("User not found.")
    return {
        "profile": await _collect_profile(db, user),
        "financial": await _collect_financial(db, user_id),
        "reviews": await _collect_reviews(db, user_id),
        "frameworks": await _collect_frameworks(db, user_id),
        "projects": await _collect_projects(db, user_id),
        "attestation": await _collect_attestation(db, user_id),
        "developer": await _collect_developer(db, user_id),
        "reputation": {},
        "security_audit": await _collect_security_audit(db, user_id),
        "organization_memberships": await export_user_org_memberships(
            db, user_id=user_id
        ),
        "connected_integrations": await export_user_connections(
            db, user_id=user_id
        ),
    }
