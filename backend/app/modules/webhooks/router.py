"""Payment provider webhook routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.webhooks import service
from app.modules.webhooks.schemas import WebhookIngestResponse

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/stripe", response_model=WebhookIngestResponse)
async def ingest_stripe_webhook(
    request: Request,
    db: DatabaseSession,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> WebhookIngestResponse:
    """Verify and dispatch a Stripe webhook event."""
    raw_body = await request.body()
    return await service.handle_stripe_webhook(
        db=db,
        payload=raw_body,
        signature_header=stripe_signature,
    )
