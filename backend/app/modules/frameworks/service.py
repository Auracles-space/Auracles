"""Service logic for contributor Framework draft CRUD."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.integrations import s3
from app.modules.auth.models import User
from app.modules.frameworks.models import (
    Framework,
    FrameworkVersion,
    FrameworkVersionArtifact,
    License,
    Review,
)
from app.modules.frameworks.models_artifact import (
    Artifact,
    ArtifactPiiAudit,
    ArtifactRarityAudit,
)
from app.modules.frameworks.pipeline_gate import evaluate_framework_pipeline
from app.modules.frameworks.schemas import (
    ArtifactConfirmRequest,
    ArtifactResponse,
    ArtifactUploadUrlRequest,
    ArtifactUploadUrlResponse,
    FrameworkCreate,
    FrameworkListItem,
    FrameworkResponse,
    FrameworkReviewCreate,
    FrameworkReviewListResponse,
    FrameworkReviewResponse,
    FrameworkReviewUpdate,
    FrameworkUpdate,
    FrameworkVersionCreate,
    PreviewArtifactRequest,
    PricingConfig,
    SimilarityNotice,
    SimilarityNoticeAcknowledgementRequest,
)
from app.modules.projects.models import Deliverable, Milestone, Project, Proposal
from app.workers.tasks.artifacts import process_artifact, scan_artifact
from app.workers.tasks.notifications import notify_licensees_of_new_version
from app.workers.tasks.processing.minhash_index import (
    index_framework_artifacts,
    remove_framework_artifacts_from_index,
)
from app.workers.tasks.processing.search_index import tags_to_search_text

ALLOWED_ARTIFACT_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/zip",
    "image/jpeg",
    "image/png",
    "image/webp",
}
ARTIFACT_MAX_TOTAL_SIZE = 500 * 1024 * 1024
ARTIFACT_UPLOAD_URL_TTL_SECONDS = 900
REVIEW_EDIT_WINDOW = timedelta(days=30)


def _tags_text(tags: list[str]) -> str:
    """Join tags into the immutable text field used by the FTS index."""
    return " ".join(tags)


def _artifact_to_response(artifact: Artifact) -> ArtifactResponse:
    """Map an Artifact row to the contributor-facing status response."""
    metadata = artifact.metadata_vector or {}
    redaction = metadata.get("redaction") or {}
    raw_similarity_notice = metadata.get("similarity_notice")
    similarity_notice = (
        SimilarityNotice.model_validate(raw_similarity_notice)
        if isinstance(raw_similarity_notice, dict)
        else None
    )
    return ArtifactResponse(
        id=artifact.id,
        framework_id=artifact.framework_id,
        name=artifact.name,
        file_key=artifact.file_key,
        file_size=artifact.file_size,
        mime_type=artifact.mime_type,
        scan_status=artifact.scan_status,
        processing_status=artifact.processing_status,
        pii_detected=artifact.pii_detected,
        pii_review_needed=artifact.pii_review_needed,
        redaction_available=artifact.clean_file_key is not None,
        redaction_status=(
            str(redaction.get("status")) if redaction.get("status") else None
        ),
        redaction_accepted=bool(redaction.get("accepted")),
        rarity_score=artifact.rarity_score,
        near_duplicate_blocked=bool(metadata.get("near_duplicate_blocked")),
        similarity_notice=similarity_notice,
        created_at=artifact.created_at,
    )


def _extension_for_filename(filename: str) -> str:
    """Return a safe filename extension from the original upload name."""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return "".join(character for character in suffix if character.isalnum()) or "bin"


def _bump_semver(version: str, change_type: str) -> str:
    """Return the next semantic version for a requested change type."""
    major, minor, patch = (int(part) for part in version.split("."))
    if version == "0.0.0":
        return "1.0.0"
    if change_type == "fix":
        return f"{major}.{minor}.{patch + 1}"
    if change_type == "improvement":
        return f"{major}.{minor + 1}.0"
    return f"{major + 1}.0.0"


def framework_to_response(framework: Framework) -> FrameworkResponse:
    """Map an ORM Framework row to the contributor-facing response schema."""
    return FrameworkResponse(
        id=framework.id,
        contributor_id=framework.contributor_id,
        source_project_id=framework.source_project_id,
        title=framework.title,
        description=framework.description,
        version=framework.version,
        status=framework.status,
        category=framework.category,
        sector=framework.sector,
        industry=framework.industry,
        function=framework.business_function,
        tags=framework.tags,
        jurisdiction=framework.jurisdiction,
        complexity=framework.complexity,
        org_size=framework.org_size,
        lifecycle_stage=framework.lifecycle_stage,
        pricing=PricingConfig(
            price=framework.price,
            currency=framework.currency,
            license_types=framework.license_types,
            commercial_rights=framework.commercial_rights,
            usage_restrictions=framework.usage_restrictions,
        ),
        preview_artifact_id=framework.preview_artifact_id,
        created_at=framework.created_at,
        updated_at=framework.updated_at,
        published_at=framework.published_at,
    )


def _framework_to_list_item(framework: Framework) -> FrameworkListItem:
    """Map a Framework row to the contributor dashboard list shape."""
    return FrameworkListItem(
        id=framework.id,
        title=framework.title,
        version=framework.version,
        status=framework.status,
        category=framework.category,
        price=framework.price,
        currency=framework.currency,
        created_at=framework.created_at,
        updated_at=framework.updated_at,
    )


def _review_to_response(review: Review) -> FrameworkReviewResponse:
    """Map a Review ORM row to the public review response schema."""
    return FrameworkReviewResponse(
        id=review.id,
        framework_id=review.framework_id,
        operator_id=review.operator_id,
        score=review.score,
        body=review.body,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


def _review_average(scores: list[int]) -> Decimal | None:
    """Return a two-decimal average for a collection of review scores."""
    if not scores:
        return None
    return (Decimal(sum(scores)) / Decimal(len(scores))).quantize(Decimal("0.01"))


def _require_reviewable_framework(framework: Framework) -> None:
    """Reject new reviews for Frameworks outside the published catalog."""
    if framework.status != "published":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only published Frameworks accept new reviews.",
        )


async def _load_active_operator_license(
    db: AsyncSession,
    *,
    framework_id: UUID,
    operator_id: UUID,
) -> License:
    """Load an active, unexpired Operator License or raise 403."""
    now = datetime.now(UTC)
    license_row = await db.scalar(
        select(License).where(
            License.framework_id == framework_id,
            License.operator_id == operator_id,
            License.status == "active",
            or_(License.expires_at.is_(None), License.expires_at > now),
        )
    )
    if license_row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active License is required to review this Framework.",
        )
    return license_row


async def _load_owned_framework(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
) -> Framework:
    """Load a Framework owned by the Contributor or raise 404."""
    framework = await db.scalar(
        select(Framework).where(
            Framework.id == framework_id,
            Framework.contributor_id == contributor.id,
        )
    )
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    return framework


async def _load_owned_framework_by_user_id(
    db: AsyncSession,
    contributor_id: UUID,
    framework_id: UUID,
) -> Framework:
    """Load a Framework owned by a Contributor id or raise 404."""
    framework = await db.scalar(
        select(Framework).where(
            Framework.id == framework_id,
            Framework.contributor_id == contributor_id,
        )
    )
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    return framework


def _require_draft(framework: Framework) -> None:
    """Reject metadata mutations unless the Framework is still a draft."""
    if framework.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft Frameworks can be modified.",
        )


async def _ensure_source_project_can_seed_framework(
    *,
    db: AsyncSession,
    contributor_id: UUID,
    source_project_id: UUID | None,
) -> None:
    """Validate that a Project source has approved work from this Contributor."""
    if source_project_id is None:
        return

    deliverable_id = await db.scalar(
        select(Deliverable.id)
        .join(Milestone, Milestone.id == Deliverable.milestone_id)
        .join(Project, Project.id == Milestone.project_id)
        .join(Proposal, Proposal.id == Project.accepted_proposal_id)
        .where(
            Project.id == source_project_id,
            Proposal.contributor_id == contributor_id,
            Proposal.status == "accepted",
            Deliverable.contributor_id == contributor_id,
            Deliverable.status.in_(("approved", "auto_approved")),
        )
        .limit(1)
    )
    if deliverable_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "source_project_id must reference a Project with an approved "
                "Deliverable from this Contributor."
            ),
        )


async def create_framework(
    db: AsyncSession,
    contributor: User,
    payload: FrameworkCreate,
) -> FrameworkResponse:
    """Create a draft Framework owned by the verified Contributor."""
    contributor_id = contributor.id
    pricing = payload.pricing
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        await _ensure_source_project_can_seed_framework(
            db=db,
            contributor_id=contributor_id,
            source_project_id=payload.source_project_id,
        )
        framework = Framework(
            contributor_id=contributor_id,
            source_project_id=payload.source_project_id,
            title=payload.title.strip(),
            description=payload.description.strip(),
            category=payload.category.strip(),
            sector=payload.sector.strip() if payload.sector else None,
            industry=payload.industry.strip() if payload.industry else None,
            business_function=payload.function.strip() if payload.function else None,
            tags=payload.tags,
            tags_text=_tags_text(payload.tags),
            jurisdiction=payload.jurisdiction.strip() if payload.jurisdiction else None,
            complexity=payload.complexity,
            org_size=payload.org_size,
            lifecycle_stage=(
                payload.lifecycle_stage.strip() if payload.lifecycle_stage else None
            ),
            price=pricing.price,
            currency=pricing.currency,
            license_types=list(pricing.license_types),
            commercial_rights=pricing.commercial_rights,
            usage_restrictions=pricing.usage_restrictions,
        )
        db.add(framework)
        await db.flush()
        audit_metadata = {"status": framework.status}
        if framework.source_project_id is not None:
            audit_metadata["source_project_id"] = str(framework.source_project_id)
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="framework_created",
            target_type="framework",
            target_id=framework.id,
            metadata=audit_metadata,
        )
        if framework.source_project_id is not None:
            await write_audit(
                db=db,
                actor_id=contributor_id,
                action="framework_published_from_project",
                target_type="framework",
                target_id=framework.id,
                metadata={"source_project_id": str(framework.source_project_id)},
            )
        await db.flush()
    await db.refresh(framework)
    logger.bind(
        module="frameworks",
        action="create_framework",
        user_id=contributor_id,
        framework_id=framework.id,
    ).info("framework_created")
    return framework_to_response(framework)


async def get_framework_for_contributor(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
) -> FrameworkResponse:
    """Return one Framework owned by the current Contributor."""
    framework = await _load_owned_framework(db, contributor, framework_id)
    return framework_to_response(framework)


async def list_contributor_frameworks(
    db: AsyncSession,
    contributor: User,
) -> list[FrameworkListItem]:
    """Return Frameworks owned by the current Contributor."""
    frameworks = (
        (
            await db.execute(
                select(Framework)
                .where(Framework.contributor_id == contributor.id)
                .order_by(desc(Framework.created_at))
            )
        )
        .scalars()
        .all()
    )
    return [_framework_to_list_item(framework) for framework in frameworks]


async def create_framework_review(
    db: AsyncSession,
    operator: User,
    framework_id: UUID,
    payload: FrameworkReviewCreate,
) -> FrameworkReviewResponse:
    """Create the current Operator's review for an actively licensed Framework."""
    operator_id = operator.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        framework = await db.scalar(
            select(Framework).where(Framework.id == framework_id)
        )
        if framework is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Framework not found.",
            )
        _require_reviewable_framework(framework)
        if framework.contributor_id == operator_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Contributors cannot review their own Frameworks.",
            )
        license_row = await _load_active_operator_license(
            db,
            framework_id=framework_id,
            operator_id=operator_id,
        )
        existing_review = await db.scalar(
            select(Review).where(
                Review.framework_id == framework_id,
                Review.operator_id == operator_id,
            )
        )
        if existing_review is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Operator has already reviewed this Framework.",
            )
        review = Review(
            framework_id=framework_id,
            operator_id=operator_id,
            license_id=license_row.id,
            score=payload.score,
            body=payload.body,
        )
        db.add(review)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="framework_review_created",
            target_type="framework",
            target_id=framework_id,
            metadata={"review_id": str(review.id), "score": payload.score},
        )
    await db.refresh(review)
    logger.bind(
        module="frameworks",
        action="create_framework_review",
        user_id=operator_id,
        framework_id=framework_id,
    ).info("framework_review_created")
    return _review_to_response(review)


async def update_my_framework_review(
    db: AsyncSession,
    operator: User,
    framework_id: UUID,
    payload: FrameworkReviewUpdate,
) -> FrameworkReviewResponse:
    """Update the current Operator's review before the 30-day edit window closes."""
    operator_id = operator.id
    if db.in_transaction():
        await db.rollback()

    async with db.begin():
        review = await db.scalar(
            select(Review).where(
                Review.framework_id == framework_id,
                Review.operator_id == operator_id,
            )
        )
        if review is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Review not found.",
            )
        if review.created_at < datetime.now(UTC) - REVIEW_EDIT_WINDOW:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Review edit window has closed.",
            )
        if payload.score is not None:
            review.score = payload.score
        if "body" in payload.model_fields_set:
            review.body = payload.body
        await db.flush()
        await write_audit(
            db=db,
            actor_id=operator_id,
            action="framework_review_updated",
            target_type="framework",
            target_id=framework_id,
            metadata={"review_id": str(review.id), "score": review.score},
        )
    await db.refresh(review)
    logger.bind(
        module="frameworks",
        action="update_framework_review",
        user_id=operator_id,
        framework_id=framework_id,
    ).info("framework_review_updated")
    return _review_to_response(review)


async def list_framework_reviews(
    db: AsyncSession,
    framework_id: UUID,
    *,
    viewer_id: UUID | None,
    viewer_roles: set[str],
) -> FrameworkReviewListResponse:
    """Return reviews and score aggregates for one Framework."""
    framework = await db.scalar(select(Framework).where(Framework.id == framework_id))
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    if framework.status != "published":
        if viewer_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Framework not found.",
            )
        if "admin" not in viewer_roles:
            await _load_active_operator_license(
                db,
                framework_id=framework_id,
                operator_id=viewer_id,
            )
    rows = await db.execute(
        select(Review)
        .where(Review.framework_id == framework_id)
        .order_by(Review.created_at.desc())
    )
    reviews = list(rows.scalars().all())
    return FrameworkReviewListResponse(
        reviews=[_review_to_response(review) for review in reviews],
        average_score=_review_average([review.score for review in reviews]),
        review_count=len(reviews),
    )


async def update_framework(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    payload: FrameworkUpdate,
) -> FrameworkResponse:
    """Update metadata and pricing for an owned draft Framework."""
    framework = await _load_owned_framework(db, contributor, framework_id)
    _require_draft(framework)

    fields = payload.model_fields_set
    if "title" in fields and payload.title is not None:
        framework.title = payload.title.strip()
    if "description" in fields and payload.description is not None:
        framework.description = payload.description.strip()
    if "category" in fields and payload.category is not None:
        framework.category = payload.category.strip()
    if "sector" in fields:
        framework.sector = payload.sector.strip() if payload.sector else None
    if "industry" in fields:
        framework.industry = payload.industry.strip() if payload.industry else None
    if "function" in fields:
        framework.business_function = (
            payload.function.strip() if payload.function else None
        )
    if "tags" in fields and payload.tags is not None:
        framework.tags = payload.tags
        framework.tags_text = _tags_text(payload.tags)
    if "jurisdiction" in fields:
        framework.jurisdiction = (
            payload.jurisdiction.strip() if payload.jurisdiction else None
        )
    if "complexity" in fields:
        framework.complexity = payload.complexity
    if "org_size" in fields:
        framework.org_size = payload.org_size
    if "lifecycle_stage" in fields:
        framework.lifecycle_stage = (
            payload.lifecycle_stage.strip() if payload.lifecycle_stage else None
        )
    if payload.pricing is not None:
        framework.price = payload.pricing.price
        framework.currency = payload.pricing.currency
        framework.license_types = list(payload.pricing.license_types)
        framework.commercial_rights = payload.pricing.commercial_rights
        framework.usage_restrictions = payload.pricing.usage_restrictions

    await write_audit(
        db=db,
        actor_id=contributor.id,
        action="framework_updated",
        target_type="framework",
        target_id=framework.id,
        metadata={"status": framework.status},
    )
    await db.commit()
    await db.refresh(framework)
    logger.bind(
        module="frameworks",
        action="update_framework",
        user_id=contributor.id,
        framework_id=framework.id,
    ).info("framework_updated")
    return framework_to_response(framework)


async def delete_draft(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
) -> None:
    """Delete an owned draft Framework."""
    framework = await _load_owned_framework(db, contributor, framework_id)
    _require_draft(framework)
    await write_audit(
        db=db,
        actor_id=contributor.id,
        action="framework_draft_deleted",
        target_type="framework",
        target_id=framework.id,
        metadata={"status": framework.status},
    )
    await db.delete(framework)
    await db.commit()
    logger.bind(
        module="frameworks",
        action="delete_draft",
        user_id=contributor.id,
        framework_id=framework_id,
    ).info("framework_draft_deleted")


async def unpublish_framework(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
) -> FrameworkResponse:
    """Move an owned published Framework out of the public catalog."""
    framework = await _load_owned_framework(db, contributor, framework_id)
    if framework.status == "unpublished":
        return framework_to_response(framework)
    if framework.status != "published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only published Frameworks can be unpublished.",
        )

    framework.status = "unpublished"
    await write_audit(
        db=db,
        actor_id=contributor.id,
        action="framework_unpublished",
        target_type="framework",
        target_id=framework.id,
        metadata={"version": framework.version},
    )
    await db.commit()
    try:
        await remove_framework_artifacts_from_index(framework.id)
    except Exception as exc:
        logger.bind(
            module="frameworks",
            action="remove_framework_from_lsh",
            user_id=contributor.id,
            framework_id=framework.id,
        ).error("artifact_lsh_remove_failed", error=str(exc))
    await db.refresh(framework)
    logger.bind(
        module="frameworks",
        action="unpublish_framework",
        user_id=contributor.id,
        framework_id=framework.id,
    ).info("framework_unpublished")
    return framework_to_response(framework)


async def submit_framework(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
) -> FrameworkResponse:
    """Submit an owned draft Framework into the processing gate."""
    framework = await _load_owned_framework(db, contributor, framework_id)
    if framework.status not in {"draft", "pipeline_failed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft or failed Frameworks can be submitted.",
        )

    artifacts = (
        (
            await db.execute(
                select(Artifact)
                .where(
                    Artifact.framework_id == framework.id,
                    Artifact.current_for_framework.is_(True),
                )
                .order_by(Artifact.created_at)
            )
        )
        .scalars()
        .all()
    )
    if not artifacts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one Artifact is required.",
        )

    framework.status = "submitted"
    framework.pipeline_failure_reasons = {}
    framework.last_pipeline_run_at = datetime.now(UTC)
    await write_audit(
        db=db,
        actor_id=contributor.id,
        action="framework_submitted",
        target_type="framework",
        target_id=framework.id,
        metadata={"artifact_count": len(artifacts)},
    )
    dispatched_artifact_ids: list[str] = []
    for artifact in artifacts:
        if artifact.processing_status in {"pending", "processing"}:
            artifact.processing_status = "processing"
            dispatched_artifact_ids.append(str(artifact.id))

    await evaluate_framework_pipeline(db, framework, force=True)
    await db.commit()
    for artifact_id in dispatched_artifact_ids:
        scan_artifact.delay(artifact_id)

    await db.refresh(framework)
    logger.bind(
        module="frameworks",
        action="submit_framework",
        user_id=contributor.id,
        framework_id=framework.id,
    ).info("framework_submitted")
    return framework_to_response(framework)


async def request_artifact_upload_url(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    payload: ArtifactUploadUrlRequest,
) -> ArtifactUploadUrlResponse:
    """Create a pending Artifact row and return a private S3 POST upload target."""
    framework = await _load_owned_framework(db, contributor, framework_id)
    _require_draft(framework)
    if payload.mime_type not in ALLOWED_ARTIFACT_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported artifact MIME type.",
        )

    existing_size = await db.scalar(
        select(func.coalesce(func.sum(Artifact.file_size), 0)).where(
            Artifact.framework_id == framework.id
        )
    )
    total_size = int(existing_size or 0) + payload.file_size
    if total_size > ARTIFACT_MAX_TOTAL_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Framework artifacts exceed the 500MB limit.",
        )

    artifact_id = uuid4()
    file_key = (
        f"frameworks/{framework.id}/artifacts/{artifact_id}."
        f"{_extension_for_filename(payload.filename)}"
    )
    artifact = Artifact(
        id=artifact_id,
        framework_id=framework.id,
        name=payload.filename.strip(),
        file_key=file_key,
        file_size=payload.file_size,
        mime_type=payload.mime_type,
    )
    db.add(artifact)
    await write_audit(
        db=db,
        actor_id=contributor.id,
        action="artifact_uploaded",
        target_type="artifact",
        target_id=artifact.id,
        metadata={
            "framework_id": str(framework.id),
            "status": "upload_url_created",
        },
    )
    settings = get_settings()
    upload_target = s3.storage.presigned_post(
        bucket=settings.s3_artifacts_bucket,
        key=file_key,
        mime_type=payload.mime_type,
        max_size=ARTIFACT_MAX_TOTAL_SIZE,
        expires_in=ARTIFACT_UPLOAD_URL_TTL_SECONDS,
    )
    await db.commit()
    logger.bind(
        module="frameworks",
        action="request_artifact_upload_url",
        user_id=contributor.id,
        framework_id=framework.id,
        artifact_id=artifact.id,
    ).info("artifact_upload_url_created")
    return ArtifactUploadUrlResponse(
        artifact_id=artifact.id,
        upload_url=str(upload_target["url"]),
        fields={
            str(field_name): str(field_value)
            for field_name, field_value in upload_target["fields"].items()
        },
        file_key=file_key,
        max_size=ARTIFACT_MAX_TOTAL_SIZE,
        expires_in=ARTIFACT_UPLOAD_URL_TTL_SECONDS,
    )


async def list_artifacts(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
) -> list[ArtifactResponse]:
    """Return Artifacts attached to an owned Framework."""
    framework = await _load_owned_framework(db, contributor, framework_id)
    artifacts = (
        (
            await db.execute(
                select(Artifact)
                .where(
                    Artifact.framework_id == framework.id,
                    Artifact.current_for_framework.is_(True),
                )
                .order_by(Artifact.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [_artifact_to_response(artifact) for artifact in artifacts]


async def _load_owned_artifact(
    db: AsyncSession,
    framework: Framework,
    artifact_id: UUID,
) -> Artifact:
    """Load an Artifact attached to an owned Framework or raise 404."""
    artifact = await db.scalar(
        select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.framework_id == framework.id,
            Artifact.current_for_framework.is_(True),
        )
    )
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact not found.",
        )
    return artifact


async def confirm_artifact_upload(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    payload: ArtifactConfirmRequest,
) -> ArtifactResponse:
    """Confirm an Artifact object exists in S3 and dispatch virus scanning."""
    framework = await _load_owned_framework(db, contributor, framework_id)
    _require_draft(framework)
    artifact = await _load_owned_artifact(db, framework, payload.artifact_id)

    settings = get_settings()
    if not s3.storage.object_exists(settings.s3_artifacts_bucket, artifact.file_key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Artifact object has not been uploaded.",
        )

    if artifact.processing_status == "pending":
        artifact.processing_status = "processing"
        await write_audit(
            db=db,
            actor_id=contributor.id,
            action="artifact_uploaded",
            target_type="artifact",
            target_id=artifact.id,
            metadata={"framework_id": str(framework.id)},
        )
        await db.commit()
        scan_artifact.delay(str(artifact.id))
        logger.bind(
            module="frameworks",
            action="confirm_artifact_upload",
            user_id=contributor.id,
            framework_id=framework.id,
            artifact_id=artifact.id,
        ).info("artifact_processing_started")
    else:
        await db.commit()

    await db.refresh(artifact)
    return _artifact_to_response(artifact)


async def set_preview_artifact(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    payload: PreviewArtifactRequest,
) -> FrameworkResponse:
    """Designate one owned Artifact as the Framework preview artifact."""
    framework = await _load_owned_framework(db, contributor, framework_id)
    _require_draft(framework)
    artifact = await _load_owned_artifact(db, framework, payload.artifact_id)
    framework.preview_artifact_id = artifact.id
    await write_audit(
        db=db,
        actor_id=contributor.id,
        action="framework_preview_artifact_set",
        target_type="framework",
        target_id=framework.id,
        metadata={"artifact_id": str(artifact.id)},
    )
    await db.commit()
    await db.refresh(framework)
    return framework_to_response(framework)


async def delete_artifact(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    artifact_id: UUID,
) -> None:
    """Delete an Artifact from an owned draft Framework."""
    framework = await _load_owned_framework(db, contributor, framework_id)
    _require_draft(framework)
    artifact = await _load_owned_artifact(db, framework, artifact_id)
    # Block deletion while the processing pipeline is actively running on this
    # artifact: a concurrent worker write would otherwise race a removed row and
    # could orphan the S3 object. "pending" (not yet dispatched) stays deletable.
    if artifact.processing_status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete an artifact while it is processing.",
        )
    if framework.preview_artifact_id == artifact.id:
        framework.preview_artifact_id = None
        await db.flush()
    version_reference_count = await db.scalar(
        select(func.count(FrameworkVersionArtifact.artifact_id)).where(
            FrameworkVersionArtifact.artifact_id == artifact.id
        )
    )
    await write_audit(
        db=db,
        actor_id=contributor.id,
        action="artifact_deleted",
        target_type="artifact",
        target_id=artifact.id,
        metadata={"framework_id": str(framework.id)},
    )
    if int(version_reference_count or 0) > 0:
        artifact.current_for_framework = False
    else:
        await db.delete(artifact)
    await db.commit()
    logger.bind(
        module="frameworks",
        action="delete_artifact",
        user_id=contributor.id,
        framework_id=framework.id,
        artifact_id=artifact.id,
    ).info("artifact_deleted")


async def _snapshot_current_version(
    db: AsyncSession,
    framework: Framework,
    current_artifacts: list[Artifact],
    payload: FrameworkVersionCreate,
) -> FrameworkVersion:
    """Ensure the current published version has an immutable Artifact snapshot."""
    snapshot = await db.scalar(
        select(FrameworkVersion).where(
            FrameworkVersion.framework_id == framework.id,
            FrameworkVersion.version == framework.version,
        )
    )
    if snapshot is None:
        snapshot = FrameworkVersion(
            framework_id=framework.id,
            version=framework.version,
            change_type=payload.change_type,
            change_log=payload.change_log.strip(),
        )
        db.add(snapshot)
        await db.flush()

    for artifact in current_artifacts:
        existing = await db.get(FrameworkVersionArtifact, (snapshot.id, artifact.id))
        if existing is None:
            db.add(
                FrameworkVersionArtifact(
                    framework_version_id=snapshot.id,
                    artifact_id=artifact.id,
                    is_preview=framework.preview_artifact_id == artifact.id,
                )
            )
    return snapshot


async def _ensure_published_version_snapshot(
    db: AsyncSession,
    framework: Framework,
    current_artifacts: list[Artifact],
) -> FrameworkVersion:
    """Create or complete the immutable snapshot for the current version."""
    snapshot = await db.scalar(
        select(FrameworkVersion).where(
            FrameworkVersion.framework_id == framework.id,
            FrameworkVersion.version == framework.version,
        )
    )
    if snapshot is None:
        snapshot = FrameworkVersion(
            framework_id=framework.id,
            version=framework.version,
            change_type=framework.change_type or "major",
            change_log=(
                "Initial publish."
                if framework.version == "1.0.0"
                else "Published version."
            ),
        )
        db.add(snapshot)
        await db.flush()

    for artifact in current_artifacts:
        existing = await db.get(FrameworkVersionArtifact, (snapshot.id, artifact.id))
        if existing is None:
            db.add(
                FrameworkVersionArtifact(
                    framework_version_id=snapshot.id,
                    artifact_id=artifact.id,
                    is_preview=framework.preview_artifact_id == artifact.id,
                )
            )
    return snapshot


async def acknowledge_soft_fail(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    ip_address: str | None,
) -> FrameworkResponse:
    """Record Contributor acknowledgement for external rarity soft failures."""
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        framework = await _load_owned_framework_by_user_id(
            db,
            contributor_id,
            framework_id,
        )
        if framework.status != "pipeline_failed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only failed pipeline checks can be acknowledged.",
            )

        artifacts = (
            (
                await db.execute(
                    select(Artifact).where(
                        Artifact.framework_id == framework.id,
                        Artifact.current_for_framework.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        for artifact in artifacts:
            audit = await db.scalar(
                select(ArtifactRarityAudit).where(
                    ArtifactRarityAudit.artifact_id == artifact.id
                )
            )
            if audit is None:
                audit = ArtifactRarityAudit(artifact_id=artifact.id)
                db.add(audit)
            audit.soft_fail_acknowledged = True
            audit.acknowledged_at = datetime.now(UTC)
            audit.acknowledged_ip = ip_address

        failure_reasons = dict(framework.pipeline_failure_reasons or {})
        failure_reasons.pop("external_check", None)
        framework.pipeline_failure_reasons = failure_reasons
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="soft_fail_acknowledged",
            target_type="framework",
            target_id=framework.id,
            metadata={"ip_address": ip_address},
        )
        await evaluate_framework_pipeline(db, framework, force=True)
    await db.refresh(framework)
    return framework_to_response(framework)


async def acknowledge_similarity_notice(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    payload: SimilarityNoticeAcknowledgementRequest,
) -> FrameworkResponse:
    """Record Contributor context for a non-blocking similarity notice."""
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        framework = await _load_owned_framework_by_user_id(
            db,
            contributor_id,
            framework_id,
        )
        artifacts = (
            (
                await db.execute(
                    select(Artifact).where(
                        Artifact.framework_id == framework.id,
                        Artifact.current_for_framework.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        notices = [
            {
                "artifact_id": str(artifact.id),
                "notice": (artifact.metadata_vector or {}).get("similarity_notice"),
            }
            for artifact in artifacts
            if isinstance(
                (artifact.metadata_vector or {}).get("similarity_notice"),
                dict,
            )
        ]
        if not notices:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Framework has no similarity notice to acknowledge.",
            )
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="similarity_notice_acknowledged",
            target_type="framework",
            target_id=framework.id,
            metadata={
                "differentiation_note": payload.differentiation_note,
                "notices": notices,
            },
        )
    await db.refresh(framework)
    return framework_to_response(framework)


async def resolve_pii_review(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    artifact_id: UUID,
) -> ArtifactResponse:
    """Reset a replaced PII Artifact and dispatch a fresh scan."""
    framework = await _load_owned_framework(db, contributor, framework_id)
    if framework.status not in {"draft", "pipeline_failed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft or failed Frameworks can resolve PII review.",
        )
    artifact = await _load_owned_artifact(db, framework, artifact_id)
    artifact.scan_status = "pending"
    artifact.processing_status = "processing"
    artifact.pii_detected = False
    artifact.pii_review_needed = False
    artifact.clean_file_key = None
    artifact.minhash_signature = None
    artifact.simhash = None
    artifact.metadata_vector = None
    artifact.internal_rarity = None
    artifact.external_rarity = None
    artifact.rarity_score = None
    artifact.nearest_match_id = None
    framework.status = "processing"
    framework.pipeline_failure_reasons = {}
    await write_audit(
        db=db,
        actor_id=contributor.id,
        action="artifact_pii_review_resolved",
        target_type="artifact",
        target_id=artifact.id,
        metadata={"framework_id": str(framework.id)},
    )
    await db.commit()
    scan_artifact.delay(str(artifact.id))
    await db.refresh(artifact)
    return _artifact_to_response(artifact)


async def accept_redaction(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    artifact_id: UUID,
) -> ArtifactResponse:
    """Accept a generated redacted Artifact copy and re-run processing."""
    framework = await _load_owned_framework(db, contributor, framework_id)
    artifact = await _load_owned_artifact(db, framework, artifact_id)
    metadata = dict(artifact.metadata_vector or {})
    redaction = dict(metadata.get("redaction") or {})
    already_accepted = bool(redaction.get("accepted"))

    if already_accepted:
        await db.commit()
        await db.refresh(artifact)
        return _artifact_to_response(artifact)

    if not artifact.clean_file_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No generated redacted artifact is available to accept.",
        )

    original_file_key = redaction.get("original_file_key") or artifact.file_key
    redaction.update(
        {
            "status": "accepted",
            "accepted": True,
            "accepted_at": datetime.now(UTC).isoformat(),
            "accepted_by": str(contributor.id),
            "original_file_key": original_file_key,
            "clean_file_key": artifact.clean_file_key,
        }
    )
    metadata = {"redaction": redaction}
    artifact.file_key = artifact.clean_file_key
    artifact.scan_status = "clean"
    artifact.processing_status = "processing"
    artifact.pii_detected = False
    artifact.pii_review_needed = False
    artifact.minhash_signature = None
    artifact.simhash = None
    artifact.metadata_vector = metadata
    artifact.internal_rarity = None
    artifact.external_rarity = None
    artifact.rarity_score = None
    artifact.nearest_match_id = None
    framework.status = "processing"
    framework.pipeline_failure_reasons = {}
    audit = await db.scalar(
        select(ArtifactPiiAudit).where(ArtifactPiiAudit.artifact_id == artifact.id)
    )
    if audit is None:
        audit = ArtifactPiiAudit(artifact_id=artifact.id)
        db.add(audit)
    audit.flagged_for_review = False
    audit.reviewed_by = contributor.id
    audit.reviewed_at = datetime.now(UTC)
    await write_audit(
        db=db,
        actor_id=contributor.id,
        action="artifact_redaction_accepted",
        target_type="artifact",
        target_id=artifact.id,
        metadata={
            "framework_id": str(framework.id),
            "original_file_key_preserved": True,
        },
    )
    await db.commit()
    process_artifact.delay(str(artifact.id))

    await db.refresh(artifact)
    return _artifact_to_response(artifact)


async def publish_framework(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
) -> FrameworkResponse:
    """Publish an owned Framework after every pipeline gate has passed."""
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        framework = await _load_owned_framework_by_user_id(
            db,
            contributor_id,
            framework_id,
        )
        if framework.status != "pipeline_passed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Framework must pass pipeline checks before publish.",
            )
        current_artifacts = (
            (
                await db.execute(
                    select(Artifact)
                    .where(
                        Artifact.framework_id == framework.id,
                        Artifact.current_for_framework.is_(True),
                    )
                    .order_by(Artifact.created_at)
                )
            )
            .scalars()
            .all()
        )
        if not current_artifacts:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="At least one Artifact is required.",
            )

        await _ensure_published_version_snapshot(db, framework, list(current_artifacts))
        framework.status = "published"
        framework.published_at = datetime.now(UTC)
        framework.tags_text = tags_to_search_text(framework.tags)
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="framework_published",
            target_type="framework",
            target_id=framework.id,
            metadata={"version": framework.version},
        )
    try:
        await index_framework_artifacts(framework.id)
    except Exception as exc:
        logger.bind(
            module="frameworks",
            action="index_framework_artifacts",
            user_id=contributor_id,
            framework_id=framework.id,
        ).error("artifact_lsh_index_failed", error=str(exc))
    if framework.version != "1.0.0":
        notify_licensees_of_new_version.delay(str(framework.id), framework.version)

    await db.refresh(framework)
    logger.bind(
        module="frameworks",
        action="publish_framework",
        user_id=contributor_id,
        framework_id=framework.id,
    ).info("framework_published")
    return framework_to_response(framework)


async def create_new_version(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    payload: FrameworkVersionCreate,
) -> FrameworkResponse:
    """Start a new draft version from a published or unpublished Framework."""
    if not payload.artifact_inheritance:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Nothing to bump.",
        )

    settings = get_settings()
    contributor_id = contributor.id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        framework = await db.scalar(
            select(Framework).where(
                Framework.id == framework_id,
                Framework.contributor_id == contributor_id,
            )
        )
        if framework is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Framework not found.",
            )
        if framework.status not in {"published", "unpublished"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only published or unpublished Frameworks can be versioned.",
            )

        current_artifact_rows = await db.execute(
            select(Artifact)
            .where(
                Artifact.framework_id == framework.id,
                Artifact.current_for_framework.is_(True),
            )
            .order_by(Artifact.created_at)
        )
        current_artifacts = list(current_artifact_rows.scalars().all())
        current_artifact_ids = {artifact.id for artifact in current_artifacts}
        requested_artifact_ids = set(payload.artifact_inheritance)
        if not requested_artifact_ids.issubset(current_artifact_ids):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Artifact inheritance contains non-current Artifacts.",
            )
        if not current_artifacts:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="At least one Artifact is required to create a new version.",
            )

        await _snapshot_current_version(db, framework, current_artifacts, payload)

        preview_replacement_id: UUID | None = None
        cloned_artifact_ids: list[str] = []
        for artifact in current_artifacts:
            should_inherit = payload.artifact_inheritance.get(artifact.id, True)
            if should_inherit:
                continue

            artifact.current_for_framework = False
            new_artifact_id = uuid4()
            extension = _extension_for_filename(artifact.name)
            new_file_key = (
                f"frameworks/{framework.id}/artifacts/{new_artifact_id}.{extension}"
            )
            s3.storage.copy_object(
                settings.s3_artifacts_bucket,
                artifact.file_key,
                settings.s3_artifacts_bucket,
                new_file_key,
            )
            new_artifact = Artifact(
                id=new_artifact_id,
                framework_id=framework.id,
                name=artifact.name,
                file_key=new_file_key,
                file_size=artifact.file_size,
                mime_type=artifact.mime_type,
                current_for_framework=True,
            )
            db.add(new_artifact)
            await db.flush()
            cloned_artifact_ids.append(str(new_artifact_id))
            if framework.preview_artifact_id == artifact.id:
                preview_replacement_id = new_artifact_id

        if preview_replacement_id is not None:
            framework.preview_artifact_id = preview_replacement_id
        framework.version = _bump_semver(framework.version, payload.change_type)
        framework.status = "draft"
        framework.change_type = payload.change_type
        framework.published_at = None
        framework.pipeline_failure_reasons = {}
        await write_audit(
            db=db,
            actor_id=contributor_id,
            action="framework_version_bumped",
            target_type="framework",
            target_id=framework.id,
            metadata={
                "version": framework.version,
                "change_type": payload.change_type,
                "cloned_artifact_ids": cloned_artifact_ids,
            },
        )

    await db.refresh(framework)
    logger.bind(
        module="frameworks",
        action="create_new_version",
        user_id=contributor_id,
        framework_id=framework.id,
    ).info("framework_version_bumped")
    return framework_to_response(framework)
