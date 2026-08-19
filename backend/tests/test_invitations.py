"""Access given before somebody has ever signed in."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedUser
from app.core.config import settings
from app.models.entities import AppUser
from app.models.enums import AccessRole, AccessStatus
from app.services import user_service


@pytest.fixture(autouse=True)
def _no_mail_server():
    """Nothing here should try to reach a mail server.

    Sending is best-effort and swallows its own failures, so an unconfigured
    host makes these tests exercise the records rather than the network.
    """
    original = settings.smtp_host
    settings.smtp_host = ""
    yield
    settings.smtp_host = original


async def test_an_invitation_is_an_account_nobody_has_signed_in_to(session: AsyncSession) -> None:
    row = await user_service.invite(session, "Invited@Example.com ", invited_by="boss@example.com")

    # Lower-cased and trimmed, because it is matched against what Google sends
    # back and that is not going to be capitalised the same way.
    assert row.email == "invited@example.com"
    assert row.subject is None
    assert row.status is AccessStatus.APPROVED
    assert row.role is AccessRole.MEMBER
    assert row.invited_by == "boss@example.com"


async def test_signing_in_claims_the_invitation(session: AsyncSession) -> None:
    invited = await user_service.invite(session, "arrives@example.com", invited_by="boss@x.com")
    assert invited.subject is None

    resolved = await user_service.resolve(
        session,
        AuthenticatedUser(id="google-sub-1", email="arrives@example.com", name="Arrives"),
    )

    # The same row, now attached to a real sign-in, and still approved: the
    # point of an invitation is not joining the queue it let you skip.
    assert resolved is not None
    assert resolved.id == invited.id
    assert resolved.subject == "google-sub-1"
    assert resolved.status is AccessStatus.APPROVED
    assert resolved.name == "Arrives"

    everyone = (await session.execute(select(AppUser))).scalars().all()
    assert len([r for r in everyone if r.email == "arrives@example.com"]) == 1


async def test_somebody_uninvited_still_has_to_wait(session: AsyncSession) -> None:
    settings.auth_require_approval = True
    settings.auth_admin_emails_raw = ""

    resolved = await user_service.resolve(
        session, AuthenticatedUser(id="google-sub-2", email="stranger@example.com")
    )

    assert resolved is not None
    assert resolved.status is AccessStatus.PENDING


async def test_re_inviting_a_refused_account_lets_them_back_in(session: AsyncSession) -> None:
    """Re-inviting is how a rejection made by mistake is undone."""
    settings.auth_require_approval = True
    settings.auth_admin_emails_raw = ""

    person = await user_service.resolve(
        session, AuthenticatedUser(id="google-sub-3", email="oops@example.com")
    )
    assert person is not None
    await user_service.set_status(
        session, person, AccessStatus.REJECTED, decided_by="boss@example.com"
    )
    assert person.status is AccessStatus.REJECTED

    again = await user_service.invite(session, "oops@example.com", invited_by="boss@example.com")

    assert again.id == person.id
    assert again.status is AccessStatus.APPROVED
    # Still the same sign-in, not a second account for the same person.
    assert again.subject == "google-sub-3"


async def test_an_invitation_is_matched_on_the_address_alone(session: AsyncSession) -> None:
    """Which is the whole security model, and worth stating out loud.

    Anybody who can receive mail at the invited address can claim it. That is
    the intent — it is why the address has to be one only they control.
    """
    await user_service.invite(session, "shared@example.com", invited_by="boss@example.com")

    claimed = await user_service.resolve(
        session, AuthenticatedUser(id="whoever-signs-in-first", email="shared@example.com")
    )

    assert claimed is not None
    assert claimed.subject == "whoever-signs-in-first"
    assert claimed.status is AccessStatus.APPROVED


async def test_the_welcome_is_sent_once(session: AsyncSession, monkeypatch) -> None:
    """Once, on the first sign-in that gets through.

    Not on every visit — the stamp is what makes the difference, and it is set
    before the send so a slow mail server cannot turn one welcome into one per
    page load.
    """
    sent: list[list[str]] = []

    async def record(to, **_kwargs):
        sent.append(to)
        return True

    monkeypatch.setattr(user_service.mailer, "send", record)
    settings.auth_admin_emails_raw = "boss@example.com"

    caller = AuthenticatedUser(id="sub-welcome", email="boss@example.com", name="Boss")
    first = await user_service.resolve(session, caller)

    assert first is not None
    assert first.welcomed_at is not None
    assert sent == [["boss@example.com"]]

    await user_service.resolve(session, caller)
    await user_service.resolve(session, caller)

    assert sent == [["boss@example.com"]], "the welcome went out again on a later visit"


async def test_somebody_still_waiting_is_not_welcomed(session: AsyncSession, monkeypatch) -> None:
    """A welcome to an account that cannot get in would be a lie."""
    subjects: list[str] = []

    async def record(_to, subject: str, **_kwargs):
        subjects.append(subject)
        return True

    monkeypatch.setattr(user_service.mailer, "send", record)
    settings.auth_admin_emails_raw = ""
    settings.auth_require_approval = True

    row = await user_service.resolve(
        session, AuthenticatedUser(id="sub-waiting", email="waiting@example.com")
    )

    assert row is not None
    assert row.status is AccessStatus.PENDING
    assert row.welcomed_at is None
    assert not any("Welcome" in s for s in subjects)


async def test_an_invited_person_is_welcomed_when_they_arrive(
    session: AsyncSession, monkeypatch
) -> None:
    subjects: list[str] = []

    async def record(_to, subject: str, **_kwargs):
        subjects.append(subject)
        return True

    monkeypatch.setattr(user_service.mailer, "send", record)
    settings.auth_admin_emails_raw = ""

    await user_service.invite(session, "guest@example.com", invited_by="boss@example.com")
    subjects.clear()

    row = await user_service.resolve(
        session, AuthenticatedUser(id="sub-guest", email="guest@example.com", name="Guest")
    )

    assert row is not None
    assert row.welcomed_at is not None
    assert any("Welcome" in s for s in subjects)
