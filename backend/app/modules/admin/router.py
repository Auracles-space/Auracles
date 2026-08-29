"""FastAPI router for admin endpoints."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role, require_superadmin
from app.core.redis import get_redis
from app.modules.admin import service
from app.modules.admin.schemas import (
    AdminAnalyticsDashboardResponse,
    AdminAuditLogsResponse,
    AdminConfigItem,
    AdminConfigPatchRequest,
    AdminConfigResponse,
    AdminConnectorsResponse,
    AdminDeletionRequestsResponse,
    AdminDisputeResolveRequest,
    AdminEscrowDirectoryResponse,
    AdminEscrowOverrideRequest,
    AdminEscrowResponse,
    AdminExportRequestsResponse,
    AdminFinancialEventsResponse,
    AdminFrameworkDirectoryResponse,
    AdminFrameworkStatusResponse,
    AdminFrameworkSuspendRequest,
    AdminInvoicesResponse,
    AdminKycReviewRequest,
    AdminKycReviewResponse,
    AdminLicenseGrantRequest,
    AdminLicenseGrantResponse,
    AdminModerationQueueResponse,
    AdminPayoutDirectoryResponse,
    AdminRarityBlockOverrideRequest,
    AdminReputationRecomputeRequest,
    AdminReputationRecomputeResponse,
    AdminRoleAssignmentRequest,
    AdminRoleAssignmentResponse,
    AdminSuspendedFrameworksResponse,
    AdminTransactionDetailResponse,
    AdminTransactionDirectoryResponse,
    AdminUserDirectoryResponse,
    AdminUserSuspendRequest,
    AdminUserSuspensionResponse,
    AdminUserUnsuspendRequest,
    AdminWaitlistResponse,
    AdminWebhookEventsResponse,
)
from app.modules.attestation import credential_service
from app.modules.attestation.schemas import (
    AdminCredentialRejectRequest,
    AdminCredentialResponse,
    AdminCredentialsResponse,
    CredentialEvidenceDownloadResponse,
)
from app.modules.auth.models import User
from app.modules.financials.models import Escrow, PlatformConfig
from app.modules.projects import dispute_service
from app.modules.projects.schemas import AdminDisputesResponse, DisputeResponse

router = APIRouter(prefix="/admin", tags=["Admin"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
AdminUser = Annotated[User, Depends(require_role("admin"))]
SuperAdminUser = Annotated[User, Depends(require_superadmin)]


def _escrow_response(escrow: Escrow) -> AdminEscrowResponse:
    """Map an escrow model to an admin response schema."""
    return AdminEscrowResponse(
        escrow_id=escrow.id,
        transaction_id=escrow.transaction_id,
        ref_id=escrow.ref_id,
        ref_type=escrow.ref_type,
        amount=str(escrow.amount),
        currency=escrow.currency,
        status=escrow.status,
        released_at=escrow.released_at,
        released_by=escrow.released_by,
    )


def _config_response(items: list[PlatformConfig]) -> AdminConfigResponse:
    """Map config model rows to the admin response schema."""
    return AdminConfigResponse(
        items=[
            AdminConfigItem(
                key=item.key,
                value=item.value,
                editable=item.key in service.EDITABLE_PLATFORM_CONFIG_KEYS,
                updated_at=item.updated_at,
                updated_by=item.updated_by,
            )
            for item in items
        ]
    )


@router.get("/config", response_model=AdminConfigResponse)
async def list_platform_config(
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminConfigResponse:
    """List platform financial configuration for admin review."""
    del admin
    items = await service.list_platform_config(db=db)
    return _config_response(items)


@router.get(
    "/analytics/dashboard",
    response_model=AdminAnalyticsDashboardResponse,
    summary="Get admin dashboard analytics",
    description=(
        "Return current-state admin analytics aggregates plus frozen daily "
        "trend rows from snapshot history."
    ),
)
async def get_admin_analytics_dashboard(
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminAnalyticsDashboardResponse:
    """Return current-state analytics for the admin dashboard."""
    del admin
    dashboard = await service.get_dashboard_analytics(db=db)
    return AdminAnalyticsDashboardResponse.model_validate(dashboard)


@router.get(
    "/analytics/export",
    summary="Export admin analytics as CSV",
    description=(
        "Stream frozen snapshot history plus current live totals as one flat "
        "CSV for bounded admin-selected UTC dates."
    ),
    responses={
        200: {
            "description": "CSV export stream",
            "content": {
                "text/csv": {
                    "schema": {
                        "type": "string",
                        "format": "binary",
                    }
                }
            },
        }
    },
)
async def export_admin_analytics(
    from_date: Annotated[date, Query(alias="from")],
    to_date: Annotated[date, Query(alias="to")],
    admin: AdminUser,
    db: DatabaseSession,
) -> StreamingResponse:
    """Stream the admin analytics CSV export for a bounded UTC date range."""
    filename, csv_payload = await service.export_dashboard_csv(
        db=db,
        admin=admin,
        from_date=from_date,
        to_date=to_date,
    )
    return StreamingResponse(
        iter([csv_payload]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/moderation/queue",
    response_model=AdminModerationQueueResponse,
    summary="List moderation queue rows",
    description=(
        "Aggregate current rarity, near-duplicate, and PII review signals into "
        "one paginated admin moderation queue."
    ),
)
async def list_moderation_queue(
    admin: AdminUser,
    db: DatabaseSession,
    queue_type: Annotated[
        str,
        Query(
            alias="type",
            pattern="^(all|rarity_review|near_duplicate_block|pii_review)$",
        ),
    ] = "all",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminModerationQueueResponse:
    """Return the aggregated moderation queue for admin review."""
    queue = await service.list_moderation_queue(
        db=db,
        admin=admin,
        queue_type=queue_type,
        page=page,
        page_size=page_size,
    )
    return AdminModerationQueueResponse.model_validate(queue)


@router.patch("/config", response_model=AdminConfigResponse)
async def update_platform_config(
    payload: AdminConfigPatchRequest,
    admin: SuperAdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AdminConfigResponse:
    """Update editable platform configuration. Super-admin only, with 2FA."""
    items = await service.update_platform_config(
        db=db,
        redis=redis,
        admin=admin,
        updates=[(item.key, item.value) for item in payload.updates],
        reason=payload.reason,
        totp_code=payload.totp_code,
    )
    return _config_response(items)


@router.patch("/users/{user_id}/roles", response_model=AdminRoleAssignmentResponse)
async def assign_role(
    user_id: UUID,
    payload: AdminRoleAssignmentRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AdminRoleAssignmentResponse:
    """Assign or approve a user role.

    Requires a valid admin TOTP; granting the admin role is super-admin only.
    """
    assigned_role = await service.assign_user_role(
        db=db,
        redis=redis,
        admin=admin,
        target_user_id=user_id,
        role=payload.role,
        totp_code=payload.totp_code,
    )
    return AdminRoleAssignmentResponse(
        user_id=user_id,
        role=assigned_role.role,
        approved=assigned_role.approved_at is not None,
    )


@router.get(
    "/users",
    response_model=AdminUserDirectoryResponse,
    summary="List users for admin account controls",
    description=(
        "Return a paginated admin user directory with search and suspension "
        "status filters for account moderation workflows."
    ),
)
async def list_admin_users(
    admin: AdminUser,
    db: DatabaseSession,
    query: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    status_filter: Annotated[
        str,
        Query(alias="status", pattern="^(all|active|suspended|kyc_pending)$"),
    ] = "all",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminUserDirectoryResponse:
    """Return the admin user directory."""
    del admin
    users = await service.list_admin_users(
        db=db,
        query=query,
        status_filter=status_filter,
        page=page,
        page_size=page_size,
    )
    return AdminUserDirectoryResponse.model_validate(users)


@router.get(
    "/payouts",
    response_model=AdminPayoutDirectoryResponse,
    summary="List payouts for admin financial oversight",
    description=(
        "Return a paginated, read-only payout directory with status and provider "
        "filters. Payout-account destination details are never included."
    ),
)
async def list_admin_payouts(
    admin: AdminUser,
    db: DatabaseSession,
    status_filter: Annotated[
        str,
        Query(alias="status", pattern="^(all|pending|processing|completed|failed)$"),
    ] = "all",
    provider_filter: Annotated[
        str,
        Query(alias="provider", pattern="^(all|stripe|paystack)$"),
    ] = "all",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminPayoutDirectoryResponse:
    """Return the admin payout oversight directory."""
    del admin
    payouts = await service.list_admin_payouts(
        db=db,
        status_filter=status_filter,
        provider_filter=provider_filter,
        page=page,
        page_size=page_size,
    )
    return AdminPayoutDirectoryResponse.model_validate(payouts)


@router.get(
    "/invoices",
    response_model=AdminInvoicesResponse,
    summary="List issued invoices for admin oversight",
    description=(
        "Return a paginated, read-only issued-invoice directory with an "
        "optional search over invoice number or buyer. Internal PDF storage "
        "keys are never included."
    ),
)
async def list_admin_invoices(
    admin: AdminUser,
    db: DatabaseSession,
    query: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminInvoicesResponse:
    """Return the admin issued-invoice directory."""
    del admin
    invoices = await service.list_admin_invoices(
        db=db,
        query=query,
        page=page,
        page_size=page_size,
    )
    return AdminInvoicesResponse.model_validate(invoices)


@router.get(
    "/waitlist",
    response_model=AdminWaitlistResponse,
    summary="List pre-launch waitlist signups",
    description=(
        "Return a paginated, read-only pre-launch waitlist directory with an "
        "optional case-insensitive email search."
    ),
)
async def list_admin_waitlist(
    admin: AdminUser,
    db: DatabaseSession,
    query: Annotated[str | None, Query(min_length=1, max_length=320)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminWaitlistResponse:
    """Return the admin pre-launch waitlist directory."""
    del admin
    waitlist = await service.list_admin_waitlist(
        db=db,
        query=query,
        page=page,
        page_size=page_size,
    )
    return AdminWaitlistResponse.model_validate(waitlist)


@router.get(
    "/connectors",
    response_model=AdminConnectorsResponse,
    summary="List external connections for admin oversight",
    description=(
        "Return a paginated, read-only directory of user OAuth connections to "
        "external file providers with status and provider filters. Encrypted "
        "tokens are never included."
    ),
)
async def list_admin_connectors(
    admin: AdminUser,
    db: DatabaseSession,
    status_filter: Annotated[
        str,
        Query(alias="status", pattern="^(all|active|revoked|reauth_required)$"),
    ] = "all",
    provider: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminConnectorsResponse:
    """Return the admin external-connection oversight directory."""
    del admin
    connectors = await service.list_admin_connectors(
        db=db,
        status_filter=status_filter,
        provider_filter=provider,
        page=page,
        page_size=page_size,
    )
    return AdminConnectorsResponse.model_validate(connectors)


@router.get(
    "/gdpr/deletion-requests",
    response_model=AdminDeletionRequestsResponse,
    summary="List account-deletion requests for GDPR oversight",
    description=(
        "Return a paginated, read-only account-deletion request queue with a "
        "status filter, including any blocked-obligation reasons."
    ),
)
async def list_admin_deletion_requests(
    admin: AdminUser,
    db: DatabaseSession,
    status_filter: Annotated[
        str,
        Query(
            alias="status",
            pattern="^(all|pending|scheduled|blocked|cancelled|completed)$",
        ),
    ] = "all",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminDeletionRequestsResponse:
    """Return the admin account-deletion request queue."""
    del admin
    requests = await service.list_admin_deletion_requests(
        db=db,
        status_filter=status_filter,
        page=page,
        page_size=page_size,
    )
    return AdminDeletionRequestsResponse.model_validate(requests)


@router.get(
    "/gdpr/export-requests",
    response_model=AdminExportRequestsResponse,
    summary="List data-export requests for GDPR oversight",
    description=(
        "Return a paginated, read-only data-export request queue with a status "
        "filter. Internal bundle storage keys are never included."
    ),
)
async def list_admin_export_requests(
    admin: AdminUser,
    db: DatabaseSession,
    status_filter: Annotated[
        str,
        Query(
            alias="status",
            pattern="^(all|pending|processing|ready|failed|expired)$",
        ),
    ] = "all",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminExportRequestsResponse:
    """Return the admin data-export request queue."""
    del admin
    requests = await service.list_admin_export_requests(
        db=db,
        status_filter=status_filter,
        page=page,
        page_size=page_size,
    )
    return AdminExportRequestsResponse.model_validate(requests)


@router.post(
    "/users/{user_id}/suspend",
    response_model=AdminUserSuspensionResponse,
)
async def suspend_user(
    user_id: UUID,
    payload: AdminUserSuspendRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AdminUserSuspensionResponse:
    """Suspend a user account and revoke their active session surface."""
    user = await service.suspend_user(
        db=db,
        redis=redis,
        admin=admin,
        target_user_id=user_id,
        reason=payload.reason,
        totp_code=payload.totp_code,
    )
    return AdminUserSuspensionResponse(
        user_id=user.id,
        suspended=user.suspended_at is not None,
        suspended_at=user.suspended_at,
        suspended_by=user.suspended_by,
        suspension_reason=user.suspension_reason,
    )


@router.post(
    "/users/{user_id}/unsuspend",
    response_model=AdminUserSuspensionResponse,
)
async def unsuspend_user(
    user_id: UUID,
    payload: AdminUserUnsuspendRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AdminUserSuspensionResponse:
    """Restore a previously suspended user account."""
    user = await service.unsuspend_user(
        db=db,
        redis=redis,
        admin=admin,
        target_user_id=user_id,
        totp_code=payload.totp_code,
    )
    return AdminUserSuspensionResponse(
        user_id=user.id,
        suspended=user.suspended_at is not None,
        suspended_at=user.suspended_at,
        suspended_by=user.suspended_by,
        suspension_reason=user.suspension_reason,
    )


@router.patch("/users/{user_id}/kyc", response_model=AdminKycReviewResponse)
async def review_kyc(
    user_id: UUID,
    payload: AdminKycReviewRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AdminKycReviewResponse:
    """Manually override a user's identity-verification status.

    Requires a valid admin TOTP: the verified status unlocks payouts.
    """
    user = await service.review_user_kyc(
        db=db,
        redis=redis,
        admin=admin,
        target_user_id=user_id,
        review_status=payload.status,
        notes=payload.notes,
        totp_code=payload.totp_code,
    )
    return AdminKycReviewResponse(
        user_id=user_id,
        kyc_status=user.kyc_status,
    )


@router.get("/credentials", response_model=AdminCredentialsResponse)
async def list_credential_review_queue(
    admin: AdminUser,
    db: DatabaseSession,
    status_filter: Annotated[
        Literal["unverified", "pending", "verified", "rejected"] | None,
        Query(alias="status"),
    ] = "pending",
) -> AdminCredentialsResponse:
    """List credentials awaiting (or filtered by) verification status."""
    del admin
    credentials = await credential_service.list_credentials_for_review(
        db=db, verification_status=status_filter
    )
    return AdminCredentialsResponse(
        credentials=[
            AdminCredentialResponse.model_validate(credential)
            for credential in credentials
        ]
    )


@router.post(
    "/credentials/{credential_id}/verify",
    response_model=AdminCredentialResponse,
)
async def verify_credential(
    credential_id: UUID,
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminCredentialResponse:
    """Mark a pending Credential verified."""
    credential = await credential_service.verify_credential(
        db=db, admin_id=admin.id, credential_id=credential_id
    )
    return AdminCredentialResponse.model_validate(credential)


@router.post(
    "/credentials/{credential_id}/reject",
    response_model=AdminCredentialResponse,
)
async def reject_credential(
    credential_id: UUID,
    payload: AdminCredentialRejectRequest,
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminCredentialResponse:
    """Reject a pending Credential with a reason."""
    credential = await credential_service.reject_credential(
        db=db,
        admin_id=admin.id,
        credential_id=credential_id,
        reason=payload.reason,
    )
    return AdminCredentialResponse.model_validate(credential)


@router.get(
    "/credentials/{credential_id}/evidence",
    response_model=CredentialEvidenceDownloadResponse,
)
async def download_credential_evidence(
    credential_id: UUID,
    admin: AdminUser,
    db: DatabaseSession,
    key: Annotated[str, Query(min_length=1)],
) -> CredentialEvidenceDownloadResponse:
    """Return a presigned URL for an admin to download credential evidence."""
    url = await credential_service.generate_evidence_download_url(
        db=db,
        requester_id=admin.id,
        credential_id=credential_id,
        key=key,
        is_admin=True,
    )
    return CredentialEvidenceDownloadResponse(url=url)


@router.get(
    "/frameworks",
    response_model=AdminFrameworkDirectoryResponse,
    summary="List published Frameworks for admin delist control",
    description=(
        "Return published Frameworks with their owning Contributor so an admin "
        "can find and delist an arbitrary Framework, not only signal-flagged ones."
    ),
)
async def list_admin_frameworks(
    admin: AdminUser,
    db: DatabaseSession,
    query: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
) -> AdminFrameworkDirectoryResponse:
    """List published Frameworks available for post-publish delisting."""
    del admin
    return AdminFrameworkDirectoryResponse.model_validate(
        await service.list_admin_frameworks(db=db, query=query)
    )


@router.get(
    "/frameworks/suspended",
    response_model=AdminSuspendedFrameworksResponse,
)
async def list_suspended_frameworks(
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminSuspendedFrameworksResponse:
    """List Frameworks suspended from the marketplace for reinstatement review."""
    return AdminSuspendedFrameworksResponse.model_validate(
        await service.list_suspended_frameworks(db=db)
    )


@router.post(
    "/frameworks/{framework_id}/suspend",
    response_model=AdminFrameworkStatusResponse,
)
async def suspend_framework(
    framework_id: UUID,
    payload: AdminFrameworkSuspendRequest,
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminFrameworkStatusResponse:
    """Suspend a published Framework from marketplace discovery."""
    framework = await service.suspend_framework(
        db=db,
        admin=admin,
        framework_id=framework_id,
        reason=payload.reason,
    )
    return AdminFrameworkStatusResponse(
        framework_id=framework.id,
        status=framework.status,
        reason=framework.rejection_reason,
    )


@router.post(
    "/frameworks/{framework_id}/reinstate",
    response_model=AdminFrameworkStatusResponse,
)
async def reinstate_framework(
    framework_id: UUID,
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminFrameworkStatusResponse:
    """Reverse a takedown, returning a suspended Framework to the marketplace."""
    framework = await service.reinstate_framework(
        db=db,
        admin=admin,
        framework_id=framework_id,
    )
    return AdminFrameworkStatusResponse(
        framework_id=framework.id,
        status=framework.status,
        reason=framework.rejection_reason,
    )


@router.post(
    "/frameworks/{framework_id}/rarity-block/override",
    response_model=AdminFrameworkStatusResponse,
)
async def override_rarity_block(
    framework_id: UUID,
    payload: AdminRarityBlockOverrideRequest,
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminFrameworkStatusResponse:
    """Override a near-duplicate rarity hard block after admin review."""
    framework = await service.override_rarity_block(
        db=db,
        admin=admin,
        framework_id=framework_id,
        reason=payload.reason,
    )
    return AdminFrameworkStatusResponse(
        framework_id=framework.id,
        status=framework.status,
        reason=payload.reason,
    )


@router.post(
    "/licenses",
    response_model=AdminLicenseGrantResponse,
    status_code=201,
)
async def grant_license(
    payload: AdminLicenseGrantRequest,
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminLicenseGrantResponse:
    """Grant a Framework license to an Operator during Phase 2."""
    license_row = await service.grant_license(
        db=db,
        admin=admin,
        framework_id=payload.framework_id,
        operator_id=payload.operator_id,
        license_type=payload.type,
        expires_at=payload.expires_at,
        seats_total=payload.seats_total,
    )
    return AdminLicenseGrantResponse(
        license_id=license_row.id,
        framework_id=license_row.framework_id,
        operator_id=license_row.operator_id,
        type=license_row.license_type,
        status=license_row.status,
        version_at_grant=license_row.version_at_grant,
        seats_used=license_row.seats_used,
        seats_total=license_row.seats_total,
        expires_at=license_row.expires_at,
    )


@router.post(
    "/escrows/{escrow_id}/release",
    response_model=AdminEscrowResponse,
)
async def release_escrow(
    escrow_id: UUID,
    payload: AdminEscrowOverrideRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AdminEscrowResponse:
    """Release held escrow funds through an audited admin override."""
    escrow = await service.release_escrow_override(
        db=db,
        redis=redis,
        admin=admin,
        escrow_id=escrow_id,
        reason=payload.reason,
        totp_code=payload.totp_code,
    )
    return _escrow_response(escrow)


@router.post(
    "/escrows/{escrow_id}/refund",
    response_model=AdminEscrowResponse,
)
async def refund_escrow(
    escrow_id: UUID,
    payload: AdminEscrowOverrideRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AdminEscrowResponse:
    """Refund held escrow funds through an audited admin override."""
    escrow = await service.refund_escrow_override(
        db=db,
        redis=redis,
        admin=admin,
        escrow_id=escrow_id,
        reason=payload.reason,
        totp_code=payload.totp_code,
    )
    return _escrow_response(escrow)


@router.post(
    "/reputation/recompute",
    response_model=AdminReputationRecomputeResponse,
    status_code=202,
)
async def recompute_reputation_subject(
    payload: AdminReputationRecomputeRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AdminReputationRecomputeResponse:
    """Queue an audited, 2FA-gated recompute for one reputation subject."""
    await service.recompute_reputation_subject(
        db=db,
        redis=redis,
        admin=admin,
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        reason=payload.reason,
        totp_code=payload.totp_code,
    )
    return AdminReputationRecomputeResponse(
        status="queued",
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
    )


@router.get(
    "/projects/disputes",
    response_model=AdminDisputesResponse,
    summary="List Project disputes for the admin queue",
    description=(
        "Return Project milestone disputes across all Projects, enriched with "
        "the milestone budget, held escrow amount, project title, and raising "
        "party. Defaults to active disputes (open or under_review); pass an "
        "explicit status to view a single status such as resolved."
    ),
)
async def list_project_disputes(
    admin: AdminUser,
    db: DatabaseSession,
    status: Annotated[
        Literal["open", "under_review", "resolved"] | None,
        Query(description="Filter by an exact dispute status."),
    ] = None,
) -> AdminDisputesResponse:
    """Return the Project dispute queue for an authenticated admin."""
    del admin
    return await dispute_service.list_disputes_for_admin(
        db=db,
        status_filter=status,
    )


@router.post(
    "/projects/disputes/{dispute_id}/resolve",
    response_model=DisputeResponse,
)
async def resolve_project_dispute(
    dispute_id: UUID,
    payload: AdminDisputeResolveRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> DisputeResponse:
    """Resolve a Project dispute through an audited 2FA-gated admin action."""
    dispute = await dispute_service.resolve_dispute(
        db=db,
        redis=redis,
        admin=admin,
        dispute_id=dispute_id,
        resolution_type=payload.resolution_type,
        release_amount=payload.release_amount,
        refund_amount=payload.refund_amount,
        resolution_notes=payload.resolution_notes,
        totp_code=payload.totp_code,
    )
    return DisputeResponse.model_validate(dispute)


@router.get(
    "/transactions",
    response_model=AdminTransactionDirectoryResponse,
    summary="List transactions for admin financial oversight",
    description=(
        "Return a paginated, read-only transaction directory with status, "
        "provider, and exact provider-reference filters. Each row carries the "
        "newest normalized failure cause from the financial ledger, so a "
        "failed payment can be triaged without opening it."
    ),
)
async def list_admin_transactions(
    admin: AdminUser,
    db: DatabaseSession,
    status_filter: Annotated[
        str,
        Query(alias="status", pattern="^(all|pending|completed|failed|refunded)$"),
    ] = "all",
    provider_filter: Annotated[
        str,
        Query(alias="provider", pattern="^(all|stripe|paystack)$"),
    ] = "all",
    provider_ref: Annotated[
        str | None,
        Query(
            max_length=255,
            description="Exact provider charge or transfer reference.",
        ),
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminTransactionDirectoryResponse:
    """Return the admin transaction oversight directory."""
    del admin
    transactions = await service.list_admin_transactions(
        db=db,
        status_filter=status_filter,
        provider_filter=provider_filter,
        provider_ref=provider_ref,
        page=page,
        page_size=page_size,
    )
    return AdminTransactionDirectoryResponse.model_validate(transactions)


@router.get(
    "/transactions/{transaction_id}",
    response_model=AdminTransactionDetailResponse,
    summary="Trace one payment end to end",
    description=(
        "Return one transaction with its escrow holdings and its full ledger "
        "timeline, oldest first. The timeline is the only place intermediate "
        "states survive: the status column keeps just the final value."
    ),
)
async def get_admin_transaction_detail(
    transaction_id: UUID,
    admin: AdminUser,
    db: DatabaseSession,
) -> AdminTransactionDetailResponse:
    """Return one payment's escrow holdings and ledger timeline."""
    del admin
    detail = await service.get_admin_transaction_detail(
        db=db,
        transaction_id=transaction_id,
    )
    return AdminTransactionDetailResponse.model_validate(detail)


@router.get(
    "/financial-events",
    response_model=AdminFinancialEventsResponse,
    summary="Read the financial ledger feed",
    description=(
        "Return the append-only financial ledger, newest first, filterable by "
        "entity type, event type, normalized failure cause, and provider. The "
        "failure vocabulary is provider-neutral, so one cause filter matches "
        "both Stripe and Paystack."
    ),
)
async def list_admin_financial_events(
    admin: AdminUser,
    db: DatabaseSession,
    entity_type: Annotated[str | None, Query(max_length=50)] = None,
    event_type: Annotated[str | None, Query(max_length=100)] = None,
    reason_code: Annotated[str | None, Query(max_length=100)] = None,
    provider_filter: Annotated[
        str,
        Query(alias="provider", pattern="^(all|stripe|paystack)$"),
    ] = "all",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminFinancialEventsResponse:
    """Return the admin financial ledger feed."""
    del admin
    events = await service.list_admin_financial_events(
        db=db,
        entity_type=entity_type,
        event_type=event_type,
        reason_code=reason_code,
        provider_filter=provider_filter,
        page=page,
        page_size=page_size,
    )
    return AdminFinancialEventsResponse.model_validate(events)


@router.get(
    "/escrows",
    response_model=AdminEscrowDirectoryResponse,
    summary="List escrow holdings for admin financial oversight",
    description=(
        "Return a paginated, read-only escrow directory. Releases and refunds "
        "remain on their own explicit, audited endpoints."
    ),
)
async def list_admin_escrows(
    admin: AdminUser,
    db: DatabaseSession,
    status_filter: Annotated[
        str,
        Query(alias="status", pattern="^(all|held|released|refunded)$"),
    ] = "all",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminEscrowDirectoryResponse:
    """Return the admin escrow oversight directory."""
    del admin
    escrows = await service.list_admin_escrows(
        db=db,
        status_filter=status_filter,
        page=page,
        page_size=page_size,
    )
    return AdminEscrowDirectoryResponse.model_validate(escrows)


@router.get(
    "/webhook-events",
    response_model=AdminWebhookEventsResponse,
    summary="Read the provider webhook delivery log",
    description=(
        "Return stored provider webhook deliveries, newest first, including "
        "the error recorded when an event failed to apply. Only the payload "
        "hash is stored, so no signed provider body is exposed."
    ),
)
async def list_admin_webhook_events(
    admin: AdminUser,
    db: DatabaseSession,
    status_filter: Annotated[
        str,
        Query(alias="status", pattern="^(all|received|processed|failed)$"),
    ] = "all",
    provider_filter: Annotated[
        str,
        Query(alias="provider", pattern="^(all|stripe|paystack)$"),
    ] = "all",
    event_type: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminWebhookEventsResponse:
    """Return the admin webhook delivery log."""
    del admin
    events = await service.list_admin_webhook_events(
        db=db,
        status_filter=status_filter,
        provider_filter=provider_filter,
        event_type=event_type,
        page=page,
        page_size=page_size,
    )
    return AdminWebhookEventsResponse.model_validate(events)


@router.get(
    "/audit-logs",
    response_model=AdminAuditLogsResponse,
    summary="Read the audit log",
    description=(
        "Return audit entries, newest first, filterable by action, target "
        "type, and actor. Complements the financial ledger: the ledger answers "
        "what happened to a payment, this answers who acted."
    ),
)
async def list_admin_audit_logs(
    admin: AdminUser,
    db: DatabaseSession,
    action: Annotated[str | None, Query(max_length=100)] = None,
    target_type: Annotated[str | None, Query(max_length=100)] = None,
    actor_id: Annotated[UUID | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminAuditLogsResponse:
    """Return the admin audit log view."""
    del admin
    logs = await service.list_admin_audit_logs(
        db=db,
        action=action,
        target_type=target_type,
        actor_id=actor_id,
        page=page,
        page_size=page_size,
    )
    return AdminAuditLogsResponse.model_validate(logs)
