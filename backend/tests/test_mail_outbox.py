"""Mail that survives the process it was written in."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core import mailer
from app.database.base import utcnow
from app.models.entities import MailOutbox


@pytest.fixture(autouse=True)
def _smtp_configured():
    """Most of this file is about what happens once a host exists.

    Restored rather than left set: `settings` is one object for the whole
    session, and a test that switches something on and leaves it on does not
    fail — it fails whatever runs next, in a file that has never heard of it.
    """
    from app.core.config import settings

    was = (settings.smtp_host, settings.smtp_from)
    settings.smtp_host = "smtp.example.com"
    settings.smtp_from = "noreply@example.com"
    yield
    settings.smtp_host, settings.smtp_from = was


async def _rows(session):
    return list((await session.scalars(select(MailOutbox))).all())


async def test_queueing_writes_a_row_rather_than_sending(session) -> None:
    mailer.queue(session, ["a@example.com"], subject="Hi", text="body", html="<p>body</p>")
    await session.flush()

    rows = await _rows(session)
    assert len(rows) == 1
    assert rows[0].status == "pending"
    assert rows[0].attempts == 0
    assert rows[0].sent_at is None


async def test_an_empty_recipient_list_queues_nothing(session) -> None:
    mailer.queue(session, [], subject="Hi", text="body")
    mailer.queue(session, ["", "   "], subject="Hi", text="body")
    await session.flush()

    assert await _rows(session) == []


async def test_a_rolled_back_decision_leaves_no_mail_behind(session) -> None:
    """The reason this is a table and not a background task.

    A message scheduled on the event loop goes out whatever happens to the
    transaction that scheduled it — so a decision that failed to commit could
    still tell somebody they were approved.
    """
    mailer.queue(session, ["a@example.com"], subject="Approved", text="body")
    await session.rollback()

    assert await _rows(session) == []


async def test_sending_marks_the_row_and_does_not_send_it_twice(session, monkeypatch) -> None:
    delivered = []
    monkeypatch.setattr(
        mailer, "_deliver", lambda to, subject, text, html: delivered.append(subject)
    )

    mailer.queue(session, ["a@example.com"], subject="Hi", text="body")
    await session.commit()

    assert await mailer.flush_outbox(session) == (1, 0)
    assert delivered == ["Hi"]

    # The second pass has nothing due, which is what stops a restart from
    # mailing everybody again.
    assert await mailer.flush_outbox(session) == (0, 0)
    assert delivered == ["Hi"]

    row = (await _rows(session))[0]
    assert row.status == "sent"
    assert row.sent_at is not None


async def test_a_failure_is_retried_later_rather_than_lost(session, monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(mailer, "_deliver", boom)

    mailer.queue(session, ["a@example.com"], subject="Hi", text="body")
    await session.commit()

    assert await mailer.flush_outbox(session) == (0, 0)

    row = (await _rows(session))[0]
    assert row.status == "pending", "a transient failure must not discard the message"
    assert row.attempts == 1
    assert "connection refused" in row.last_error
    # Compared without a timezone: sqlite hands back what postgres would give
    # as aware, and the assertion here is about the delay, not about storage.
    assert row.next_attempt_at.replace(tzinfo=None) > utcnow().replace(tzinfo=None)

    # Not due yet, so a tight loop cannot burn the attempts in one second.
    assert await mailer.flush_outbox(session) == (0, 0)
    assert (await _rows(session))[0].attempts == 1


async def test_retrying_stops_rather_than_going_on_forever(session, monkeypatch) -> None:
    """A revoked password will not start working, and a table that retries it
    every minute for a week is a log nobody can read."""

    def boom(*_args, **_kwargs):
        raise OSError("nope")

    monkeypatch.setattr(mailer, "_deliver", boom)

    mailer.queue(session, ["a@example.com"], subject="Hi", text="body")
    await session.commit()

    for _ in range(mailer.MAX_ATTEMPTS):
        row = (await _rows(session))[0]
        row.next_attempt_at = utcnow() - timedelta(seconds=1)
        await session.commit()
        await mailer.flush_outbox(session)

    row = (await _rows(session))[0]
    assert row.status == "failed"
    assert row.attempts == mailer.MAX_ATTEMPTS


async def test_one_bad_address_does_not_roll_back_the_ones_that_went(
    session, monkeypatch
) -> None:
    sent = []

    def selective(to, subject, text, html):
        if subject == "bad":
            raise OSError("refused")
        sent.append(subject)

    monkeypatch.setattr(mailer, "_deliver", selective)

    mailer.queue(session, ["a@example.com"], subject="bad", text="b")
    mailer.queue(session, ["b@example.com"], subject="good", text="b")
    await session.commit()

    assert await mailer.flush_outbox(session) == (1, 0)
    assert sent == ["good"]

    by_subject = {row.subject: row for row in await _rows(session)}
    assert by_subject["good"].status == "sent"
    assert by_subject["bad"].status == "pending"


async def test_a_batch_is_bounded(session, monkeypatch) -> None:
    monkeypatch.setattr(mailer, "_deliver", lambda *a, **k: None)

    for n in range(mailer.BATCH + 5):
        mailer.queue(session, ["a@example.com"], subject=f"m{n}", text="b")
    await session.commit()

    sent, _ = await mailer.flush_outbox(session)
    assert sent == mailer.BATCH


async def test_nothing_is_burned_while_smtp_is_unconfigured(session, monkeypatch) -> None:
    """Configuring the mail server later must still deliver what is waiting.

    Attempted against a host that is not there, every queued message would
    spend its five attempts in three hours and land in `failed` — so a
    deployment that queued mail before SMTP was set up would deliver none of
    it afterwards, silently.
    """
    from app.core.config import settings

    settings.smtp_host = ""
    try:
        mailer.queue(session, ["a@example.com"], subject="Hi", text="body")
        await session.commit()

        assert await mailer.flush_outbox(session) == (0, 0)
        row = (await _rows(session))[0]
        assert row.status == "pending"
        assert row.attempts == 0
    finally:
        settings.smtp_host = "smtp.example.com"

    monkeypatch.setattr(mailer, "_deliver", lambda *a, **k: None)
    assert await mailer.flush_outbox(session) == (1, 0)
