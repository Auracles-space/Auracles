"""Integrations module ORM models.

Stores per-user OAuth connections to external file providers
(Google Drive in v1). Tokens are Fernet-encrypted at rest and are
never exposed through any schema or log.

Maps to: Framework Artifact Connectors design (Phase A).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models.base import UpdatedAtMixin


class OAuthConnection(UpdatedAtMixin, Base):
    """A user's OAuth grant to an external file provider.

    One row per (user, provider): reconnecting replaces the stored
    tokens rather than adding a second connection.

    Attributes:
        provider: Provider key, e.g. ``google_drive``.
        provider_account_email: Display-only email of the connected account.
        access_token_encrypted: Fernet-encrypted OAuth access token.
        refresh_token_encrypted: Fernet-encrypted refresh token, if granted.
        token_expires_at: Access-token expiry used to refresh proactively.
        scopes: Space-separated granted scopes.
        status: ``active`` | ``revoked`` | ``reauth_required``.
    """

    __tablename__ = "oauth_connections"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", name="uq_oauth_connections_user_provider"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_account_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scopes: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'active'")
    )
