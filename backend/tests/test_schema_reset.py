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
    squatter = sqlite3.connect(_SQLITE_DB, isolation_level=None)
    try:
        squatter.execute("BEGIN EXCLUSIVE")

        await _reset_schema()

        session.add(Dataset(name="after the reset", status=DatasetStatus.READY))
        await session.flush()
        assert (await session.execute(select(Dataset.name))).scalars().all() == ["after the reset"]
    finally:
        squatter.close()
