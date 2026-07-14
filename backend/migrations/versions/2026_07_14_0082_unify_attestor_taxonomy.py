"""Unify attestor taxonomy with framework taxonomy.

Renames the attestor ``framework_categories`` column to ``functions`` on both
application and profile tables, and remaps existing attestor rows from the
legacy vocabulary to the canonical framework slugs used across the marketplace.
Unmapped jurisdiction free text is left as-is and logged for manual cleanup.

Revision ID: 2026_07_14_0082
Revises: 2026_07_13_0081
Create Date: 2026-07-14
"""

from __future__ import annotations

from alembic import op
from loguru import logger
from sqlalchemy import text

from app.shared.taxonomy import JURISDICTIONS
from migrations.attestor_taxonomy_remap import (
    FUNCTION_MAP,
    JURISDICTION_MAP,
    SECTOR_MAP,
    _remap_array,
)

revision = "2026_07_14_0082"
down_revision = "2026_07_13_0081"
branch_labels = None
depends_on = None

_TABLES = ("org_attestor_applications", "org_attestor_profiles")


def _reverse(mapping: dict[str, str]) -> dict[str, str]:
    """Reverse a one-to-one remap table for downgrade remapping."""
    return {value: key for key, value in mapping.items()}


def _remap_rows(*, function_col: str, forward: bool) -> None:
    """Remap sector, function, and jurisdiction arrays on both attestor tables."""
    bind = op.get_bind()
    sector_map = SECTOR_MAP if forward else _reverse(SECTOR_MAP)
    function_map = FUNCTION_MAP if forward else _reverse(FUNCTION_MAP)
    jurisdiction_map = JURISDICTION_MAP if forward else _reverse(JURISDICTION_MAP)

    for table in _TABLES:
        rows = bind.execute(
            text(
                f"SELECT id, sectors, {function_col}, jurisdictions "
                f"FROM {table}"
            )
        ).mappings()
        for row in rows:
            existing_jurisdictions = list(row["jurisdictions"] or [])
            # Flag only values that remain non-canonical after remapping;
            # already-canonical slugs pass through and must not be logged.
            unmapped = [
                value
                for value in existing_jurisdictions
                if forward
                and JURISDICTION_MAP.get(value, value) not in JURISDICTIONS
            ]
            if unmapped:
                logger.bind(
                    module="migration",
                    action="unify_attestor_taxonomy",
                    table=table,
                    row_id=str(row["id"]),
                ).warning(f"unmapped_jurisdictions values={unmapped}")

            bind.execute(
                text(
                    f"UPDATE {table} "
                    f"SET sectors = :sectors, {function_col} = :functions, "
                    "jurisdictions = :jurisdictions "
                    "WHERE id = :row_id"
                ),
                {
                    "sectors": _remap_array(list(row["sectors"] or []), sector_map),
                    "functions": _remap_array(
                        list(row[function_col] or []),
                        function_map,
                    ),
                    "jurisdictions": _remap_array(
                        existing_jurisdictions,
                        jurisdiction_map,
                    ),
                    "row_id": row["id"],
                },
            )


def upgrade() -> None:
    """Rename the attestor taxonomy column, then remap legacy values."""
    for table in _TABLES:
        op.alter_column(table, "framework_categories", new_column_name="functions")
    _remap_rows(function_col="functions", forward=True)


def downgrade() -> None:
    """Reverse remapped values, then rename the column back."""
    _remap_rows(function_col="functions", forward=False)
    for table in _TABLES:
        op.alter_column(table, "functions", new_column_name="framework_categories")
