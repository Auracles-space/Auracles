"""Add Framework Collections schema foundation.

Supports Phase 5b-1 Slice 1 by creating durable bundle tables, checkout-time
purchase snapshots, earning allocation rows, and license source metadata before
CRUD, purchase, webhook, and refund slices depend on them.

Revision ID: 2026_06_11_0020
Revises: 2026_06_11_0019
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_11_0020"
down_revision: str | Sequence[str] | None = "2026_06_11_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


collection_status_enum = postgresql.ENUM(
    "draft",
    "published",
    "unpublished",
    name="collection_status_enum",
    create_type=False,
)
license_source_enum = postgresql.ENUM(
    "individual",
    "collection",
    name="license_source_enum",
    create_type=False,
)
license_type_enum = postgresql.ENUM(
    "single_user",
    "team",
    "organizational",
    "enterprise",
    name="license_type_enum",
    create_type=False,
)


def upgrade() -> None:
    """Create collection tables and tag collection-sourced licenses."""
    bind = op.get_bind()
    collection_status_enum.create(bind, checkfirst=True)
    license_source_enum.create(bind, checkfirst=True)

    op.create_table(
        "framework_collections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("contributor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("bundle_price", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
        sa.Column(
            "status",
            collection_status_enum,
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "bundle_price > 0",
            name="ck_framework_collections_bundle_price_positive",
        ),
        sa.CheckConstraint(
            "currency = 'USD'",
            name="ck_framework_collections_currency_usd",
        ),
        sa.ForeignKeyConstraint(["contributor_id"], ["users.id"]),
    )
    op.create_index(
        "idx_framework_collections_contributor_status",
        "framework_collections",
        ["contributor_id", "status"],
    )

    op.create_table(
        "collection_frameworks",
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("framework_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["framework_collections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["framework_id"],
            ["frameworks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "collection_id",
            "framework_id",
            name="pk_collection_frameworks",
        ),
    )
    op.create_index(
        "idx_collection_frameworks_framework",
        "collection_frameworks",
        ["framework_id"],
    )

    op.create_table(
        "collection_purchase_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("framework_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("list_price_at_purchase", sa.Numeric(12, 2), nullable=False),
        sa.Column("license_type", license_type_enum, nullable=False),
        sa.Column(
            "already_owned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["collection_id"], ["framework_collections.id"]),
        sa.ForeignKeyConstraint(["framework_id"], ["frameworks.id"]),
        sa.UniqueConstraint(
            "transaction_id",
            "framework_id",
            name="uq_collection_purchase_snapshots_transaction_framework",
        ),
    )
    op.create_index(
        "idx_collection_purchase_snapshots_collection",
        "collection_purchase_snapshots",
        ["collection_id"],
    )
    op.create_index(
        "idx_collection_purchase_snapshots_framework",
        "collection_purchase_snapshots",
        ["framework_id"],
    )
    op.create_index(
        "idx_collection_purchase_snapshots_transaction",
        "collection_purchase_snapshots",
        ["transaction_id"],
    )

    op.create_table(
        "collection_earning_allocations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("framework_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("allocated_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "allocated_amount >= 0",
            name="ck_collection_earning_allocations_amount_nonnegative",
        ),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["collection_id"], ["framework_collections.id"]),
        sa.ForeignKeyConstraint(["framework_id"], ["frameworks.id"]),
    )
    op.create_index(
        "idx_collection_earning_allocations_transaction",
        "collection_earning_allocations",
        ["transaction_id"],
    )
    op.create_index(
        "idx_collection_earning_allocations_collection",
        "collection_earning_allocations",
        ["collection_id"],
    )
    op.create_index(
        "idx_collection_earning_allocations_framework",
        "collection_earning_allocations",
        ["framework_id"],
    )

    op.add_column(
        "licenses",
        sa.Column(
            "source",
            license_source_enum,
            nullable=False,
            server_default="individual",
        ),
    )
    op.add_column(
        "licenses",
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_licenses_collection_id_framework_collections",
        "licenses",
        "framework_collections",
        ["collection_id"],
        ["id"],
    )
    op.create_index("idx_licenses_collection", "licenses", ["collection_id"])


def downgrade() -> None:
    """Remove collection schema objects and license source metadata."""
    bind = op.get_bind()
    op.drop_index("idx_licenses_collection", table_name="licenses")
    op.drop_constraint(
        "fk_licenses_collection_id_framework_collections",
        "licenses",
        type_="foreignkey",
    )
    op.drop_column("licenses", "collection_id")
    op.drop_column("licenses", "source")

    op.drop_index(
        "idx_collection_earning_allocations_framework",
        table_name="collection_earning_allocations",
    )
    op.drop_index(
        "idx_collection_earning_allocations_collection",
        table_name="collection_earning_allocations",
    )
    op.drop_index(
        "idx_collection_earning_allocations_transaction",
        table_name="collection_earning_allocations",
    )
    op.drop_table("collection_earning_allocations")

    op.drop_index(
        "idx_collection_purchase_snapshots_transaction",
        table_name="collection_purchase_snapshots",
    )
    op.drop_index(
        "idx_collection_purchase_snapshots_framework",
        table_name="collection_purchase_snapshots",
    )
    op.drop_index(
        "idx_collection_purchase_snapshots_collection",
        table_name="collection_purchase_snapshots",
    )
    op.drop_table("collection_purchase_snapshots")

    op.drop_index(
        "idx_collection_frameworks_framework",
        table_name="collection_frameworks",
    )
    op.drop_table("collection_frameworks")

    op.drop_index(
        "idx_framework_collections_contributor_status",
        table_name="framework_collections",
    )
    op.drop_table("framework_collections")

    license_source_enum.drop(bind, checkfirst=True)
    collection_status_enum.drop(bind, checkfirst=True)
