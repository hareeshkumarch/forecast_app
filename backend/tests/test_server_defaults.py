from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.database.base import Base

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def emitted_ddl() -> str:
    """The whole schema as Postgres would receive it, without needing a server.

    `alembic check` compares types but not server defaults, so a column whose
    model promises `now()` and whose migration omits it survives a green CI.
    """
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "base:head", "--sql"],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(BACKEND),
            "SYNC_DATABASE_URL": "postgresql+psycopg://u:p@localhost/db",
            "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db",
        },
    )
    if result.returncode != 0:
        pytest.skip(f"offline DDL unavailable: {result.stderr[-300:]}")
    return result.stdout


def _emitted_defaults(ddl: str) -> dict[tuple[str, str], bool]:
    found: dict[tuple[str, str], bool] = {}
    for table, body in re.findall(r"CREATE TABLE (\w+) \((.*?)\n\);", ddl, re.S):
        for raw in body.splitlines():
            line = raw.strip().rstrip(",")
            match = re.match(r"^(\w+)\s+(.*)$", line)
            if match is None or match.group(1).upper() in {
                "CONSTRAINT",
                "PRIMARY",
                "UNIQUE",
                "FOREIGN",
                "CHECK",
            }:
                continue
            found[(table, match.group(1))] = "DEFAULT" in match.group(2)

    # A later migration can add or remove one, and several do.
    for table, column, verb in re.findall(
        r"ALTER TABLE (\w+) ALTER COLUMN (\w+) (SET DEFAULT|DROP DEFAULT)", ddl
    ):
        found[(table, column)] = verb == "SET DEFAULT"
    return found


def test_every_promised_server_default_is_actually_created(emitted_ddl: str) -> None:
    """A model that declares one and a migration that omits it is the harmful
    direction: a write outside the ORM hits a not-null violation on a column the
    model says the database fills in."""
    emitted = _emitted_defaults(emitted_ddl)
    assert emitted, "no CREATE TABLE statements were parsed"

    broken = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if column.server_default is not None and emitted.get((table.name, column.name)) is False
    ]

    assert not broken, "declared server_default, never emitted: " + ", ".join(sorted(broken))
