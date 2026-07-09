"""Organization shared legal-identity service.

Maintains the one-per-org legal profile used by contributor and attestor
commercial flows: legal name, registration number, billing address, and the
private tax-document upload pointer.

RBAC is enforced by router dependencies; this layer assumes an authorized org
owner actor and performs the TOTP step-up for sensitive writes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.attestation.credential_service import (
    CREDENTIAL_EVIDENCE_MAX_BYTES,
    CREDENTIAL_EVIDENCE_UPLOAD_TTL_SECONDS,
    _safe_file_name,
)
from app.modules.attestation.schemas import CredentialEvidenceUploadSessionResponse
from app.modules.auth import service as auth_service
from app.modules.auth.models import User
from app.modules.organizations.models import OrgLegalProfile
from app.modules.organizations.schemas import OrgAttestorTaxDocumentRequest

LEGAL_PROFILE_TAX_DOCUMENT_MAX_BYTES = CREDENTIAL_EVIDENCE_MAX_BYTES
LEGAL_PROFILE_TAX_DOCUMENT_UPLOAD_TTL_SECONDS = (
    CREDENTIAL_EVIDENCE_UPLOAD_TTL_SECONDS
)


async def get_legal_profile(
    db: AsyncSession,
    *,
    org_id: UUID,
) -> OrgLegalProfile | None:
    """Return the current shared legal profile for one organization."""
    return cast(
        "OrgLegalProfile | None",
        await db.scalar(
            select(OrgLegalProfile).where(OrgLegalProfile.org_id == org_id).limit(1)
        ),
    )


async def upsert_legal_profile(
    db: AsyncSession,
    redis: Redis,
    *,
    org_id: UUID,
    actor_id: UUID,
    totp_code: str,
    legal_name: str,
    registration_number: str | None,
    address: dict[str, Any] | None,
) -> OrgLegalProfile:
    """Create or update the org's shared legal profile after TOTP step-up."""
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        actor = await db.get(User, actor_id, with_for_update=True)
        if actor is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token.",
            )
        await auth_service.verify_totp_for_sensitive_action(
            db=db,
            redis=redis,
            user=actor,
            code=totp_code,
        )

        profile = await db.scalar(
            select(OrgLegalProfile)
            .where(OrgLegalProfile.org_id == org_id)
            .with_for_update()
        )
        if profile is None:
            profile = OrgLegalProfile(
                org_id=org_id,
                legal_name=legal_name,
                registration_number=registration_number,
                address=address,
            )
            db.add(profile)
            action = "org_legal_profile_created"
        else:
            profile.legal_name = legal_name
            profile.registration_number = registration_number
            profile.address = address
            action = "org_legal_profile_updated"

        await db.flush()
        await write_audit(
            db=db,
            actor_id=actor_id,
            action=action,
            target_type="organization",
            target_id=org_id,
            metadata={"legal_profile_set": True},
        )

    return profile


async def set_tax_document(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor_id: UUID,
    payload: OrgAttestorTaxDocumentRequest,
) -> CredentialEvidenceUploadSessionResponse:
    """Create a presigned upload session for the org legal profile tax document."""
    if payload.size_bytes > LEGAL_PROFILE_TAX_DOCUMENT_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Tax document upload is too large.",
        )
    if db.in_transaction():
        await db.rollback()

    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=LEGAL_PROFILE_TAX_DOCUMENT_UPLOAD_TTL_SECONDS)
    async with db.begin():
        profile = await db.scalar(
            select(OrgLegalProfile)
            .where(OrgLegalProfile.org_id == org_id)
            .with_for_update()
        )
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization legal profile not found.",
            )
        key = (
            f"org-legal-profiles/{org_id}/tax-documents/"
            f"{uuid4()}-{_safe_file_name(payload.file_name)}"
        )
        profile.tax_document_type = payload.tax_document_type
        profile.tax_document_key = key
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="org_legal_profile_tax_document_set",
            target_type="organization",
            target_id=org_id,
            metadata={"tax_document_set": True},
        )

    settings = get_settings()
    post = s3.storage.presigned_post(
        settings.s3_artifacts_bucket,
        key,
        payload.content_type,
        LEGAL_PROFILE_TAX_DOCUMENT_MAX_BYTES,
        LEGAL_PROFILE_TAX_DOCUMENT_UPLOAD_TTL_SECONDS,
    )
    return CredentialEvidenceUploadSessionResponse(
        id=uuid4(),
        s3_key=key,
        url=str(post["url"]),
        fields={str(k): str(v) for k, v in post["fields"].items()},
        expires_at=expires_at,
        size_limit=LEGAL_PROFILE_TAX_DOCUMENT_MAX_BYTES,
        scan_status="pending_scan",
    )
