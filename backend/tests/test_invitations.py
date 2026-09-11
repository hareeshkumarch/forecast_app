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
    original = settings.smtp_host
    settings.smtp_host = ""
    yield
    settings.smtp_host = original


async def test_an_invitation_is_an_account_nobody_has_signed_in_to(session: AsyncSession) -> None:
    row = await user_service.invite(session, "Invited@Example.com ", invited_by="boss@example.com")

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
    assert again.subject == "google-sub-3"


async def test_an_invitation_is_matched_on_the_address_alone(session: AsyncSession) -> None:
    await user_service.invite(session, "shared@example.com", invited_by="boss@example.com")

    claimed = await user_service.resolve(
        session, AuthenticatedUser(id="whoever-signs-in-first", email="shared@example.com")
    )

    assert claimed is not None
    assert claimed.subject == "whoever-signs-in-first"
    assert claimed.status is AccessStatus.APPROVED


async def test_signing_in_again_sends_nothing(session: AsyncSession, monkeypatch) -> None:
    sent: list[str] = []

    def record(_session, _to, *, subject: str, **_kwargs):
        sent.append(subject)

    monkeypatch.setattr(user_service.mailer, "queue", record)
    settings.auth_admin_emails_raw = "boss@example.com"

    caller = AuthenticatedUser(id="sub-welcome", email="boss@example.com", name="Boss")
    await user_service.resolve(session, caller)
    await user_service.resolve(session, caller)
    await user_service.resolve(session, caller)

    assert sent == [], f"signing in should send nothing, sent {sent}"


async def test_asking_for_access_tells_the_asker_and_nobody_else(
    session: AsyncSession, monkeypatch
) -> None:
    recipients: list[list[str]] = []

    def record(_session, to, **_kwargs):
        recipients.append(to)

    monkeypatch.setattr(user_service.mailer, "queue", record)
    settings.auth_admin_emails_raw = "boss@example.com"
    settings.auth_require_approval = True

    row = await user_service.resolve(
        session, AuthenticatedUser(id="sub-waiting", email="waiting@example.com")
    )

    assert row is not None
    assert row.status is AccessStatus.PENDING
    assert recipients == [["waiting@example.com"]]
    assert ["boss@example.com"] not in recipients


async def test_an_invited_person_arriving_gets_no_second_message(
    session: AsyncSession, monkeypatch
) -> None:
    subjects: list[str] = []

    def record(_session, _to, *, subject: str, **_kwargs):
        subjects.append(subject)

    monkeypatch.setattr(user_service.mailer, "queue", record)
    settings.auth_admin_emails_raw = ""

    await user_service.invite(session, "guest@example.com", invited_by="boss@example.com")
    assert len(subjects) == 1, "the invitation itself"
    subjects.clear()

    row = await user_service.resolve(
        session, AuthenticatedUser(id="sub-guest", email="guest@example.com", name="Guest")
    )

    assert row is not None
    assert row.status is AccessStatus.APPROVED
    assert subjects == []


async def test_a_bulk_change_still_honours_every_guard(session: AsyncSession, monkeypatch) -> None:
    from app.api.routes import auth as auth_routes
    from app.core.auth import AuthenticatedUser as Caller

    monkeypatch.setattr(user_service.mailer, "queue", lambda *a, **k: None)
    settings.auth_admin_emails_raw = "boss@example.com"

    boss = await user_service.resolve(session, Caller(id="sub-boss", email="boss@example.com"))
    ordinary = await user_service.invite(session, "ordinary@example.com", invited_by="boss@x.com")
    assert boss is not None

    result = await auth_routes._each(
        session,
        Caller(id="sub-boss", email="boss@example.com"),
        [boss.id, ordinary.id],
        lambda target: user_service.set_status(
            session, target, AccessStatus.REJECTED, decided_by="boss@example.com"
        ),
    )

    assert result.changed == 1
    assert "boss@example.com" in result.skipped
    assert boss.status is AccessStatus.APPROVED
    assert ordinary.status is AccessStatus.REJECTED


async def test_a_missing_row_in_a_bulk_change_is_reported_not_fatal(
    session: AsyncSession, monkeypatch
) -> None:
    import uuid as uuid_module

    from app.api.routes import auth as auth_routes
    from app.core.auth import AuthenticatedUser as Caller

    monkeypatch.setattr(user_service.mailer, "queue", lambda *a, **k: None)
    settings.auth_admin_emails_raw = ""

    real = await user_service.invite(session, "real@example.com", invited_by="boss@x.com")
    ghost = uuid_module.uuid4()

    result = await auth_routes._each(
        session,
        Caller(id="sub-admin", email="admin@example.com"),
        [real.id, ghost],
        lambda target: user_service.set_status(
            session, target, AccessStatus.REJECTED, decided_by="admin@example.com"
        ),
    )

    assert result.changed == 1
    assert str(ghost) in result.skipped


async def test_mail_does_not_hold_up_the_answer(session, monkeypatch) -> None:
    from app.core import mailer

    def explode(*_args, **_kwargs):
        raise AssertionError("queueing must not touch SMTP")

    monkeypatch.setattr(mailer, "_send_blocking", explode)
    monkeypatch.setattr(mailer, "_deliver", explode)

    mailer.queue(session, ["someone@example.com"], subject="s", text="t")
    await session.flush()


async def test_two_messages_exist_and_no_more(session: AsyncSession, monkeypatch) -> None:
    from app.core import email_templates

    assert sorted(
        name
        for name, value in vars(email_templates).items()
        if callable(value)
        and not name.startswith("_")
        and name not in {"layout", "Action", "Message", "dataclass"}
    ) == ["access_approved", "request_received"]

    subjects: list[str] = []

    def record(_session, _to, *, subject: str, **_kwargs):
        subjects.append(subject)

    monkeypatch.setattr(user_service.mailer, "queue", record)
    settings.auth_admin_emails_raw = ""
    settings.auth_require_approval = True

    row = await user_service.resolve(
        session, AuthenticatedUser(id="sub-contract", email="asker@example.com")
    )
    assert row is not None
    assert subjects == ["Your access request is with an administrator"]

    await user_service.set_status(session, row, AccessStatus.APPROVED, decided_by="boss@x.com")
    assert subjects[-1] == "You have access to Forecast Hub"

    before = len(subjects)
    await user_service.set_status(session, row, AccessStatus.REJECTED, decided_by="boss@x.com")
    await user_service.set_role(session, row, AccessRole.ADMIN, decided_by="boss@x.com")
    await session.flush()
    assert len(subjects) == before, "revoking and changing a role send nothing"


async def test_an_invitation_sends_the_same_message_as_an_approval(
    session: AsyncSession, monkeypatch
) -> None:
    subjects: list[str] = []

    def record(_session, _to, *, subject: str, **_kwargs):
        subjects.append(subject)

    monkeypatch.setattr(user_service.mailer, "queue", record)
    settings.auth_admin_emails_raw = ""

    await user_service.invite(session, "guest@example.com", invited_by="boss@example.com")

    assert subjects == ["You have access to Forecast Hub"]


async def test_no_administrator_is_emailed_about_anybody_else(
    session: AsyncSession, monkeypatch
) -> None:
    recipients: list[str] = []

    def record(_session, to, **_kwargs):
        recipients.extend(to)

    monkeypatch.setattr(user_service.mailer, "queue", record)
    settings.auth_admin_emails_raw = "boss@example.com"
    settings.auth_require_approval = True

    row = await user_service.resolve(
        session, AuthenticatedUser(id="sub-sweep", email="asker@example.com")
    )
    assert row is not None
    await user_service.set_status(
        session, row, AccessStatus.APPROVED, decided_by="boss@example.com"
    )
    await user_service.set_status(
        session, row, AccessStatus.REJECTED, decided_by="boss@example.com"
    )
    await user_service.invite(session, "guest@example.com", invited_by="boss@example.com")
    await session.flush()

    assert recipients, "something should have been sent"
    assert "boss@example.com" not in recipients, f"an administrator was emailed: {recipients}"
    assert set(recipients) == {"asker@example.com", "guest@example.com"}
