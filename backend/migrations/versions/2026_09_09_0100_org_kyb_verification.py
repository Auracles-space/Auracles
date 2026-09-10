"""Move business verification onto the org's shared legal profile.

Supports DESIGN-1. KYB existed only on ``org_attestor_applications``, so an
organization's legal identity was verified solely as a side effect of applying
to be an Attestor. Contributor and Operator capabilities self-activated with no
identity check at all.

KYB becomes a precondition of every capability, so the verdict moves to
``org_legal_profiles`` — the row that already holds ``legal_name`` and
``registration_number`` and already feeds invoices. Attaching it to the
organization instead would have separated an identity from its verification,
leaving two rows free to disagree about who the org legally is.

Existing applications carry their data across, creating the legal profile where
one does not exist yet, and an application an admin already verified promotes
to a verified profile so nobody re-verifies. Everything else starts
``unverified``: staging holds only test organizations and no production
environment exists yet, so there is nothing to grandfather.

The attestor application's KYB columns are dropped rather than left behind
(human-approved 2026-09-09). ``downgrade`` restores the columns and copies the
values back from the legal profile, so the step is reversible.

Revision ID: 2026_09_09_0100
Revises: 2026_09_06_0099
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_09_09_0100"
down_revision: str | Sequence[str] | None = "2026_09_06_0099"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

org_kyb_status_enum = postgresql.ENUM(
    "unverified",
    "pending",
    "verified",
    "rejected",
    name="org_kyb_status_enum",
    create_type=False,
)


def upgrade() -> None:
    """Add KYB to the legal profile, carry data across, drop the old columns."""
    bind = op.get_bind()
    org_kyb_status_enum.create(bind, checkfirst=True)

    op.add_column(
        "org_legal_profiles",
        sa.Column(
            "incorporation_doc_keys",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "org_legal_profiles",
        sa.Column(
            "kyb_status",
            org_kyb_status_enum,
            nullable=False,
            server_default="unverified",
        ),
    )
    op.add_column(
        "org_legal_profiles",
        sa.Column("kyb_submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "org_legal_profiles",
        sa.Column("kyb_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "org_legal_profiles",
        sa.Column(
            "kyb_verified_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "org_legal_profiles", sa.Column("kyb_review_notes", sa.Text(), nullable=True)
    )

    # One application per org is the norm, but a rejected one can be followed
    # by a reapplication, so prefer the most recently verified row and fall
    # back to the newest. Only rows carrying a legal name are usable: the
    # profile's legal_name is NOT NULL.
    latest_application = """
        SELECT DISTINCT ON (org_id)
            org_id,
            legal_name,
            registration_number,
            incorporation_doc_keys,
            kyb_verified_at,
            kyb_verified_by
        FROM org_attestor_applications
        WHERE legal_name IS NOT NULL AND legal_name <> ''
        ORDER BY org_id, kyb_verified_at DESC NULLS LAST, created_at DESC
    """

    # Orgs that applied but never created a legal profile get one now, so the
    # verification they already passed is not lost.
    op.execute(
        f"""
        INSERT INTO org_legal_profiles (
            org_id, legal_name, registration_number,
            incorporation_doc_keys, kyb_status, kyb_submitted_at,
            kyb_verified_at, kyb_verified_by
        )
        SELECT a.org_id,
               a.legal_name,
               a.registration_number,
               a.incorporation_doc_keys,
               CASE
                   WHEN a.kyb_verified_at IS NOT NULL THEN 'verified'
                   WHEN a.registration_number IS NOT NULL
                        AND array_length(a.incorporation_doc_keys, 1) > 0
                       THEN 'pending'
                   ELSE 'unverified'
               END::org_kyb_status_enum,
               a.kyb_verified_at,
               a.kyb_verified_at,
               a.kyb_verified_by
        FROM ({latest_application}) AS a
        WHERE NOT EXISTS (
            SELECT 1 FROM org_legal_profiles p WHERE p.org_id = a.org_id
        )
        """
    )

    # Orgs that already had a profile keep its legal name and take the
    # application's documents and verdict.
    op.execute(
        f"""
        UPDATE org_legal_profiles AS p
        SET registration_number = COALESCE(
                p.registration_number, a.registration_number
            ),
            incorporation_doc_keys = a.incorporation_doc_keys,
            kyb_verified_at = a.kyb_verified_at,
            kyb_verified_by = a.kyb_verified_by,
            kyb_submitted_at = a.kyb_verified_at,
            kyb_status = CASE
                WHEN a.kyb_verified_at IS NOT NULL THEN 'verified'
                WHEN array_length(a.incorporation_doc_keys, 1) > 0 THEN 'pending'
                ELSE 'unverified'
            END::org_kyb_status_enum
        FROM ({latest_application}) AS a
        WHERE a.org_id = p.org_id
        """
    )

    # The admin review queue lists profiles awaiting a verdict.
    op.create_index(
        "idx_org_legal_profiles_kyb_status",
        "org_legal_profiles",
        ["kyb_status"],
    )

    op.drop_column("org_attestor_applications", "kyb_verified_by")
    op.drop_column("org_attestor_applications", "kyb_verified_at")
    op.drop_column("org_attestor_applications", "incorporation_doc_keys")
    op.drop_column("org_attestor_applications", "registration_number")
    op.drop_column("org_attestor_applications", "legal_name")


def downgrade() -> None:
    """Restore the attestor application's KYB columns and their values."""
    bind = op.get_bind()
    op.add_column(
        "org_attestor_applications", sa.Column("legal_name", sa.Text(), nullable=True)
    )
    op.add_column(
        "org_attestor_applications",
        sa.Column("registration_number", sa.Text(), nullable=True),
    )
    op.add_column(
        "org_attestor_applications",
        sa.Column(
            "incorporation_doc_keys",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "org_attestor_applications",
        sa.Column("kyb_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "org_attestor_applications",
        sa.Column(
            "kyb_verified_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE org_attestor_applications AS a
        SET legal_name = p.legal_name,
            registration_number = p.registration_number,
            incorporation_doc_keys = p.incorporation_doc_keys,
            kyb_verified_at = p.kyb_verified_at,
            kyb_verified_by = p.kyb_verified_by
        FROM org_legal_profiles AS p
        WHERE p.org_id = a.org_id
        """
    )

    op.drop_index(
        "idx_org_legal_profiles_kyb_status", table_name="org_legal_profiles"
    )
    for column in (
        "kyb_review_notes",
        "kyb_verified_by",
        "kyb_verified_at",
        "kyb_submitted_at",
        "kyb_status",
        "incorporation_doc_keys",
    ):
        op.drop_column("org_legal_profiles", column)
    org_kyb_status_enum.drop(bind, checkfirst=True)
