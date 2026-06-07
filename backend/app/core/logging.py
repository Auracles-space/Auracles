"""Logging configuration and HTTP request middleware.

Configures Loguru with colored output for local development and JSON
serialization for production (Render log drain / CloudWatch). Provides
`RequestLoggingMiddleware`, which assigns a UUID `request_id` to each
incoming request and emits structured start/completion logs.

Maps to: CLAUDE.md "Logging Standards" section.
"""

import sys
import time
import uuid
from collections.abc import Awaitable, Callable

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


def configure_logging(log_format: str) -> None:
    """Configure Loguru sinks for local text logs or production JSON logs."""
    logger.remove()
    if log_format == "json":
        logger.add(sys.stdout, serialize=True)
        return

    logger.add(
        sys.stdout,
        colorize=True,
        format=(
            "<dim>{time:YYYY-MM-DD HH:mm:ss}</dim> | <level>{level}</level> | "
            "{extra[module]}.{extra[action]} | {message}"
        ),
    )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Attach a request ID and structured lifecycle logs to each HTTP request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process a single HTTP request, emitting structured logs.

        Generates a UUID `request_id`, contextualises all downstream logs
        with it, logs `request_started` before handler dispatch, and
        `request_completed` with status code and duration after.

        Args:
            request: Incoming Starlette request.
            call_next: Coroutine that invokes the next middleware/handler.

        Returns:
            The downstream response, with `X-Request-ID` header attached.
        """
        request_id = str(uuid.uuid4())
        started_at = time.perf_counter()
        with logger.contextualize(request_id=request_id):
            logger.bind(
                module="core",
                action="request_started",
                method=request.method,
                path=request.url.path,
            ).info("request_started")
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            response.headers["X-Request-ID"] = request_id
            logger.bind(
                module="core",
                action="request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            ).info("request_completed")
            return response
