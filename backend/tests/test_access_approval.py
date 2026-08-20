"""Signing in is not the same as being let in."""

from __future__ import annotations

import uuid

import pytest

from app.core import approvals
from app.core.approvals import InvalidApprovalLink, mint, verify
from app.core.config import settings


@pytest.fixture(autouse=True)
def _short_lived():
    """Restore every setting these tests touch, not only the ones they set.

    `settings` is one object for the whole session. A test that switches
    authentication on and leaves it on does not fail — it fails every test that
    runs after it, in files it has never heard of, with a 401 that looks like a
    bug in the endpoint.
    """
    original = (
        settings.credential_secret_key,
        settings.auth_approval_link_ttl_hours,
        settings.auth_enabled,
        settings.auth_require_approval,
        settings.auth_admin_emails_raw,
    )
    settings.credential_secret_key = "test-signing-key"
    settings.auth_approval_link_ttl_hours = 24
    yield
    (
        settings.credential_secret_key,
        settings.auth_approval_link_ttl_hours,
        settings.auth_enabled,
        settings.auth_require_approval,
        settings.auth_admin_emails_raw,
    ) = original


def test_a_link_carries_one_decision_about_one_account() -> None:
    account = uuid.uuid4()

    decision = verify(mint(account, approvals.APPROVE))

    assert decision.user_id == account
    assert decision.action == approvals.APPROVE


def test_a_rejection_link_cannot_be_read_as_an_approval() -> None:
    account = uuid.uuid4()
    assert verify(mint(account, approvals.REJECT)).action == approvals.REJECT


def test_an_altered_link_is_refused() -> None:
    """The signature is the whole control: without it the link is a user id."""
    token = mint(uuid.uuid4(), approvals.APPROVE)
    body, _, signature = token.partition(".")
    forged = mint(uuid.uuid4(), approvals.APPROVE).partition(".")[0]

    with pytest.raises(InvalidApprovalLink):
        verify(f"{forged}.{signature}")
    with pytest.raises(InvalidApprovalLink):
        verify(f"{body}.{'a' * len(signature)}")


def test_a_link_signed_with_another_key_is_refused() -> None:
    token = mint(uuid.uuid4(), approvals.APPROVE)
    settings.credential_secret_key = "a-different-key"

    with pytest.raises(InvalidApprovalLink):
        verify(token)


def test_an_expired_link_is_refused() -> None:
    settings.auth_approval_link_ttl_hours = 1
    token = mint(uuid.uuid4(), approvals.APPROVE)
    settings.auth_approval_link_ttl_hours = 24

    import time as clock

    real = clock.time
    clock.time = lambda: real() + 7200  # type: ignore[assignment]
    try:
        with pytest.raises(InvalidApprovalLink):
            verify(token)
    finally:
        clock.time = real  # type: ignore[assignment]


@pytest.mark.parametrize("token", ["", ".", "garbage", "a.b.c", "notbase64!.sig"])
def test_nonsense_is_refused_rather_than_crashing(token: str) -> None:
    with pytest.raises(InvalidApprovalLink):
        verify(token)


def test_a_decision_the_link_does_not_carry_is_refused() -> None:
    with pytest.raises(ValueError):
        mint(uuid.uuid4(), "delete-everything")


def test_administrators_are_recognised_by_email() -> None:
    from app.services import user_service

    original = settings.auth_admin_emails_raw
    settings.auth_admin_emails_raw = "boss@example.com, Other@Example.com"
    try:
        assert user_service.is_admin("boss@example.com")
        # Case is not something a person should have to get right in a config.
        assert user_service.is_admin("OTHER@example.com")
        assert not user_service.is_admin("stranger@example.com")
        assert not user_service.is_admin("")
    finally:
        settings.auth_admin_emails_raw = original


class _Row:
    def __init__(self, status):
        self.status = status


async def test_an_unregistered_account_is_not_treated_as_approved(monkeypatch) -> None:
    """The absence of a decision is not a decision.

    A new sign-in has a valid token and no row. Reading that as permission
    would let it skip the endpoint that registers it and walk past the gate.
    """
    from app.api import deps
    from app.core.auth import AuthenticatedUser, ForbiddenError
    from app.models.enums import AccessStatus
    from app.services import user_service

    settings.auth_enabled = True
    settings.auth_require_approval = True
    caller = AuthenticatedUser(id="new-person", email="new@example.com")

    monkeypatch.setattr(deps, "current_user", _returning(caller))

    async def absent(_session, _user):
        return None

    monkeypatch.setattr(user_service, "status_of", absent)

    with pytest.raises(ForbiddenError):
        await deps.approved_user(request=object(), session=object())

    async def approved(_session, _user):
        return _Row(AccessStatus.APPROVED)

    monkeypatch.setattr(user_service, "status_of", approved)
    assert await deps.approved_user(request=object(), session=object()) is caller


def _returning(value):
    async def call(_request):
        return value

    return call


async def test_a_rejected_account_is_refused(monkeypatch) -> None:
    from app.api import deps
    from app.core.auth import AuthenticatedUser, ForbiddenError
    from app.models.enums import AccessStatus
    from app.services import user_service

    settings.auth_enabled = True
    settings.auth_require_approval = True
    caller = AuthenticatedUser(id="blocked", email="blocked@example.com")
    monkeypatch.setattr(deps, "current_user", _returning(caller))

    async def rejected(_session, _user):
        return _Row(AccessStatus.REJECTED)

    monkeypatch.setattr(user_service, "status_of", rejected)

    with pytest.raises(ForbiddenError):
        await deps.approved_user(request=object(), session=object())


class _Account:
    def __init__(self, email, role, status, subject="s"):
        self.id = uuid.uuid4()
        self.email = email
        self.role = role
        self.status = status
        self.subject = subject
        self.decided_at = None
        self.decided_by = None


async def test_the_configured_admin_cannot_be_locked_out(monkeypatch) -> None:
    """The floor under the role column.

    Demote or refuse everyone through the UI and the account named in the
    environment must still get back in, or a deployment can be left with
    nobody able to approve anybody — a state with no way out but a shell.
    """
    from app.models.enums import AccessRole, AccessStatus
    from app.services import user_service
    from app.services.user_service import LastAdminError

    settings.auth_admin_emails_raw = "boss@example.com"
    boss = _Account("boss@example.com", AccessRole.ADMIN, AccessStatus.APPROVED)

    with pytest.raises(LastAdminError):
        await user_service.set_status(None, boss, AccessStatus.REJECTED, decided_by="x")
    with pytest.raises(LastAdminError):
        await user_service.set_role(None, boss, AccessRole.MEMBER, decided_by="x")

    assert boss.status is AccessStatus.APPROVED
    assert boss.role is AccessRole.ADMIN


async def test_the_last_administrator_cannot_step_down(monkeypatch) -> None:
    from app.models.enums import AccessRole, AccessStatus
    from app.services import user_service
    from app.services.user_service import LastAdminError

    settings.auth_admin_emails_raw = ""
    only = _Account("only@example.com", AccessRole.ADMIN, AccessStatus.APPROVED)

    async def one(_session):
        return 1

    monkeypatch.setattr(user_service, "_admin_count", one)

    with pytest.raises(LastAdminError):
        await user_service.set_role(None, only, AccessRole.MEMBER, decided_by="x")


async def test_promoting_somebody_waiting_lets_them_in(monkeypatch) -> None:
    """An administrator who cannot sign in is not one."""
    from app.models.enums import AccessRole, AccessStatus
    from app.services import user_service

    settings.auth_admin_emails_raw = ""
    waiting = _Account("new@example.com", AccessRole.MEMBER, AccessStatus.PENDING)

    class _Session:
        async def flush(self):
            return None

        def add(self, _row):
            return None

    async def two(_session):
        return 2

    monkeypatch.setattr(user_service, "_admin_count", two)

    await user_service.set_role(_Session(), waiting, AccessRole.ADMIN, decided_by="boss")

    assert waiting.role is AccessRole.ADMIN
    assert waiting.status is AccessStatus.APPROVED


def test_a_role_in_the_database_grants_admin_without_the_config() -> None:
    from app.models.enums import AccessRole
    from app.services import user_service

    settings.auth_admin_emails_raw = "boss@example.com"

    assert user_service.is_admin("boss@example.com")
    assert user_service.is_admin("promoted@example.com", AccessRole.ADMIN)
    assert not user_service.is_admin("member@example.com", AccessRole.MEMBER)


async def test_only_being_let_in_sends_anything(monkeypatch) -> None:
    """The yes is the only message a decision produces.

    A refusal and a revocation used to send one each. Both told somebody they
    had lost or been denied something, with nothing in them to act on, and the
    app says either the moment they next look. The approval is the one
    somebody is actually waiting for.
    """
    from app.models.enums import AccessRole, AccessStatus
    from app.services import user_service

    settings.auth_admin_emails_raw = ""
    sent: list[str] = []

    def capture(_session, _to, subject, **_rest):
        sent.append(subject)

    monkeypatch.setattr(user_service.mailer, "queue", capture)

    class _Session:
        async def flush(self):
            return None

        def add(self, _row):
            return None

    async def decide(was, now):
        sent.clear()
        row = _Account("someone@example.com", AccessRole.MEMBER, was)
        await user_service.set_status(_Session(), row, now, decided_by="boss")
        return sent

    assert await decide(AccessStatus.PENDING, AccessStatus.APPROVED) == [
        "You have access to Forecast Hub"
    ]
    assert await decide(AccessStatus.REJECTED, AccessStatus.APPROVED) == [
        "You have access to Forecast Hub"
    ]
    assert await decide(AccessStatus.PENDING, AccessStatus.REJECTED) == []
    assert await decide(AccessStatus.APPROVED, AccessStatus.REJECTED) == []

    # And nothing at all when nothing changed.
    assert await decide(AccessStatus.APPROVED, AccessStatus.APPROVED) == []


def test_production_refuses_to_start_on_a_secret_manager_it_cannot_read() -> None:
    """The fallback stops being a smaller version of the deployment.

    Falling back to the environment is right while the environment still holds
    everything. Once the file on the box has been emptied — the whole point of
    adopting a secret manager — the same fallback comes up with AUTH_ENABLED
    defaulting to false, which is a publicly readable API with nothing saying
    so out loud.
    """
    import app.core.config as config

    was = (config.secrets_load.configured, config.secrets_load.loaded, config.secrets_load.error)

    def build():
        return config.Settings(
            APP_ENV="production",
            credential_secret_key="x" * 40,
            database_fallback_enabled=False,
            cors_origins_raw="https://example.com",
        )

    try:
        config.secrets_load.configured, config.secrets_load.loaded = True, False
        config.secrets_load.error = "ConnectionError: refused"
        with pytest.raises(Exception, match="Infisical"):
            build()

        config.secrets_load.loaded = True
        build()

        # A deployment that never adopted it is untouched.
        config.secrets_load.configured, config.secrets_load.loaded = False, False
        build()
    finally:
        (
            config.secrets_load.configured,
            config.secrets_load.loaded,
            config.secrets_load.error,
        ) = was
