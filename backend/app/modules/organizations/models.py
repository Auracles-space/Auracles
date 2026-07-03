"""SQLAlchemy models for Organizations Core.

Six tables: organizations, org_members, org_invitations, org_teams,
org_team_members, org_capabilities. Invitations and teams are added by
later migrations in this sub-project; this file grows with them.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models.base import CreatedAtMixin, UpdatedAtMixin

ORG_MEMBER_ROLE_ENUM = ENUM(
    "owner",
    "admin",
    "member",
    name="org_member_role_enum",
    create_type=False,
)
ORG_CAPABILITY_ENUM = ENUM(
    "attestor",
    "contributor",
    "operator",
    name="org_capability_enum",
    create_type=False,
)
ORG_CAPABILITY_STATUS_ENUM = ENUM(
    "pending",
    "active",
    "suspended",
    "revoked",
    name="org_capability_status_enum",
    create_type=False,
)


class Organization(UpdatedAtMixin, Base):
    """An organization base entity with no commercial powers by itself."""

    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    logo_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class OrgMember(CreatedAtMixin, Base):
    """Membership of a user in an organization with a fixed role."""

    __tablename__ = "org_members"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_members_org_user"),
        Index(
            "uq_org_members_single_owner",
            "org_id",
            unique=True,
            postgresql_where=text("role = 'owner'"),
        ),
        Index("idx_org_members_user", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(ORG_MEMBER_ROLE_ENUM, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class OrgCapability(UpdatedAtMixin, Base):
    """Commercial capability status row for an organization."""

    __tablename__ = "org_capabilities"
    __table_args__ = (
        UniqueConstraint("org_id", "capability", name="uq_org_capabilities_org_cap"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    capability: Mapped[str] = mapped_column(ORG_CAPABILITY_ENUM, nullable=False)
    status: Mapped[str] = mapped_column(ORG_CAPABILITY_STATUS_ENUM, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
