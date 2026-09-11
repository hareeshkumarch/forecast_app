from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


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


def _deliver(to: list[str], subject: str, text: str, html: str | None) -> None:
    _send_blocking(_build(to, subject, text, html))


BACKOFF_SECONDS = (60, 300, 1_800, 7_200)
MAX_ATTEMPTS = len(BACKOFF_SECONDS) + 1

BATCH = 20


def queue(
    session: AsyncSession,
    to: list[str],
    subject: str,
    text: str,
    html: str | None = None,
) -> None:
    from app.models.entities import MailOutbox

    recipients = [address.strip() for address in to if address and address.strip()]
    if not recipients:
        return
    session.add(
        MailOutbox(
            recipients=", ".join(recipients),
            subject=subject,
            body_text=text,
            body_html=html,
        )
    )


async def flush_outbox(session: AsyncSession) -> tuple[int, int]:
    from datetime import timedelta

    from sqlalchemy import select

    from app.database.base import utcnow
    from app.models.entities import MailOutbox

    due = (
        select(MailOutbox)
        .where(MailOutbox.status == "pending", MailOutbox.next_attempt_at <= utcnow())
        .order_by(MailOutbox.next_attempt_at)
        .limit(BATCH)
    )
    rows = list((await session.scalars(due)).all())
    if rows and not settings.smtp_configured:
        logger.warning("%d message(s) are waiting, but no SMTP host is configured.", len(rows))
        return 0, 0

    sent = failed = 0
    for row in rows:
        recipients = [address.strip() for address in row.recipients.split(",") if address.strip()]
        try:
            await asyncio.to_thread(_deliver, recipients, row.subject, row.body_text, row.body_html)
        except Exception as exc:
            row.attempts += 1
            row.last_error = f"{type(exc).__name__}: {exc}"[:500]
            if row.attempts >= MAX_ATTEMPTS:
                row.status = "failed"
                failed += 1
                logger.error(
                    "Giving up on '%s' to %s after %d attempts: %s",
                    row.subject,
                    row.recipients,
                    row.attempts,
                    row.last_error,
                )
            else:
                wait = BACKOFF_SECONDS[row.attempts - 1]
                row.next_attempt_at = utcnow() + timedelta(seconds=wait)
                logger.warning(
                    "Could not send '%s' (attempt %d), retrying in %ds: %s",
                    row.subject,
                    row.attempts,
                    wait,
                    row.last_error,
                )
        else:
            row.status = "sent"
            row.sent_at = utcnow()
            row.attempts += 1
            sent += 1
        await session.commit()

    return sent, failed
