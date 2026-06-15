"""Attestation API router."""

from __future__ import annotations

from datetime import date as _date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.redis import get_redis
from app.modules.attestation import (
    application_service,
    credential_service,
    dispute_service,
    matching_service,
    release_service,
)
from app.modules.attestation import (
    report as report_service,
)
from app.modules.attestation import service as attestation_service
from app.modules.attestation.dependencies import require_approved_attestor
from app.modules.attestation.models import Credential as _CredentialModel
from app.modules.attestation.schemas import (
    AdminAttestationAssignRequest,
    AdminAttestationDisputeResolveRequest,
    AdminAttestationRefundRequest,
    AttestationDisputeCreateRequest,
    AttestationDisputeResponse,
    AttestationEvidenceUploadCreateRequest,
    AttestationEvidenceUploadSessionResponse,
    AttestationFundingResponse,
    AttestationReportSubmitRequest,
    AttestationRequestCreateRequest,
    AttestationRequestResponse,
    AttestationsResponse,
    AttestorApplicationCreateRequest,
    AttestorApplicationResponse,
    AttestorApplicationReviewRequest,
    AttestorApplicationsResponse,
    AttestorAssignmentResponse,
    AttestorAssignmentsResponse,
    CredentialCreateRequest,
    CredentialEvidenceUploadCreateRequest,
    CredentialEvidenceUploadSessionResponse,
    CredentialResponse,
    CredentialsResponse,
    CredentialUpdateRequest,
)
from app.modules.auth.models import User

router = APIRouter(tags=["Attestation"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]
CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_role("admin"))]
ApprovedAttestorUser = Annotated[User, Depends(require_approved_attestor)]


def _credential_response(credential: _CredentialModel) -> CredentialResponse:
    """Build a CredentialResponse with the derived ``expired`` flag."""
    expired = (
        credential.expires_date is not None
        and credential.expires_date < _date.today()
    )
    return CredentialResponse.model_validate(
        {
            **{
                column: getattr(credential, column)
                for column in (
                    "id",
                    "user_id",
                    "title",
                    "issuer",
                    "issued_date",
                    "expires_date",
                    "evidence_file_keys",
                    "credential_type",
                    "verification_url",
                    "reference_number",
                    "issuer_type",
                    "verification_status",
                    "submitted_at",
                    "verified_at",
                    "reviewed_by",
                    "rejection_reason",
                    "created_at",
                    "updated_at",
                )
            },
            "expired": expired,
        }
    )
RequestorUser = Annotated[User, Depends(require_role("contributor", "operator"))]


@router.post(
    "/attestations",
    response_model=AttestationFundingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_attestation(
    payload: AttestationRequestCreateRequest,
    requestor: RequestorUser,
    db: DatabaseSession,
) -> AttestationFundingResponse:
    """Create an escrow-funded Attestation request for an owned target."""
    return await attestation_service.request_attestation(
        db=db,
        requestor=requestor,
        payload=payload,
    )


@router.get("/attestations", response_model=AttestationsResponse)
async def list_attestations(
    user: CurrentUser,
    db: DatabaseSession,
    role: Literal["requestor", "attestor"] = Query(default="requestor"),
) -> AttestationsResponse:
    """List Attestations visible to the authenticated user by workflow role."""
    attestations = await attestation_service.list_attestations_for_user(
        db=db,
        user=user,
        role=role,
    )
    return AttestationsResponse(
        attestations=[
            AttestationRequestResponse.model_validate(attestation)
            for attestation in attestations
        ]
    )


@router.get(
    "/attestations/{attestation_id}",
    response_model=AttestationRequestResponse,
)
async def get_attestation(
    attestation_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
) -> AttestationRequestResponse:
    """Return Attestation details visible to an involved user."""
    attestation = await matching_service.get_attestation_for_user(
        db=db,
        attestation_id=attestation_id,
        user=user,
    )
    return AttestationRequestResponse.model_validate(attestation)


@router.post(
    "/attestations/{attestation_id}/accept",
    response_model=AttestationRequestResponse,
)
async def accept_attestation_offer(
    attestation_id: UUID,
    attestor: ApprovedAttestorUser,
    db: DatabaseSession,
) -> AttestationRequestResponse:
    """Accept an open Attestation cohort offer as an approved Attestor."""
    attestation = await matching_service.accept_attestation_offer(
        db=db,
        attestation_id=attestation_id,
        attestor=attestor,
    )
    return AttestationRequestResponse.model_validate(attestation)


@router.post(
    "/attestations/{attestation_id}/decline",
    response_model=AttestationRequestResponse,
)
async def decline_attestation_offer(
    attestation_id: UUID,
    attestor: ApprovedAttestorUser,
    db: DatabaseSession,
) -> AttestationRequestResponse:
    """Decline an open Attestation cohort offer as an approved Attestor."""
    attestation = await matching_service.decline_attestation_offer(
        db=db,
        attestation_id=attestation_id,
        attestor=attestor,
    )
    return AttestationRequestResponse.model_validate(attestation)


@router.post(
    "/attestations/{attestation_id}/uploads",
    response_model=AttestationEvidenceUploadSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_attestation_report_evidence_upload_session(
    attestation_id: UUID,
    payload: AttestationEvidenceUploadCreateRequest,
    attestor: ApprovedAttestorUser,
    db: DatabaseSession,
) -> AttestationEvidenceUploadSessionResponse:
    """Create a presigned POST upload session for report evidence."""
    return await report_service.create_report_evidence_upload_session(
        db=db,
        attestor=attestor,
        attestation_id=attestation_id,
        payload=payload,
    )


@router.post(
    "/attestations/{attestation_id}/report",
    response_model=AttestationRequestResponse,
)
async def submit_attestation_report(
    attestation_id: UUID,
    payload: AttestationReportSubmitRequest,
    attestor: ApprovedAttestorUser,
    db: DatabaseSession,
) -> AttestationRequestResponse:
    """Submit the assigned Attestor's structured report and queue PDF rendering."""
    attestation = await report_service.submit_report(
        db=db,
        attestor=attestor,
        attestation_id=attestation_id,
        payload=payload,
    )
    return AttestationRequestResponse.model_validate(attestation)


@router.post(
    "/attestations/{attestation_id}/accept-report",
    response_model=AttestationRequestResponse,
)
async def accept_attestation_report(
    attestation_id: UUID,
    requestor: RequestorUser,
    db: DatabaseSession,
) -> AttestationRequestResponse:
    """Accept a submitted Attestation report and release held escrow."""
    attestation = await release_service.accept_report(
        db=db,
        requestor=requestor,
        attestation_id=attestation_id,
    )
    return AttestationRequestResponse.model_validate(attestation)


@router.post(
    "/attestations/{attestation_id}/disputes",
    response_model=AttestationDisputeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_attestation_dispute(
    attestation_id: UUID,
    payload: AttestationDisputeCreateRequest,
    requestor: RequestorUser,
    db: DatabaseSession,
) -> AttestationDisputeResponse:
    """Raise a dispute against a submitted Attestation report."""
    dispute = await dispute_service.create_dispute(
        db=db,
        requestor=requestor,
        attestation_id=attestation_id,
        payload=payload,
    )
    return AttestationDisputeResponse.model_validate(dispute)


@router.post(
    "/admin/attestation-disputes/{dispute_id}/resolve",
    response_model=AttestationDisputeResponse,
)
async def resolve_attestation_dispute(
    dispute_id: UUID,
    payload: AdminAttestationDisputeResolveRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AttestationDisputeResponse:
    """Resolve an Attestation dispute through a 2FA-gated admin action."""
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
    return AttestationDisputeResponse.model_validate(dispute)


@router.post(
    "/admin/attestations/{attestation_id}/assign",
    response_model=AttestationRequestResponse,
)
async def admin_assign_attestation(
    attestation_id: UUID,
    payload: AdminAttestationAssignRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AttestationRequestResponse:
    """Manually assign a needs-admin Attestation to an approved Attestor."""
    attestation = await dispute_service.assign_needs_admin_attestation(
        db=db,
        redis=redis,
        admin=admin,
        attestation_id=attestation_id,
        attestor_id=payload.attestor_id,
        reason=payload.reason,
        totp_code=payload.totp_code,
    )
    return AttestationRequestResponse.model_validate(attestation)


@router.post(
    "/admin/attestations/{attestation_id}/refund",
    response_model=AttestationRequestResponse,
)
async def admin_refund_attestation(
    attestation_id: UUID,
    payload: AdminAttestationRefundRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AttestationRequestResponse:
    """Refund and close a needs-admin Attestation."""
    attestation = await dispute_service.refund_needs_admin_attestation(
        db=db,
        redis=redis,
        admin=admin,
        attestation_id=attestation_id,
        reason=payload.reason,
        totp_code=payload.totp_code,
    )
    return AttestationRequestResponse.model_validate(attestation)


@router.get(
    "/attestor/assignments",
    response_model=AttestorAssignmentsResponse,
)
async def list_attestor_assignments(
    attestor: ApprovedAttestorUser,
    db: DatabaseSession,
) -> AttestorAssignmentsResponse:
    """List offered and accepted Attestation assignments for an Attestor."""
    assignments = await matching_service.list_attestor_assignments(
        db=db,
        attestor=attestor,
    )
    return AttestorAssignmentsResponse(
        assignments=[
            AttestorAssignmentResponse(
                offer_id=offer.id,
                attestation_id=attestation.id,
                target_type=attestation.target_type,
                target_id=attestation.target_id,
                attestation_status=attestation.status,
                offer_status=offer.status,
                cohort_index=offer.cohort_index,
                requested_specializations=attestation.requested_specializations,
                requested_jurisdictions=attestation.requested_jurisdictions,
                expires_at=offer.expires_at,
                accepted_at=attestation.accepted_at,
                completion_due_at=attestation.completion_due_at,
            )
            for offer, attestation in assignments
        ]
    )


@router.post(
    "/attestor/applications",
    response_model=AttestorApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_attestor_application(
    payload: AttestorApplicationCreateRequest,
    user: CurrentUser,
    db: DatabaseSession,
) -> AttestorApplicationResponse:
    """Submit an Attestor application as any authenticated user."""
    application = await application_service.submit_application(
        db=db,
        user=user,
        payload=payload,
    )
    return AttestorApplicationResponse.model_validate(application)


@router.get(
    "/attestor/applications/mine",
    response_model=AttestorApplicationsResponse,
)
async def list_my_attestor_applications(
    user: CurrentUser,
    db: DatabaseSession,
) -> AttestorApplicationsResponse:
    """List the authenticated user's Attestor application history."""
    applications = await application_service.list_my_applications(db=db, user=user)
    return AttestorApplicationsResponse(
        applications=[
            AttestorApplicationResponse.model_validate(application)
            for application in applications
        ]
    )


@router.patch(
    "/attestor/applications/{application_id}/withdraw",
    response_model=AttestorApplicationResponse,
)
async def withdraw_attestor_application(
    application_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
) -> AttestorApplicationResponse:
    """Withdraw a pending Attestor application owned by the current user."""
    application = await application_service.withdraw_application(
        db=db,
        user=user,
        application_id=application_id,
    )
    return AttestorApplicationResponse.model_validate(application)


@router.get(
    "/admin/attestor/applications",
    response_model=AttestorApplicationsResponse,
)
async def list_attestor_applications_for_admin(
    admin: AdminUser,
    db: DatabaseSession,
    status_filter: Literal[
        "pending",
        "approved",
        "rejected",
        "withdrawn",
    ]
    | None = Query(default=None, alias="status"),
) -> AttestorApplicationsResponse:
    """List Attestor applications for admin review."""
    del admin
    applications = await application_service.list_applications_for_admin(
        db=db,
        status_filter=status_filter,
    )
    return AttestorApplicationsResponse(
        applications=[
            AttestorApplicationResponse.model_validate(application)
            for application in applications
        ]
    )


@router.post(
    "/admin/attestor/applications/{application_id}/review",
    response_model=AttestorApplicationResponse,
)
async def review_attestor_application(
    application_id: UUID,
    payload: AttestorApplicationReviewRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AttestorApplicationResponse:
    """Approve or reject an Attestor application as a 2FA-confirmed admin."""
    application = await application_service.review_application(
        db=db,
        redis=redis,
        admin=admin,
        application_id=application_id,
        payload=payload,
    )
    return AttestorApplicationResponse.model_validate(application)


@router.post(
    "/credentials",
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_credential(
    payload: CredentialCreateRequest,
    user: CurrentUser,
    db: DatabaseSession,
) -> CredentialResponse:
    """Create a user-owned professional Credential."""
    credential = await credential_service.create_credential(
        db=db,
        user=user,
        payload=payload,
    )
    return _credential_response(credential)


@router.get("/credentials", response_model=CredentialsResponse)
async def list_credentials(
    user: CurrentUser,
    db: DatabaseSession,
) -> CredentialsResponse:
    """List Credentials owned by the authenticated user."""
    credentials = await credential_service.list_credentials(db=db, user=user)
    return CredentialsResponse(
        credentials=[
            _credential_response(credential) for credential in credentials
        ]
    )


@router.patch("/credentials/{credential_id}", response_model=CredentialResponse)
async def update_credential(
    credential_id: UUID,
    payload: CredentialUpdateRequest,
    user: CurrentUser,
    db: DatabaseSession,
) -> CredentialResponse:
    """Update a user-owned Credential."""
    credential = await credential_service.update_credential(
        db=db,
        user=user,
        credential_id=credential_id,
        payload=payload,
    )
    return _credential_response(credential)


@router.post(
    "/credentials/{credential_id}/submit",
    response_model=CredentialResponse,
)
async def submit_credential(
    credential_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
) -> CredentialResponse:
    """Submit an owned Credential for manual Admin verification."""
    credential = await credential_service.submit_credential(
        db=db, user=user, credential_id=credential_id
    )
    return _credential_response(credential)


@router.delete("/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
) -> None:
    """Delete a user-owned Credential."""
    await credential_service.delete_credential(
        db=db,
        user=user,
        credential_id=credential_id,
    )


@router.post(
    "/credentials/{credential_id}/uploads",
    response_model=CredentialEvidenceUploadSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_credential_evidence_upload_session(
    credential_id: UUID,
    payload: CredentialEvidenceUploadCreateRequest,
    user: CurrentUser,
    db: DatabaseSession,
) -> CredentialEvidenceUploadSessionResponse:
    """Create a presigned POST upload session for Credential evidence."""
    return await credential_service.create_evidence_upload_session(
        db=db,
        user=user,
        credential_id=credential_id,
        payload=payload,
    )
