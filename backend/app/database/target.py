from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.engine import URL, make_url

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

ASYNC_DRIVER = "postgresql+asyncpg"
SYNC_DRIVER = "postgresql+psycopg"

_LIBPQ_ONLY = frozenset(
    {
        "sslmode",
        "sslrootcert",
        "sslcert",
        "sslkey",
        "channel_binding",
        "target_session_attrs",
        "options",
        "connect_timeout",
        "application_name",
        "gssencmode",
    }
)


@dataclass(frozen=True)
class DatabaseTarget:
    name: Literal["supabase", "local"]
    url: str
    sync_url: str
    pooled: bool

    @property
    def label(self) -> str:
        return "Supabase" if self.name == "supabase" else "local PostgreSQL"

    @property
    def safe_url(self) -> str:
        return make_url(self.url).render_as_string(hide_password=True)


def _with_driver(url: URL, driver: str) -> URL:
    backend = url.get_backend_name()
    if backend != "postgresql":
        return url
    return url.set(drivername=driver)


def _for_asyncpg(raw: str) -> str:
    url = _with_driver(make_url(raw), ASYNC_DRIVER)
    if url.get_backend_name() != "postgresql":
        return url.render_as_string(hide_password=False)
    query = {key: value for key, value in url.query.items() if key not in _LIBPQ_ONLY}
    return url.set(query=query).render_as_string(hide_password=False)


def _for_psycopg(raw: str, *, require_ssl: bool) -> str:
    url = _with_driver(make_url(raw), SYNC_DRIVER)
    if url.get_backend_name() != "postgresql":
        return url.render_as_string(hide_password=False)
    query = dict(url.query)
    if require_ssl:
        query.setdefault("sslmode", "require")
    return url.set(query=query).render_as_string(hide_password=False)


def _is_pooled(raw: str) -> bool:
    url = make_url(raw)
    host = (url.host or "").lower()
    return "pooler.supabase" in host or url.port == 6543


def _reachable(raw: str, timeout: float) -> bool:
    url = make_url(raw)
    host, port = url.host, url.port or 5432
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError as exc:
        logger.warning("Supabase at %s:%s is not reachable: %s", host, port, exc)
        return False


def supabase_target() -> DatabaseTarget | None:
    dsn = settings.supabase_dsn
    if not dsn:
        return None
    return DatabaseTarget(
        name="supabase",
        url=_for_asyncpg(dsn),
        sync_url=_for_psycopg(dsn, require_ssl=True),
        pooled=_is_pooled(dsn),
    )


def local_target() -> DatabaseTarget:
    return DatabaseTarget(
        name="local",
        url=settings.database_url,
        sync_url=settings.sync_database_url,
        pooled=False,
    )


def resolve_target() -> DatabaseTarget:
    supabase = supabase_target()
    if supabase is None:
        logger.info("Supabase is not configured; using %s.", local_target().safe_url)
        return local_target()

    if _reachable(supabase.url, settings.database_probe_timeout):
        logger.info("Primary store: Supabase at %s.", supabase.safe_url)
        return supabase

    if not settings.database_fallback_enabled:
        raise RuntimeError(
            "Supabase is configured but unreachable, and DATABASE_FALLBACK_ENABLED is false."
        )

    fallback = local_target()
    logger.warning(
        "Supabase is unreachable; falling back to %s. Rows written now stay on this node.",
        fallback.safe_url,
    )
    return fallback


def connect_args(target: DatabaseTarget) -> dict[str, object]:
    backend = make_url(target.url).get_backend_name()

    if backend == "sqlite":
        return {"timeout": 30}

    if backend != "postgresql":
        return {}

    args: dict[str, object] = {}
    if settings.db_write_timeout_seconds > 0:
        args["command_timeout"] = settings.db_write_timeout_seconds
    if target.name == "supabase":
        args["ssl"] = "require"
    if target.pooled:
        args["statement_cache_size"] = 0
        args["prepared_statement_cache_size"] = 0
        args["prepared_statement_name_func"] = lambda: ""
    return args
