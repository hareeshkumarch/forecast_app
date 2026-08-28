"""Secrets from Infisical, loaded before anything reads configuration.

The values land in the process environment rather than in a bespoke settings
path, so every setting already defined keeps working exactly as written — the
change is where the values come from, not how sixty of them are declared.

Bootstrap credentials are read from the real environment, and have to be: a
secret manager cannot hold the credential used to reach it.
"""

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
    #: Names only. The values are secrets and never reach a log line.
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
    """Fetch every secret for this environment and put it in os.environ.

    Infisical wins over a value already in the environment. It has been made
    the source of truth, and a leftover variable on a box silently overriding
    the thing everyone is editing is the failure that wastes an afternoon.
    """
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
    """The secrets out of whatever shape the SDK returned.

    Read defensively rather than against one version's attribute name: this
    runs before the app has a config to fall back on, and a rename upstream
    should degrade to "no secrets" rather than to a crash at import time.
    """
    for name in ("secrets", "data"):
        found = getattr(response, name, None)
        if isinstance(found, list):
            return found
    if isinstance(response, dict):
        found = response.get("secrets")
        if isinstance(found, list):
            return found
    return response if isinstance(response, list) else []
