from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

HOST_VAR = "INFISICAL_HOST"
CLIENT_ID_VAR = "INFISICAL_CLIENT_ID"
CLIENT_SECRET_VAR = "INFISICAL_CLIENT_SECRET"
PROJECT_VAR = "INFISICAL_PROJECT_ID"
ENVIRONMENT_VAR = "INFISICAL_ENVIRONMENT"
PATH_VAR = "INFISICAL_SECRET_PATH"

DEFAULT_HOST = "https://app.infisical.com"
DEFAULT_ENVIRONMENT = "prod"
DEFAULT_PATH = "/"


@dataclass(slots=True)
class SecretsLoad:
    configured: bool = False
    loaded: bool = False
    keys: list[str] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "loaded": self.loaded,
            "count": len(self.keys),
            "error": self.error,
        }


def configured() -> bool:
    return all(os.environ.get(name) for name in (CLIENT_ID_VAR, CLIENT_SECRET_VAR, PROJECT_VAR))


def hydrate() -> SecretsLoad:
    load = SecretsLoad(configured=configured())
    if not load.configured:
        return load

    try:
        from infisical_sdk import InfisicalSDKClient
    except ImportError as exc:
        load.error = f"the Infisical SDK is not installed ({exc})"
        logger.warning("Infisical is configured but %s", load.error)
        return load

    try:
        client = InfisicalSDKClient(host=os.environ.get(HOST_VAR) or DEFAULT_HOST)
        client.auth.universal_auth.login(
            client_id=os.environ[CLIENT_ID_VAR],
            client_secret=os.environ[CLIENT_SECRET_VAR],
        )
        response = client.secrets.list_secrets(
            project_id=os.environ[PROJECT_VAR],
            environment_slug=os.environ.get(ENVIRONMENT_VAR) or DEFAULT_ENVIRONMENT,
            secret_path=os.environ.get(PATH_VAR) or DEFAULT_PATH,
            expand_secret_references=True,
            recursive=False,
        )
    except Exception as exc:
        load.error = f"{type(exc).__name__}: {exc}"
        logger.warning("Could not read secrets from Infisical: %s", load.error)
        return load

    for secret in _entries(response):
        key = getattr(secret, "secretKey", None) or getattr(secret, "secret_key", None)
        value = getattr(secret, "secretValue", None) or getattr(secret, "secret_value", None)
        if not key or value is None:
            continue
        os.environ[str(key)] = str(value)
        load.keys.append(str(key))

    load.loaded = True
    logger.info("Loaded %d secret(s) from Infisical.", len(load.keys))
    return load


def _entries(response: object) -> list:
    for name in ("secrets", "data"):
        found = getattr(response, name, None)
        if isinstance(found, list):
            return found
    if isinstance(response, dict):
        found = response.get("secrets")
        if isinstance(found, list):
            return found
    return response if isinstance(response, list) else []
