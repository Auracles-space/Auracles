"""Service logic for contributor Framework draft CRUD."""

from __future__ import annotations

import hashlib
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
from app.modules.frameworks.ownership import FrameworkOwner
from app.modules.frameworks.pipeline_gate import evaluate_framework_pipeline
from app.modules.frameworks.schemas import (
    ArtifactConfirmRequest,
    ArtifactFromConnectorRequest,
    ArtifactResponse,
    ArtifactUploadUrlRequest,
    ArtifactUploadUrlResponse,
    FrameworkCreate,
    FrameworkListItem,
    FrameworkMetadataUpdate,
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
    SourcePreviewResponse,
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
_SOURCE_PREVIEW_MAX_BYTES = 5 * 1024 * 1024
_SOURCE_PREVIEW_URL_TTL_SECONDS = 300
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
        source_kind=artifact.source_kind,
        scan_status=artifact.scan_status,
        processing_status=artifact.processing_status,
        pii_detected=artifact.pii_detected,
        pii_review_needed=artifact.pii_review_needed,
        pii_types_found=[str(t) for t in (metadata.get("pii_review_types") or [])],
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


def _reauth_conflict() -> HTTPException:
    """Return the standard 409 telling the caller to reconnect the source."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"error_code": "reauth_required",
                "message": "The connection is no longer authorized. Reconnect it."},
    )


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
        contributor_org_id=framework.contributor_org_id,
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
        reviewer_org_id=review.reviewer_org_id,
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


async def _load_active_org_license(
    db: AsyncSession,
    *,
    framework_id: UUID,
    org_id: UUID,
) -> License:
    """Load an active org-owned License or raise 403."""
    now = datetime.now(UTC)
    license_row = await db.scalar(
        select(License).where(
            License.framework_id == framework_id,
            License.licensee_org_id == org_id,
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


async def _load_owned_framework_by_owner(
    db: AsyncSession,
    owner: FrameworkOwner,
    framework_id: UUID,
) -> Framework:
    """Load a Framework owned by the provided owner context or raise 404."""
    statement = select(Framework).where(Framework.id == framework_id)
    if owner.org_id is not None:
        statement = statement.where(Framework.contributor_org_id == owner.org_id)
    else:
        statement = statement.where(Framework.contributor_id == owner.user_id)
    framework = await db.scalar(statement)
    if framework is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Framework not found.",
        )
    return framework


def _require_live_state_access(owner: FrameworkOwner) -> None:
    """Reject live-state mutations unless the owner context permits them."""
    if owner.can_manage_live_state:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not permitted.",
    )


def _require_draft(framework: Framework) -> None:
    """Reject mutations unless the Framework is still a draft."""
    if framework.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft Frameworks can be modified.",
        )


# Statuses whose listing metadata (title, price, description, tags, taxonomy)
# may be edited in place. These fields live on the Framework row, not the
# immutable published-version snapshot, so a live edit never rewrites version
# history. Artifact changes stay version-gated via `_require_editable_artifacts`.
_METADATA_EDITABLE_STATUSES = {"draft", "published", "unpublished"}


def _require_metadata_editable(framework: Framework) -> None:
    """Reject metadata edits while a Framework is mid-pipeline or suspended."""
    if framework.status not in _METADATA_EDITABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Framework metadata can only be edited while it is a draft, "
                "published, or delisted."
            ),
        )


def _apply_framework_metadata_update(
    framework: Framework,
    payload: FrameworkUpdate | FrameworkMetadataUpdate,
) -> None:
    """Apply mutable metadata fields from a Framework patch payload."""
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


def _apply_framework_pricing_update(
    framework: Framework,
    pricing: PricingConfig,
) -> None:
    """Apply pricing and licensing fields to a Framework row."""
    framework.price = pricing.price
    framework.currency = pricing.currency
    framework.license_types = list(pricing.license_types)
    framework.commercial_rights = pricing.commercial_rights
    framework.usage_restrictions = pricing.usage_restrictions


def _require_editable_artifacts(framework: Framework) -> None:
    """Allow artifact add/remove while a Framework is pre-publish.

    A draft is obviously editable; a pipeline_failed Framework must also accept
    artifact changes so a Contributor can replace or remove the offending file
    and re-run the pipeline. A pipeline_passed Framework also accepts artifact
    changes, which reverts it to draft status. Published, submitted, processing,
    and unpublished Frameworks stay locked.
    """
    if framework.status not in {"draft", "pipeline_failed", "pipeline_passed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Only draft, failed, or passed pre-publish Frameworks can "
                "change artifacts."
            ),
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
    owner: FrameworkOwner,
    payload: FrameworkCreate,
) -> FrameworkResponse:
    """Create a draft Framework owned by the verified Contributor."""
    contributor_id = owner.user_id or owner.actor_id
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
            contributor_id=owner.user_id,
            contributor_org_id=owner.org_id,
            authoring_member_id=owner.authoring_member_id,
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


async def get_framework_for_owner(
    db: AsyncSession,
    owner: FrameworkOwner,
    framework_id: UUID,
) -> FrameworkResponse:
    """Return one Framework owned by the provided owner context."""
    framework = await _load_owned_framework_by_owner(db, owner, framework_id)
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


async def list_frameworks_for_owner(
    db: AsyncSession,
    owner: FrameworkOwner,
) -> list[FrameworkListItem]:
    """Return Frameworks owned by the provided owner context."""
    statement = select(Framework)
    if owner.org_id is not None:
        statement = statement.where(Framework.contributor_org_id == owner.org_id)
    else:
        statement = statement.where(Framework.contributor_id == owner.user_id)
    frameworks = (
        (
            await db.execute(
                statement.order_by(desc(Framework.created_at))
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


async def create_org_framework_review(
    db: AsyncSession,
    *,
    org_id: UUID,
    actor: User,
    reviewing_member_id: UUID,
    framework_id: UUID,
    payload: FrameworkReviewCreate,
) -> FrameworkReviewResponse:
    """Create one organization-authored review for an actively licensed Framework."""
    actor_id = actor.id
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
        license_row = await _load_active_org_license(
            db,
            framework_id=framework_id,
            org_id=org_id,
        )
        existing_review = await db.scalar(
            select(Review).where(
                Review.framework_id == framework_id,
                Review.reviewer_org_id == org_id,
            )
        )
        if existing_review is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Organization has already reviewed this Framework.",
            )
        review = Review(
            framework_id=framework_id,
            operator_id=None,
            reviewer_org_id=org_id,
            reviewing_member_id=reviewing_member_id,
            license_id=license_row.id,
            score=payload.score,
            body=payload.body,
        )
        db.add(review)
        await db.flush()
        await write_audit(
            db=db,
            actor_id=actor_id,
            action="framework_review_created",
            target_type="framework",
            target_id=framework_id,
            metadata={
                "review_id": str(review.id),
                "score": payload.score,
                "reviewer_org_id": str(org_id),
            },
        )
    await db.refresh(review)
    logger.bind(
        module="frameworks",
        action="create_org_framework_review",
        user_id=actor_id,
        framework_id=framework_id,
        org_id=org_id,
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
    owner: FrameworkOwner,
    framework_id: UUID,
    payload: FrameworkUpdate,
) -> FrameworkResponse:
    """Update listing metadata and pricing for an owned Framework.

    Editable in place while the Framework is a draft, published, or delisted
    (unpublished); locked while it moves through the publishing pipeline or is
    suspended. Editing a live Framework does not bump the version — these fields
    are not part of the immutable published-version snapshot. Pricing edits are
    a live-state operation and require an owner permitted to manage live state.
    """
    framework = await _load_owned_framework_by_owner(db, owner, framework_id)
    _require_metadata_editable(framework)
    _apply_framework_metadata_update(framework, payload)
    if payload.pricing is not None:
        _require_live_state_access(owner)
        _apply_framework_pricing_update(framework, payload.pricing)

    await write_audit(
        db=db,
        actor_id=owner.actor_id,
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
        user_id=owner.actor_id,
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
    owner: FrameworkOwner,
    framework_id: UUID,
) -> FrameworkResponse:
    """Move an owned published Framework out of the public catalog."""
    _require_live_state_access(owner)
    framework = await _load_owned_framework_by_owner(db, owner, framework_id)
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
        actor_id=owner.actor_id,
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
            user_id=owner.actor_id,
            framework_id=framework.id,
        ).error("artifact_lsh_remove_failed", error=str(exc))
    await db.refresh(framework)
    logger.bind(
        module="frameworks",
        action="unpublish_framework",
        user_id=owner.actor_id,
        framework_id=framework.id,
    ).info("framework_unpublished")
    return framework_to_response(framework)


async def current_artifacts_block_publish(
    db: AsyncSession,
    framework_id: UUID,
) -> bool:
    """Return whether any current Artifact fails a safety-critical trust gate.

    A read-only re-check of the hard publish blockers (virus, scan error,
    unfinished or failed processing, PII flag) used to guard a same-version
    relist. Does not mutate Framework status. Similarity/rarity bands are not
    re-evaluated here — they already cleared at the original publish and only
    soften over time; the virus and PII gates are the ones that must never be
    bypassed on republish.
    """
    blocked = await db.scalar(
        select(func.count(Artifact.id)).where(
            Artifact.framework_id == framework_id,
            Artifact.current_for_framework.is_(True),
            or_(
                Artifact.scan_status.in_(("infected", "error")),
                Artifact.processing_status.in_(
                    ("pending", "processing", "failed", "flagged_pii")
                ),
                Artifact.pii_review_needed.is_(True),
            ),
        )
    )
    return bool(blocked)


async def current_artifact_file_missing(
    db: AsyncSession,
    framework_id: UUID,
) -> bool:
    """Return whether any current Artifact's S3 object is absent.

    The pipeline gate (`evaluate_framework_pipeline`) only inspects DB columns,
    so a file removed from S3 out of band after processing (lifecycle expiry,
    manual console delete, quarantine that left the row) leaves a current
    Artifact whose bytes are gone. Publishing or relisting it would seed a
    dangling ``file_key`` into the catalog whose presigned download 404s for the
    buying Operator. Re-verify object existence before the Framework goes public.

    Args:
        db: Async session for loading current Artifact file keys.
        framework_id: UUID of the Framework whose artifacts are checked.

    Returns:
        True if at least one current Artifact has no object in storage.
    """
    settings = get_settings()
    file_keys = (
        (
            await db.execute(
                select(Artifact.file_key).where(
                    Artifact.framework_id == framework_id,
                    Artifact.current_for_framework.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    return any(
        not s3.storage.object_exists(settings.s3_artifacts_bucket, file_key)
        for file_key in file_keys
    )


async def relist_framework(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
) -> FrameworkResponse:
    """Return an owned, delisted Framework to the public catalog.

    Relist is the inverse of unpublish: the Framework already passed the
    pipeline before it was published, so a same-version relist skips
    re-processing and flips ``unpublished`` straight back to ``published``.
    Content edits still require a new version (which reverts to draft and
    re-runs the pipeline) — relist never changes the artifacts or version.

    Args:
        db: Async SQLAlchemy session.
        contributor: Authenticated owning Contributor.
        framework_id: UUID of the Framework to relist.

    Returns:
        The relisted Framework as a contributor-facing response.

    Raises:
        HTTPException(404): If the Framework does not exist or is not owned.
        HTTPException(409): If the Framework is not currently unpublished.
    """
    framework = await _load_owned_framework(db, contributor, framework_id)
    if framework.status == "published":
        return framework_to_response(framework)
    if framework.status != "unpublished":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only unpublished Frameworks can be relisted.",
        )

    # A delisted Framework may have drifted since it was last live (an accepted
    # redaction that re-flagged, a re-processed artifact). Re-verify the safety-
    # critical trust gates before flipping it back to public so relist can never
    # leak a flagged artifact into the catalog. The status stays unpublished on
    # refusal; the Contributor resolves the artifact via a new version.
    if await current_artifacts_block_publish(db, framework.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This framework can't be relisted because an artifact failed a "
                "trust check (virus or PII). Start a new version to resolve it."
            ),
        )
    # A file deleted from S3 while delisted leaves a dangling file_key; block
    # relist so the catalog never re-exposes an artifact whose bytes are gone.
    if await current_artifact_file_missing(db, framework.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An artifact file is no longer available in storage. "
                "Re-upload the affected artifact in a new version to relist."
            ),
        )

    framework.status = "published"
    framework.published_at = datetime.now(UTC)
    await write_audit(
        db=db,
        actor_id=contributor.id,
        action="framework_relisted",
        target_type="framework",
        target_id=framework.id,
        metadata={"version": framework.version},
    )
    await db.commit()
    try:
        await index_framework_artifacts(framework.id)
    except Exception as exc:
        logger.bind(
            module="frameworks",
            action="index_framework_artifacts",
            user_id=contributor.id,
            framework_id=framework.id,
        ).error("artifact_lsh_index_failed", error=str(exc))
    await db.refresh(framework)
    logger.bind(
        module="frameworks",
        action="relist_framework",
        user_id=contributor.id,
        framework_id=framework.id,
    ).info("framework_relisted")
    return framework_to_response(framework)


async def submit_framework(
    db: AsyncSession,
    owner: FrameworkOwner,
    framework_id: UUID,
) -> FrameworkResponse:
    """Submit an owned draft Framework into the processing gate."""
    framework = await _load_owned_framework_by_owner(db, owner, framework_id)
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
        actor_id=owner.actor_id,
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
        user_id=owner.actor_id,
        framework_id=framework.id,
    ).info("framework_submitted")
    return framework_to_response(framework)


async def import_artifact_from_connector(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    payload: ArtifactFromConnectorRequest,
) -> ArtifactResponse:
    """Import a connected-source file as a new draft Artifact.

    Copies the bytes from the contributor's connected provider into our
    private S3 bucket and dispatches the standard artifact pipeline — an
    imported artifact is indistinguishable from an uploaded one except
    for audit metadata. Google-native documents are exported to their
    Office equivalents before import.

    Args:
        db: Async database session.
        contributor: The requesting contributor (must own the framework).
        framework_id: Framework receiving the artifact.
        payload: The connection and provider file to import.

    Returns:
        The created Artifact's processing status.

    Raises:
        HTTPException(404): Framework or connection not found/foreign.
        HTTPException(409): Connection needs re-authorization.
        HTTPException(413): Import would exceed the size budget.
        HTTPException(415): Unsupported effective MIME type.
        HTTPException(502): Provider failure.
    """
    # Local import: integrations depends on this module for the MIME
    # allow-list, so the forward import stays function-scoped here too.
    from app.integrations.google_drive import (
        EXPORT_MIME_MAP,
        DriveFileTooLargeError,
        GoogleDriveAuthError,
        GoogleDriveError,
        download_drive_file,
        get_drive_file_metadata,
    )
    from app.modules.integrations.service import (
        get_active_connection_with_fresh_token,
    )

    framework = await _load_owned_framework(db, contributor, framework_id)
    _require_editable_artifacts(framework)
    if framework.status == "pipeline_passed":
        framework.status = "draft"
        framework.pipeline_failure_reasons = {}

    connection, access_token = await get_active_connection_with_fresh_token(
        db, user_id=contributor.id, connection_id=payload.connection_id
    )

    log = logger.bind(
        module="frameworks",
        action="import_artifact_from_connector",
        user_id=str(contributor.id),
        framework_id=str(framework.id),
    )
    try:
        metadata = await get_drive_file_metadata(
            access_token=access_token, file_id=payload.file_id
        )
    except GoogleDriveAuthError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "reauth_required",
                "message": "The connection is no longer authorized. Reconnect it.",
            },
        ) from None
    except GoogleDriveError as exc:
        log.error("connector_metadata_failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The file provider is unavailable.",
        ) from exc

    source_mime = str(metadata.get("mimeType", ""))
    source_name = str(metadata.get("name", "")).strip() or "import"
    export_mapping = EXPORT_MIME_MAP.get(source_mime)
    if export_mapping is not None:
        effective_mime, extension = export_mapping
        export_mime: str | None = effective_mime
        filename = f"{source_name}.{extension}"
    else:
        effective_mime = source_mime
        export_mime = None
        filename = source_name
    if effective_mime not in ALLOWED_ARTIFACT_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported artifact MIME type.",
        )

    metadata_size = metadata.get("size")
    existing_bytes = await _reserve_artifact_budget(
        db,
        framework.id,
        add_bytes=int(metadata_size) if metadata_size is not None else 0,
        exclude_id=None,
    )
    remaining = ARTIFACT_MAX_TOTAL_SIZE - existing_bytes

    try:
        body = await download_drive_file(
            access_token=access_token,
            file_id=payload.file_id,
            export_mime=export_mime,
            max_bytes=remaining,
        )
    except DriveFileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Framework artifacts exceed the 500MB limit.",
        ) from None
    except GoogleDriveAuthError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "reauth_required",
                "message": "The connection is no longer authorized. Reconnect it.",
            },
        ) from None
    except GoogleDriveError as exc:
        log.error("connector_download_failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The file provider is unavailable.",
        ) from exc

    artifact_id = uuid4()
    file_key = (
        f"frameworks/{framework.id}/artifacts/{artifact_id}."
        f"{_extension_for_filename(filename)}"
    )
    artifact = Artifact(
        id=artifact_id,
        framework_id=framework.id,
        name=filename,
        file_key=file_key,
        file_size=len(body),
        mime_type=effective_mime,
        processing_status="processing",
        processing_started_at=datetime.now(UTC),
        content_sha256=hashlib.sha256(body).hexdigest(),
        source_kind="google_drive",
        source_external_id=payload.file_id,
        source_connection_id=connection.id,
        source_last_synced_at=datetime.now(UTC),
        source_synced_revision=(
            str(metadata.get("modifiedTime"))
            if metadata.get("modifiedTime")
            else None
        ),
    )
    db.add(artifact)
    settings = get_settings()
    s3.storage.upload_bytes(
        bucket=settings.s3_artifacts_bucket,
        key=file_key,
        body=body,
        mime_type=effective_mime,
    )
    await write_audit(
        db=db,
        actor_id=contributor.id,
        action="artifact_uploaded",
        target_type="artifact",
        target_id=artifact.id,
        metadata={
            "framework_id": str(framework.id),
            "source": "google_drive",
            "connection_id": str(connection.id),
            "external_file_id": payload.file_id,
        },
    )
    await db.commit()
    scan_artifact.delay(str(artifact.id))
    log.bind(artifact_id=str(artifact.id)).info("artifact_import_completed")
    return _artifact_to_response(artifact)


async def request_artifact_upload_url(
    db: AsyncSession,
    owner: FrameworkOwner,
    framework_id: UUID,
    payload: ArtifactUploadUrlRequest,
) -> ArtifactUploadUrlResponse:
    """Create a pending Artifact row and return a private S3 POST upload target."""
    framework = await _load_owned_framework_by_owner(db, owner, framework_id)
    _require_editable_artifacts(framework)
    if framework.status == "pipeline_passed":
        framework.status = "draft"
        framework.pipeline_failure_reasons = {}
    if payload.mime_type not in ALLOWED_ARTIFACT_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported artifact MIME type.",
        )

    await _reserve_artifact_budget(
        db,
        framework.id,
        add_bytes=payload.file_size,
        exclude_id=None,
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
        actor_id=owner.actor_id,
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
        user_id=owner.actor_id,
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


async def get_source_preview(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    artifact_id: UUID,
) -> SourcePreviewResponse:
    """Return the owner-only draft source preview for a connector artifact."""
    from app.integrations import google_drive
    from app.integrations.google_drive import (
        DriveFileTooLargeError,
        GoogleDriveAuthError,
        GoogleDriveError,
    )
    from app.modules.integrations.service import (
        get_active_connection_with_fresh_token,
    )

    framework = await _load_owned_framework(db, contributor, framework_id)
    _require_editable_artifacts(framework)
    artifact = await db.scalar(
        select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.framework_id == framework.id,
            Artifact.current_for_framework.is_(True),
        )
    )
    if (
        artifact is None
        or artifact.source_kind != "google_drive"
        or artifact.source_connection_id is None
        or artifact.source_external_id is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No connector source for this artifact.",
        )

    _, access_token = await get_active_connection_with_fresh_token(
        db,
        user_id=contributor.id,
        connection_id=artifact.source_connection_id,
    )
    try:
        modified_time, thumbnail_link = await google_drive.fetch_drive_source_state(
            access_token=access_token,
            file_id=artifact.source_external_id,
        )
    except GoogleDriveAuthError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "reauth_required",
                "message": "The connection is no longer authorized. Reconnect it.",
            },
        ) from None
    except GoogleDriveError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The file provider is unavailable.",
        ) from exc

    source_updated = bool(modified_time) and modified_time != (
        artifact.source_synced_revision or ""
    )
    preview_url: str | None = None
    settings = get_settings()
    bucket = settings.s3_artifacts_bucket
    if thumbnail_link and modified_time:
        prefix = (
            f"frameworks/{framework.id}/artifacts/{artifact.id}/source-preview/"
        )
        key = f"{prefix}{modified_time}.png"
        if not s3.storage.object_exists(bucket, key):
            try:
                body = await google_drive.download_drive_thumbnail(
                    thumbnail_link=thumbnail_link,
                    access_token=access_token,
                    max_bytes=_SOURCE_PREVIEW_MAX_BYTES,
                )
            except (DriveFileTooLargeError, GoogleDriveError):
                body = None
            if body is not None:
                s3.storage.delete_prefix(bucket, prefix)
                s3.storage.upload_bytes(
                    bucket=bucket,
                    key=key,
                    body=body,
                    mime_type="image/png",
                )
        if s3.storage.object_exists(bucket, key):
            preview_url = s3.storage.presigned_get(
                bucket,
                key,
                _SOURCE_PREVIEW_URL_TTL_SECONDS,
            )

    return SourcePreviewResponse(
        preview_url=preview_url,
        source_updated=source_updated,
        source_last_synced_at=artifact.source_last_synced_at,
    )


async def bind_and_sync(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    artifact_id: UUID,
    *,
    connection_id: UUID,
    file_id: str,
    allow_noop_skip: bool,
) -> ArtifactResponse:
    """Fork a new artifact row from the latest bytes of a connector source.

    Serves re-sync (same source), attach (unbound → bound), and repoint
    (different source). Bytes are write-once: this never overwrites an existing
    row. The prior current row is deleted unless a published version references
    it, in which case it is retained ``current_for_framework=False``.

    Args:
        db: Async database session.
        contributor: The requesting owner.
        framework_id: The owning Framework (must be editable).
        artifact_id: The current artifact being replaced.
        connection_id: The connection to pull from.
        file_id: The provider file to pull.
        allow_noop_skip: When True (re-sync), an unchanged source raises 409 and
            an unchanged content hash short-circuits without forking.

    Returns:
        The forked artifact's status (or the same artifact on a content-skip).

    Raises:
        HTTPException(404): Framework/artifact not found or foreign.
        HTTPException(409): reauth_required / rebind_required / source_unavailable
            / artifact_processing / already_up_to_date.
        HTTPException(413): Would exceed the size budget.
        HTTPException(415): Unsupported effective MIME type.
        HTTPException(502): Provider failure.
    """
    from app.integrations.google_drive import (
        EXPORT_MIME_MAP,
        DriveFileTooLargeError,
        GoogleDriveAuthError,
        GoogleDriveError,
        GoogleDriveNotFoundError,
        download_drive_file,
        get_drive_file_metadata,
    )
    from app.modules.integrations.service import (
        get_active_connection_with_fresh_token,
    )

    settings = get_settings()
    framework = await _load_owned_framework(db, contributor, framework_id)
    _require_editable_artifacts(framework)

    artifact = await db.scalar(
        select(Artifact)
        .where(
            Artifact.id == artifact_id,
            Artifact.framework_id == framework.id,
            Artifact.current_for_framework.is_(True),
        )
        .with_for_update()
    )
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found."
        )

    # TTL-aware in-flight guard: a fresh processing lease blocks a competing
    # sync; a stale lease falls through (the reaper will fail it).
    if artifact.processing_status == "processing" and (
        artifact.processing_started_at is not None
        and artifact.processing_started_at
        > datetime.now(UTC)
        - timedelta(minutes=settings.artifact_processing_lease_minutes)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "artifact_processing",
                    "message": "This artifact is still processing."},
        )

    log = logger.bind(
        module="frameworks",
        action="bind_and_sync",
        user_id=str(contributor.id),
        framework_id=str(framework.id),
        artifact_id=str(artifact.id),
    )

    connection, access_token = await get_active_connection_with_fresh_token(
        db, user_id=contributor.id, connection_id=connection_id
    )

    try:
        metadata = await get_drive_file_metadata(
            access_token=access_token, file_id=file_id
        )
    except GoogleDriveAuthError:
        raise _reauth_conflict() from None
    except GoogleDriveNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "source_unavailable",
                    "message": "The source file is no longer available."},
        ) from None
    except GoogleDriveError as exc:
        log.error("connector_metadata_failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The file provider is unavailable.",
        ) from exc

    modified_time = (
        str(metadata.get("modifiedTime")) if metadata.get("modifiedTime") else None
    )
    if allow_noop_skip and modified_time == (artifact.source_synced_revision or None):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "already_up_to_date",
                    "message": "The source has not changed."},
        )

    source_mime = str(metadata.get("mimeType", ""))
    source_name = str(metadata.get("name", "")).strip() or "import"
    export_mapping = EXPORT_MIME_MAP.get(source_mime)
    if export_mapping is not None:
        effective_mime, extension = export_mapping
        export_mime: str | None = effective_mime
        filename = f"{source_name}.{extension}"
    else:
        effective_mime = source_mime
        export_mime = None
        filename = source_name
    if effective_mime not in ALLOWED_ARTIFACT_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported artifact MIME type.",
        )

    metadata_size = metadata.get("size")
    if metadata_size is not None:
        await _reserve_artifact_budget(
            db, framework.id, add_bytes=int(metadata_size), exclude_id=artifact.id
        )

    try:
        body = await download_drive_file(
            access_token=access_token,
            file_id=file_id,
            export_mime=export_mime,
            max_bytes=ARTIFACT_MAX_TOTAL_SIZE,
        )
    except DriveFileTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Framework artifacts exceed the 500MB limit.",
        ) from None
    except GoogleDriveAuthError:
        raise _reauth_conflict() from None
    except GoogleDriveNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "source_unavailable",
                    "message": "The source file is no longer available."},
        ) from None
    except GoogleDriveError as exc:
        log.error("connector_download_failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The file provider is unavailable.",
        ) from exc

    new_hash = hashlib.sha256(body).hexdigest()

    # Content-skip (re-sync only): the file's modifiedTime moved but the bytes
    # are identical — advance the markers, do not fork, do not re-run pipeline.
    if allow_noop_skip and artifact.content_sha256 == new_hash:
        artifact.source_last_synced_at = datetime.now(UTC)
        artifact.source_synced_revision = modified_time
        await write_audit(
            db=db, actor_id=contributor.id, action="artifact_resynced",
            target_type="artifact", target_id=artifact.id,
            metadata={"framework_id": str(framework.id), "result": "content_unchanged"},
        )
        await db.commit()
        log.info("artifact_resync_content_unchanged")
        return _artifact_to_response(artifact)

    old_file_key = artifact.file_key
    old_preview_prefix = (
        f"frameworks/{framework.id}/artifacts/{artifact.id}/source-preview/"
    )
    new_artifact_id = uuid4()
    new_file_key = (
        f"frameworks/{framework.id}/artifacts/{new_artifact_id}."
        f"{_extension_for_filename(filename)}"
    )
    new_artifact = Artifact(
        id=new_artifact_id,
        framework_id=framework.id,
        name=filename,
        file_key=new_file_key,
        file_size=len(body),
        mime_type=effective_mime,
        content_sha256=new_hash,
        processing_status="processing",
        processing_started_at=datetime.now(UTC),
        current_for_framework=True,
        source_kind="google_drive",
        source_external_id=file_id,
        source_connection_id=connection.id,
        source_last_synced_at=datetime.now(UTC),
        source_synced_revision=modified_time,
    )
    db.add(new_artifact)

    version_reference_count = await db.scalar(
        select(func.count(FrameworkVersionArtifact.artifact_id)).where(
            FrameworkVersionArtifact.artifact_id == artifact.id
        )
    )
    old_row_deleted = int(version_reference_count or 0) == 0
    if old_row_deleted:
        await db.delete(artifact)
    else:
        artifact.current_for_framework = False

    if framework.preview_artifact_id == artifact_id:
        framework.preview_artifact_id = new_artifact_id

    await db.flush()

    s3.storage.upload_bytes(
        bucket=settings.s3_artifacts_bucket,
        key=new_file_key,
        body=body,
        mime_type=effective_mime,
    )
    await write_audit(
        db=db, actor_id=contributor.id, action="artifact_resynced",
        target_type="artifact", target_id=new_artifact_id,
        metadata={"framework_id": str(framework.id),
                  "replaced_artifact_id": str(artifact_id)},
    )
    await db.commit()

    # Post-commit S3 cleanup: always purge the old preview cache; drop the old
    # bytes only when the old row was deleted (retained rows keep their bytes).
    s3.storage.delete_prefix(settings.s3_artifacts_bucket, old_preview_prefix)
    if old_row_deleted:
        s3.storage.delete_object(settings.s3_artifacts_bucket, old_file_key)

    scan_artifact.delay(str(new_artifact_id))
    log.bind(new_artifact_id=str(new_artifact_id)).info("artifact_resynced")
    await db.refresh(new_artifact)
    return _artifact_to_response(new_artifact)


async def resync_artifact(
    db: AsyncSession,
    contributor: User,
    framework_id: UUID,
    artifact_id: UUID,
) -> ArtifactResponse:
    """Pull the latest bytes of an artifact's own bound source into a new row.

    Raises:
        HTTPException(404): No connector source bound to this artifact.
    """
    framework = await _load_owned_framework(db, contributor, framework_id)
    _require_editable_artifacts(framework)
    artifact = await db.scalar(
        select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.framework_id == framework.id,
            Artifact.current_for_framework.is_(True),
        )
    )
    if (
        artifact is None
        or artifact.source_kind != "google_drive"
        or artifact.source_connection_id is None
        or artifact.source_external_id is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No connector source for this artifact.",
        )
    return await bind_and_sync(
        db,
        contributor,
        framework_id,
        artifact_id,
        connection_id=artifact.source_connection_id,
        file_id=artifact.source_external_id,
        allow_noop_skip=True,
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


async def _reserve_artifact_budget(
    db: AsyncSession,
    framework_id: UUID,
    *,
    add_bytes: int,
    exclude_id: UUID | None,
) -> int:
    """Serialize the 500MB framework artifact budget check under a row lock.

    Locks the Framework row FOR UPDATE, then sums the current artifact bytes
    (optionally excluding the artifact being replaced) and rejects if the new
    bytes would exceed the cap. The lock makes the check-then-act atomic across
    concurrent import/upload/re-sync on the same Framework.

    Args:
        db: Async database session (an open transaction is required for the lock).
        framework_id: Framework whose budget is being reserved.
        add_bytes: Bytes about to be added.
        exclude_id: An artifact id to exclude from the sum (the row being replaced).

    Returns:
        The current total artifact bytes for the framework (excluding
        ``exclude_id``), so callers can derive a real streaming cap.

    Raises:
        HTTPException(413): If the reservation would exceed the size budget.
    """
    await db.execute(
        select(Framework.id).where(Framework.id == framework_id).with_for_update()
    )
    conditions = [Artifact.framework_id == framework_id]
    if exclude_id is not None:
        conditions.append(Artifact.id != exclude_id)
    existing = await db.scalar(
        select(func.coalesce(func.sum(Artifact.file_size), 0)).where(*conditions)
    )
    if int(existing or 0) + add_bytes > ARTIFACT_MAX_TOTAL_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Framework artifacts exceed the 500MB limit.",
        )
    return int(existing or 0)


async def confirm_artifact_upload(
    db: AsyncSession,
    owner: FrameworkOwner,
    framework_id: UUID,
    payload: ArtifactConfirmRequest,
) -> ArtifactResponse:
    """Confirm an Artifact object exists in S3 and dispatch virus scanning."""
    framework = await _load_owned_framework_by_owner(db, owner, framework_id)
    _require_editable_artifacts(framework)
    artifact = await _load_owned_artifact(db, framework, payload.artifact_id)

    settings = get_settings()
    if not s3.storage.object_exists(settings.s3_artifacts_bucket, artifact.file_key):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Artifact object has not been uploaded.",
        )

    if artifact.processing_status == "pending":
        artifact.processing_status = "processing"
        artifact.processing_started_at = datetime.now(UTC)
        await write_audit(
            db=db,
            actor_id=owner.actor_id,
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
            user_id=owner.actor_id,
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
    """Delete an Artifact from an owned draft or pipeline_failed Framework."""
    framework = await _load_owned_framework(db, contributor, framework_id)
    _require_editable_artifacts(framework)
    if framework.status == "pipeline_passed":
        framework.status = "draft"
        framework.pipeline_failure_reasons = {}
    artifact = await _load_owned_artifact(db, framework, artifact_id)
    # Capture the connector-preview cache prefix before the row is mutated: a
    # removed connector artifact must not leave orphaned source-preview
    # thumbnails behind in private storage.
    source_preview_prefix = (
        f"frameworks/{framework.id}/artifacts/{artifact.id}/source-preview/"
        if artifact.source_kind == "google_drive"
        else None
    )
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
    await db.flush()

    # Removing the last artifact returns the Framework to a clean draft. With no
    # files there is nothing to gate, so a stale pipeline_failed/processing
    # status (and its failure reasons) would otherwise leave the contributor
    # stuck on a "Checks failed" badge for checks that can no longer run.
    remaining = await db.scalar(
        select(func.count(Artifact.id)).where(
            Artifact.framework_id == framework.id,
            Artifact.current_for_framework.is_(True),
        )
    )
    if int(remaining or 0) == 0 and framework.status in {
        "submitted",
        "processing",
        "pipeline_failed",
        "pipeline_passed",
    }:
        framework.status = "draft"
        framework.pipeline_failure_reasons = {}

    await db.commit()
    if source_preview_prefix is not None:
        s3.storage.delete_prefix(
            get_settings().s3_artifacts_bucket, source_preview_prefix
        )
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
    owner: FrameworkOwner,
    framework_id: UUID,
) -> FrameworkResponse:
    """Publish an owned Framework after every pipeline gate has passed."""
    _require_live_state_access(owner)
    if owner.org_id is not None:
        from app.modules.organizations.contributor_service import (
            contributor_capability_active,
        )

        if not await contributor_capability_active(db, org_id=owner.org_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error_code": "capability_suspended"},
            )
    contributor_id = owner.actor_id
    if db.in_transaction():
        await db.rollback()
    gate_failed = False
    async with db.begin():
        framework = await _load_owned_framework_by_owner(db, owner, framework_id)
        if framework.status != "pipeline_passed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Framework must pass pipeline checks before publish.",
            )
        # Never trust a possibly-stale pipeline_passed: re-run the gate against
        # the live Artifact state at publish time so a current Artifact that
        # drifted back to flagged_pii / infected (re-processing, an added file)
        # can never leak into the public catalog. force=True because the status
        # is pipeline_passed, which is outside the normally-gated set. A failed
        # re-check persists the corrected status, then publish is refused.
        await evaluate_framework_pipeline(db, framework, force=True)
        if framework.status != "pipeline_passed":
            gate_failed = True
        else:
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
            # The pipeline gate only inspects DB columns; re-verify the bytes
            # still exist so a file removed from S3 out of band never publishes
            # as a dangling file_key that 404s on the Operator's download.
            if await current_artifact_file_missing(db, framework.id):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "An artifact file is no longer available in storage. "
                        "Re-upload the affected artifact and resubmit."
                    ),
                )

            await _ensure_published_version_snapshot(
                db, framework, list(current_artifacts)
            )
            framework.status = "published"
            framework.published_at = datetime.now(UTC)
            framework.tags_text = tags_to_search_text(framework.tags)
            settings = get_settings()
            for artifact in current_artifacts:
                if artifact.source_kind == "google_drive":
                    s3.storage.delete_prefix(
                        settings.s3_artifacts_bucket,
                        (
                            f"frameworks/{framework.id}/artifacts/{artifact.id}/"
                            "source-preview/"
                        ),
                    )
            await write_audit(
                db=db,
                actor_id=contributor_id,
                action="framework_published",
                target_type="framework",
                target_id=framework.id,
                metadata={"version": framework.version},
            )
    # The re-check failed: the corrected (non-passing) status is now committed.
    # Refuse the publish outside the transaction so the correction persists.
    if gate_failed:
        logger.bind(
            module="frameworks",
            action="publish_framework",
            user_id=contributor_id,
            framework_id=framework_id,
        ).warning("publish_blocked_pipeline_recheck_failed")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Framework no longer passes pipeline checks and cannot be "
                "published. Resolve the flagged artifacts and resubmit."
            ),
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
    owner: FrameworkOwner,
    framework_id: UUID,
    payload: FrameworkVersionCreate,
) -> FrameworkResponse:
    """Start a new draft version from a published or unpublished Framework."""
    _require_live_state_access(owner)
    if not payload.artifact_inheritance:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Nothing to bump.",
        )

    settings = get_settings()
    actor_id = owner.actor_id
    if db.in_transaction():
        await db.rollback()
    async with db.begin():
        framework = await _load_owned_framework_by_owner(db, owner, framework_id)
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
            actor_id=actor_id,
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
        user_id=actor_id,
        framework_id=framework.id,
    ).info("framework_version_bumped")
    return framework_to_response(framework)
