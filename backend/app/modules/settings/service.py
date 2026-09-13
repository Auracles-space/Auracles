"""Service logic for authenticated account settings."""

from __future__ import annotations

import json
from typing import cast
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.rate_limit import RateLimiter, RedisCounter
from app.core.security import generate_opaque_token, hash_token, verify_password
from app.integrations import persona, s3
from app.integrations.persona import PersonaProviderError
from app.modules.auth import service as auth_service
from app.modules.auth.models import IdentityVerification, KycDocument, User
from app.modules.settings.schemas import (
    KycDocumentResponse,
    KycDocumentUploadRequest,
    KycDocumentUploadResponse,
    KycStatusResponse,
    KycVerificationSessionResponse,
    SessionResponse,
    SessionsResponse,
)
from app.workers.tasks.kyc_document_scan import scan_kyc_document
from app.workers.tasks.notifications import (
    send_email_change_alert,
    send_email_change_verification,
)

EMAIL_CHANGE_PREFIX = "ec_"
EMAIL_CHANGE_TTL_SECONDS = 86_400

# Identity documents are photographs or scans, not archives or office files.
# Restricting the set keeps what an admin opens during review to formats a
# browser renders inertly, and the extension is taken from here rather than from
# the client-supplied filename.
KYC_DOCUMENT_MIME_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "application/pdf": "pdf",
}
# A passport page or NIN slip is a photograph, not a data set. 10 MB is generous
# for a phone camera capture and bounds what one account can push into storage.
KYC_DOCUMENT_MAX_SIZE = 10 * 1024 * 1024
KYC_DOCUMENT_UPLOAD_URL_TTL_SECONDS = 900
# Four document types exist and a user may legitimately re-submit a rejected
# one, so the cap sits above any honest need while still bounding abuse.
KYC_MAX_DOCUMENTS = 10

# Cap identity-verification session starts to limit per-check provider cost
# from a single account: five new Persona inquiries per hour per user.
_kyc_session_limiter = RateLimiter("kyc_session", limit=5, window=3600)
# Manual submission costs storage rather than per-check provider fees, so the
# window is wider — but still bounded, since each request reserves an object key.
_kyc_document_limiter = RateLimiter("kyc_document", limit=20, window=3600)


def _require_provider_verification() -> None:
    """Reject provider-flow calls unless ``KYC_PROVIDER=persona``.

    Under manual review the hosted provider flow is not part of the product.
    Answering 404 rather than 501 keeps the disabled route indistinguishable
    from one that was never deployed.

    Raises:
        HTTPException(404): If the platform is configured for manual review.
    """
    if get_settings().kyc_provider != "persona":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider identity verification is not enabled.",
        )


def _email_change_key(token: str) -> str:
    """Build the Redis lookup key for a pending account email change."""
    return f"email_change:{hash_token(token)}"


def _redis_text(value: object) -> str:
    """Normalize Redis bytes/strings to text."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


async def start_identity_verification(
    db: AsyncSession,
    redis: Redis,
    user: User,
) -> KycVerificationSessionResponse:
    """Start a Persona identity-verification inquiry for the current user.

    Creates a Persona inquiry tagged with the user id, persists the mapping so
    the signed webhook can resolve the decision, marks the user ``pending``, and
    returns the hosted link the user opens to verify. Rate-limited to cap the
    per-check provider cost a single account can incur.

    Args:
        db: Async DB session.
        redis: Redis client for the rate-limit window.
        user: The authenticated user starting verification.

    Returns:
        The hosted Persona verification URL and inquiry id.

    Raises:
        HTTPException(404): If the platform runs manual review (KYC_PROVIDER).
        HTTPException(409): If the user is already verified.
        HTTPException(429): If the per-user session window is exceeded.
        HTTPException(502): If Persona cannot create the inquiry.
    """
    _require_provider_verification()
    if user.kyc_status == "verified":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Identity is already verified.",
        )

    await _kyc_session_limiter.check(cast(RedisCounter, redis), str(user.id))

    log = logger.bind(
        module="kyc",
        action="verification_started",
        user_id=user.id,
    )
    # Hosted flow, not `create_inquiry`: Persona mints the inquiry when the user
    # lands on the link, so nothing is called server-side. The Auracles Persona
    # environment does not have `inquiries.create.api` enabled and no API key can
    # grant it, so the API path returns 403 for every key (verified 2026-09-06).
    # Consequence: no inquiry id yet — the row is claimed later by reference id.
    try:
        hosted_url = persona.build_hosted_inquiry_url(reference_id=str(user.id))
    except PersonaProviderError as exc:
        log.error("persona_inquiry_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Identity verification provider is unavailable.",
        ) from exc

    db.add(
        IdentityVerification(
            user_id=user.id,
            provider="persona",
            inquiry_id=None,
            status="created",
        )
    )
    user.kyc_status = "pending"
    await write_audit(
        db=db,
        actor_id=user.id,
        action="kyc_status_change",
        target_type="user",
        target_id=user.id,
        metadata={"status": "pending", "provider": "persona"},
    )
    await db.commit()
    log.info("verification_started")
    return KycVerificationSessionResponse(
        hosted_url=hosted_url,
        inquiry_id=None,
    )


async def sync_kyc_from_return(
    db: AsyncSession,
    user: User,
    inquiry_id: str,
) -> KycStatusResponse:
    """Reconcile KYC state by reading an inquiry's verdict straight from Persona.

    Backs the on-return path (identity verification design, 2026-06-24): the
    hosted-flow redirect carries no trusted decision and the inbound webhook may
    be delayed or unreachable (e.g. local dev). On return the app reads the
    authoritative status server-to-server and applies the same terminal-decision
    logic the webhook uses — idempotent, and a no-op while the inquiry is still
    pending.

    Ownership is enforced against our own ``IdentityVerification`` row: a caller
    may only sync an inquiry that belongs to them, so a leaked/guessed inquiry id
    cannot move another account's KYC state.

    Args:
        db: Async DB session.
        user: The authenticated user returning from the hosted flow.
        inquiry_id: The Persona inquiry id from the return URL.

    Returns:
        The user's KYC status (and documents) after reconciliation.

    Raises:
        HTTPException(404): If the platform runs manual review (KYC_PROVIDER),
            or the inquiry is unknown or owned by another user.
        HTTPException(502): If Persona cannot be reached.
    """
    _require_provider_verification()
    # Local import avoids a module-load cycle: webhooks.service pulls in several
    # modules at import time; settings.service is one of the leaves.
    from app.modules.webhooks.service import _apply_persona_decision

    record = await db.scalar(
        select(IdentityVerification).where(
            IdentityVerification.inquiry_id == inquiry_id
        )
    )
    if record is None:
        # First return from a hosted flow: the row has no inquiry id yet, so
        # match the caller's own pending row. Scoped to `user.id` — the id in
        # the request is attacker-supplied, and matching it against anyone
        # else's pending row would let a caller bind a stranger's inquiry.
        record = await db.scalar(
            select(IdentityVerification)
            .where(
                IdentityVerification.user_id == user.id,
                IdentityVerification.inquiry_id.is_(None),
            )
            .order_by(IdentityVerification.created_at.desc())
            .limit(1)
        )
    if record is None or record.user_id != user.id:
        # Deny by default; do not distinguish "unknown" from "not yours".
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification inquiry not found.",
        )

    log = logger.bind(
        module="kyc",
        action="verification_synced",
        user_id=user.id,
        inquiry_id=inquiry_id,
    )
    try:
        inquiry = await persona.fetch_inquiry(inquiry_id=inquiry_id)
    except PersonaProviderError as exc:
        log.error("persona_inquiry_fetch_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Identity verification provider is unavailable.",
        ) from exc

    # Persona is the authority on who this inquiry belongs to. The id arrives
    # from the client (Persona appends it to the return URL), and under hosted
    # flow the local row cannot vouch for it: a row awaiting its id would
    # otherwise adopt any inquiry the caller names, including an approved one
    # belonging to somebody else. Deny by default on any mismatch.
    if inquiry.reference_id != str(user.id):
        log.warning(
            "inquiry_reference_mismatch",
            provider="persona",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification inquiry not found.",
        )

    # Read the id before the rollback below: rolling back expires every ORM
    # instance, so touching `user.id` afterwards triggers a lazy reload from a
    # non-async context and raises MissingGreenlet.
    reference_id = str(user.id)

    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        ingest_status = await _apply_persona_decision(
            db,
            inquiry_id=inquiry_id,
            inquiry_status=inquiry.status,
            reference_id=reference_id,
        )
    log.info("verification_synced", ingest_status=ingest_status)

    await db.refresh(user)
    return await get_kyc_status(db=db, user=user)


async def get_kyc_status(db: AsyncSession, user: User) -> KycStatusResponse:
    """Return the current user's KYC status and submitted document metadata.

    Rows still ``awaiting_upload`` are reservations, not submissions — the
    presigned target was issued but the browser never completed the upload — so
    they are excluded. Showing them would tell a user they had submitted a
    document that does not exist.

    Maps to: FR-SET-004.

    Args:
        db: Async DB session.
        user: The authenticated user whose status is read.

    Returns:
        The user's KYC status and the metadata of every submitted document.
    """
    documents = (
        (
            await db.execute(
                select(KycDocument)
                .where(
                    KycDocument.user_id == user.id,
                    KycDocument.scan_status != "awaiting_upload",
                )
                .order_by(desc(KycDocument.created_at))
            )
        )
        .scalars()
        .all()
    )
    return KycStatusResponse(kyc_status=user.kyc_status, documents=list(documents))


async def request_kyc_document_upload_url(
    db: AsyncSession,
    redis: Redis,
    user: User,
    payload: KycDocumentUploadRequest,
) -> KycDocumentUploadResponse:
    """Reserve an identity document and return a private S3 POST upload target.

    Creates the ``KycDocument`` row in ``awaiting_upload`` so the object key is
    fixed before the browser uploads, then hands back a presigned POST policy
    that S3 itself enforces the MIME type and size ceiling against. The account
    does not move to ``pending`` here — only a confirmed upload opens a review.

    The object key is built entirely from UUIDs and the MIME type, never from
    the client-supplied filename, so no user input reaches the storage path.

    Maps to: FR-AUTH-009.

    Args:
        db: Async DB session.
        redis: Redis client backing the per-user rate-limit window.
        user: The authenticated user submitting the document.
        payload: Declared document type, filename, MIME type and size.

    Returns:
        The presigned POST target and the reserved document id.

    Raises:
        HTTPException(409): If the user's identity is already verified.
        HTTPException(413): If the declared size exceeds the KYC ceiling.
        HTTPException(415): If the MIME type is not an accepted document format.
        HTTPException(422): If the per-user document cap is already reached.
        HTTPException(429): If the per-user upload window is exceeded.
    """
    log = logger.bind(
        module="kyc",
        action="request_kyc_document_upload_url",
        user_id=user.id,
    )
    # Unhappy paths first: a settled verification must not be silently reopened,
    # and both file constraints are checked before any storage work happens.
    if user.kyc_status == "verified":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Identity is already verified.",
        )
    if payload.mime_type not in KYC_DOCUMENT_MIME_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Identity documents must be a JPEG, PNG, or PDF.",
        )
    if payload.file_size > KYC_DOCUMENT_MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                "Identity documents must be "
                f"{KYC_DOCUMENT_MAX_SIZE // (1024 * 1024)} MB or smaller."
            ),
        )

    await _kyc_document_limiter.check(cast(RedisCounter, redis), str(user.id))

    existing_count = await db.scalar(
        select(func.count())
        .select_from(KycDocument)
        .where(KycDocument.user_id == user.id)
    )
    if (existing_count or 0) >= KYC_MAX_DOCUMENTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"At most {KYC_MAX_DOCUMENTS} identity documents can be held "
                "on an account. Contact support to replace one."
            ),
        )

    document_id = uuid4()
    extension = KYC_DOCUMENT_MIME_EXTENSIONS[payload.mime_type]
    s3_key = f"kyc/{user.id}/{document_id}.{extension}"
    db.add(
        KycDocument(
            id=document_id,
            user_id=user.id,
            doc_type=payload.doc_type,
            s3_key=s3_key,
            mime_type=payload.mime_type,
            file_size=payload.file_size,
            status="pending",
            scan_status="awaiting_upload",
        )
    )
    settings = get_settings()
    upload_target = s3.storage.presigned_post(
        bucket=settings.s3_artifacts_bucket,
        key=s3_key,
        mime_type=payload.mime_type,
        max_size=KYC_DOCUMENT_MAX_SIZE,
        expires_in=KYC_DOCUMENT_UPLOAD_URL_TTL_SECONDS,
    )
    await db.commit()
    log.bind(document_id=str(document_id)).info("kyc_upload_url_created")
    return KycDocumentUploadResponse(
        document_id=document_id,
        upload_url=str(upload_target["url"]),
        fields={
            str(field_name): str(field_value)
            for field_name, field_value in upload_target["fields"].items()
        },
        max_size=KYC_DOCUMENT_MAX_SIZE,
        expires_in=KYC_DOCUMENT_UPLOAD_URL_TTL_SECONDS,
    )


async def confirm_kyc_document(
    db: AsyncSession,
    user: User,
    document_id: UUID,
) -> KycDocumentResponse:
    """Confirm an uploaded identity document and open it for admin review.

    Verifies the object actually landed in private storage, queues the malware
    scan an admin's download is gated on, and moves the account to ``pending``
    so it appears in the admin review queue. Idempotent: a repeated call returns
    the document without queuing a second scan.

    Maps to: FR-AUTH-009.

    Args:
        db: Async DB session.
        user: The authenticated user who owns the document.
        document_id: The reserved document to confirm.

    Returns:
        The confirmed document's metadata.

    Raises:
        HTTPException(404): If the document does not exist or is not the
            caller's — the two are deliberately indistinguishable.
        HTTPException(422): If no object was uploaded against the reservation.
    """
    log = logger.bind(
        module="kyc",
        action="confirm_kyc_document",
        user_id=user.id,
        document_id=str(document_id),
    )
    document = await db.scalar(
        select(KycDocument).where(
            KycDocument.id == document_id,
            # Ownership is part of the lookup, not a check after it: a document
            # belonging to someone else must be indistinguishable from one that
            # does not exist.
            KycDocument.user_id == user.id,
        )
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identity document not found.",
        )
    if document.scan_status != "awaiting_upload":
        return KycDocumentResponse.model_validate(document)

    settings = get_settings()
    if not s3.storage.object_exists(settings.s3_artifacts_bucket, document.s3_key):
        log.warning("kyc_document_missing_object")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Upload the document before confirming it.",
        )

    document.scan_status = "pending_scan"
    # A submitted document is what puts the account in front of an admin; the
    # admin queue is filtered on users whose kyc_status is pending.
    if user.kyc_status != "verified":
        user.kyc_status = "pending"
    await write_audit(
        db=db,
        actor_id=user.id,
        action="kyc_document_uploaded",
        target_type="kyc_document",
        target_id=document.id,
        metadata={"doc_type": document.doc_type, "provider": "manual"},
    )
    await db.commit()
    await db.refresh(document)
    scan_kyc_document.delay(str(document.id))
    log.info("kyc_document_uploaded")
    return KycDocumentResponse.model_validate(document)


async def list_sessions(
    redis: Redis,
    user: User,
    current_refresh_token: str | None,
) -> SessionsResponse:
    """List active refresh-token sessions for the authenticated user."""
    sessions = await auth_service.list_refresh_sessions(
        redis=redis,
        user=user,
        current_token=current_refresh_token,
    )
    return SessionsResponse(
        sessions=[SessionResponse.model_validate(session) for session in sessions]
    )


async def revoke_session(
    db: AsyncSession,
    redis: Redis,
    user: User,
    session_id: str,
    current_refresh_token: str | None,
) -> bool:
    """Revoke a single refresh-token session owned by the authenticated user."""
    revoked = await auth_service.revoke_refresh_session(
        redis=redis,
        user=user,
        session_id=session_id,
    )
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found.",
        )

    current = (
        auth_service.refresh_session_id(current_refresh_token) == session_id
        if current_refresh_token
        else False
    )
    await write_audit(
        db=db,
        actor_id=user.id,
        action="session_revoked",
        target_type="session",
        target_id=user.id,
        metadata={"session_id": session_id, "current": current},
    )
    await db.commit()
    return current


async def revoke_other_sessions(
    db: AsyncSession,
    redis: Redis,
    user: User,
    current_refresh_token: str | None,
) -> int:
    """Revoke every user session except the current browser session."""
    revoked = await auth_service.revoke_other_refresh_sessions(
        redis=redis,
        user=user,
        current_token=current_refresh_token,
    )
    await write_audit(
        db=db,
        actor_id=user.id,
        action="sessions_revoked",
        target_type="user",
        target_id=user.id,
        metadata={"revoked_count": revoked, "scope": "others"},
    )
    await db.commit()
    return revoked


async def request_email_change(
    db: AsyncSession,
    redis: Redis,
    user: User,
    new_email: str,
    password: str | None,
) -> None:
    """Create a new-email verification token after re-authentication.

    Re-auth substitutes the factor the account actually has. Password accounts
    re-authenticate with the account password; passwordless (e.g. Google)
    accounts skip the password and rely on the new-address verification link as
    proof of intent. Accounts with 2FA enabled must already hold an open
    step-up window, enforced by ``require_step_up_if_enrolled`` on the route.
    The current (old) address is notified for awareness.
    """
    normalized_email = auth_service.normalize_email(new_email)
    if normalized_email == user.email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already belongs to this account.",
        )
    existing = await db.scalar(select(User).where(User.email == normalized_email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already in use.",
        )

    # Password accounts must re-authenticate; passwordless accounts have no
    # password to demand, so the new-address verification link is the factor.
    if user.password_hash is not None:
        if password is None or not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect password.",
            )

    previous_email = user.email
    token = f"{EMAIL_CHANGE_PREFIX}{generate_opaque_token()}"
    await redis.setex(
        _email_change_key(token),
        EMAIL_CHANGE_TTL_SECONDS,
        json.dumps({"user_id": str(user.id), "new_email": normalized_email}),
    )
    send_email_change_verification.delay(normalized_email, token)
    # Alert the existing address so an unauthorized change can be caught early.
    send_email_change_alert.delay(previous_email, normalized_email)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="email_change_requested",
        target_type="user",
        target_id=user.id,
        metadata={"new_email": normalized_email},
    )
    await db.commit()


async def confirm_email_change(
    db: AsyncSession,
    redis: Redis,
    token: str,
) -> UUID:
    """Confirm a new account email address and revoke all sessions."""
    if not token.startswith(EMAIL_CHANGE_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email-change token.",
        )

    key = _email_change_key(token)
    raw_record = await redis.get(key)
    if raw_record is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Email-change token expired or already used.",
        )

    record = json.loads(_redis_text(raw_record))
    user_id = UUID(str(record["user_id"]))
    new_email = str(record["new_email"])
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None or user.deactivated_at is not None:
        await redis.delete(key)
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Email-change token expired or already used.",
        )

    if await db.scalar(select(User).where(User.email == new_email)) is not None:
        await redis.delete(key)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already in use.",
        )

    user.email = new_email
    user.email_verified = True
    await auth_service.revoke_all_user_sessions(redis=redis, user=user)
    await redis.delete(key)
    await write_audit(
        db=db,
        actor_id=user.id,
        action="email_changed",
        target_type="user",
        target_id=user.id,
        metadata={"new_email": new_email},
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already in use.",
        ) from exc
    return user.id
