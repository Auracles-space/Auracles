"""Resend transactional email adapter.

Handles formatting and dispatching transactional/lifecycle emails
via the Resend API with custom brand-aligned Bento Box layouts.
"""

from html import escape
from typing import TYPE_CHECKING
from urllib.parse import quote

from loguru import logger

from app.core.config import get_settings

if TYPE_CHECKING:
    from resend import Emails


class EmailDeliveryError(Exception):
    """Base class for classified Resend delivery failures."""


class TransientEmailError(EmailDeliveryError):
    """A retryable provider failure (per-second rate limit, 5xx, network)."""


class PermanentEmailError(EmailDeliveryError):
    """A non-retryable provider failure (daily-quota exhaustion, validation).

    Retrying these wastes attempts and, for quota errors, re-burns the daily
    allowance the moment it resets. The caller must log and stop, not retry.
    """


# Substrings (matched case-insensitively against the provider error message)
# that mark a failure as permanent. Everything else is treated as transient so
# genuine blips still retry. The per-second limit ("requests per second") is
# deliberately absent here — it is transient and should retry with backoff.
_PERMANENT_MARKERS = (
    "daily email sending quota",
    "exceeded your daily",
    "validation_error",
    "invalid `to`",
    "invalid `from`",
    "not a valid email",
)


def classify_email_error(exc: Exception) -> EmailDeliveryError:
    """Classify a raw provider exception as transient or permanent.

    Args:
        exc: The exception raised by the Resend SDK (or a network error).

    Returns:
        A ``PermanentEmailError`` if the message matches a known non-retryable
        marker, otherwise a ``TransientEmailError``.
    """
    message = str(exc)
    lowered = message.lower()
    if any(marker in lowered for marker in _PERMANENT_MARKERS):
        return PermanentEmailError(message)
    return TransientEmailError(message)


def _dispatch(payload: "Emails.SendParams") -> None:
    """Send a prepared payload through Resend, classifying any failure.

    The caller is responsible for setting ``resend.api_key`` and skipping the
    send entirely when Resend is not configured.

    Args:
        payload: The Resend ``Emails.send`` payload (from/to/subject/html).

    Raises:
        PermanentEmailError: Provider rejected the send non-retryably.
        TransientEmailError: Provider/network failure worth retrying.
    """
    import resend

    try:
        resend.Emails.send(payload)
    except Exception as exc:  # noqa: BLE001 - re-raised as a classified error
        raise classify_email_error(exc) from exc


def _delivery_disabled(
    module: str,
    action: str,
    email: str,
    **fields: object,
) -> bool:
    """Log the lifecycle email and skip sending when delivery is disabled.

    When ``EMAIL_SEND_ENABLED`` is false (local/dev), the email is logged with
    its identifying fields (e.g. the verification token) instead of calling
    Resend, so a flow can be completed without an inbox or burning the daily
    quota. Production leaves the flag at its default ``True`` and always sends.

    Args:
        module: Logging module tag (e.g. ``"auth"``).
        action: Logging action tag (e.g. ``"send_verification_email"``).
        email: Recipient address (logged, not sent).
        **fields: Extra dev-relevant fields to log (token, link, ip, ...).

    Returns:
        True when delivery is disabled (caller must return without sending),
        False when the email should be delivered through Resend.
    """
    if get_settings().email_send_enabled:
        return False
    # Inline the fields into the message: the dev (text) log format renders only
    # {message} and drops bound extras, so the token must live in the message to
    # be retrievable without switching to JSON logs.
    parts = [f"email={email}", *(f"{key}={value}" for key, value in fields.items())]
    logger.bind(module=module, action=action).info(
        "email_delivery_disabled " + " ".join(parts)
    )
    return True


def _frontend_base_url() -> str:
    """Return the app's public base URL for building email links.

    Delegates to the shared setting so email links and provider redirect
    targets (Paystack's `callback_url`) can never disagree about which origin
    the browser is on.
    """
    return get_settings().frontend_base_url


def _render_email_html(
    title: str,
    content_html: str,
    action_url: str | None = None,
    action_text: str | None = None,
) -> str:
    """Wrap email content in a responsive, brand-aligned Bento HTML layout."""
    frontend_url = _frontend_base_url()
    # Assets and action links deliberately may diverge: links carry tokens and
    # must target the app origin even before it serves; the logo just needs a
    # host that exists (staging points EMAIL_ASSET_BASE_URL at the live apex).
    asset_base = get_settings().email_asset_base_url or frontend_url
    logo_url = f"{asset_base}/images/logo-text-black.png"

    # Notification links are stored as app paths; a relative href in an email
    # resolves against no host, so the renderer pins every action to the
    # frontend origin here rather than trusting each sender to remember.
    if action_url and action_url.startswith("/"):
        action_url = f"{frontend_url}{action_url}"

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


def send_verification_email(
    email: str, token: str, next_path: str | None = None
) -> None:
    """Send a verification email through Resend when configured.

    Args:
        email: Recipient address.
        token: One-time verification token.
        next_path: Optional in-app path appended as ``&next=`` so the
            verification page can send the user on (an invitation, say).
    """
    settings = get_settings()
    verify_url = f"{_frontend_base_url()}/verify-email?token={quote(token, safe='')}"
    if next_path:
        verify_url = f"{verify_url}&next={quote(next_path, safe='')}"
    if _delivery_disabled(
        "auth", "send_verification_email", email, token=token, link=verify_url
    ):
        return
    if settings.resend_api_key is None:
        logger.bind(module="auth", action="send_verification_email").info(
            "resend_not_configured",
            email=email,
        )
        return

    import resend

    resend.api_key = settings.resend_api_key.get_secret_value()

    content_html = f"""
    <p style="margin: 0 0 20px 0;">Welcome to Auracles! Click the button below to verify your account and unlock full access to the knowledge marketplace.</p>
    <p style="margin: 0 0 8px 0; font-size: 13px; color: #6B7280;">If the button does not work, paste this token on the verification page:</p>
    <div style="background-color: #F1EDE6; border: 1px solid #EAE5DC; border-radius: 12px; padding: 16px; font-family: monospace; font-size: 13px; font-weight: bold; color: #C74634; text-align: center; word-break: break-all;">
        {escape(token)}
    </div>
    """
    html = _render_email_html(
        title="Verify your Auracles account",
        content_html=content_html,
        action_url=verify_url,
        action_text="Verify email",
    )

    _dispatch(
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
    reset_url = f"{_frontend_base_url()}/reset-password?token={quote(token, safe='')}"
    if _delivery_disabled(
        "auth", "send_password_reset_email", email, token=token, link=reset_url
    ):
        return
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
        action_url=reset_url,
        action_text="Reset password",
    )

    _dispatch(
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
    if _delivery_disabled(
        "settings", "send_email_change_verification", email, token=token
    ):
        return
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

    _dispatch(
        {
            "from": settings.resend_from_address,
            "to": email,
            "subject": "Confirm your new Auracles email",
            "html": html,
        }
    )


def send_email_change_alert(email: str, new_email: str) -> None:
    """Notify the current (old) address that an email change was requested.

    Sent to the existing address so the account owner can react if the change
    was not initiated by them (account-takeover early warning).
    """
    settings = get_settings()
    if _delivery_disabled(
        "settings", "send_email_change_alert", email, new_email=new_email
    ):
        return
    if settings.resend_api_key is None:
        logger.bind(module="settings", action="send_email_change_alert").info(
            "resend_not_configured",
            email=email,
        )
        return

    import resend

    resend.api_key = settings.resend_api_key.get_secret_value()

    content_html = f"""
    <p style="margin: 0 0 16px 0;">A request was made to change the email address on your Auracles account to <strong>{escape(new_email)}</strong>.</p>
    <p style="margin: 0 0 16px 0;">The change only takes effect after the new address is confirmed. Your current address stays active until then.</p>
    <p style="margin: 16px 0 0 0; font-size: 12px; color: #DC2626;">If you did not request this, reset your password immediately and contact platform support — your account may be compromised.</p>
    """
    html = _render_email_html(
        title="Email change requested on your account",
        content_html=content_html,
    )

    _dispatch(
        {
            "from": settings.resend_from_address,
            "to": email,
            "subject": "Security alert: email change requested",
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
    if _delivery_disabled(
        "auth", "send_new_device_email", email, ip=ip, user_agent=user_agent
    ):
        return
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

    _dispatch(
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
    if _delivery_disabled(
        "notifications", "send_project_notification_email", email, link=link
    ):
        return
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

    _dispatch(
        {
            "from": settings.resend_from_address,
            "to": email,
            "subject": title,
            "html": html,
        }
    )


def send_org_invitation_email(
    *,
    email: str,
    org_name: str,
    role: str,
    token: str,
) -> None:
    """Send an organization invitation email.

    In local/dev (``EMAIL_SEND_ENABLED`` false) the accept link is logged
    instead of sent, mirroring the password-reset flow so an invite can be
    completed without an inbox. Production leaves the flag ``True`` and never
    logs the link.

    Args:
        email: Invitation recipient address.
        org_name: Organization display name.
        role: Invited organization role.
        token: Raw invitation token for the accept link.
    """
    settings = get_settings()
    accept_url = f"{_frontend_base_url()}/org-invitations/{quote(token, safe='')}"
    if _delivery_disabled(
        "organizations", "send_org_invitation_email", email, link=accept_url
    ):
        return
    if settings.resend_api_key is None:
        logger.bind(module="organizations", action="send_org_invitation_email").info(
            "resend_not_configured"
        )
        return

    import resend

    resend.api_key = settings.resend_api_key.get_secret_value()

    content_html = f"""
    <p style="margin: 0 0 16px 0;">You've been invited to join <strong>{escape(org_name)}</strong> on Auracles.</p>
    <p style="margin: 0 0 16px 0;">If you accept, you'll join the organization as <strong>{escape(role)}</strong>.</p>
    <p style="margin: 0;">Invitation links expire after 7 days.</p>
    """
    html = _render_email_html(
        title=f"You're invited to join {org_name} on Auracles",
        content_html=content_html,
        action_url=accept_url,
        action_text="Review invitation",
    )

    _dispatch(
        {
            "from": settings.resend_from_address,
            "to": email,
            "subject": f"You're invited to join {org_name} on Auracles",
            "html": html,
        }
    )


def send_kyc_verdict_email(*, email: str, verified: bool) -> None:
    """Tell a user the outcome of their identity verification.

    Manual review is asynchronous and invisible from the user's side: they
    upload a document and then have no signal that anyone looked at it. The
    in-app notification only reaches someone already on the site, so without
    this the verdict effectively never arrives.

    Rejection copy deliberately does not carry the admin's review notes. Those
    are written for the audit trail, not for the applicant, and the usual cause
    is simply an unreadable photo.

    Args:
        email: The applicant's address.
        verified: True when the identity was accepted, False when rejected.
    """
    settings = get_settings()
    action_url = f"{_frontend_base_url()}/settings/kyc"
    if _delivery_disabled("settings", "send_kyc_verdict_email", email, link=action_url):
        return
    if settings.resend_api_key is None:
        logger.bind(module="settings", action="send_kyc_verdict_email").info(
            "resend_not_configured"
        )
        return

    import resend

    resend.api_key = settings.resend_api_key.get_secret_value()

    if verified:
        subject = "Your identity is verified"
        content_html = (
            '<p style="margin: 0 0 16px 0;">Your identity has been verified.</p>'
            '<p style="margin: 0;">Payouts and paid work are now open to you. '
            "Nothing further is needed.</p>"
        )
        action_text = "Go to your account"
    else:
        subject = "Your identity verification needs attention"
        content_html = (
            '<p style="margin: 0 0 16px 0;">We could not verify your identity '
            "from the document you submitted.</p>"
            '<p style="margin: 0;">The most common reason is a photo that is '
            "blurred, cropped, or too dark to read. You can submit another "
            "document at any time.</p>"
        )
        action_text = "Submit a new document"

    _dispatch(
        {
            "from": settings.resend_from_address,
            "to": email,
            "subject": subject,
            "html": _render_email_html(
                title=subject,
                content_html=content_html,
                action_url=action_url,
                action_text=action_text,
            ),
        }
    )
