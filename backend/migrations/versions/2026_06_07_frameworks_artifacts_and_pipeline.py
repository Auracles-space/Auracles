"""Create Phase 2 marketplace schema foundation.

Revision ID: 2026_06_07_0005
Revises: 2026_06_07_0004
Create Date: 2026-06-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_06_07_0005"
down_revision: str | Sequence[str] | None = "2026_06_07_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

framework_status_enum = postgresql.ENUM(
    "draft",
    "submitted",
    "processing",
    "pipeline_passed",
    "pipeline_failed",
    "published",
    "unpublished",
    "suspended",
    name="framework_status_enum",
    create_type=False,
)
scan_status_enum = postgresql.ENUM(
    "pending",
    "clean",
    "infected",
    "error",
    name="scan_status_enum",
    create_type=False,
)
processing_status_enum = postgresql.ENUM(
    "pending",
    "processing",
    "processed",
    "failed",
    "flagged_pii",
    "flagged_rarity",
    name="processing_status_enum",
    create_type=False,
)
org_size_enum = postgresql.ENUM(
    "startup",
    "small_business",
    "sme",
    "mid_market",
    "enterprise",
    name="org_size_enum",
    create_type=False,
)
license_type_enum = postgresql.ENUM(
    "single_user",
    "team",
    "enterprise",
    name="license_type_enum",
    create_type=False,
)
license_status_enum = postgresql.ENUM(
    "active",
    "expired",
    "revoked",
    name="license_status_enum",
    create_type=False,
)
change_type_enum = postgresql.ENUM(
    "fix",
    "improvement",
    "major",
    name="change_type_enum",
    create_type=False,
)
version_action_enum = postgresql.ENUM(
    "created",
    "published",
    "unpublished",
    "suspended",
    name="version_action_enum",
    create_type=False,
)


def upgrade() -> None:
    """Apply the marketplace schema foundation for Phase 2 Slice 1."""
    bind = op.get_bind()

    framework_status_enum.create(bind, checkfirst=True)
    scan_status_enum.create(bind, checkfirst=True)
    processing_status_enum.create(bind, checkfirst=True)
    org_size_enum.create(bind, checkfirst=True)
    license_type_enum.create(bind, checkfirst=True)
    license_status_enum.create(bind, checkfirst=True)
    change_type_enum.create(bind, checkfirst=True)
    version_action_enum.create(bind, checkfirst=True)

    op.create_table(
        "frameworks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("contributor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "version",
            sa.String(length=20),
            nullable=False,
            server_default="1.0.0",
        ),
        sa.Column(
            "status",
            framework_status_enum,
            nullable=False,
            server_default="draft",
        ),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("sector", sa.String(length=100), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("function", sa.String(length=100), nullable=True),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        # Later framework services keep this materialized for immutable FTS.
        sa.Column("tags_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("jurisdiction", sa.String(length=100), nullable=True),
        sa.Column("complexity", sa.SmallInteger(), nullable=True),
        sa.Column("org_size", org_size_enum, nullable=True),
        sa.Column("lifecycle_stage", sa.String(length=100), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
        sa.Column(
            "license_types",
            postgresql.ARRAY(license_type_enum),
            nullable=False,
        ),
        sa.Column("commercial_rights", sa.Text(), nullable=True),
        sa.Column("usage_restrictions", sa.Text(), nullable=True),
        sa.Column("preview_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("change_type", change_type_enum, nullable=True),
        sa.Column("last_pipeline_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "pipeline_failure_reasons",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("price > 0", name="ck_frameworks_price_positive"),
        sa.CheckConstraint(
            "complexity IS NULL OR complexity BETWEEN 1 AND 5",
            name="ck_frameworks_complexity_range",
        ),
        sa.ForeignKeyConstraint(["contributor_id"], ["users.id"]),
    )
    op.create_index("idx_frameworks_status", "frameworks", ["status"])
    op.create_index("idx_frameworks_contributor", "frameworks", ["contributor_id"])
    op.create_index("idx_frameworks_category", "frameworks", ["category"])
    op.create_index("idx_frameworks_sector", "frameworks", ["sector"])
    op.create_index("idx_frameworks_price", "frameworks", ["price"])
    op.create_index(
        "idx_frameworks_tags",
        "frameworks",
        ["tags"],
        postgresql_using="gin",
    )
    op.execute(
        """
        CREATE INDEX idx_frameworks_search
        ON frameworks
        USING gin (
            to_tsvector(
                'english',
                title || ' ' || description || ' ' || tags_text
            )
        )
        """
    )

    op.create_table(
        "artifacts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("framework_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("file_key", sa.Text(), nullable=False),
        sa.Column("clean_file_key", sa.Text(), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column(
            "scan_status",
            scan_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "processing_status",
            processing_status_enum,
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "pii_detected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "pii_review_needed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("minhash_signature", postgresql.BYTEA(), nullable=True),
        sa.Column("simhash", sa.BigInteger(), nullable=True),
        sa.Column("metadata_vector", postgresql.JSONB(), nullable=True),
        sa.Column("internal_rarity", sa.Numeric(5, 4), nullable=True),
        sa.Column("external_rarity", sa.Numeric(5, 4), nullable=True),
        sa.Column("rarity_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("nearest_match_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "file_size >= 0",
            name="ck_artifacts_file_size_nonnegative",
        ),
        sa.CheckConstraint(
            "internal_rarity IS NULL OR internal_rarity BETWEEN 0 AND 1",
            name="ck_artifacts_internal_rarity_range",
        ),
        sa.CheckConstraint(
            "external_rarity IS NULL OR external_rarity BETWEEN 0 AND 1",
            name="ck_artifacts_external_rarity_range",
        ),
        sa.CheckConstraint(
            "rarity_score IS NULL OR rarity_score BETWEEN 0 AND 1",
            name="ck_artifacts_rarity_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["framework_id"],
            ["frameworks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["nearest_match_id"], ["artifacts.id"]),
    )
    op.create_index("idx_artifacts_framework", "artifacts", ["framework_id"])
    op.create_index(
        "idx_artifacts_processing_status",
        "artifacts",
        ["processing_status"],
    )
    op.create_index("idx_artifacts_simhash", "artifacts", ["simhash"])
    op.create_foreign_key(
        "fk_frameworks_preview_artifact_id_artifacts",
        "frameworks",
        "artifacts",
        ["preview_artifact_id"],
        ["id"],
    )

    op.create_table(
        "framework_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("framework_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("change_type", change_type_enum, nullable=False),
        sa.Column("change_log", sa.Text(), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["framework_id"],
            ["frameworks.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "framework_id",
            "version",
            name="uq_framework_versions_framework_version",
        ),
    )
    op.create_index(
        "idx_framework_versions_framework",
        "framework_versions",
        ["framework_id"],
    )

    op.create_table(
        "artifact_pii_audit",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "pii_types_found",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "auto_redacted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "flagged_for_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
    )
    op.create_index(
        "idx_artifact_pii_audit_artifact",
        "artifact_pii_audit",
        ["artifact_id"],
    )

    op.create_table(
        "artifact_rarity_audit",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("internal_jaccard", sa.Numeric(5, 4), nullable=True),
        sa.Column("nearest_match_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "external_phrases_queried",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "external_hit_counts",
            postgresql.ARRAY(sa.Integer()),
            nullable=False,
            server_default=sa.text("'{}'::integer[]"),
        ),
        sa.Column("metadata_uplift", sa.Numeric(5, 4), nullable=True),
        sa.Column("blended_score", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "soft_fail_acknowledged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_ip", postgresql.INET(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "internal_jaccard IS NULL OR internal_jaccard BETWEEN 0 AND 1",
            name="ck_artifact_rarity_audit_internal_jaccard_range",
        ),
        sa.CheckConstraint(
            "metadata_uplift IS NULL OR metadata_uplift BETWEEN 0 AND 1",
            name="ck_artifact_rarity_audit_metadata_uplift_range",
        ),
        sa.CheckConstraint(
            "blended_score IS NULL OR blended_score BETWEEN 0 AND 1",
            name="ck_artifact_rarity_audit_blended_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["nearest_match_id"], ["artifacts.id"]),
    )
    op.create_index(
        "idx_artifact_rarity_audit_artifact",
        "artifact_rarity_audit",
        ["artifact_id"],
    )

    op.create_table(
        "licenses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("framework_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Phase 3 financials will add the transactions FK and make this required.
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", license_type_enum, nullable=False),
        sa.Column(
            "status",
            license_status_enum,
            nullable=False,
            server_default="active",
        ),
        sa.Column("version_at_grant", sa.String(length=20), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["framework_id"], ["frameworks.id"]),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"]),
        sa.UniqueConstraint(
            "framework_id",
            "operator_id",
            name="uq_licenses_owner",
        ),
    )
    op.create_index("idx_licenses_operator", "licenses", ["operator_id"])
    op.create_index("idx_licenses_framework", "licenses", ["framework_id"])

    op.create_table(
        "artifact_downloads",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("license_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column(
            "downloaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["license_id"], ["licenses.id"]),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index(
        "idx_artifact_downloads_license",
        "artifact_downloads",
        ["license_id"],
    )
    op.create_index(
        "idx_artifact_downloads_artifact",
        "artifact_downloads",
        ["artifact_id"],
    )

    op.create_table(
        "reviews",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("framework_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("license_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
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
        sa.CheckConstraint("score BETWEEN 1 AND 5", name="ck_reviews_score_range"),
        sa.ForeignKeyConstraint(
            ["framework_id"],
            ["frameworks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["operator_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["license_id"], ["licenses.id"]),
        sa.UniqueConstraint(
            "framework_id",
            "operator_id",
            name="uq_reviews_framework_operator",
        ),
    )
    op.create_index("idx_reviews_framework", "reviews", ["framework_id"])


def downgrade() -> None:
    """Remove the Phase 2 marketplace schema foundation."""
    bind = op.get_bind()

    op.drop_index("idx_reviews_framework", table_name="reviews")
    op.drop_table("reviews")

    op.drop_index("idx_artifact_downloads_artifact", table_name="artifact_downloads")
    op.drop_index("idx_artifact_downloads_license", table_name="artifact_downloads")
    op.drop_table("artifact_downloads")

    op.drop_index("idx_licenses_framework", table_name="licenses")
    op.drop_index("idx_licenses_operator", table_name="licenses")
    op.drop_table("licenses")

    op.drop_index(
        "idx_artifact_rarity_audit_artifact",
        table_name="artifact_rarity_audit",
    )
    op.drop_table("artifact_rarity_audit")

    op.drop_index("idx_artifact_pii_audit_artifact", table_name="artifact_pii_audit")
    op.drop_table("artifact_pii_audit")

    op.drop_index(
        "idx_framework_versions_framework",
        table_name="framework_versions",
    )
    op.drop_table("framework_versions")

    op.drop_constraint(
        "fk_frameworks_preview_artifact_id_artifacts",
        "frameworks",
        type_="foreignkey",
    )
    op.drop_index("idx_artifacts_simhash", table_name="artifacts")
    op.drop_index("idx_artifacts_processing_status", table_name="artifacts")
    op.drop_index("idx_artifacts_framework", table_name="artifacts")
    op.drop_table("artifacts")

    op.execute("DROP INDEX IF EXISTS idx_frameworks_search")
    op.drop_index("idx_frameworks_tags", table_name="frameworks")
    op.drop_index("idx_frameworks_price", table_name="frameworks")
    op.drop_index("idx_frameworks_sector", table_name="frameworks")
    op.drop_index("idx_frameworks_category", table_name="frameworks")
    op.drop_index("idx_frameworks_contributor", table_name="frameworks")
    op.drop_index("idx_frameworks_status", table_name="frameworks")
    op.drop_table("frameworks")

    version_action_enum.drop(bind, checkfirst=True)
    change_type_enum.drop(bind, checkfirst=True)
    license_status_enum.drop(bind, checkfirst=True)
    license_type_enum.drop(bind, checkfirst=True)
    org_size_enum.drop(bind, checkfirst=True)
    processing_status_enum.drop(bind, checkfirst=True)
    scan_status_enum.drop(bind, checkfirst=True)
    framework_status_enum.drop(bind, checkfirst=True)
