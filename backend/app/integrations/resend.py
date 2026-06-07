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


def send_password_reset_email(email: str, token: str) -> None:
    """Send a password reset email through Resend when configured."""
    settings = get_settings()
    if settings.resend_api_key is None:
        logger.bind(module="auth", action="send_password_reset_email").info(
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
            "subject": "Reset your Auracles password",
            "html": f"<p>Use this password reset token: <code>{token}</code></p>",
        }
    )


def send_new_device_email(
    email: str,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """Send a new-device notification email through Resend when configured."""
    settings = get_settings()
    if settings.resend_api_key is None:
        logger.bind(module="auth", action="send_new_device_email").info(
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
            "subject": "New Auracles login",
            "html": (
                "<p>Your Auracles account was accessed from a new device.</p>"
                f"<p>IP: <code>{ip or 'unknown'}</code></p>"
                f"<p>User agent: <code>{user_agent or 'unknown'}</code></p>"
            ),
        }
    )
