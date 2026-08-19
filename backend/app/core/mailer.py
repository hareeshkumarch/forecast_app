"""Sending mail over plain SMTP.

No provider SDK on purpose. SMTP is what a free Gmail app password speaks, and
a Brevo or Resend free tier, and a paid service later — swapping between them
is configuration rather than a code change, which matters when the deployment
budget is nothing.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmailNotSent(Exception):
    pass


def _build(to: list[str], subject: str, text: str, html: str | None) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def _send_blocking(message: EmailMessage) -> None:
    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
    ) as server:
        if settings.smtp_starttls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


async def send(to: list[str], subject: str, text: str, html: str | None = None) -> bool:
    """Send, and say whether it went. Never raises into a request.

    A failure here must not fail whatever the caller was doing: somebody
    signing in has done nothing wrong if the mail server is down, and turning
    that into a 500 would lock out the very people the mail was about. The
    request is recorded either way, so an administrator can still find it.
    """
    recipients = [address for address in to if address]
    if not recipients:
        return False
    if not settings.smtp_configured:
        logger.warning("No SMTP host is configured, so '%s' was not sent.", subject)
        return False

    try:
        await asyncio.to_thread(_deliver, recipients, subject, text, html)
    except Exception as exc:
        logger.warning("Could not send '%s': %s: %s", subject, type(exc).__name__, exc)
        return False
    return True


def _deliver(to: list[str], subject: str, text: str, html: str | None) -> None:
    _send_blocking(_build(to, subject, text, html))
