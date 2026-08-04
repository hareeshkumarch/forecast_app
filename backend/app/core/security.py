from __future__ import annotations

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.errors import AppError

_INSECURE_DEFAULT = "dev-only-insecure-key-change-me"


class CredentialDecryptionError(AppError):
    status_code = 500
    code = "credential_decryption_failed"


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.credential_secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def using_insecure_default_key() -> bool:
    return settings.credential_secret_key == _INSECURE_DEFAULT


def encrypt_credentials(payload: dict[str, str]) -> tuple[str, list[str]]:
    cleaned = {k: v for k, v in payload.items() if v not in (None, "")}
    token = _fernet().encrypt(json.dumps(cleaned, sort_keys=True).encode("utf-8"))
    return token.decode("utf-8"), sorted(cleaned)


def decrypt_credentials(ciphertext: str) -> dict[str, str]:
    try:
        raw = _fernet().decrypt(ciphertext.encode("utf-8"))
    except InvalidToken as exc:
        raise CredentialDecryptionError(
            "Stored credentials could not be decrypted. This usually means "
            "CREDENTIAL_SECRET_KEY changed after the connector was saved. "
            "Re-enter the credentials to fix it."
        ) from exc

    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise CredentialDecryptionError("Stored credential payload is malformed.")
    return {str(k): str(v) for k, v in decoded.items()}


def mask(value: str, *, keep: int = 2) -> str:
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "*" * (len(value) - keep)
