"""Add KYC document storage.

Revision ID: 2026_06_07_0004
Revises: 2026_06_07_0003
Create Date: 2026-06-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_07_0004"
down_revision: str | Sequence[str] | None = "2026_06_07_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

kyc_doc_type_enum = postgresql.ENUM(
    "passport",
    "drivers_license",
    "national_id",
    "proof_of_address",
    name="kyc_doc_type_enum",
    create_type=False,
)
kyc_document_status_enum = postgresql.ENUM(
    "pending",
    "verified",
    "rejected",
    name="kyc_document_status_enum",
    create_type=False,
)


def upgrade() -> None:
    """Create KYC document records for identity review."""
    bind = op.get_bind()
    kyc_doc_type_enum.create(bind, checkfirst=True)
    kyc_document_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "kyc_documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doc_type", kyc_doc_type_enum, nullable=False),
        sa.Column("s3_key", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            kyc_document_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
    )
    op.create_index(
        "ix_kyc_documents_user_id_created_at",
        "kyc_documents",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_kyc_documents_status_created_at",
        "kyc_documents",
        ["status", "created_at"],
    )


def downgrade() -> None:
    """Remove KYC document records and enums."""
    bind = op.get_bind()
    op.drop_index("ix_kyc_documents_status_created_at", table_name="kyc_documents")
    op.drop_index("ix_kyc_documents_user_id_created_at", table_name="kyc_documents")
    op.drop_table("kyc_documents")
    kyc_document_status_enum.drop(bind, checkfirst=True)
    kyc_doc_type_enum.drop(bind, checkfirst=True)
