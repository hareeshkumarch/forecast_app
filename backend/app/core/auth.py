from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

SUPABASE_AUDIENCE = "authenticated"

ASYMMETRIC_ALGORITHMS = ("RS256", "ES256")

JWKS_TTL_SECONDS = 600

JWKS_TIMEOUT_SECONDS = 5.0

JWKS_MISS_COOLDOWN_SECONDS = 30

MAX_TOKEN_BYTES = 8_192

VERIFIED_CACHE_MAX = 4_096
VERIFIED_CACHE_TTL_SECONDS = 60.0


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


ANONYMOUS = AuthenticatedUser(id="anonymous", email="", name="Anonymous")


_jwks_cache: dict[str, Any] = {}
_jwks_fetched_at = 0.0
_jwks_lock = asyncio.Lock()
_jwks_misses: dict[str, float] = {}


def _fresh() -> bool:
    return bool(_jwks_cache) and time.monotonic() - _jwks_fetched_at < JWKS_TTL_SECONDS


async def _refresh_jwks() -> None:
    global _jwks_fetched_at

    url = settings.supabase_jwks_url
    if not url:
        raise AuthError("This deployment has no Supabase project configured to verify tokens.")

    try:
        async with httpx.AsyncClient(timeout=JWKS_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
            response.raise_for_status()
            document = response.json()
    except Exception as exc:
        logger.warning("Could not fetch the Supabase key set: %s", exc)
        raise AuthError("The sign-in service could not be reached to verify this session.") from exc

    replacement: dict[str, Any] = {}
    for entry in document.get("keys", []):
        try:
            replacement[entry["kid"]] = jwt.PyJWK(entry).key
        except Exception:
            continue

    if not replacement:
        logger.warning("The Supabase key set came back with no usable keys.")
        raise AuthError("The sign-in service returned no keys this deployment can verify with.")

    _jwks_cache.clear()
    _jwks_cache.update(replacement)
    _jwks_fetched_at = time.monotonic()
    _jwks_misses.clear()


async def _signing_key(kid: str) -> Any:
    cached = _jwks_cache.get(kid)
    if cached is not None and _fresh():
        return cached

    missed_at = _jwks_misses.get(kid)
    if missed_at is not None and time.monotonic() - missed_at < JWKS_MISS_COOLDOWN_SECONDS:
        raise AuthError("This session was signed with a key this deployment does not recognise.")

    async with _jwks_lock:
        cached = _jwks_cache.get(kid)
        if cached is not None and _fresh():
            return cached
        await _refresh_jwks()

    key = _jwks_cache.get(kid)
    if key is None:
        _jwks_misses[kid] = time.monotonic()
        raise AuthError("This session was signed with a key this deployment does not recognise.")
    return key


_verified: OrderedDict[str, tuple[float, AuthenticatedUser]] = OrderedDict()


def _verification_key(token: str) -> str:
    material = "|".join(
        (
            settings.supabase_jwt_secret,
            settings.supabase_issuer or "",
            settings.supabase_jwks_url or "",
            token,
        )
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _remember(key: str, user: AuthenticatedUser, expires_at: float) -> None:
    ceiling = time.time() + VERIFIED_CACHE_TTL_SECONDS
    _verified[key] = (min(expires_at, ceiling), user)
    _verified.move_to_end(key)
    while len(_verified) > VERIFIED_CACHE_MAX:
        _verified.popitem(last=False)


def _recall(key: str) -> AuthenticatedUser | None:
    entry = _verified.get(key)
    if entry is None:
        return None
    expires_at, user = entry
    if time.time() >= expires_at:
        _verified.pop(key, None)
        return None
    _verified.move_to_end(key)
    return user


def reset_caches() -> None:
    _verified.clear()
    _jwks_cache.clear()
    _jwks_misses.clear()


async def verify_token(token: str) -> AuthenticatedUser:
    if len(token) > MAX_TOKEN_BYTES:
        raise AuthError("This session token is too large to be one this deployment issued.")

    cache_key = _verification_key(token)
    remembered = _recall(cache_key)
    if remembered is not None:
        _assert_admitted(remembered)
        return remembered

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

    subject = str(claims["sub"]).strip()
    if not subject:
        raise AuthError("This session token names nobody.")
    if subject == ANONYMOUS.id:
        raise AuthError("This session token is not valid.")

    user = AuthenticatedUser(
        id=subject,
        email=str(claims.get("email") or "").lower(),
        name=_claim(claims, "name") or _claim(claims, "full_name"),
        picture=_claim(claims, "picture") or _claim(claims, "avatar_url"),
    )

    _remember(cache_key, user, float(claims["exp"]))
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
