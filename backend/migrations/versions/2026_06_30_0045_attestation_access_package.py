"""Add Attestation access-package schema: consent state, ack, access log.

Implements Module 2b (workflow-doc section 2.5). Adds the
pending_owner_consent status value, per-accept content acknowledgment
columns, the attestation_artifact_access audit table, and the
owner-consent timeout config. The enum value is intentionally left in
place on downgrade because Postgres cannot safely remove a single enum
label in-place.

Revision ID: 2026_06_30_0045
Revises: 2026_06_30_0044
Create Date: 2026-06-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_30_0045"
down_revision: str | Sequence[str] | None = "2026_06_30_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSENT_HOURS_KEY = "attestation_owner_consent_hours"


def upgrade() -> None:
    """Add consent enum value, ack columns, access table, and consent config."""
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE attestation_status_enum ADD VALUE IF NOT EXISTS "
            "'pending_owner_consent'"
        )

    op.add_column(
        "attestations",
        sa.Column("content_ack_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "attestations",
        sa.Column("content_ack_version", sa.Text(), nullable=True),
    )
    op.create_table(
        "attestation_artifact_access",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("attestation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attestor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["attestation_id"], ["attestations.id"]),
        sa.ForeignKeyConstraint(["attestor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
    )
    op.create_index(
        "idx_attestation_artifact_access_attestation",
        "attestation_artifact_access",
        ["attestation_id"],
    )
    op.execute(
        sa.text(
            """
            INSERT INTO platform_config (key, value)
            VALUES (:key, '72')
            ON CONFLICT (key) DO NOTHING
            """
        ).bindparams(key=CONSENT_HOURS_KEY)
    )


def downgrade() -> None:
    """Drop access table, ack columns, and consent config while leaving the enum."""
    op.execute(
        sa.text("DELETE FROM platform_config WHERE key = :key").bindparams(
            key=CONSENT_HOURS_KEY
        )
    )
    op.drop_index(
        "idx_attestation_artifact_access_attestation",
        table_name="attestation_artifact_access",
    )
    op.drop_table("attestation_artifact_access")
    op.drop_column("attestations", "content_ack_version")
    op.drop_column("attestations", "content_ack_at")
