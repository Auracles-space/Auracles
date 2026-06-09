"""Resend transactional email adapter."""

from html import escape

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


def send_email_change_verification(email: str, token: str) -> None:
    """Send a new-email verification message through Resend when configured."""
    settings = get_settings()
    if settings.resend_api_key is None:
        logger.bind(module="settings", action="send_email_change_verification").info(
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
            "subject": "Confirm your new Auracles email",
            "html": f"<p>Use this email-change token: <code>{token}</code></p>",
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


def send_project_notification_email(
    *,
    email: str,
    title: str,
    body: str,
    link: str | None,
) -> None:
    """Send a project notification email through Resend when configured."""
    settings = get_settings()
    if settings.resend_api_key is None:
        logger.bind(
            module="notifications",
            action="send_project_notification_email",
        ).info(
            "resend_not_configured",
            email=email,
        )
        return

    import resend

    resend.api_key = settings.resend_api_key.get_secret_value()
    action_html = (
        f"<p><a href='{escape(link, quote=True)}'>Open in Auracles</a></p>"
        if link
        else ""
    )
    resend.Emails.send(
        {
            "from": settings.resend_from_address,
            "to": email,
            "subject": title,
            "html": f"<p>{escape(body)}</p>{action_html}",
        }
    )
