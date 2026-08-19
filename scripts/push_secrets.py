#!/usr/bin/env python3
"""Push a local env file into Infisical, so the values never leave your machine.

    python3 scripts/push_secrets.py secrets.env
    python3 scripts/push_secrets.py secrets.env --environment prod --dry-run

Reads KEY=VALUE lines, creates what is missing and updates what has changed.
Nothing is printed but key names — the point of this script is that the values
go from your machine to Infisical and nowhere else, least of all a terminal
someone is screen-sharing.

Runs on a bare python3 — it uses the Infisical SDK if it is installed and\nits HTTP API if it is not, so there is nothing to install first.\n\nNeeds the same four bootstrap variables the backend uses:

    INFISICAL_CLIENT_ID, INFISICAL_CLIENT_SECRET, INFISICAL_PROJECT_ID
    INFISICAL_HOST (optional, defaults to Infisical Cloud)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

DEFAULT_HOST = "https://app.infisical.com"
DEFAULT_ENVIRONMENT = "prod"
DEFAULT_PATH = "/"


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"{path}:{number}: expected KEY=VALUE, found {line!r}")
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Quotes are how a value with spaces survives a shell, and are not
        # part of the value itself.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


class _Rest:
    """Infisical over its HTTP API, using nothing but the standard library.

    The SDK is one pip install away, but this script exists to be run once, on
    a laptop, by somebody who wants their secrets in and their evening back.
    Requiring a virtualenv first is how a two-minute job becomes a twenty
    minute one, so the SDK is used when it happens to be there and this is
    used when it is not. Same three calls either way.
    """

    def __init__(self, host: str, client_id: str, client_secret: str) -> None:
        self.host = host.rstrip("/")
        self.token = self._post(
            "/api/v1/auth/universal-auth/login",
            {"clientId": client_id, "clientSecret": client_secret},
        )["accessToken"]

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        import json
        import urllib.error
        import urllib.request

        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.host + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if getattr(self, "token", None):
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:400]
            raise RuntimeError(f"HTTP {exc.code} from {path}: {detail}") from None

    def _post(self, path: str, body: dict) -> dict:
        return self._request("POST", path, body)

    def list(self, project: str, environment: str, path: str) -> list[dict]:
        import urllib.parse

        query = urllib.parse.urlencode(
            {"workspaceId": project, "environment": environment, "secretPath": path}
        )
        return self._request("GET", f"/api/v3/secrets/raw?{query}").get("secrets") or []

    def put(self, name: str, value: str, project: str, environment: str, path: str) -> None:
        body = {
            "workspaceId": project,
            "environment": environment,
            "secretPath": path,
            "secretValue": value,
        }
        quoted = name.replace("/", "%2F")
        try:
            self._request("PATCH", f"/api/v3/secrets/raw/{quoted}", body)
        except RuntimeError:
            # Not there yet, which on a first run is every one of them.
            self._request("POST", f"/api/v3/secrets/raw/{quoted}", body)


class _Sdk:
    def __init__(self, host: str, client_id: str, client_secret: str) -> None:
        from infisical_sdk import InfisicalSDKClient

        self.client = InfisicalSDKClient(host=host)
        self.client.auth.universal_auth.login(
            client_id=client_id, client_secret=client_secret
        )

    def list(self, project: str, environment: str, path: str) -> list:
        response = self.client.secrets.list_secrets(
            project_id=project, environment_slug=environment, secret_path=path
        )
        return getattr(response, "secrets", None) or getattr(response, "data", None) or []

    def put(self, name: str, value: str, project: str, environment: str, path: str) -> None:
        common = {
            "project_id": project,
            "environment_slug": environment,
            "secret_path": path,
        }
        try:
            self.client.secrets.update_secret_by_name(
                current_secret_name=name, secret_value=value, **common
            )
        except Exception:
            self.client.secrets.create_secret_by_name(
                secret_name=name, secret_value=value, **common
            )


def _key_of(secret) -> str:
    if isinstance(secret, dict):
        return str(secret.get("secretKey") or secret.get("secret_key") or "")
    return str(getattr(secret, "secretKey", None) or getattr(secret, "secret_key", "") or "")


def _client():
    missing = [
        name
        for name in ("INFISICAL_CLIENT_ID", "INFISICAL_CLIENT_SECRET", "INFISICAL_PROJECT_ID")
        if not os.environ.get(name)
    ]
    if missing:
        hint = ""
        if "INFISICAL_PROJECT_ID" in missing:
            # The one nobody has to hand, and the one with a findable answer.
            hint = (
                "\n\nINFISICAL_PROJECT_ID is the id in the address bar when the project is "
                "open:\n  https://app.infisical.com/project/<THIS>/secrets/prod\n"
                "It is also under Project Settings -> General -> Project ID."
            )
        raise SystemExit(f"Set {', '.join(missing)} before running this.{hint}")

    host = os.environ.get("INFISICAL_HOST") or DEFAULT_HOST
    credentials = (host, os.environ["INFISICAL_CLIENT_ID"], os.environ["INFISICAL_CLIENT_SECRET"])
    try:
        return _Sdk(*credentials)
    except ImportError:
        return _Rest(*credentials)


def check() -> int:
    """Prove the machine identity works before anything depends on it.

    The failure everybody hits is an identity created at the organisation and
    never added to the project: the credentials are valid, the login succeeds,
    and every read comes back empty or forbidden. Doing it here means finding
    that out now rather than from a backend that quietly fell back to
    environment variables.
    """
    environment = os.environ.get("INFISICAL_ENVIRONMENT") or DEFAULT_ENVIRONMENT
    path = os.environ.get("INFISICAL_SECRET_PATH") or DEFAULT_PATH

    client = _client()
    print(f"Logged in. Reading {environment}{path} ...")

    try:
        secrets = client.list(os.environ["INFISICAL_PROJECT_ID"], environment, path)
    except Exception as exc:
        print(f"\nCould not read the project: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(
            "\nThe usual cause is the identity not being a member of the project. Add it under\n"
            "Project -> Access Control -> Identities, with a role that can read secrets.",
            file=sys.stderr,
        )
        return 1

    names = sorted(name for name in (_key_of(s) for s in secrets) if name)
    if names:
        print(f"{len(names)} secret(s) already there: {', '.join(names)}")
    else:
        print("Reachable, and empty. Push an env file to fill it.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env_file", type=Path, nargs="?")
    parser.add_argument(
        "--environment",
        default=os.environ.get("INFISICAL_ENVIRONMENT") or DEFAULT_ENVIRONMENT,
    )
    parser.add_argument(
        "--path", default=os.environ.get("INFISICAL_SECRET_PATH") or DEFAULT_PATH
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="List what would change and stop."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Log in, list what is already there, and stop. Proves the identity works.",
    )
    args = parser.parse_args()

    if args.check:
        return check()

    if args.env_file is None:
        raise SystemExit("Pass an env file, or --check to test the connection.")
    if not args.env_file.exists():
        raise SystemExit(f"{args.env_file} does not exist.")

    missing = [
        name
        for name in (
            "INFISICAL_CLIENT_ID",
            "INFISICAL_CLIENT_SECRET",
            "INFISICAL_PROJECT_ID",
        )
        if not os.environ.get(name)
    ]
    if missing:
        raise SystemExit(f"Set {', '.join(missing)} before running this.")

    values = read_env_file(args.env_file)
    if not values:
        raise SystemExit(f"{args.env_file} holds no values.")

    print(f"{len(values)} secret(s) from {args.env_file}: {', '.join(sorted(values))}")
    if args.dry_run:
        print("Dry run — nothing was sent.")
        return 0

    client = _client()
    project = os.environ["INFISICAL_PROJECT_ID"]

    pushed = failed = 0
    for key in sorted(values):
        try:
            client.put(key, values[key], project, args.environment, args.path)
            pushed += 1
            print(f"  pushed  {key}")
        except Exception as exc:
            failed += 1
            print(f"  FAILED  {key}: {type(exc).__name__}: {exc}", file=sys.stderr)

    print(f"\n{pushed} pushed, {failed} failed.")
    if failed:
        return 1
    print("Restart the backend for these to take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
