"""Attestation API router."""

from __future__ import annotations

from datetime import date as _date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.redis import get_redis
from app.modules.attestation import (
    access_service,
    badge_service,
    clarification_service,
    credential_service,
    directory_service,
    dispute_service,
    document_service,
    matching_service,
    rating_service,
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
    AttestationRatingCreate,
    AttestationRatingResponse,
    AttestationReportSubmitRequest,
    AttestationRequestCreateRequest,
    AttestationRequestResponse,
    AttestationsResponse,
    AttestorCompletedAttestation,
    AttestorDirectoryEntry,
    AttestorDirectoryResponse,
    ClarificationCreateRequest,
    ClarificationRespondRequest,
    ClarificationResponse,
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


@router.get(
    "/attestations/{attestation_id}/payment",
    response_model=AttestationFundingResponse,
    summary="Resume payment for a pending attestation fee",
    description=(
        "Return the existing Stripe PaymentIntent client secret so the "
        "requestor can complete an unpaid attestation fee without minting a "
        "second intent. Owner only."
    ),
)
async def get_attestation_fee_payment(
    attestation_id: UUID,
    requestor: RequestorUser,
    db: DatabaseSession,
) -> AttestationFundingResponse:
    """Return the client secret to resume an unpaid attestation fee."""
    return await attestation_service.get_attestation_fee_payment(
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
    "/attestor-orgs",
    response_model=AttestorDirectoryResponse,
    summary="List public attestor-organization directory",
    description=(
        "Return active attestor organizations for public directory browsing, "
        "with optional taxonomy and verification-level filters."
    ),
)
async def list_public_attestor_directory(
    db: DatabaseSession,
    sector: str | None = Query(default=None),
    function: str | None = Query(default=None),
    jurisdiction: str | None = Query(default=None),
    level: int | None = Query(default=None),
) -> AttestorDirectoryResponse:
    """Return active public attestor-organization directory entries."""
    attestors = await directory_service.list_directory(
        db=db,
        sector=sector,
        function=function,
        jurisdiction=jurisdiction,
        level=level,
    )
    return AttestorDirectoryResponse(attestors=attestors)


@router.get(
    "/attestor-orgs/{org_id}/completed",
    response_model=list[AttestorCompletedAttestation],
    summary="List an attestor organization's public completed attestations",
)
async def list_attestor_completed_attestations(
    org_id: UUID,
    db: DatabaseSession,
) -> list[AttestorCompletedAttestation]:
    """Return the org's public positive completed attestations."""
    return await badge_service.list_attestor_completed(db, org_id=org_id)


@router.get(
    "/attestor-orgs/{org_id}",
    response_model=AttestorDirectoryEntry,
    summary="Get public attestor-organization directory profile",
    description=(
        "Return one active attestor organization's public directory profile, "
        "including its matching taxonomy, member count, and completed count."
    ),
)
async def get_public_attestor_directory_profile(
    org_id: UUID,
    db: DatabaseSession,
) -> AttestorDirectoryEntry:
    """Return one active public attestor-organization directory entry."""
    return await directory_service.get_directory_profile(db=db, org_id=org_id)


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
    attestor: CurrentUser,
    db: DatabaseSession,
) -> AttestationRequestResponse:
    """Open the assigned Attestor's review workspace."""
    attestation = await workspace_service.start_review(
        db=db,
        attestor=attestor,
        attestation_id=attestation_id,
    )
    return AttestationRequestResponse.model_validate(attestation)


@router.post(
    "/attestations/{attestation_id}/content-ack",
    response_model=AttestationRequestResponse,
    summary="Acknowledge content use before review",
    description=(
        "Record the staffed reviewing member's binding content-use "
        "acknowledgment, unlocking full framework-content access and the "
        "review workspace."
    ),
)
async def acknowledge_attestation_content(
    attestation_id: UUID,
    payload: AttestationAcceptRequest,
    attestor: CurrentUser,
    db: DatabaseSession,
) -> AttestationRequestResponse:
    """Record the reviewing member's content-use acknowledgment."""
    attestation = await workspace_service.acknowledge_content(
        db=db,
        attestor=attestor,
        attestation_id=attestation_id,
        content_ack=payload.content_ack,
        ack_version=payload.ack_version,
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
    attestor: CurrentUser,
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
    attestor: CurrentUser,
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
    attestor: CurrentUser,
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
    attestor: CurrentUser,
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
    attestor: CurrentUser,
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
    attestor: CurrentUser,
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
    "/attestations/{attestation_id}/uploads",
    response_model=AttestationEvidenceUploadSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_attestation_report_evidence_upload_session(
    attestation_id: UUID,
    payload: AttestationEvidenceUploadCreateRequest,
    attestor: CurrentUser,
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
    attestor: CurrentUser,
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
        outcome=payload.outcome,
        resolution_notes=payload.resolution_notes,
        totp_code=payload.totp_code,
        is_complex=payload.is_complex,
    )
    return AttestationDisputeResponse.model_validate(dispute)


@router.get(
    "/admin/attestations",
    response_model=AttestationsResponse,
    summary="List attestations for admin triage",
    description=(
        "List Attestations in a given status for admin action. Defaults to the "
        "needs_admin queue — requests auto-matching could not staff, which an "
        "admin must assign or refund. Admin only."
    ),
)
async def list_admin_attestations(
    admin: AdminUser,
    db: DatabaseSession,
    status_value: str = Query(default="needs_admin", alias="status"),
) -> AttestationsResponse:
    """List Attestations in a given status for admin triage."""
    del admin
    attestations = await attestation_service.list_admin_attestations(
        db=db,
        status_value=status_value,
    )
    return AttestationsResponse(
        attestations=[
            AttestationRequestResponse.model_validate(attestation)
            for attestation in attestations
        ]
    )


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
    """Manually assign a needs-admin Attestation to an attestor org + member."""
    attestation = await dispute_service.assign_needs_admin_attestation(
        db=db,
        redis=redis,
        admin=admin,
        attestation_id=attestation_id,
        attestor_org_id=payload.attestor_org_id,
        reviewing_member_id=payload.reviewing_member_id,
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


@router.post(
    "/attestations/{attestation_id}/rating",
    response_model=AttestationRatingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Rate a stood attestation report",
    description=(
        "Record the requestor's one-time 1-5 rating of a stood report. Only "
        "callable by the attestation's requestor once the report has stood."
    ),
)
async def rate_attestation(
    attestation_id: UUID,
    payload: AttestationRatingCreate,
    requestor: RequestorUser,
    db: DatabaseSession,
) -> AttestationRatingResponse:
    """Submit a rating for an attestation."""
    rating = await rating_service.submit_rating(
        db=db,
        requestor=requestor,
        attestation_id=attestation_id,
        stars=payload.stars,
        comment=payload.comment,
    )
    return AttestationRatingResponse.model_validate(rating)


@router.get(
    "/attestations/{attestation_id}/invoice",
    summary="Fetch the requestor tax invoice for a settled attestation",
    description=(
        "Return the requestor-facing tax invoice PDF for a settled attestation. "
        "If the PDF has not been rendered yet, queue generation and return 202."
    ),
)
async def get_attestation_invoice(
    attestation_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
) -> Response:
    """Deliver the requestor tax invoice for a settled attestation."""
    return await document_service.get_tax_invoice(
        db,
        attestation_id=attestation_id,
        user=user,
    )


@router.get(
    "/attestations/{attestation_id}/earnings-statement",
    summary="Fetch the attestor earnings statement for a settled attestation",
    description=(
        "Return the attestor-facing earnings statement PDF for a settled "
        "attestation. If the PDF has not been rendered yet, queue generation "
        "and return 202."
    ),
)
async def get_attestation_earnings_statement(
    attestation_id: UUID,
    user: CurrentUser,
    db: DatabaseSession,
) -> Response:
    """Deliver the attestor earnings statement for a settled attestation."""
    return await document_service.get_earnings_statement(
        db,
        attestation_id=attestation_id,
        user=user,
    )


@router.get(
    "/attestations/earnings/annual/{year}",
    summary="Fetch the caller's annual attestation earnings summary",
    description=(
        "Return the approved attestor's annual earnings summary PDF for the "
        "requested year when the Jan-2 batch has generated it."
    ),
)
async def get_attestation_annual_summary(
    year: int,
    user: ApprovedAttestorUser,
    db: DatabaseSession,
) -> Response:
    """Deliver the caller's annual attestation earnings summary."""
    return await document_service.get_annual_summary(db, user=user, year=year)
