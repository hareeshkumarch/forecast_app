from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import polars as pl

from app.models.enums import ConnectorStatus, ConnectorType


@dataclass(slots=True)
class TestOutcome:
    ok: bool
    status: ConnectorStatus
    message: str
    latency_ms: float | None = None
    server_version: str | None = None


@dataclass(slots=True)
class TableInfo:
    schema_name: str
    table_name: str
    row_estimate: int | None = None
    columns: list[tuple[str, str, bool]] = field(default_factory=list)                          


@dataclass(slots=True)
class FormField:

    key: str
    label: str

    secret: bool = False
    required: bool = True
    kind: str = "text"                                                  
    placeholder: str = ""
    help_text: str = ""


class ConnectorAdapter(ABC):

    type: ConnectorType
    display_name: str

    supports_import: bool = False
    form_fields: tuple[FormField, ...] = ()
    default_port: int | None = None

    def __init__(self, config: dict[str, object], credentials: dict[str, str]) -> None:
        self.config = config or {}
        self.credentials = credentials or {}

    @abstractmethod
    def test(self) -> TestOutcome:
        pass

    def list_tables(self) -> list[TableInfo]:
        return []

    def fetch(
        self, *, schema: str | None, table: str | None, query: str | None, limit: int
    ) -> pl.DataFrame:
        raise NotImplementedError(
            f"{self.display_name} does not support importing data in this POC."
        )


    def _value(self, key: str) -> str:
        if key in self.credentials:
            return str(self.credentials.get(key) or "")
        return str(self.config.get(key) or "")

    def _missing_required(self) -> list[str]:
        return [f.label for f in self.form_fields if f.required and not self._value(f.key).strip()]

    def _not_configured(self) -> TestOutcome:
        missing = self._missing_required()
        detail = f" Missing: {', '.join(missing)}." if missing else ""
        return TestOutcome(
            ok=False,
            status=ConnectorStatus.NOT_CONFIGURED,
            message=f"{self.display_name} is not configured.{detail}",
        )

    @staticmethod
    def _timed(start: float) -> float:
        return round((time.perf_counter() - start) * 1000, 2)
