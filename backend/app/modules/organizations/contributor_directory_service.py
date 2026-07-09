"""Public contributor-organization directory read helpers.

Returns active contributor organizations only, exposing organization identity,
verification level, published Framework count, member count, and reputation
without leaking member identities or internal staffing metadata.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.frameworks.models import Framework
from app.modules.organizations.models import (
    Organization,
    OrgCapability,
    OrgContributorProfile,
    OrgMember,
)
from app.modules.organizations.schemas import ContributorOrgDirectoryEntry


def _public_directory_query() -> Select[
    tuple[Organization, OrgContributorProfile, int, int]
]:
    """Build the shared query for active public contributor organizations."""
    published_framework_count = (
        select(func.count(Framework.id))
        .where(
            Framework.contributor_org_id == Organization.id,
            Framework.status == "published",
        )
        .correlate(Organization)
        .scalar_subquery()
    )
    member_count = (
        select(func.count(OrgMember.id))
        .where(OrgMember.org_id == Organization.id)
        .correlate(Organization)
        .scalar_subquery()
    )
    return (
        select(
            Organization,
            OrgContributorProfile,
            published_framework_count.label("published_framework_count"),
            member_count.label("member_count"),
        )
        .join(OrgContributorProfile, OrgContributorProfile.org_id == Organization.id)
        .join(
            OrgCapability,
            and_(
                OrgCapability.org_id == Organization.id,
                OrgCapability.capability == "contributor",
                OrgCapability.status == "active",
            ),
        )
        .where(
            OrgContributorProfile.active.is_(True),
            Organization.suspended_at.is_(None),
            Organization.deactivated_at.is_(None),
        )
        .order_by(Organization.name.asc(), Organization.id.asc())
    )


def _entry_from_row(
    organization: Organization,
    profile: OrgContributorProfile,
    *,
    published_framework_count: int,
    member_count: int,
) -> ContributorOrgDirectoryEntry:
    """Map one public contributor-organization row into the response schema."""
    raw_reputation = profile.reputation_score
    reputation: Decimal | None = (
        Decimal(str(raw_reputation)).quantize(Decimal("0.01"))
        if raw_reputation is not None
        else None
    )
    return ContributorOrgDirectoryEntry(
        org_id=organization.id,
        name=organization.name,
        slug=organization.slug,
        logo_key=organization.logo_key,
        country=organization.country,
        website=organization.website,
        description=organization.description,
        verification_level=profile.verification_level,
        published_framework_count=published_framework_count,
        member_count=member_count,
        reputation=reputation,
    )


async def list_contributor_orgs(
    db: AsyncSession,
) -> list[ContributorOrgDirectoryEntry]:
    """Return public contributor organizations with aggregate counts."""
    rows = (await db.execute(_public_directory_query())).all()
    return [
        _entry_from_row(
            organization,
            profile,
            published_framework_count=int(published_framework_count or 0),
            member_count=int(member_count or 0),
        )
        for organization, profile, published_framework_count, member_count in rows
    ]


async def get_contributor_org(
    db: AsyncSession,
    *,
    org_slug: str,
) -> ContributorOrgDirectoryEntry:
    """Return one contributor-organization public profile by slug or raise 404."""
    row = (
        await db.execute(
            _public_directory_query().where(
                func.lower(Organization.slug) == org_slug.lower()
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contributor organization not found.",
        )
    organization, profile, published_framework_count, member_count = row
    return _entry_from_row(
        organization,
        profile,
        published_framework_count=int(published_framework_count or 0),
        member_count=int(member_count or 0),
    )
