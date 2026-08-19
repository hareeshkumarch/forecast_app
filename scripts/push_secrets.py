#!/usr/bin/env python3
"""Push a local env file into Infisical, so the values never leave your machine.

    python3 scripts/push_secrets.py secrets.env
    python3 scripts/push_secrets.py secrets.env --environment prod --dry-run

On an instance that is already running, the live file is the best source —
the values are known-good and nothing has to be retyped or copied out of a
terminal:

    sudo -E python3 scripts/push_secrets.py /opt/forecast/.env

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


#: Never pushed, however they got into the file. These four are the credential
#: that opens Infisical, so putting them inside it is both circular and a way
#: to end up with a stale client secret overriding the live one on the box.
#: Skipped rather than rejected, so the live /opt/forecast/.env can be handed
#: to this script as-is — which beats copying thirty lines out of a terminal
#: that treats Ctrl-C as an interrupt.
BOOTSTRAP_PREFIX = "INFISICAL_"


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
        if key.startswith(BOOTSTRAP_PREFIX):
            continue
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


#: Anything still carrying one of these is a line nobody filled in. Pushing it
#: turns a blank into a value that looks deliberate, and the failure surfaces
#: days later as mail that never arrives or a bucket that was never written.
PLACEHOLDERS = ("YOUR-PROJECT-REF", "YOUR-SITE", "YOUR_", "CHANGE-ME", "changeme", "<")


def audit(values: dict[str, str]) -> list[str]:
    """What is missing, said before anything is sent.

    Conditional on purpose: SMTP only matters if mail is wanted, storage keys
    only if a bucket is named, the JWT secret only if sign-in is on. A checker
    that demands everything gets ignored, which is worse than not having one.
    """
    problems = []

    def on(key: str) -> bool:
        return values.get(key, "").strip().lower() in {"1", "true", "yes", "on"}

    def need(keys, because: str) -> None:
        for key in keys:
            if not values.get(key, "").strip():
                problems.append(f"{key} is empty — {because}")

    for key, value in sorted(values.items()):
        if any(mark in value for mark in PLACEHOLDERS):
            problems.append(f"{key} still holds the template text, not a value")

    need(["CREDENTIAL_SECRET_KEY"], "every stored credential is encrypted with it")
    need(["SUPABASE_DB_URL"], "the API has nowhere to read or write")

    if on("AUTH_ENABLED"):
        need(["SUPABASE_JWT_SECRET"], "no token can be verified, so every request is 401")
        need(["AUTH_ADMIN_EMAILS"], "nobody could approve anybody, including themselves")
        need(["PUBLIC_API_BASE_URL"], "the approve and reject links in the mail go nowhere")
        need(["SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"], "no mail is sent")

    if values.get("STORAGE_BUCKET", "").strip():
        need(
            ["STORAGE_ENDPOINT", "STORAGE_ACCESS_KEY_ID", "STORAGE_SECRET_ACCESS_KEY"],
            "a bucket is named but nothing can be written to it",
        )

    return problems


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
        "--dry-run", action="store_true", help="Check the file and stop, sending nothing."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Push anyway when the file is incomplete. Rarely what you want.",
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

    values = read_env_file(args.env_file)
    if not values:
        raise SystemExit(f"{args.env_file} holds no values.")

    skipped = sum(
        1
        for line in args.env_file.read_text().splitlines()
        if line.strip().startswith(BOOTSTRAP_PREFIX)
    )
    if skipped:
        print(f"Skipping {skipped} INFISICAL_* line(s) — those stay on the instance.")

    print(f"{len(values)} secret(s) from {args.env_file}: {', '.join(sorted(values))}")

    problems = audit(values)
    if problems:
        print(f"\n{len(problems)} thing(s) to fix in {args.env_file}:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        if not args.force:
            print("\nNothing was sent. Fill those in, or --force past this.", file=sys.stderr)
            return 1
        print("\nPushing anyway because --force was given.", file=sys.stderr)
    elif args.dry_run:
        print("\nNothing missing.")

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
