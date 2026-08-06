from __future__ import annotations

import pytest

from app.core.config import Settings
from app.database import target as target_module
from app.database.target import (
    DatabaseTarget,
    connect_args,
    local_target,
    resolve_target,
    supabase_target,
)

DIRECT = "postgresql://postgres:s3cr3t@db.abcdefghijklm.supabase.co:5432/postgres"
POOLED = (
    "postgresql://postgres.abcdefghijklm:s3cr3t"
    "@aws-0-eu-west-1.pooler.supabase.com:6543/postgres?sslmode=require"
)


@pytest.fixture
def configure(monkeypatch: pytest.MonkeyPatch):
    def apply(**overrides: object) -> Settings:
        replacement = Settings(**overrides)  # type: ignore[arg-type]
        monkeypatch.setattr(target_module, "settings", replacement)
        return replacement

    return apply


def test_project_url_and_password_build_a_dsn() -> None:
    settings = Settings(
        supabase_url="https://abcdefghijklm.supabase.co",
        supabase_db_password="p@ss word/1",
    )

    assert settings.supabase_project_ref == "abcdefghijklm"
    assert settings.supabase_configured
    # The password is percent-encoded, or the URL parses into the wrong host.
    assert "p%40ss%20word%2F1" in settings.supabase_dsn
    assert "@db.abcdefghijklm.supabase.co:5432/postgres" in settings.supabase_dsn


def test_an_explicit_connection_string_wins() -> None:
    settings = Settings(
        supabase_db_url=DIRECT,
        supabase_url="https://ignored.supabase.co",
        supabase_db_password="ignored",
    )

    assert settings.supabase_dsn == DIRECT


def test_nothing_configured_is_not_supabase() -> None:
    assert Settings().supabase_configured is False
    assert Settings(supabase_url="https://abcdefghijklm.supabase.co").supabase_configured is False


def test_drivers_are_set_per_use(configure) -> None:
    configure(supabase_db_url=DIRECT)
    resolved = supabase_target()

    assert resolved is not None
    assert resolved.url.startswith("postgresql+asyncpg://")
    assert resolved.sync_url.startswith("postgresql+psycopg://")
    assert resolved.safe_url.count("s3cr3t") == 0


def test_libpq_only_parameters_are_kept_away_from_asyncpg(configure) -> None:
    configure(supabase_db_url=POOLED)
    resolved = supabase_target()

    assert resolved is not None
    # asyncpg raises on sslmode; TLS is a connect argument instead.
    assert "sslmode" not in resolved.url
    assert connect_args(resolved)["ssl"] == "require"
    # Alembic goes through libpq, which does want it.
    assert "sslmode=require" in resolved.sync_url


def test_the_pooler_disables_statement_caching(configure) -> None:
    configure(supabase_db_url=POOLED)
    pooled = supabase_target()
    assert pooled is not None and pooled.pooled

    args = connect_args(pooled)
    assert args["statement_cache_size"] == 0
    assert args["prepared_statement_cache_size"] == 0

    configure(supabase_db_url=DIRECT)
    direct = supabase_target()
    assert direct is not None and not direct.pooled
    assert "statement_cache_size" not in connect_args(direct)


def test_unreachable_supabase_falls_back_to_local(configure, monkeypatch) -> None:
    configure(supabase_db_url=DIRECT)
    monkeypatch.setattr(target_module, "_reachable", lambda *_, **__: False)

    resolved = resolve_target()

    assert resolved.name == "local"
    assert resolved.url == local_target().url


def test_reachable_supabase_is_preferred(configure, monkeypatch) -> None:
    configure(supabase_db_url=DIRECT)
    monkeypatch.setattr(target_module, "_reachable", lambda *_, **__: True)

    assert resolve_target().name == "supabase"


def test_fallback_can_be_refused(configure, monkeypatch) -> None:
    configure(supabase_db_url=DIRECT, database_fallback_enabled=False)
    monkeypatch.setattr(target_module, "_reachable", lambda *_, **__: False)

    with pytest.raises(RuntimeError, match="unreachable"):
        resolve_target()


def test_sqlite_is_left_alone(configure) -> None:
    configure(database_url="sqlite+aiosqlite:///./test.db")
    resolved = resolve_target()

    assert resolved.name == "local"
    assert resolved.url.startswith("sqlite+aiosqlite://")
    assert connect_args(resolved) == {}


def test_label_names_the_store() -> None:
    assert DatabaseTarget(name="supabase", url=DIRECT, sync_url=DIRECT, pooled=False).label == (
        "Supabase"
    )
    assert local_target().label == "local PostgreSQL"
