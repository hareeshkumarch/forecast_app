"""Approve-or-reject links that carry their own authority.

An administrator reading the request on their phone has no session with this
API and should not need one, so the link is the credential: a user id, a
decision and an expiry, signed with the deployment's secret key. Anyone
holding the link can act on that one account, once it is checked, and nothing
else — it grants no session and no other permission.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass

from app.core.config import settings
from app.core.errors import AppError

APPROVE = "approve"
REJECT = "reject"
DECISIONS = (APPROVE, REJECT)


class InvalidApprovalLink(AppError):
    status_code = 400
    code = "invalid_approval_link"


@dataclass(slots=True, frozen=True)
class Decision:
    user_id: uuid.UUID
    action: str


def _key() -> bytes:
    return settings.credential_secret_key.encode("utf-8")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def mint(user_id: uuid.UUID, action: str) -> str:
    if action not in DECISIONS:
        raise ValueError(f"{action!r} is not a decision this link can carry.")

    payload = {
        "u": str(user_id),
        "a": action,
        "e": int(time.time()) + settings.auth_approval_link_ttl_hours * 3600,
    }
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _b64(hmac.new(_key(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def verify(token: str) -> Decision:
    try:
        body, _, signature = token.partition(".")
        if not body or not signature:
            raise ValueError("malformed")
        expected = _b64(hmac.new(_key(), body.encode("ascii"), hashlib.sha256).digest())
        # Constant time, so a wrong signature cannot be found a character at a
        # time by measuring how long the comparison took.
        if not hmac.compare_digest(expected, signature):
            raise ValueError("bad signature")
        payload = json.loads(_unb64(body))
    except InvalidApprovalLink:
        raise
    except Exception as exc:
        raise InvalidApprovalLink(
            "This approval link could not be read. It may have been altered in transit."
        ) from exc

    if int(payload.get("e", 0)) < time.time():
        raise InvalidApprovalLink(
            "This approval link has expired. Ask for the request to be sent again."
        )
    if payload.get("a") not in DECISIONS:
        raise InvalidApprovalLink("This approval link does not carry a decision.")

    try:
        user_id = uuid.UUID(str(payload["u"]))
    except Exception as exc:
        raise InvalidApprovalLink("This approval link does not name an account.") from exc

    return Decision(user_id=user_id, action=str(payload["a"]))


def link(user_id: uuid.UUID, action: str) -> str:
    base = settings.public_api_base_url.rstrip("/")
    return f"{base}/api/auth/decide?token={mint(user_id, action)}"
