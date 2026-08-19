"""Signing in is not the same as being let in."""

from __future__ import annotations

import uuid

import pytest

from app.core import approvals
from app.core.approvals import InvalidApprovalLink, mint, verify
from app.core.config import settings


@pytest.fixture(autouse=True)
def _short_lived():
    original = (settings.credential_secret_key, settings.auth_approval_link_ttl_hours)
    settings.credential_secret_key = "test-signing-key"
    settings.auth_approval_link_ttl_hours = 24
    yield
    settings.credential_secret_key, settings.auth_approval_link_ttl_hours = original


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
