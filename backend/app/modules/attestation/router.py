"""Attestation API router."""

from __future__ import annotations

from datetime import date as _date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.redis import get_redis
from app.modules.attestation import (
    access_service,
    application_service,
    clarification_service,
    credential_service,
    directory_service,
    dispute_service,
    matching_service,
    release_service,
    workspace_service,
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
    AnnotationCreateRequest,
    AnnotationResponse,
    AnnotationUpdateRequest,
    AttestationAcceptRequest,
    AttestationArtifactAccessResponse,
    AttestationConsentPendingResponse,
    AttestationConsentRequest,
    AttestationDisputeCreateRequest,
    AttestationDisputeResponse,
    AttestationEvidenceUploadCreateRequest,
    AttestationEvidenceUploadSessionResponse,
    AttestationFundingResponse,
    AttestationPackageResponse,
    AttestationReportSubmitRequest,
    AttestationRequestCreateRequest,
    AttestationRequestResponse,
    AttestationsResponse,
    AttestorActivateRequest,
    AttestorApplicationCreateRequest,
    AttestorApplicationRejectRequest,
    AttestorApplicationResponse,
    AttestorApplicationsResponse,
    AttestorApplicationUpdateRequest,
    AttestorAssignmentResponse,
    AttestorAssignmentsResponse,
    AttestorCredentialCheckRequest,
    AttestorDirectoryEntry,
    AttestorDirectoryResponse,
    AttestorKycVerifyRequest,
    AttestorPayoutAttachRequest,
    AttestorTaxDocumentRequest,
    AttestorTrialAssignRequest,
    AttestorTrialDecideRequest,
    AttestorTrialResponse,
    CoiDeclarationRequest,
    ClarificationCreateRequest,
    ClarificationRespondRequest,
    ClarificationResponse,
    ConfidentialityAgreementRequest,
    CredentialCreateRequest,
    CredentialEvidenceDownloadResponse,
    CredentialEvidenceUploadCreateRequest,
    CredentialEvidenceUploadSessionResponse,
    CredentialResponse,
    CredentialsResponse,
    CredentialUpdateRequest,
    RubricScoreResponse,
    RubricScoreUpsertRequest,
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
        credential.expires_date is not None and credential.expires_date < _date.today()
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
    response_model=AttestationFundingResponse | AttestationConsentPendingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_attestation(
    payload: AttestationRequestCreateRequest,
    requestor: RequestorUser,
    db: DatabaseSession,
) -> AttestationFundingResponse | AttestationConsentPendingResponse:
    """Create an Attestation request; fund now or await owner consent."""
    return await attestation_service.request_attestation(
        db=db,
        requestor=requestor,
        payload=payload,
    )


@router.post(
    "/attestations/{attestation_id}/consent",
    response_model=AttestationRequestResponse,
)
async def decide_owner_consent(
    attestation_id: UUID,
    payload: AttestationConsentRequest,
    user: CurrentUser,
    db: DatabaseSession,
) -> AttestationRequestResponse:
    """Approve or decline an operator-initiated attestation as the framework owner."""
    attestation = await attestation_service.decide_owner_consent(
        db=db,
        owner=user,
        attestation_id=attestation_id,
        decision=payload.decision,
    )
    return AttestationRequestResponse.model_validate(attestation)


@router.post(
    "/attestations/{attestation_id}/fund",
    response_model=AttestationFundingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Fund an owner-approved attestation request",
    description=(
        "Create the Stripe PaymentIntent for an operator-initiated attestation "
        "after the framework owner has approved consent."
    ),
)
async def fund_attestation(
    attestation_id: UUID,
    requestor: RequestorUser,
    db: DatabaseSession,
) -> AttestationFundingResponse:
    """Fund an owner-approved operator-initiated attestation as the requestor."""
    return await attestation_service.fund_attestation(
        db=db,
        requestor=requestor,
        attestation_id=attestation_id,
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
    "/attestors",
    response_model=AttestorDirectoryResponse,
    summary="List public Attestor directory",
    description=(
        "Return active Attestors for public directory browsing, with optional "
        "taxonomy and verification-level filters."
    ),
)
async def list_public_attestor_directory(
    db: DatabaseSession,
    sector: str | None = Query(default=None),
    framework_category: str | None = Query(default=None),
    jurisdiction: str | None = Query(default=None),
    level: int | None = Query(default=None),
) -> AttestorDirectoryResponse:
    """Return active public Attestor directory entries."""
    attestors = await directory_service.list_directory(
        db=db,
        sector=sector,
        framework_category=framework_category,
        jurisdiction=jurisdiction,
        level=level,
    )
    return AttestorDirectoryResponse(attestors=attestors)


@router.get(
    "/attestors/{user_id}",
    response_model=AttestorDirectoryEntry,
    summary="Get public Attestor directory profile",
    description=(
        "Return one active Attestor's public directory profile, including "
        "safe verified credentials and completed-attestation count."
    ),
)
async def get_public_attestor_directory_profile(
    user_id: UUID,
    db: DatabaseSession,
) -> AttestorDirectoryEntry:
    """Return one active public Attestor directory entry."""
    return await directory_service.get_directory_profile(db=db, user_id=user_id)


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
    payload: AttestationAcceptRequest,
    attestor: ApprovedAttestorUser,
    db: DatabaseSession,
) -> AttestationRequestResponse:
    """Accept an open cohort offer with the content-use acknowledgment."""
    attestation = await matching_service.accept_attestation_offer(
        db=db,
        attestation_id=attestation_id,
        attestor=attestor,
        content_ack=payload.content_ack,
        ack_version=payload.ack_version,
    )
    return AttestationRequestResponse.model_validate(attestation)


@router.post(
    "/attestations/{attestation_id}/start-review",
    response_model=AttestationRequestResponse,
    summary="Open the review workspace",
    description=(
        "Move an accepted assigned attestation into the in_review workspace "
        "state for the approved Attestor."
    ),
)
async def start_attestation_review(
    attestation_id: UUID,
    attestor: ApprovedAttestorUser,
    db: DatabaseSession,
) -> AttestationRequestResponse:
    """Open the assigned Attestor's review workspace."""
    attestation = await workspace_service.start_review(
        db=db,
        attestor=attestor,
        attestation_id=attestation_id,
    )
    return AttestationRequestResponse.model_validate(attestation)


@router.put(
    "/attestations/{attestation_id}/rubric/{dimension_key}",
    response_model=RubricScoreResponse,
    summary="Score one rubric dimension",
    description=(
        "Create or update the assigned Attestor's draft score and comment for "
        "one rubric dimension during in_review work."
    ),
)
async def upsert_attestation_rubric_score(
    attestation_id: UUID,
    dimension_key: str,
    payload: RubricScoreUpsertRequest,
    attestor: ApprovedAttestorUser,
    db: DatabaseSession,
) -> RubricScoreResponse:
    """Create or update one rubric score in the review workspace."""
    score = await workspace_service.upsert_rubric_score(
        db,
        attestor=attestor,
        attestation_id=attestation_id,
        dimension_key=dimension_key,
        score=payload.score,
        comment=payload.comment,
    )
    return RubricScoreResponse.model_validate(score)


@router.get(
    "/attestations/{attestation_id}/annotations",
    response_model=list[AnnotationResponse],
    summary="List workspace annotations",
    description=(
        "Return the assigned Attestor's clause-level annotations for one "
        "attestation workspace."
    ),
)
async def list_attestation_annotations(
    attestation_id: UUID,
    attestor: ApprovedAttestorUser,
    db: DatabaseSession,
) -> list[AnnotationResponse]:
    """List the assigned Attestor's workspace annotations."""
    annotations = await workspace_service.list_annotations(
        db,
        attestor=attestor,
        attestation_id=attestation_id,
    )
    return [AnnotationResponse.model_validate(annotation) for annotation in annotations]


@router.post(
    "/attestations/{attestation_id}/annotations",
    response_model=AnnotationResponse,
    summary="Create a workspace annotation",
    description=(
        "Attach a clause-level free-anchor annotation to an in-review "
        "attestation workspace."
    ),
)
async def create_attestation_annotation(
    attestation_id: UUID,
    payload: AnnotationCreateRequest,
    attestor: ApprovedAttestorUser,
    db: DatabaseSession,
) -> AnnotationResponse:
    """Create one clause-level annotation in the review workspace."""
    annotation = await workspace_service.create_annotation(
        db,
        attestor=attestor,
        attestation_id=attestation_id,
        artifact_id=payload.artifact_id,
        location_label=payload.location_label,
        quoted_excerpt=payload.quoted_excerpt,
        annotation_type=payload.annotation_type,
        comment=payload.comment,
    )
    return AnnotationResponse.model_validate(annotation)


@router.patch(
    "/attestations/{attestation_id}/annotations/{annotation_id}",
    response_model=AnnotationResponse,
    summary="Update a workspace annotation",
    description=(
        "Replace the editable fields of one assigned Attestor annotation while "
        "the attestation remains in_review."
    ),
)
async def update_attestation_annotation(
    attestation_id: UUID,
    annotation_id: UUID,
    payload: AnnotationUpdateRequest,
    attestor: ApprovedAttestorUser,
    db: DatabaseSession,
) -> AnnotationResponse:
    """Update one clause-level workspace annotation."""
    annotation = await workspace_service.update_annotation(
        db,
        attestor=attestor,
        attestation_id=attestation_id,
        annotation_id=annotation_id,
        location_label=payload.location_label,
        quoted_excerpt=payload.quoted_excerpt,
        annotation_type=payload.annotation_type,
        comment=payload.comment,
    )
    return AnnotationResponse.model_validate(annotation)


@router.delete(
    "/attestations/{attestation_id}/annotations/{annotation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a workspace annotation",
    description=(
        "Remove one assigned Attestor annotation from an in-review attestation "
        "workspace."
    ),
)
async def delete_attestation_annotation(
    attestation_id: UUID,
    annotation_id: UUID,
    attestor: ApprovedAttestorUser,
    db: DatabaseSession,
) -> None:
    """Delete one clause-level workspace annotation."""
    await workspace_service.delete_annotation(
        db,
        attestor=attestor,
        attestation_id=attestation_id,
        annotation_id=annotation_id,
    )


@router.get(
    "/attestations/{attestation_id}/clarifications",
    response_model=list[ClarificationResponse],
    summary="List workspace clarifications",
    description=(
        "Return attestation clarification rows visible to the assigned "
        "attestor or the requestor."
    ),
)
async def list_attestation_clarifications(
    attestation_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
) -> list[ClarificationResponse]:
    """List clarification rows for one visible attestation thread."""
    clarifications = await clarification_service.list_clarifications(
        db=db,
        user=user,
        attestation_id=attestation_id,
    )
    return [
        ClarificationResponse.model_validate(clarification)
        for clarification in clarifications
    ]


@router.post(
    "/attestations/{attestation_id}/clarifications",
    response_model=ClarificationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a workspace clarification",
    description=(
        "Allow the assigned attestor to ask the requestor one clarification "
        "question during in_review work."
    ),
)
async def create_attestation_clarification(
    attestation_id: UUID,
    payload: ClarificationCreateRequest,
    attestor: ApprovedAttestorUser,
    db: DatabaseSession,
) -> ClarificationResponse:
    """Create one attestation clarification from the assigned attestor."""
    clarification = await clarification_service.send_clarification(
        db=db,
        attestor=attestor,
        attestation_id=attestation_id,
        question=payload.question,
    )
    return ClarificationResponse.model_validate(clarification)


@router.post(
    "/attestations/{attestation_id}/clarifications/{clarification_id}/respond",
    response_model=ClarificationResponse,
    summary="Respond to a workspace clarification",
    description=(
        "Allow the attestation requestor to answer one open clarification and "
        "return the unused SLA remainder."
    ),
)
async def respond_to_attestation_clarification(
    attestation_id: UUID,
    clarification_id: UUID,
    payload: ClarificationRespondRequest,
    user: CurrentUser,
    db: DatabaseSession,
) -> ClarificationResponse:
    """Respond to one open attestation clarification as the requestor."""
    clarification = await clarification_service.respond_to_clarification(
        db=db,
        requestor=user,
        attestation_id=attestation_id,
        clarification_id=clarification_id,
        response=payload.response,
    )
    return ClarificationResponse.model_validate(clarification)


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
    "/attestor/applications/{application_id}",
    response_model=AttestorApplicationResponse,
)
async def update_attestor_application(
    application_id: UUID,
    payload: AttestorApplicationUpdateRequest,
    user: CurrentUser,
    db: DatabaseSession,
) -> AttestorApplicationResponse:
    """Edit a pending Attestor application owned by the current user."""
    application = await application_service.update_application(
        db=db,
        user=user,
        application_id=application_id,
        payload=payload,
    )
    return AttestorApplicationResponse.model_validate(application)


@router.post(
    "/attestor/applications/{application_id}/coi",
    response_model=AttestorApplicationResponse,
    summary="Sign conflict-of-interest declaration",
    description=(
        "Record or refresh the applicant's conflict-of-interest declaration "
        "before activation. This does not change onboarding status."
    ),
)
async def sign_attestor_application_coi(
    application_id: UUID,
    payload: CoiDeclarationRequest,
    user: CurrentUser,
    db: DatabaseSession,
) -> AttestorApplicationResponse:
    """Sign the owner's conflict-of-interest declaration for one application."""
    application = await application_service.sign_coi(
        db=db,
        user=user,
        application_id=application_id,
        payload=payload,
    )
    return AttestorApplicationResponse.model_validate(application)


@router.post(
    "/attestor/applications/{application_id}/confidentiality",
    response_model=AttestorApplicationResponse,
    summary="Sign confidentiality / non-use agreement",
    description=(
        "Record the applicant's acceptance of the one-time confidentiality and "
        "non-use agreement. This is required before activation but does not "
        "change the application status."
    ),
)
async def sign_attestor_application_confidentiality(
    application_id: UUID,
    payload: ConfidentialityAgreementRequest,
    user: CurrentUser,
    db: DatabaseSession,
) -> AttestorApplicationResponse:
    """Sign the one-time confidentiality agreement for an application."""
    application = await application_service.sign_confidentiality(
        db=db,
        user=user,
        application_id=application_id,
        payload=payload,
    )
    return AttestorApplicationResponse.model_validate(application)


@router.post(
    "/attestor/applications/{application_id}/payout",
    response_model=AttestorApplicationResponse,
    summary="Attach payout account",
    description=(
        "Attach one of the applicant's existing payout accounts before "
        "activation. This does not change onboarding status."
    ),
)
async def attach_attestor_application_payout(
    application_id: UUID,
    payload: AttestorPayoutAttachRequest,
    user: CurrentUser,
    db: DatabaseSession,
) -> AttestorApplicationResponse:
    """Attach an owned payout account to one Attestor application."""
    application = await application_service.attach_payout(
        db=db,
        user=user,
        application_id=application_id,
        payout_account_id=payload.payout_account_id,
    )
    return AttestorApplicationResponse.model_validate(application)


@router.post(
    "/attestor/applications/{application_id}/tax-document",
    response_model=CredentialEvidenceUploadSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create tax-document upload session",
    description=(
        "Create a presigned POST upload session for the applicant's tax "
        "document and record the selected tax document type."
    ),
)
async def create_attestor_tax_document_upload_session(
    application_id: UUID,
    payload: AttestorTaxDocumentRequest,
    user: CurrentUser,
    db: DatabaseSession,
) -> CredentialEvidenceUploadSessionResponse:
    """Create a presigned POST upload session for an Attestor tax document."""
    return await application_service.set_tax_document(
        db=db,
        user=user,
        application_id=application_id,
        payload=payload,
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
        "submitted",
        "identity_verified",
        "professional_verified",
        "expert_verified",
        "active",
        "rejected",
        "withdrawn",
        "held",
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
    "/admin/attestor/applications/{application_id}/reject",
    response_model=AttestorApplicationResponse,
)
async def reject_attestor_application(
    application_id: UUID,
    payload: AttestorApplicationRejectRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AttestorApplicationResponse:
    """Reject a non-active Attestor application as a 2FA-confirmed admin."""
    application = await application_service.reject_application(
        db=db,
        redis=redis,
        admin=admin,
        application_id=application_id,
        payload=payload,
    )
    return AttestorApplicationResponse.model_validate(application)


@router.post(
    "/admin/attestor/applications/{application_id}/verify-kyc",
    response_model=AttestorApplicationResponse,
)
async def verify_attestor_application_kyc(
    application_id: UUID,
    payload: AttestorKycVerifyRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AttestorApplicationResponse:
    """Advance a submitted application through the KYC verification gate."""
    application = await application_service.verify_kyc(
        db=db,
        redis=redis,
        admin=admin,
        application_id=application_id,
        name_match=payload.name_match,
        totp_code=payload.totp_code,
    )
    return AttestorApplicationResponse.model_validate(application)


@router.post(
    "/admin/attestor/applications/{application_id}/verify-credential",
    response_model=AttestorApplicationResponse,
)
async def verify_attestor_application_credential(
    application_id: UUID,
    payload: AttestorCredentialCheckRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AttestorApplicationResponse:
    """Advance an identity-verified application through credential review."""
    application = await application_service.verify_credential(
        db=db,
        redis=redis,
        admin=admin,
        application_id=application_id,
        payload=payload,
    )
    return AttestorApplicationResponse.model_validate(application)


@router.post(
    "/admin/attestor/applications/{application_id}/trial",
    response_model=AttestorTrialResponse,
    summary="Assign calibration trial",
    description=(
        "Assign a stubbed calibration trial to a professional-verified "
        "Attestor application after admin TOTP verification."
    ),
)
async def assign_attestor_application_trial(
    application_id: UUID,
    payload: AttestorTrialAssignRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AttestorTrialResponse:
    """Assign a calibration trial to an eligible Attestor application."""
    trial = await application_service.assign_trial(
        db=db,
        redis=redis,
        admin=admin,
        application_id=application_id,
        seeded_framework_id=payload.seeded_framework_id,
        totp_code=payload.totp_code,
    )
    return AttestorTrialResponse.model_validate(trial)


@router.post(
    "/admin/attestor/applications/{application_id}/trial/{trial_id}/decide",
    response_model=AttestorApplicationResponse,
    summary="Decide calibration trial",
    description=(
        "Record a pass or fail decision for a stubbed calibration trial after "
        "admin TOTP verification."
    ),
)
async def decide_attestor_application_trial(
    application_id: UUID,
    trial_id: UUID,
    payload: AttestorTrialDecideRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AttestorApplicationResponse:
    """Decide an assigned calibration trial for an Attestor application."""
    application = await application_service.decide_trial(
        db=db,
        redis=redis,
        admin=admin,
        application_id=application_id,
        trial_id=trial_id,
        passed=payload.passed,
        feedback=payload.feedback,
        totp_code=payload.totp_code,
    )
    return AttestorApplicationResponse.model_validate(application)


@router.post(
    "/admin/attestor/applications/{application_id}/activate",
    response_model=AttestorApplicationResponse,
    summary="Activate Attestor application",
    description=(
        "Activate an expert-verified Attestor application after confirming "
        "all onboarding prerequisites and admin TOTP verification."
    ),
)
async def activate_attestor_application(
    application_id: UUID,
    payload: AttestorActivateRequest,
    admin: AdminUser,
    db: DatabaseSession,
    redis: RedisClient,
) -> AttestorApplicationResponse:
    """Activate a fully verified Attestor application."""
    application = await application_service.activate_attestor(
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
        credentials=[_credential_response(credential) for credential in credentials]
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


@router.get(
    "/credentials/{credential_id}/evidence",
    response_model=CredentialEvidenceDownloadResponse,
)
async def download_credential_evidence(
    credential_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
    key: Annotated[str, Query(min_length=1)],
) -> CredentialEvidenceDownloadResponse:
    """Return a presigned URL to download one of the owner's evidence files."""
    url = await credential_service.generate_evidence_download_url(
        db=db,
        requester_id=user.id,
        credential_id=credential_id,
        key=key,
        is_admin=False,
    )
    return CredentialEvidenceDownloadResponse(url=url)


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


@router.post(
    "/attestations/{attestation_id}/artifacts/{artifact_id}/access",
    response_model=AttestationArtifactAccessResponse,
)
async def request_attestation_artifact_access(
    attestation_id: UUID,
    artifact_id: UUID,
    request: Request,
    user: CurrentUser,
    db: DatabaseSession,
) -> AttestationArtifactAccessResponse:
    """Issue an entitlement-checked presigned URL for an Attestation artifact."""
    return await access_service.request_artifact_access(
        db=db,
        user=user,
        attestation_id=attestation_id,
        artifact_id=artifact_id,
        ip_address=request.client.host if request.client else None,
    )


@router.get(
    "/attestations/{attestation_id}/package",
    response_model=AttestationPackageResponse,
)
async def get_attestation_package(
    attestation_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
) -> AttestationPackageResponse:
    """Return the read-only Attestation access package for a participant."""
    return await access_service.get_attestation_package(
        db=db, user=user, attestation_id=attestation_id
    )
