"""Sending mail over plain SMTP, from a table rather than from the request.

No provider SDK on purpose. SMTP is what a free Gmail app password speaks, and
a Brevo or Resend free tier, and a paid service later — swapping between them
is configuration rather than a code change, which matters when the deployment
budget is nothing.

Nothing here is called from a request path. `queue` writes the message down in
the caller's transaction and returns; `flush_outbox` is what actually speaks
SMTP, driven by app/services/mail_sender.py. That split is the whole point: a
message scheduled on the event loop went out whatever happened to the
transaction that scheduled it, and vanished without trace if the process
restarted first.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

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


#: How long a failed send waits before the next try, by attempt number. Ends
#: rather than repeating forever: a Gmail password that has been revoked will
#: not start working, and an outbox that retries it every minute for a week is
#: a log nobody can read and a table nobody can trim. Five attempts across
#: roughly three hours covers every outage worth riding out.
BACKOFF_SECONDS = (60, 300, 1_800, 7_200)
MAX_ATTEMPTS = len(BACKOFF_SECONDS) + 1

#: One send is one SMTP handshake against a provider that rate limits. Twenty
#: at a time is far more than this platform generates and small enough that a
#: backlog cannot monopolise the loop.
BATCH = 20


def queue(session, to: list[str], subject: str, text: str, html: str | None = None) -> None:
    """Write the message down in the caller's transaction.

    Not sent here, and deliberately not scheduled here either. The row commits
    with whatever caused it, so an approval and its mail cannot disagree in
    either direction: the decision does not land without the message, and a
    decision that rolls back leaves no message to explain it.
    """
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


async def flush_outbox(session) -> tuple[int, int]:
    """Send what is due. Returns (sent, failed).

    Each message is committed on its own. A batch in one transaction would
    mean one refused address rolling back the record of nineteen that went,
    and the next pass sending them all again.
    """
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
        # Left to run, every message would burn its five attempts against a
        # host that is not there and land in `failed` — so configuring SMTP
        # later would deliver nothing that had been queued before it. Held
        # instead, and they go out on the first pass after the host appears.
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
