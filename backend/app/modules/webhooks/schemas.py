"""Pydantic schemas for payment webhook responses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class WebhookIngestResponse(BaseModel):
    """Small acknowledgement returned to payment providers."""

    received: bool
    status: Literal["processed", "received", "duplicate"]
