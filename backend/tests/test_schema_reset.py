from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import select

from app.models.entities import Dataset
from app.models.enums import DatasetStatus
from tests.conftest import _SQLITE_DB, _reset_schema

pytestmark = pytest.mark.skipif(
    _SQLITE_DB is None, reason="the orphaned writer this covers is a SQLite condition"
)


async def test_the_reset_survives_a_writer_that_never_lets_go(session):
    """The condition that failed four pushes in a row, made deterministic.

    A forecast run outlives the test that started it, and the aiosqlite worker
    thread behind its connection outlives the event loop that owned it — the
    suite prints `RuntimeError: Event loop is closed` from that thread when it
    happens. Such a connection can neither commit nor roll back, so the write
    lock it holds is held for the rest of the process.

    An exclusive transaction nobody will ever close stands in for it. The
    reset this replaces waited on a deadline and then raised, which is why the
    failure always surfaced at the setup of whichever unrelated test came
    next; this one has to come back with a schema regardless.
    """
    squatter = sqlite3.connect(_SQLITE_DB, isolation_level=None)
    try:
        squatter.execute("BEGIN EXCLUSIVE")

        await _reset_schema()

        session.add(Dataset(name="after the reset", status=DatasetStatus.READY))
        await session.flush()
        assert (await session.execute(select(Dataset.name))).scalars().all() == ["after the reset"]
    finally:
        squatter.close()
