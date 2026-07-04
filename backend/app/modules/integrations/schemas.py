"""Pydantic schemas for the integrations (connectors) API.

Response models expose connection metadata only — encrypted tokens never
appear in any schema.

Maps to: Framework Artifact Connectors design (Phase A).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ConnectorStatusItem(BaseModel):
    """Connection status for one supported provider."""

    provider: str
    connected: bool
    connection_id: UUID | None = None
    status: str | None = None
    account_email: str | None = None


class ConnectorsResponse(BaseModel):
    """Connection status for every supported provider."""

    connectors: list[ConnectorStatusItem]


class ConnectorConnectResponse(BaseModel):
    """The provider consent URL the browser should navigate to."""

    authorization_url: str


class ConnectorFileItem(BaseModel):
    """One importable file in the contributor's connected Drive."""

    id: str
    name: str
    mime_type: str
    size: int | None = None
    modified_time: datetime | None = None
    icon_link: str | None = None
    importable: bool


class ConnectorFilesResponse(BaseModel):
    """One page of Drive files plus the pagination cursor."""

    files: list[ConnectorFileItem]
    next_page_token: str | None = None
