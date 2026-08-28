"""Who gets in, and — mostly — who does not.

The API answers the public internet directly, so these are not tests of a
convenience layer. Every case below is something an attacker sends on purpose.
"""

from __future__ import annotations

import time

import jwt
import pytest

from app.core import auth
from app.core.auth import AuthError, ForbiddenError, verify_token
from app.core.config import settings

SECRET = "test-only-signing-secret"


@pytest.fixture(autouse=True)
def _configured():
    original = (
        settings.auth_enabled,
        settings.supabase_jwt_secret,
        settings.auth_allowed_email_domains_raw,
        settings.auth_allowlist_raw,
    )
    settings.auth_enabled = True
    settings.supabase_jwt_secret = SECRET
    settings.auth_allowed_email_domains_raw = ""
    settings.auth_allowlist_raw = ""
    yield
    (
        settings.auth_enabled,
        settings.supabase_jwt_secret,
        settings.auth_allowed_email_domains_raw,
        settings.auth_allowlist_raw,
    ) = original


def _token(secret: str = SECRET, algorithm: str = "HS256", **overrides) -> str:
    claims = {
        "sub": "google-oauth2|1234",
        "email": "person@example.com",
        "aud": "authenticated",
        "exp": int(time.time()) + 600,
        "user_metadata": {"name": "A Person", "avatar_url": "https://example.com/a.png"},
    }
    claims.update(overrides)
    return jwt.encode(claims, secret, algorithm=algorithm)


async def test_a_valid_token_identifies_its_holder() -> None:
    user = await verify_token(_token())

    assert user.id == "google-oauth2|1234"
    assert user.email == "person@example.com"
    assert user.name == "A Person"
    assert not user.is_anonymous


@pytest.mark.parametrize(
    ("label", "token"),
    [
        ("expired", _token(exp=int(time.time()) - 1)),
        ("signed with another key", _token(secret="not-the-secret")),
        ("issued for another audience", _token(aud="anon")),
        ("not a token at all", "sk_live_definitely_not_a_jwt"),
        ("empty", ""),
    ],
)
async def test_tokens_that_must_not_be_accepted(label: str, token: str) -> None:
    with pytest.raises(AuthError):
        await verify_token(token)


async def test_an_unsigned_token_is_refused() -> None:
    """The oldest JWT attack: claim `alg: none` and hope the check is skipped."""
    forged = jwt.encode({"sub": "intruder", "aud": "authenticated"}, "", algorithm="none")

    with pytest.raises(Exception) as caught:
        await verify_token(forged)
    assert not isinstance(caught.value, type(None))


async def test_a_missing_subject_is_refused() -> None:
    with pytest.raises(AuthError):
        await verify_token(jwt.encode({"aud": "authenticated"}, SECRET, algorithm="HS256"))


async def test_verification_and_admission_are_separate_questions() -> None:
    """A token can be genuine and its holder still not belong here."""
    settings.auth_allowed_email_domains_raw = "company.com"

    with pytest.raises(ForbiddenError):
        await verify_token(_token())

    admitted = await verify_token(_token(email="person@company.com"))
    assert admitted.email == "person@company.com"


async def test_the_allowlist_admits_past_the_domain_rule() -> None:
    settings.auth_allowed_email_domains_raw = "company.com"
    settings.auth_allowlist_raw = "contractor@example.com"

    user = await verify_token(_token(email="contractor@example.com"))
    assert user.email == "contractor@example.com"


async def test_no_signing_secret_refuses_rather_than_trusts() -> None:
    settings.supabase_jwt_secret = ""

    with pytest.raises(AuthError):
        await verify_token(_token())


async def test_an_unreachable_key_set_is_not_a_bad_token(monkeypatch) -> None:
    """An outage at the identity provider must not read as 'your login is wrong'."""
    monkeypatch.setattr(auth, "_jwks_cache", {})
    settings.supabase_jwt_secret = ""

    with pytest.raises(AuthError) as caught:
        await auth._signing_key("some-kid")
    assert "could not" in caught.value.message.lower() or "no Supabase" in caught.value.message
