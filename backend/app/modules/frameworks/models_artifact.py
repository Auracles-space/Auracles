"""SQLAlchemy models for marketplace artifacts and processing audit data.

Artifacts are stored privately in S3; these tables track ownership, scan state,
processing state, public preview selection support, rarity signals, and
download audit records. Upload and processing services arrive in later slices.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, ENUM, INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.models.base import CreatedAtMixin

SCAN_STATUS_ENUM = ENUM(
    "pending",
    "clean",
    "infected",
    "error",
    name="scan_status_enum",
    create_type=False,
)
PROCESSING_STATUS_ENUM = ENUM(
    "pending",
    "processing",
    "processed",
    "failed",
    "flagged_pii",
    "flagged_rarity",
    name="processing_status_enum",
    create_type=False,
)


class Artifact(CreatedAtMixin, Base):
    """File attached to a Framework with pipeline processing state."""

    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint("file_size >= 0", name="ck_artifacts_file_size_nonnegative"),
        CheckConstraint(
            "internal_rarity IS NULL OR internal_rarity BETWEEN 0 AND 1",
            name="ck_artifacts_internal_rarity_range",
        ),
        CheckConstraint(
            "external_rarity IS NULL OR external_rarity BETWEEN 0 AND 1",
            name="ck_artifacts_external_rarity_range",
        ),
        CheckConstraint(
            "rarity_score IS NULL OR rarity_score BETWEEN 0 AND 1",
            name="ck_artifacts_rarity_score_range",
        ),
        Index("idx_artifacts_framework", "framework_id"),
        Index("idx_artifacts_processing_status", "processing_status"),
        Index("idx_artifacts_simhash", "simhash"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    framework_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("frameworks.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_key: Mapped[str] = mapped_column(Text, nullable=False)
    clean_file_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    scan_status: Mapped[str] = mapped_column(
        SCAN_STATUS_ENUM,
        nullable=False,
        server_default="pending",
    )
    processing_status: Mapped[str] = mapped_column(
        PROCESSING_STATUS_ENUM,
        nullable=False,
        server_default="pending",
    )
    pii_detected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    pii_review_needed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    minhash_signature: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    simhash: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    metadata_vector: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    internal_rarity: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )
    external_rarity: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )
    rarity_score: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )
    nearest_match_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id"),
        nullable=True,
    )

    pii_audits: Mapped[list[ArtifactPiiAudit]] = relationship(
        back_populates="artifact",
        cascade="all, delete-orphan",
    )
    rarity_audits: Mapped[list[ArtifactRarityAudit]] = relationship(
        back_populates="artifact",
        cascade="all, delete-orphan",
        foreign_keys="ArtifactRarityAudit.artifact_id",
    )
    downloads: Mapped[list[ArtifactDownload]] = relationship(
        back_populates="artifact",
        cascade="all, delete-orphan",
    )


class ArtifactPiiAudit(Base):
    """PII detection and redaction audit trail for an Artifact."""

    __tablename__ = "artifact_pii_audit"
    __table_args__ = (Index("idx_artifact_pii_audit_artifact", "artifact_id"),)

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    artifact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    pii_types_found: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    auto_redacted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    flagged_for_review: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
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
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    artifact: Mapped[Artifact] = relationship(back_populates="pii_audits")


class ArtifactRarityAudit(CreatedAtMixin, Base):
    """Inputs and decisions that produced an Artifact rarity score."""

    __tablename__ = "artifact_rarity_audit"
    __table_args__ = (
        CheckConstraint(
            "internal_jaccard IS NULL OR internal_jaccard BETWEEN 0 AND 1",
            name="ck_artifact_rarity_audit_internal_jaccard_range",
        ),
        CheckConstraint(
            "metadata_uplift IS NULL OR metadata_uplift BETWEEN 0 AND 1",
            name="ck_artifact_rarity_audit_metadata_uplift_range",
        ),
        CheckConstraint(
            "blended_score IS NULL OR blended_score BETWEEN 0 AND 1",
            name="ck_artifact_rarity_audit_blended_score_range",
        ),
        Index("idx_artifact_rarity_audit_artifact", "artifact_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    artifact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    internal_jaccard: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )
    nearest_match_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id"),
        nullable=True,
    )
    external_phrases_queried: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    external_hit_counts: Mapped[list[int]] = mapped_column(
        ARRAY(Integer),
        nullable=False,
        server_default=text("'{}'::integer[]"),
    )
    metadata_uplift: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )
    blended_score: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )
    soft_fail_acknowledged: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    acknowledged_ip: Mapped[str | None] = mapped_column(INET, nullable=True)

    artifact: Mapped[Artifact] = relationship(
        back_populates="rarity_audits",
        foreign_keys=[artifact_id],
    )


class ArtifactDownload(Base):
    """Audit record for a licensed Artifact download."""

    __tablename__ = "artifact_downloads"
    __table_args__ = (
        Index("idx_artifact_downloads_license", "license_id"),
        Index("idx_artifact_downloads_artifact", "artifact_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    license_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("licenses.id"),
        nullable=False,
    )
    artifact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    downloaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    artifact: Mapped[Artifact] = relationship(back_populates="downloads")
