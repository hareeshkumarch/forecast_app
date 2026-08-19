"""Who is calling, established from a Supabase-issued token.

The check runs here rather than in the frontend because the API answers the
public internet directly: a gate the browser enforces is one a curl request
walks past. Every protected route depends on this module, not on the caller
having come through the app.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Supabase stamps this into every access token it issues.
SUPABASE_AUDIENCE = "authenticated"

ASYMMETRIC_ALGORITHMS = ("RS256", "ES256")

#: How long a fetched key set is trusted before it is fetched again. Supabase
#: rotates signing keys, and a cache that never expires turns a rotation into
#: an outage that only a restart clears.
JWKS_TTL_SECONDS = 600

JWKS_TIMEOUT_SECONDS = 5.0


class AuthError(AppError):
    status_code = 401
    code = "unauthenticated"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


@dataclass(slots=True, frozen=True)
class AuthenticatedUser:
    id: str
    email: str
    name: str | None = None
    picture: str | None = None

    @property
    def is_anonymous(self) -> bool:
        return self.id == ANONYMOUS.id


#: What every caller is when authentication is switched off. A real object
#: rather than None, so route code reads the same in both modes and cannot
#: forget the None case on the day the flag flips.
ANONYMOUS = AuthenticatedUser(id="anonymous", email="", name="Anonymous")


_jwks_cache: dict[str, Any] = {}
_jwks_fetched_at = 0.0


async def _signing_key(kid: str) -> Any:
    global _jwks_fetched_at

    cached = _jwks_cache.get(kid)
    if cached is not None and time.monotonic() - _jwks_fetched_at < JWKS_TTL_SECONDS:
        return cached

    url = settings.supabase_jwks_url
    if not url:
        raise AuthError("This deployment has no Supabase project configured to verify tokens.")

    try:
        async with httpx.AsyncClient(timeout=JWKS_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
            response.raise_for_status()
            document = response.json()
    except Exception as exc:
        # A key set that cannot be fetched is not a bad token. Saying so keeps
        # an outage at the identity provider from reading as "your login is
        # wrong" to every user at once.
        logger.warning("Could not fetch the Supabase key set: %s", exc)
        raise AuthError("The sign-in service could not be reached to verify this session.") from exc

    _jwks_cache.clear()
    for entry in document.get("keys", []):
        try:
            _jwks_cache[entry["kid"]] = jwt.PyJWK(entry).key
        except Exception:
            continue
    _jwks_fetched_at = time.monotonic()

    key = _jwks_cache.get(kid)
    if key is None:
        raise AuthError("This session was signed with a key this deployment does not recognise.")
    return key


async def verify_token(token: str) -> AuthenticatedUser:
    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:
        raise AuthError("This session token could not be read.") from exc

    algorithm = str(header.get("alg", ""))
    options = {"require": ["exp", "sub"]}

    try:
        if algorithm == "HS256":
            if not settings.supabase_jwt_secret:
                raise AuthError(
                    "This deployment has no signing secret configured for the tokens it is being "
                    "sent."
                )
            claims = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience=SUPABASE_AUDIENCE,
                options=options,
            )
        elif algorithm in ASYMMETRIC_ALGORITHMS:
            key = await _signing_key(str(header.get("kid", "")))
            claims = jwt.decode(
                token,
                key,
                algorithms=list(ASYMMETRIC_ALGORITHMS),
                audience=SUPABASE_AUDIENCE,
                issuer=settings.supabase_issuer or None,
                options=options,
            )
        else:
            raise AuthError(
                f"Tokens signed with {algorithm or 'an unnamed algorithm'} are not accepted."
            )
    except AuthError:
        raise
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("This session has expired. Sign in again.") from exc
    except Exception as exc:
        raise AuthError("This session token is not valid.") from exc

    email = str(claims.get("email") or "").lower()
    user = AuthenticatedUser(
        id=str(claims["sub"]),
        email=email,
        name=_claim(claims, "name") or _claim(claims, "full_name"),
        picture=_claim(claims, "picture") or _claim(claims, "avatar_url"),
    )

    _assert_admitted(user)
    return user


def _claim(claims: dict[str, Any], name: str) -> str | None:
    value = claims.get(name)
    if value:
        return str(value)
    metadata = claims.get("user_metadata")
    if isinstance(metadata, dict) and metadata.get(name):
        return str(metadata[name])
    return None


def _assert_admitted(user: AuthenticatedUser) -> None:
    """Whether a verified identity is one this deployment lets in.

    Separate from verifying the token on purpose: the token proving who
    somebody is says nothing about whether they were meant to have an account
    here. Left unset both rules admit everyone, which is what an open sign-up
    deployment wants and what a company one should change.
    """
    allowlist = settings.auth_allowlist
    if allowlist and user.email in allowlist:
        return

    domains = settings.auth_allowed_email_domains
    if not domains:
        return

    domain = user.email.rpartition("@")[2]
    if domain not in domains:
        raise ForbiddenError(
            "This deployment is limited to approved accounts, and "
            f"{user.email or 'this account'} is not one of them."
        )
