"""FastAPI router for the public pre-launch waitlist."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.network import client_ip
from app.core.redis import get_redis
from app.modules.waitlist import service
from app.modules.waitlist.schemas import WaitlistJoinRequest, WaitlistJoinResponse

router = APIRouter(prefix="/waitlist", tags=["Waitlist"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]


@router.post(
    "",
    response_model=WaitlistJoinResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Join the pre-launch waitlist",
    description=(
        "Record a marketing waitlist email. Public and unauthenticated. "
        "Idempotent: an already-recorded email returns 200 with "
        "already_joined=true instead of creating a duplicate."
    ),
)
async def join_waitlist(
    payload: WaitlistJoinRequest,
    request: Request,
    response: Response,
    db: DatabaseSession,
    redis: RedisClient,
) -> WaitlistJoinResponse:
    """Add an email to the waitlist, deduplicating repeat submissions."""
    result = await service.join_waitlist(
        db=db,
        redis=redis,
        request=payload,
        ip=client_ip(request),
    )
    if result.already_joined:
        response.status_code = status.HTTP_200_OK
    return result
