"""Service logic for contributor Framework draft CRUD."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.modules.auth.models import User
from app.modules.frameworks.models import Framework
from app.modules.frameworks.schemas import (
    FrameworkCreate,
    FrameworkListItem,
    FrameworkResponse,
    FrameworkUpdate,
    PricingConfig,
)


def _tags_text(tags: list[str]) -> str:
    """Join tags into the immutable text field used by the FTS index."""
    return " ".join(tags)


def framework_to_response(framework: Framework) -> FrameworkResponse:
    """Map an ORM Framework row to the contributor-facing response schema."""
    return FrameworkResponse(
        id=framework.id,
        contributor_id=framework.contributor_id,
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


def _require_draft(framework: Framework) -> None:
    """Reject metadata mutations unless the Framework is still a draft."""
    if framework.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft Frameworks can be modified.",
        )


async def create_framework(
    db: AsyncSession,
    contributor: User,
    payload: FrameworkCreate,
) -> FrameworkResponse:
    """Create a draft Framework owned by the verified Contributor."""
    pricing = payload.pricing
    framework = Framework(
        contributor_id=contributor.id,
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
    await write_audit(
        db=db,
        actor_id=contributor.id,
        action="framework_created",
        target_type="framework",
        target_id=framework.id,
        metadata={"status": framework.status},
    )
    await db.commit()
    await db.refresh(framework)
    logger.bind(
        module="frameworks",
        action="create_framework",
        user_id=contributor.id,
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
        await db.execute(
            select(Framework)
            .where(Framework.contributor_id == contributor.id)
            .order_by(desc(Framework.created_at))
        )
    ).scalars().all()
    return [_framework_to_list_item(framework) for framework in frameworks]


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
