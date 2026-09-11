from __future__ import annotations

import time
from collections.abc import Callable

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


_REJECTABLE: dict[str, Callable[[], str]] = {
    "expired": lambda: _token(exp=int(time.time()) - 1),
    "signed with another key": lambda: _token(secret="not-the-secret"),
    "issued for another audience": lambda: _token(aud="anon"),
    "not a token at all": lambda: "sk_live_definitely_not_a_jwt",
    "empty": lambda: "",
}


@pytest.mark.parametrize("label", list(_REJECTABLE))
async def test_tokens_that_must_not_be_accepted(label: str) -> None:
    with pytest.raises(AuthError):
        await verify_token(_REJECTABLE[label]())


async def test_an_unsigned_token_is_refused() -> None:
    forged = jwt.encode({"sub": "intruder", "aud": "authenticated"}, "", algorithm="none")

    with pytest.raises(Exception) as caught:
        await verify_token(forged)
    assert not isinstance(caught.value, type(None))


async def test_a_missing_subject_is_refused() -> None:
    with pytest.raises(AuthError):
        await verify_token(jwt.encode({"aud": "authenticated"}, SECRET, algorithm="HS256"))


async def test_verification_and_admission_are_separate_questions() -> None:
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
    monkeypatch.setattr(auth, "_jwks_cache", {})
    settings.supabase_jwt_secret = ""

    with pytest.raises(AuthError) as caught:
        await auth._signing_key("some-kid")
    assert "could not" in caught.value.message.lower() or "no Supabase" in caught.value.message


async def test_a_token_the_size_of_an_upload_is_refused_before_it_is_parsed() -> None:
    with pytest.raises(AuthError):
        await verify_token("a" * (auth.MAX_TOKEN_BYTES + 1))


async def test_a_token_claiming_to_be_the_anonymous_caller_is_refused() -> None:
    with pytest.raises(AuthError):
        await verify_token(_token(sub="anonymous"))


async def test_a_verified_token_is_not_verified_twice(monkeypatch) -> None:
    token = _token()
    await verify_token(token)

    def _refuse(*_args, **_kwargs):
        raise AssertionError("the second read re-verified a token it had already verified")

    monkeypatch.setattr(auth.jwt, "decode", _refuse)
    assert (await verify_token(token)).email == "person@example.com"


async def test_the_cache_does_not_survive_a_change_of_signing_key() -> None:
    token = _token()
    await verify_token(token)

    settings.supabase_jwt_secret = "a-different-secret"
    with pytest.raises(AuthError):
        await verify_token(token)


async def test_admission_is_re_asked_of_a_token_already_verified() -> None:
    token = _token()
    await verify_token(token)

    settings.auth_allowed_email_domains_raw = "company.com"
    with pytest.raises(ForbiddenError):
        await verify_token(token)


async def test_an_unknown_key_id_is_not_a_fetch_per_request(monkeypatch) -> None:
    fetches = 0

    async def _count() -> None:
        nonlocal fetches
        fetches += 1
        auth._jwks_cache["known"] = object()
        auth._jwks_fetched_at = time.monotonic()

    monkeypatch.setattr(auth, "_refresh_jwks", _count)
    auth.reset_caches()

    for _ in range(5):
        with pytest.raises(AuthError):
            await auth._signing_key("unknown")

    assert fetches == 1


async def test_a_key_set_refresh_serves_everybody_waiting_on_it(monkeypatch) -> None:
    import asyncio

    fetches = 0

    async def _slow() -> None:
        nonlocal fetches
        fetches += 1
        await asyncio.sleep(0.05)
        auth._jwks_cache["kid-1"] = object()
        auth._jwks_fetched_at = time.monotonic()

    monkeypatch.setattr(auth, "_refresh_jwks", _slow)
    auth.reset_caches()

    keys = await asyncio.gather(*(auth._signing_key("kid-1") for _ in range(8)))

    assert fetches == 1
    assert all(key is keys[0] for key in keys)


async def test_a_key_set_with_nothing_usable_in_it_is_an_outage_not_a_bad_token(
    monkeypatch,
) -> None:
    class _Response:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict:
            return {"keys": []}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, _url):
            return _Response()

    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **_kwargs: _Client())
    monkeypatch.setattr(auth.settings, "supabase_url", "https://example.supabase.co")
    auth.reset_caches()

    with pytest.raises(AuthError):
        await auth._signing_key("kid-1")


def test_a_token_may_only_ride_in_the_url_on_a_stream() -> None:
    from app.api.deps import query_token_allowed

    assert query_token_allowed("GET", "/api/forecasts/abc/events")
    assert query_token_allowed("GET", "/api/auth/events")
    assert not query_token_allowed("GET", "/api/datasets")
    assert not query_token_allowed("DELETE", "/api/datasets/abc")
    assert not query_token_allowed("POST", "/api/forecasts/abc/events")
