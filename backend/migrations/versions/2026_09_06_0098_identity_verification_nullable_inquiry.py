"""Allow identity_verifications.inquiry_id to be null until Persona mints it.

Identity verification now starts with a Persona hosted-flow link rather than a
server-side `POST /inquiries`: the Auracles Persona environment does not have
`inquiries.create.api` enabled, and this is an environment-level gate that no
API key can satisfy — three separate sandbox keys were refused identically
(2026-09-06). Persona mints the inquiry when the user lands on the link.

That means the inquiry id does not exist when the row is written. The row is
matched by `user_id` in the interim, and `inquiry_id` is backfilled from the
`reference-id` carried on the first webhook (or the on-return sync).

The unique constraint stays: Postgres allows many NULLs under one, so uniqueness
still holds for every inquiry that has actually been minted.

Backwards-compatible in both directions for the deployed version — relaxing a
NOT NULL cannot break readers, and the downgrade is safe as long as no
hosted-flow row is still awaiting its id, which is why it clears them.

Maps to: identity verification design (2026-06-24); FR-SET KYC.

Revision ID: 2026_09_06_0098
Revises: 2026_08_29_0097
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_09_06_0098"
down_revision: str | None = "2026_08_29_0097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the NOT NULL on inquiry_id."""
    op.alter_column(
        "identity_verifications",
        "inquiry_id",
        existing_type=sa.String(length=255),
        nullable=True,
    )


def downgrade() -> None:
    """Restore NOT NULL, discarding rows that never received an inquiry id.

    A row with a null inquiry_id is a verification the user started but never
    began at Persona, so it carries no decision and nothing is lost. Leaving
    them in place would make the ALTER fail.
    """
    op.execute(
        sa.text(
            "DELETE FROM identity_verifications WHERE inquiry_id IS NULL"
        )
    )
    op.alter_column(
        "identity_verifications",
        "inquiry_id",
        existing_type=sa.String(length=255),
        nullable=False,
    )
