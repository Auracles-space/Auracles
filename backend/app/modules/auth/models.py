"""SQLAlchemy models for auth and identity.

These classes mirror the Phase 1 auth foundation tables. Service logic is
introduced in later slices; this module deliberately stays focused on durable
identity state and relationships.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.models.base import CreatedAtMixin, UpdatedAtMixin

ROLE_ENUM = ENUM(
    "contributor",
    "operator",
    "attestor",
    "admin",
    name="role_enum",
    create_type=False,
)
KYC_STATUS_ENUM = ENUM(
    "unverified",
    "pending",
    "verified",
    "rejected",
    name="kyc_status_enum",
    create_type=False,
)
KYC_DOC_TYPE_ENUM = ENUM(
    "passport",
    "drivers_license",
    "national_id",
    "proof_of_address",
    name="kyc_doc_type_enum",
    create_type=False,
)
KYC_DOCUMENT_STATUS_ENUM = ENUM(
    "pending",
    "verified",
    "rejected",
    name="kyc_document_status_enum",
    create_type=False,
)


class User(UpdatedAtMixin, Base):
    """Account identity shared by all Auracles roles."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    kyc_status: Mapped[str] = mapped_column(
        KYC_STATUS_ENUM,
        nullable=False,
        server_default="unverified",
    )
    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    totp_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    roles: Mapped[list[UserRole]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="UserRole.user_id",
    )
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    backup_codes: Mapped[list[UserBackupCode]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    kyc_documents: Mapped[list[KycDocument]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="KycDocument.user_id",
    )


class UserRole(CreatedAtMixin, Base):
    """Role membership for a user, including Attestor approval state."""

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role", name="uq_user_roles_user_role"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(ROLE_ENUM, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    approved_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )

    user: Mapped[User] = relationship(
        back_populates="roles",
        foreign_keys=[user_id],
    )


class OAuthAccount(CreatedAtMixin, Base):
    """External OAuth identity linked to a user account for future OAuth support."""

    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_id",
            name="uq_oauth_accounts_provider_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(255), nullable=False)

    user: Mapped[User] = relationship(back_populates="oauth_accounts")


class UserBackupCode(CreatedAtMixin, Base):
    """Hashed single-use recovery code for TOTP-enabled accounts."""

    __tablename__ = "user_backup_codes"
    __table_args__ = (
        UniqueConstraint("user_id", "code_hash", name="uq_backup_codes_user_hash"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    user: Mapped[User] = relationship(back_populates="backup_codes")


class KycDocument(CreatedAtMixin, Base):
    """Identity document uploaded by a user for KYC review."""

    __tablename__ = "kyc_documents"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    doc_type: Mapped[str] = mapped_column(KYC_DOC_TYPE_ENUM, nullable=False)
    s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        KYC_DOCUMENT_STATUS_ENUM,
        nullable=False,
        server_default="pending",
    )
    reviewed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(
        back_populates="kyc_documents",
        foreign_keys=[user_id],
    )
