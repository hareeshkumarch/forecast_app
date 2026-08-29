"""What app_users could not answer: what happened before the last thing."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.auth import AuthenticatedUser
from app.core.config import settings
from app.models.entities import AccessAudit
from app.models.enums import AccessRole, AccessStatus
from app.services import user_service


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(user_service.mailer, "queue", lambda *a, **k: None)
    was = settings.auth_admin_emails_raw
    settings.auth_admin_emails_raw = ""
    yield
    settings.auth_admin_emails_raw = was


async def _entries(session):
    result = await session.execute(select(AccessAudit).order_by(AccessAudit.at))
    return list(result.scalars().all())


async def test_a_decision_is_recorded_with_who_made_it(session) -> None:
    row = await user_service.resolve(
        session, AuthenticatedUser(id="s1", email="new@example.com", name="New")
    )
    await user_service.set_status(
        session, row, AccessStatus.APPROVED, decided_by="boss@example.com"
    )
    await session.flush()

    entries = await _entries(session)
    actions = [entry.action for entry in entries]

    assert user_service.REQUESTED in actions
    assert user_service.APPROVED in actions
    approved = next(e for e in entries if e.action == user_service.APPROVED)
    assert approved.actor_email == "boss@example.com"
    assert approved.subject_email == "new@example.com"


async def test_the_earlier_decision_is_not_overwritten_by_the_later_one(session) -> None:
    """The whole reason this table exists.

    app_users has one decided_by and one decided_at, so approving somebody and
    then revoking them leaves no trace that the approval ever happened.
    """
    row = await user_service.resolve(
        session, AuthenticatedUser(id="s2", email="two@example.com", name="Two")
    )
    await user_service.set_status(session, row, AccessStatus.APPROVED, decided_by="a@x.com")
    await user_service.set_status(session, row, AccessStatus.REJECTED, decided_by="b@x.com")
    await session.flush()

    actions = [e.action for e in await _entries(session)]

    assert user_service.APPROVED in actions
    assert user_service.REVOKED in actions, "losing access is not the same as being refused"
    assert user_service.REJECTED not in actions


async def test_a_refusal_and_a_revocation_are_told_apart(session) -> None:
    never_in = await user_service.resolve(
        session, AuthenticatedUser(id="s3", email="three@example.com", name="Three")
    )
    await user_service.set_status(session, never_in, AccessStatus.REJECTED, decided_by="a@x.com")
    await session.flush()

    actions = [e.action for e in await _entries(session)]
    assert user_service.REJECTED in actions
    assert user_service.REVOKED not in actions


async def test_a_role_change_records_both_ends_of_it(session) -> None:
    row = await user_service.resolve(
        session, AuthenticatedUser(id="s4", email="four@example.com", name="Four")
    )
    row.status = AccessStatus.APPROVED
    await session.flush()

    await user_service.set_role(session, row, AccessRole.ADMIN, decided_by="boss@example.com")
    await session.flush()

    promoted = next(e for e in await _entries(session) if e.action == user_service.PROMOTED)
    assert promoted.detail == "member -> admin"
    assert promoted.actor_email == "boss@example.com"


async def test_the_record_outlives_the_account_it_names(session) -> None:
    """An audit trail that disappears with its subject answers nothing."""
    row = await user_service.resolve(
        session, AuthenticatedUser(id="s5", email="five@example.com", name="Five")
    )
    row.status = AccessStatus.APPROVED
    await session.flush()

    await user_service.remove(session, row, removed_by="boss@example.com")
    await session.flush()

    removed = [e for e in await _entries(session) if e.action == user_service.REMOVED]
    assert len(removed) == 1
    assert removed[0].subject_email == "five@example.com"
    assert removed[0].actor_email == "boss@example.com"


async def test_the_emailed_link_is_recorded_like_any_other_decision(session) -> None:
    """The path least likely to be watched is the one opened from an inbox.

    Recording in the service rather than the route is what makes it impossible
    for that path to skip it.
    """
    row = await user_service.resolve(
        session, AuthenticatedUser(id="s6", email="six@example.com", name="Six")
    )
    await user_service.set_status(session, row, AccessStatus.APPROVED, decided_by="approval link")
    await session.flush()

    approved = next(e for e in await _entries(session) if e.action == user_service.APPROVED)
    assert approved.actor_email == "approval link"


async def test_history_reads_newest_first(session) -> None:
    row = await user_service.resolve(
        session, AuthenticatedUser(id="s7", email="seven@example.com", name="Seven")
    )
    await user_service.set_status(session, row, AccessStatus.APPROVED, decided_by="a@x.com")
    await session.flush()

    entries = await user_service.history(session, limit=10)
    assert entries
    assert [e.at for e in entries] == sorted((e.at for e in entries), reverse=True)
