"""Resend transactional email adapter.

Handles formatting and dispatching transactional/lifecycle emails
via the Resend API with custom brand-aligned Bento Box layouts.
"""

from html import escape

from loguru import logger

from app.core.config import get_settings


def _render_email_html(
    title: str,
    content_html: str,
    action_url: str | None = None,
    action_text: str | None = None,
) -> str:
    """Wrap email content in a responsive, brand-aligned Bento HTML layout."""
    settings = get_settings()
    origins = settings.cors_origin_list
    frontend_url = origins[0] if origins else "http://localhost:3000"
    logo_url = f"{frontend_url}/images/logo-text-black.png"

    action_btn_html = ""
    if action_url and action_text:
        action_btn_html = f"""
        <div style="margin: 28px 0; text-align: center;">
            <a href="{escape(action_url)}" style="background-color: #000000; color: #FFFFFB; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 14px; font-weight: 600; text-decoration: none; border-radius: 12px; padding: 14px 28px; display: inline-block; text-align: center;">
                {escape(action_text)}
            </a>
        </div>
        """

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape(title)}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #FFFFFB; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #0A0A0A; -webkit-font-smoothing: antialiased;">
    <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #FFFFFB; padding: 40px 20px;">
        <tr>
            <td align="center">
                <!-- Bento box container card -->
                <table width="100%" max-width="560" border="0" cellspacing="0" cellpadding="0" style="max-width: 560px; background-color: #F8F6F2; border: 1px solid #EAE5DC; border-radius: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.02); overflow: hidden;">
                    <tr>
                        <td style="padding: 40px;">
                            <!-- Header Logo -->
                            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom: 32px;">
                                <tr>
                                    <td>
                                        <a href="{escape(frontend_url)}" style="text-decoration: none;">
                                            <img src="{escape(logo_url)}" alt="Auracles Logo" style="height: 28px; width: auto; display: block; border: 0; object-fit: contain;">
                                        </a>
                                    </td>
                                </tr>
                            </table>
                            
                            <!-- Email Title -->
                            <h1 style="font-size: 20px; font-weight: 600; line-height: 1.4; margin: 0 0 16px 0; color: #0A0A0A; letter-spacing: -0.01em;">
                                {escape(title)}
                            </h1>
                            
                            <!-- Email Content -->
                            <div style="font-size: 14px; line-height: 1.6; color: #374151; margin: 0;">
                                {content_html}
                            </div>
                            
                            <!-- Optional CTA button -->
                            {action_btn_html}
                            
                            <!-- Divider -->
                            <hr style="border: 0; border-top: 1px solid #EAE5DC; margin: 32px 0 24px 0;">
                            
                            <!-- Footer -->
                            <table width="100%" border="0" cellspacing="0" cellpadding="0">
                                <tr>
                                    <td style="font-size: 11px; line-height: 1.5; color: #6B7280;">
                                        <p style="margin: 0 0 8px 0; font-weight: 600; color: #0A0A0A;">Auracles</p>
                                        <p style="margin: 0 0 12px 0;">The Professional Knowledge Marketplace.</p>
                                        <p style="margin: 0;">If you did not request this email, you can safely ignore it.</p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""


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

    content_html = f"""
    <p style="margin: 0 0 20px 0;">Welcome to Auracles! Please verify your account to unlock full access to the knowledge marketplace.</p>
    <p style="margin: 0 0 8px 0; font-weight: 600;">Your verification token:</p>
    <div style="background-color: #F1EDE6; border: 1px solid #EAE5DC; border-radius: 12px; padding: 16px; font-family: monospace; font-size: 24px; font-weight: bold; color: #C74634; text-align: center; letter-spacing: 4px;">
        {escape(token)}
    </div>
    """
    html = _render_email_html(
        title="Verify your Auracles account",
        content_html=content_html,
    )

    resend.Emails.send(
        {
            "from": settings.resend_from_address,
            "to": email,
            "subject": "Verify your Auracles account",
            "html": html,
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

    content_html = f"""
    <p style="margin: 0 0 20px 0;">We received a request to reset your Auracles account password. If you requested this, please use the token below to complete the reset.</p>
    <p style="margin: 0 0 8px 0; font-weight: 600;">Your password reset token:</p>
    <div style="background-color: #F1EDE6; border: 1px solid #EAE5DC; border-radius: 12px; padding: 16px; font-family: monospace; font-size: 24px; font-weight: bold; color: #C74634; text-align: center; letter-spacing: 4px;">
        {escape(token)}
    </div>
    """
    html = _render_email_html(
        title="Reset your Auracles password",
        content_html=content_html,
    )

    resend.Emails.send(
        {
            "from": settings.resend_from_address,
            "to": email,
            "subject": "Reset your Auracles password",
            "html": html,
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

    content_html = f"""
    <p style="margin: 0 0 20px 0;">We received a request to change your account email address. Please use the verification token below to confirm this change.</p>
    <p style="margin: 0 0 8px 0; font-weight: 600;">Your email-change token:</p>
    <div style="background-color: #F1EDE6; border: 1px solid #EAE5DC; border-radius: 12px; padding: 16px; font-family: monospace; font-size: 24px; font-weight: bold; color: #C74634; text-align: center; letter-spacing: 4px;">
        {escape(token)}
    </div>
    """
    html = _render_email_html(
        title="Confirm your new Auracles email",
        content_html=content_html,
    )

    resend.Emails.send(
        {
            "from": settings.resend_from_address,
            "to": email,
            "subject": "Confirm your new Auracles email",
            "html": html,
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

    content_html = f"""
    <p style="margin: 0 0 16px 0;">Your Auracles account was accessed from a new device or browser environment.</p>
    <div style="background-color: #F1EDE6; border: 1px solid #EAE5DC; border-radius: 12px; padding: 16px; font-family: sans-serif; font-size: 13px; line-height: 1.6; color: #374151;">
        <p style="margin: 0 0 8px 0;"><strong>IP Address:</strong> <code>{escape(ip or "unknown")}</code></p>
        <p style="margin: 0;"><strong>User Agent:</strong> <code>{escape(user_agent or "unknown")}</code></p>
    </div>
    <p style="margin: 16px 0 0 0; font-size: 12px; color: #DC2626;">If this login was not performed by you, please reset your password immediately or contact platform support.</p>
    """
    html = _render_email_html(
        title="New login to your account",
        content_html=content_html,
    )

    resend.Emails.send(
        {
            "from": settings.resend_from_address,
            "to": email,
            "subject": "New Auracles login",
            "html": html,
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

    content_html = f"<p style='margin: 0; white-space: pre-wrap;'>{escape(body)}</p>"
    html = _render_email_html(
        title=title,
        content_html=content_html,
        action_url=link,
        action_text="Open in Auracles" if link else None,
    )

    resend.Emails.send(
        {
            "from": settings.resend_from_address,
            "to": email,
            "subject": title,
            "html": html,
        }
    )
