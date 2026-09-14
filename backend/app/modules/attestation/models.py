"""SQLAlchemy models for Phase 4b Attestation records.

Slice 1 is schema-only: these models define Attestor applications, profiles,
credentials, attestation requests, offers, disputes, and upload sessions before
the lifecycle services and API endpoints are added in later slices.

Module 1 (Attestor Onboarding) extends `AttestorApplication` into a gated
state machine (legal identity, KYC, taxonomy, CoI, tax docs), adds
verification levels + taxonomy + CoI to `AttestorProfile`, adds manual
registry cross-check fields to `Credential`, and introduces `AttestorTrial`
for the stubbed calibration step.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models.base import CreatedAtMixin, UpdatedAtMixin

ATTESTATION_TARGET_ENUM = ENUM(
    "framework",
    "contributor",
    "operator",
    "credential",
    name="attestation_target_enum",
    create_type=False,
)
ATTESTATION_STATUS_ENUM = ENUM(
    "pending_fee",
    "pending_owner_consent",
    "matching",
    "offered",
    "accepted",
    "in_review",
    "report_submitted",
    "revision_requested",
    "released",
    "disputed",
    "resolved",
    "needs_admin",
    "refunded",
    "closed",
    "cancelled",
    name="attestation_status_enum",
    create_type=False,
)
# Statuses meaning "the fee was released and the report stood". ``closed`` is
# the legacy value written before 2026-09-14; new releases write ``released``.
SETTLED_ATTESTATION_STATUSES: tuple[str, ...] = ("released", "closed")
# Statuses meaning "nothing further will happen on this request".
FINISHED_ATTESTATION_STATUSES: tuple[str, ...] = (
    "released",
    "refunded",
    "closed",
    "cancelled",
)
ATTESTATION_OUTCOME_ENUM = ENUM(
    "approved",
    "conditional",
    "rejected",
    name="attestation_outcome_enum",
    create_type=False,
)
ATTESTATION_DISPUTE_CATEGORY_ENUM = ENUM(
    "scope_error",
    "process_violation",
    "material_inaccuracy",
    "conflict_of_interest",
    name="attestation_dispute_category_enum",
    create_type=False,
)
ATTESTATION_OFFER_STATUS_ENUM = ENUM(
    "offered",
    "accepted",
    "declined",
    "expired",
    "superseded",
    name="attestation_offer_status_enum",
    create_type=False,
)
ATTESTATION_DISPUTE_STATUS_ENUM = ENUM(
    "open",
    "under_review",
    "resolved",
    name="attestation_dispute_status_enum",
    create_type=False,
)
ATTESTATION_DISPUTE_OUTCOME_ENUM = ENUM(
    "rejected",
    "upheld_refund",
    "upheld_revise",
    name="attestation_dispute_outcome_enum",
    create_type=False,
)
ATTESTATION_ANNOTATION_TYPE_ENUM = ENUM(
    "endorsement",
    "concern",
    "jurisdictional_caveat",
    "revision_recommended",
    name="attestation_annotation_type_enum",
    create_type=False,
)
ATTESTATION_CLARIFICATION_STATUS_ENUM = ENUM(
    "open",
    "answered",
    "expired",
    name="attestation_clarification_status_enum",
    create_type=False,
)
ATTESTATION_UPLOAD_PURPOSE_ENUM = ENUM(
    "report_evidence",
    "credential_evidence",
    "attestor_tax_document",
    name="attestation_upload_purpose_enum",
    create_type=False,
)
ATTESTATION_UPLOAD_SCAN_STATUS_ENUM = ENUM(
    "pending_scan",
    "clean",
    "infected",
    "error",
    name="attestation_upload_scan_status_enum",
    create_type=False,
)
ATTESTATION_REVIEW_TYPE_ENUM = ENUM(
    "quality",
    "compliance",
    "expert",
    "provenance",
    name="attestation_review_type_enum",
    create_type=False,
)
CREDENTIAL_VERIFICATION_STATUS_ENUM = ENUM(
    "unverified",
    "pending",
    "verified",
    "rejected",
    name="credential_verification_status_enum",
    create_type=False,
)
CREDENTIAL_ISSUER_TYPE_ENUM = ENUM(
    "institution",
    "organisation",
    "government",
    "association",
    name="credential_issuer_type_enum",
    create_type=False,
)
ATTESTOR_TRIAL_STATUS_ENUM = ENUM(
    "assigned",
    "submitted",
    "passed",
    "failed",
    name="attestor_trial_status_enum",
    create_type=False,
)
ATTESTOR_CREDENTIAL_BODY_ENUM = ENUM(
    "cfa_institute",
    "aicpa",
    "isaca",
    "rics",
    "sra",
    "state_bar",
    "fca",
    "acams",
    "other",
    name="attestor_credential_body_enum",
    create_type=False,
)


class Credential(UpdatedAtMixin, Base):
    """User-owned professional credential that can be attested."""

    __tablename__ = "credentials"
    __table_args__ = (Index("idx_credentials_user", "user_id"),)

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
    title: Mapped[str] = mapped_column(Text, nullable=False)
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    issued_date: Mapped[date] = mapped_column(Date, nullable=False)
    expires_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    evidence_file_keys: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    verification_status: Mapped[str] = mapped_column(
        CREDENTIAL_VERIFICATION_STATUS_ENUM,
        nullable=False,
        server_default="unverified",
    )
    credential_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    issuer_type: Mapped[str | None] = mapped_column(
        CREDENTIAL_ISSUER_TYPE_ENUM, nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    issuing_body: Mapped[str | None] = mapped_column(
        ATTESTOR_CREDENTIAL_BODY_ENUM, nullable=True
    )
    good_standing: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    registry_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    registry_checked_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    registry_reference: Mapped[str | None] = mapped_column(Text, nullable=True)


class Attestation(UpdatedAtMixin, Base):
    """Escrow-funded request for an independent trust report on a target."""

    __tablename__ = "attestations"
    __table_args__ = (
        CheckConstraint("currency = 'USD'", name="ck_attestations_currency_usd"),
        CheckConstraint("fee_amount > 0", name="ck_attestations_fee_amount_positive"),
        Index("idx_attestations_target", "target_type", "target_id"),
        Index(
            "idx_attestations_attestor_org_status",
            "attestor_org_id",
            "status",
        ),
        Index(
            "idx_attestations_status_dispute_window",
            "status",
            "dispute_window_ends_at",
        ),
        Index("idx_attestations_status_completion_due", "status", "completion_due_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    target_type: Mapped[str] = mapped_column(ATTESTATION_TARGET_ENUM, nullable=False)
    target_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    requestor_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    attestor_org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=True,
    )
    # Internal-only: never exposed in public/requestor response schemas.
    reviewing_member_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("org_members.id"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        ATTESTATION_STATUS_ENUM,
        nullable=False,
        server_default="pending_fee",
    )
    outcome: Mapped[str | None] = mapped_column(ATTESTATION_OUTCOME_ENUM, nullable=True)
    review_type: Mapped[str | None] = mapped_column(
        ATTESTATION_REVIEW_TYPE_ENUM,
        nullable=True,
    )
    brief: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    requested_specializations: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    requested_jurisdictions: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_references: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    report_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    escrow_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("escrows.id", ondelete="RESTRICT"),
        nullable=True,
    )
    fee_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        server_default="USD",
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completion_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    dispute_window_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    content_ack_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    content_ack_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rubric_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_late: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    revision_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    report_published_eligible: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    framework_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("framework_versions.id", ondelete="SET NULL"),
        nullable=True,
    )


class AttestationOffer(Base):
    """Per-attestor cohort offer and response audit trail."""

    __tablename__ = "attestation_offers"
    __table_args__ = (
        UniqueConstraint(
            "attestation_id",
            "org_id",
            name="uq_attestation_offers_attestation_org",
        ),
        Index("idx_attestation_offers_status_expires_at", "status", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attestation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestations.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=True,
    )
    cohort_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        ATTESTATION_OFFER_STATUS_ENUM,
        nullable=False,
        server_default="offered",
    )
    offered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    match_score: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 3),
        nullable=True,
    )
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    # Optional free text the org gave when declining; admin-visible only.
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AttestationArtifactAccess(Base):
    """Append-only log of every presigned Attestation artifact access.

    Records who accessed which artifact under what entitlement scope. The trail
    is the forensic evidence behind the content-use acknowledgment.
    """

    __tablename__ = "attestation_artifact_access"
    __table_args__ = (
        Index("idx_attestation_artifact_access_attestation", "attestation_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attestation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestations.id"),
        nullable=False,
    )
    attestor_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    artifact_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id"),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class AttestationDispute(CreatedAtMixin, Base):
    """Requestor-raised challenge to an attestation report.

    Module 5 replaces the old resolution_type/split model with a three-outcome
    enum (rejected, upheld_refund, upheld_revise) and adds SLA tracking columns.
    """

    __tablename__ = "attestation_disputes"
    __table_args__ = (
        Index("idx_attestation_disputes_status_created_at", "status", "created_at"),
        Index(
            "idx_attestation_disputes_raised_by_status_resolved",
            "raised_by",
            "status",
            "resolved_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attestation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestations.id", ondelete="CASCADE"),
        nullable=False,
    )
    raised_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(
        ATTESTATION_DISPUTE_CATEGORY_ENUM,
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        ATTESTATION_DISPUTE_STATUS_ENUM,
        nullable=False,
        server_default="open",
    )
    outcome: Mapped[str | None] = mapped_column(
        ATTESTATION_DISPUTE_OUTCOME_ENUM,
        nullable=True,
    )
    is_complex: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    resolution_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolution_overdue_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    admin_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class AttestationRating(Base):
    """Requestor's 1-5 quality rating of a stood attestation report.

    One immutable rating per attestation. Stored in Module 5; consumed by
    Module 6.4 reputation scoring. Maps to workflow section 5.3.
    """

    __tablename__ = "attestation_ratings"
    __table_args__ = (
        UniqueConstraint("attestation_id", name="uq_attestation_ratings_attestation"),
        CheckConstraint(
            "stars BETWEEN 1 AND 5", name="ck_attestation_ratings_stars_range"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attestation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestations.id", ondelete="CASCADE"),
        nullable=False,
    )
    rated_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class AttestorWarning(Base):
    """Formal warning recorded against an attestor on an upheld dispute.

    Every upheld dispute (refund or revise) records one warning. Two warnings
    inside a rolling 12 months flag the attestor's profile for human suspension
    review — never an automatic deactivation. Maps to spec section 4.7.
    """

    __tablename__ = "attestor_warnings"
    __table_args__ = (
        Index(
            "idx_attestor_warnings_attestor_created",
            "attestor_id",
            "created_at",
        ),
        Index(
            "idx_attestor_warnings_org_created",
            "attestor_org_id",
            "created_at",
        ),
        CheckConstraint(
            "(attestor_id IS NULL) != (attestor_org_id IS NULL)",
            name="ck_attestor_warnings_attestor_xor",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attestor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    attestor_org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    dispute_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestation_disputes.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class AttestationRubricDimension(Base):
    """Seeded, versioned rubric dimension for one attestation review type."""

    __tablename__ = "attestation_rubric_dimensions"
    __table_args__ = (
        UniqueConstraint(
            "review_type",
            "version",
            "key",
            name="uq_attestation_rubric_dimensions_type_version_key",
        ),
        Index(
            "idx_attestation_rubric_dimensions_type_version_order",
            "review_type",
            "version",
            "display_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    review_type: Mapped[str] = mapped_column(
        ATTESTATION_REVIEW_TYPE_ENUM,
        nullable=False,
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )


class AttestationRubricMethodology(Base):
    """Seeded canned methodology text per review type and rubric version."""

    __tablename__ = "attestation_rubric_methodology"
    __table_args__ = (
        UniqueConstraint(
            "review_type",
            "version",
            name="uq_attestation_rubric_methodology_type_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    review_type: Mapped[str] = mapped_column(
        ATTESTATION_REVIEW_TYPE_ENUM,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    text_body: Mapped[str] = mapped_column(Text, nullable=False)


class AttestationRubricScore(UpdatedAtMixin, CreatedAtMixin, Base):
    """One stored score and comment for a rubric dimension on an attestation."""

    __tablename__ = "attestation_rubric_scores"
    __table_args__ = (
        UniqueConstraint(
            "attestation_id",
            "dimension_id",
            name="uq_attestation_rubric_scores_attestation_dimension",
        ),
        CheckConstraint(
            "score IS NULL OR (score BETWEEN 1 AND 5)",
            name="ck_attestation_rubric_scores_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attestation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestations.id", ondelete="CASCADE"),
        nullable=False,
    )
    dimension_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestation_rubric_dimensions.id"),
        nullable=False,
    )
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class AttestationAnnotation(UpdatedAtMixin, CreatedAtMixin, Base):
    """Free-anchor annotation attached to one attestation workspace."""

    __tablename__ = "attestation_annotations"
    __table_args__ = (
        Index("idx_attestation_annotations_attestation", "attestation_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attestation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestations.id", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id"),
        nullable=True,
    )
    location_label: Mapped[str] = mapped_column(Text, nullable=False)
    quoted_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    annotation_type: Mapped[str] = mapped_column(
        ATTESTATION_ANNOTATION_TYPE_ENUM,
        nullable=False,
    )
    comment: Mapped[str] = mapped_column(Text, nullable=False)


class AttestationClarification(Base):
    """Attestor-to-requestor clarification with tracked response deadline."""

    __tablename__ = "attestation_clarifications"
    __table_args__ = (
        Index(
            "idx_attestation_clarifications_status_due",
            "status",
            "response_due_at",
        ),
        Index("idx_attestation_clarifications_attestation", "attestation_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attestation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestations.id", ondelete="CASCADE"),
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    response_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # When the assigned reviewer viewed the requestor's answer. Null while the
    # answer is unread, which drives the reviewer queue's "answer received" dot.
    reviewer_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        ATTESTATION_CLARIFICATION_STATUS_ENUM,
        nullable=False,
        server_default="open",
    )


class AttestationUploadSession(CreatedAtMixin, Base):
    """Server-issued permission for one private attestation evidence upload."""

    __tablename__ = "attestation_upload_sessions"
    __table_args__ = (
        CheckConstraint(
            "(attestation_id IS NOT NULL AND credential_id IS NULL) "
            "OR (attestation_id IS NULL AND credential_id IS NOT NULL)",
            name="ck_attestation_upload_sessions_single_parent",
        ),
        UniqueConstraint("s3_key", name="uq_attestation_upload_sessions_s3_key"),
        Index(
            "idx_attestation_upload_sessions_attestation_user_consumed",
            "attestation_id",
            "user_id",
            "consumed_at",
        ),
        Index(
            "idx_attestation_upload_sessions_credential_user_consumed",
            "credential_id",
            "user_id",
            "consumed_at",
        ),
        Index("idx_attestation_upload_sessions_expires_at", "expires_at"),
        Index("idx_attestation_upload_sessions_scan_status", "scan_status"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attestation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestations.id", ondelete="CASCADE"),
        nullable=True,
    )
    credential_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("credentials.id", ondelete="CASCADE"),
        nullable=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(
        ATTESTATION_UPLOAD_PURPOSE_ENUM,
        nullable=False,
    )
    s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    scan_status: Mapped[str] = mapped_column(
        ATTESTATION_UPLOAD_SCAN_STATUS_ENUM,
        nullable=False,
        server_default="pending_scan",
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class AttestorTrial(CreatedAtMixin, Base):
    """Stubbed calibration trial for an Attestor application (manual pass/fail).

    Rubric-scored evaluation arrives with Module 4; for now an admin decides
    pass/fail. A second failure holds the application.
    """

    __tablename__ = "attestor_trials"
    __table_args__ = (
        CheckConstraint(
            "attempt >= 1 AND attempt <= 2", name="ck_attestor_trials_attempt_range"
        ),
        CheckConstraint(
            "auto_result IS NULL OR auto_result IN ('pass','fail')",
            name="ck_attestor_trials_auto_result",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    org_application_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("org_attestor_applications.id", ondelete="CASCADE"),
        nullable=True,
    )
    org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id"),
        nullable=True,
    )
    # The nominated member who performs the trial review.
    member_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("org_members.id", ondelete="SET NULL"),
        nullable=True,
    )
    seeded_framework_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("frameworks.id", ondelete="SET NULL"),
        nullable=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    score_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    auto_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        ATTESTOR_TRIAL_STATUS_ENUM,
        nullable=False,
        server_default="assigned",
    )
    attempt: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    decided_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)


class AttestorTrialAnswerKey(Base):
    """Expected rubric score per dimension for one calibration fixture."""

    __tablename__ = "attestor_trial_answer_keys"
    __table_args__ = (
        UniqueConstraint(
            "framework_id",
            "dimension_id",
            name="uq_attestor_trial_answer_keys_framework_dimension",
        ),
        CheckConstraint(
            "expected_score BETWEEN 1 AND 5",
            name="ck_attestor_trial_answer_keys_score_range",
        ),
        CheckConstraint(
            "tolerance BETWEEN 0 AND 4",
            name="ck_attestor_trial_answer_keys_tolerance_range",
        ),
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
    dimension_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestation_rubric_dimensions.id"),
        nullable=False,
    )
    expected_score: Mapped[int] = mapped_column(Integer, nullable=False)
    tolerance: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )


class AttestorTrialRubricScore(UpdatedAtMixin, CreatedAtMixin, Base):
    """One nominee rubric score and comment for a trial dimension."""

    __tablename__ = "attestor_trial_rubric_scores"
    __table_args__ = (
        UniqueConstraint(
            "trial_id",
            "dimension_id",
            name="uq_attestor_trial_rubric_scores_trial_dimension",
        ),
        CheckConstraint(
            "score BETWEEN 1 AND 5",
            name="ck_attestor_trial_rubric_scores_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    trial_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestor_trials.id", ondelete="CASCADE"),
        nullable=False,
    )
    dimension_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestation_rubric_dimensions.id"),
        nullable=False,
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class AttestationBadge(CreatedAtMixin, Base):
    """Immutable published-badge / provenance snapshot for one Attestation.

    Written once when a framework-target Attestation closes and becomes
    publication-eligible. Renders the public trust badge and the private
    provenance record without reading live profile, framework, or credential
    tables, so the badge is tamper-evident against later mutation.

    Maps to: Module 6c design spec sections 4.2 and 5.1.
    """

    __tablename__ = "attestation_badges"
    __table_args__ = (
        UniqueConstraint(
            "attestation_id",
            name="uq_attestation_badges_attestation",
        ),
        Index("idx_attestation_badges_framework", "framework_id"),
        Index("idx_attestation_badges_attestor", "attestor_id"),
        Index("idx_attestation_badges_attestor_org", "attestor_org_id"),
        CheckConstraint(
            "(attestor_id IS NULL) != (attestor_org_id IS NULL)",
            name="ck_attestation_badges_attestor_xor",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    attestation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestations.id", ondelete="CASCADE"),
        nullable=False,
    )
    framework_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("frameworks.id", ondelete="CASCADE"),
        nullable=False,
    )
    review_type: Mapped[str] = mapped_column(
        ATTESTATION_REVIEW_TYPE_ENUM,
        nullable=False,
    )
    outcome: Mapped[str] = mapped_column(
        ATTESTATION_OUTCOME_ENUM,
        nullable=False,
    )
    attestor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    attestor_org_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    attestor_org_slug: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attestor_display_name: Mapped[str] = mapped_column(Text, nullable=False)
    credentials_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    framework_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
