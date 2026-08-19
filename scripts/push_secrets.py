#!/usr/bin/env python3
"""Push a local env file into Infisical, so the values never leave your machine.

    python3 scripts/push_secrets.py secrets.env
    python3 scripts/push_secrets.py secrets.env --environment prod --dry-run

Reads KEY=VALUE lines, creates what is missing and updates what has changed.
Nothing is printed but key names — the point of this script is that the values
go from your machine to Infisical and nowhere else, least of all a terminal
someone is screen-sharing.

Needs the same four bootstrap variables the backend uses:

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env_file", type=Path)
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
    args = parser.parse_args()

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

    try:
        from infisical_sdk import InfisicalSDKClient
    except ImportError:
        raise SystemExit("pip install infisicalsdk") from None

    client = InfisicalSDKClient(host=os.environ.get("INFISICAL_HOST") or DEFAULT_HOST)
    client.auth.universal_auth.login(
        client_id=os.environ["INFISICAL_CLIENT_ID"],
        client_secret=os.environ["INFISICAL_CLIENT_SECRET"],
    )
    project = os.environ["INFISICAL_PROJECT_ID"]

    created = updated = failed = 0
    for key in sorted(values):
        common = {
            "project_id": project,
            "environment_slug": args.environment,
            "secret_path": args.path,
        }
        try:
            client.secrets.update_secret_by_name(
                current_secret_name=key, secret_value=values[key], **common
            )
            updated += 1
            print(f"  updated {key}")
        except Exception:
            # An update fails when the secret is not there yet, which is not an
            # error worth stopping for — it is the first run.
            try:
                client.secrets.create_secret_by_name(
                    secret_name=key, secret_value=values[key], **common
                )
                created += 1
                print(f"  created {key}")
            except Exception as exc:
                failed += 1
                print(f"  FAILED  {key}: {type(exc).__name__}: {exc}", file=sys.stderr)

    print(f"\n{created} created, {updated} updated, {failed} failed.")
    if failed:
        return 1
    print("Restart the backend for these to take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
