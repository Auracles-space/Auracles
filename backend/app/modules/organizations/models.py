"""SQLAlchemy models for Organizations Core.

This module defines the organization base entity plus membership,
invitation, capability, and later team structures used by the
org-as-attestor/contributor/operator sub-projects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB
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
ORG_KYB_STATUS_ENUM = ENUM(
    "unverified",
    "pending",
    "verified",
    "rejected",
    name="org_kyb_status_enum",
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
ORG_INVITATION_STATUS_ENUM = ENUM(
    "pending",
    "accepted",
    "declined",
    "revoked",
    "expired",
    name="org_invitation_status_enum",
    create_type=False,
)
ORG_ATTESTOR_APPLICATION_STATUS_ENUM = ENUM(
    "draft",
    "submitted",
    "needs_info",
    "approved",
    "rejected",
    name="org_attestor_application_status_enum",
    create_type=False,
)
# Reuses the PG enum created by the individual attestor migrations; the type
# survives the individual pipeline retirement because org applications share it.
ORG_TAX_DOCUMENT_TYPE_ENUM = ENUM(
    "w9",
    "w8ben",
    "other",
    name="tax_document_type_enum",
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
    # Billing contact for purchase invoices where the org is the buyer. Falls
    # back to the org owner's email at issue time when unset.
    billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Who closed the organization and the optional reason they gave. Cleared
    # when an admin reactivates it so the record reflects the current state.
    deactivated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    deactivation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Which admin suspended the org; cleared on reinstate with the reason.
    suspended_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    # Why the platform suspended the org, written by the admin and shown to
    # the owner. Cleared on reinstate so a stale reason never outlives it.
    suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


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
    # Admin's reason for a suspended or revoked status, shown to the owner.
    # Cleared when the capability is reinstated.
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class OrgInvitation(CreatedAtMixin, Base):
    """Pending or terminal invitation for one organization email address."""

    __tablename__ = "org_invitations"
    __table_args__ = (
        Index(
            "uq_org_invitations_pending",
            "org_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("idx_org_invitations_email", "email"),
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
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(ORG_MEMBER_ROLE_ENUM, nullable=False)
    invited_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(ORG_INVITATION_STATUS_ENUM, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class OrgTeam(CreatedAtMixin, Base):
    """A sub-grouping of members within an organization."""

    __tablename__ = "org_teams"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_org_teams_org_name"),)

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
    name: Mapped[str] = mapped_column(String(80), nullable=False)


class OrgTeamMember(CreatedAtMixin, Base):
    """Membership of an OrgMember in an OrgTeam."""

    __tablename__ = "org_team_members"
    __table_args__ = (Index("idx_org_team_members_member", "member_id"),)

    team_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("org_teams.id", ondelete="CASCADE"),
        primary_key=True,
    )
    member_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("org_members.id", ondelete="CASCADE"),
        primary_key=True,
    )


class OrgTeamCapability(CreatedAtMixin, Base):
    """A marketplace capability granted to every member of one team.

    A member holds the derived role for a capability when the org capability is
    active and the member is owner/admin or sits on a team with a matching row.
    """

    __tablename__ = "org_team_capabilities"

    team_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("org_teams.id", ondelete="CASCADE"),
        primary_key=True,
    )
    capability: Mapped[str] = mapped_column(
        ORG_CAPABILITY_ENUM,
        primary_key=True,
    )


class OrgAttestorApplication(UpdatedAtMixin, Base):
    """Org application for the attestor capability with per-gate stamps.

    Replaces the individual attestor_applications flow: KYB fields,
    matching inputs, owner-signed undertakings, payout/tax gates, and the
    nominated trial member all live on one row so the admin gate checklist
    reads directly from it.
    """

    __tablename__ = "org_attestor_applications"
    __table_args__ = (
        Index(
            "uq_org_attestor_app_live",
            "org_id",
            unique=True,
            postgresql_where=text("status IN ('draft', 'submitted', 'needs_info')"),
        ),
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
    status: Mapped[str] = mapped_column(
        ORG_ATTESTOR_APPLICATION_STATUS_ENUM,
        nullable=False,
        server_default="draft",
    )
    # KYB identity (legal name, registration number, incorporation documents)
    # lives on Organization: it is one legal identity per org, verified once and
    # reused by every capability, so this row reads it rather than holding a
    # second copy that could disagree.
    specializations: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    jurisdictions: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    sectors: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    functions: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    credentials_summary: Mapped[str] = mapped_column(Text, nullable=False)
    sample_work: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    professional_references: Mapped[str] = mapped_column(Text, nullable=False)
    coi_declarations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    coi_signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    coi_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    confidentiality_signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    payout_account_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("payout_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    tax_document_type: Mapped[str | None] = mapped_column(
        ORG_TAX_DOCUMENT_TYPE_ENUM,
        nullable=True,
    )
    tax_document_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    trial_attestation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("attestations.id", ondelete="SET NULL"),
        nullable=True,
    )
    # SET NULL (not CASCADE): removing the nominated member must not delete
    # the application's KYB record; the org re-nominates instead.
    trial_member_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("org_members.id", ondelete="SET NULL"),
        nullable=True,
    )
    admin_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class OrgAttestorProfile(UpdatedAtMixin, Base):
    """Approved org attestor matching profile copied from its application."""

    __tablename__ = "org_attestor_profiles"
    __table_args__ = (
        Index(
            "idx_org_attestor_profiles_specializations_gin",
            "specializations",
            postgresql_using="gin",
        ),
        Index(
            "idx_org_attestor_profiles_jurisdictions_gin",
            "jurisdictions",
            postgresql_using="gin",
        ),
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
        unique=True,
    )
    specializations: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    jurisdictions: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    sectors: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    functions: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    verification_level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    coi_declarations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    coi_signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    coi_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    coi_reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    confidentiality_signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    late_submission_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    suspension_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    certified_attestor_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class OrgMemberNda(CreatedAtMixin, Base):
    """A member's signed platform NDA for org attestation work.

    One row per member; re-signing after a version bump updates
    nda_version and signed_at in place (Task 3 service behavior).
    """

    __tablename__ = "org_member_ndas"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    member_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("org_members.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    nda_version: Mapped[str] = mapped_column(Text, nullable=False)
    signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class OrgContributorProfile(UpdatedAtMixin, Base):
    """Directory and reputation profile for an org-backed Contributor."""

    __tablename__ = "org_contributor_profiles"
    __table_args__ = (
        UniqueConstraint("org_id", name="uq_org_contributor_profiles_org"),
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
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    verification_level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reputation_score: Mapped[float | None] = mapped_column(
        Numeric,
        nullable=True,
    )


class OrgLegalProfile(UpdatedAtMixin, Base):
    """Shared legal identity row for organization commercial capabilities."""

    __tablename__ = "org_legal_profiles"
    __table_args__ = (UniqueConstraint("org_id", name="uq_org_legal_profiles_org"),)

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
    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    registration_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tax_document_type: Mapped[str | None] = mapped_column(
        ORG_TAX_DOCUMENT_TYPE_ENUM,
        nullable=True,
    )
    tax_document_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Business verification (KYB) attaches to the legal identity it verifies,
    # rather than to the organization or to the attestor application that used
    # to own it. legal_name and registration_number above are two of the three
    # facts an admin checks, so holding the verdict anywhere else would put the
    # identity and its verification in different rows, free to disagree.
    incorporation_doc_keys: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    kyb_status: Mapped[str] = mapped_column(
        ORG_KYB_STATUS_ENUM,
        nullable=False,
        server_default="unverified",
    )
    kyb_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    kyb_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    kyb_verified_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    kyb_review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
