from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.database import session as db
from app.database.target import DatabaseTarget, connect_args


class _Recorder:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, clause, *_args, **_kwargs):
        self.statements.append(str(clause))
        return


async def test_a_read_session_is_bounded_by_the_read_timeout(monkeypatch) -> None:
    monkeypatch.setattr(db, "_TIMEOUTS_APPLY", True)
    monkeypatch.setattr(settings, "db_statement_timeout_seconds", 30.0)
    recorder = _Recorder()

    await db._limit(recorder, settings.db_statement_timeout_seconds)  # type: ignore[arg-type]

    assert recorder.statements == ["SET LOCAL statement_timeout = 30000"]


async def test_a_persisting_session_gets_the_longer_budget(monkeypatch) -> None:
    monkeypatch.setattr(db, "_TIMEOUTS_APPLY", True)
    recorder = _Recorder()

    await db._limit(recorder, settings.db_write_timeout_seconds)  # type: ignore[arg-type]

    assert recorder.statements == [
        f"SET LOCAL statement_timeout = {int(settings.db_write_timeout_seconds * 1000)}"
    ]
    assert settings.db_write_timeout_seconds > settings.db_statement_timeout_seconds


async def test_zero_switches_it_off_rather_than_setting_zero(monkeypatch) -> None:
    monkeypatch.setattr(db, "_TIMEOUTS_APPLY", True)
    recorder = _Recorder()

    await db._limit(recorder, 0.0)  # type: ignore[arg-type]

    assert recorder.statements == []


async def test_sqlite_is_left_alone(monkeypatch) -> None:
    monkeypatch.setattr(db, "_TIMEOUTS_APPLY", False)
    recorder = _Recorder()

    await db._limit(recorder, 30.0)  # type: ignore[arg-type]

    assert recorder.statements == []


def test_the_driver_carries_a_backstop_under_the_transaction_setting() -> None:
    target = DatabaseTarget(
        name="local",
        url="postgresql+asyncpg://u:p@localhost:5432/db",
        sync_url="postgresql+psycopg://u:p@localhost:5432/db",
        pooled=False,
    )

    args = connect_args(target)

    assert args["command_timeout"] == settings.db_write_timeout_seconds


def test_the_backstop_never_fires_before_the_real_control_does() -> None:
    assert settings.db_write_timeout_seconds >= settings.db_statement_timeout_seconds


@pytest.mark.skipif(
    db._backend != "postgresql", reason="SQLite has no statement_timeout to observe"
)
async def test_a_statement_over_the_limit_is_actually_cancelled() -> None:
    async with db.SessionFactory() as session:
        await db._limit(session, 0.05)
        with pytest.raises(DBAPIError):
            await session.execute(text("SELECT pg_sleep(2)"))


async def test_the_budget_is_re_armed_on_every_transaction(monkeypatch) -> None:
    monkeypatch.setattr(db, "_TIMEOUTS_APPLY", True)

    class _Connection:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def exec_driver_sql(self, statement: str) -> None:
            self.statements.append(statement)

    class _Session:
        def __init__(self) -> None:
            self.info: dict[str, object] = {}

    session = _Session()
    session.info[db._BUDGET] = 30.0
    connection = _Connection()

    db._rearm_statement_timeout(session, None, connection)

    assert connection.statements == ["SET LOCAL statement_timeout = 30000"]


async def test_a_session_with_no_budget_is_left_alone(monkeypatch) -> None:
    monkeypatch.setattr(db, "_TIMEOUTS_APPLY", True)

    class _Connection:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def exec_driver_sql(self, statement: str) -> None:
            self.statements.append(statement)

    class _Session:
        def __init__(self) -> None:
            self.info: dict[str, object] = {}

    connection = _Connection()

    db._rearm_statement_timeout(_Session(), None, connection)

    assert connection.statements == []
