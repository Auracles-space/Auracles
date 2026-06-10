"""Attestation API router."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.redis import get_redis
from app.modules.attestation import application_service, credential_service
from app.modules.attestation.schemas import (
    AttestorApplicationCreateRequest,
    AttestorApplicationResponse,
    AttestorApplicationReviewRequest,
    AttestorApplicationsResponse,
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
    return CredentialResponse.model_validate(credential)


@router.get("/credentials", response_model=CredentialsResponse)
async def list_credentials(
    user: CurrentUser,
    db: DatabaseSession,
) -> CredentialsResponse:
    """List Credentials owned by the authenticated user."""
    credentials = await credential_service.list_credentials(db=db, user=user)
    return CredentialsResponse(
        credentials=[
            CredentialResponse.model_validate(credential)
            for credential in credentials
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
    return CredentialResponse.model_validate(credential)


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
