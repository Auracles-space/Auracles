"""Resend transactional email adapter."""

from loguru import logger

from app.core.config import get_settings


def send_verification_email(email: str, token: str) -> None:
    """Send a verification email through Resend when configured."""
    settings = get_settings()
    if settings.resend_api_key is None:
        logger.bind(module="auth", action="send_verification_email").info(
            "resend_not_configured",
            email=email,
        )
        return

    import resend

    resend.api_key = settings.resend_api_key.get_secret_value()
    resend.Emails.send(
        {
            "from": settings.resend_from_address,
            "to": email,
            "subject": "Verify your Auracles account",
            "html": f"<p>Use this verification token: <code>{token}</code></p>",
        }
    )
