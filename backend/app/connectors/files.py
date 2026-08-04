from __future__ import annotations

import time
from pathlib import Path

import polars as pl

from app.connectors.base import ConnectorAdapter, FormField, TableInfo, TestOutcome
from app.core.config import settings
from app.core.errors import ConnectorError
from app.datasets.ingest import CSV_SUFFIXES, EXCEL_SUFFIXES, read_tabular
from app.models.enums import ConnectorStatus, ConnectorType


class FileAdapter(ConnectorAdapter):

    supports_import = True
    suffixes: set[str] = set()

    def _resolve(self) -> Path:
        raw = str(self.config.get("file_path") or "").strip()
        if not raw:
            raise ConnectorError("No file path is configured for this connector.")


        root = settings.uploads_dir.resolve()
        candidate = (root / raw.replace("\\", "/")).resolve()


        if not candidate.is_relative_to(root):
            raise ConnectorError(
                "The file path must be inside the uploads directory. "
                "Parent-directory references are not allowed."
            )

        if not candidate.exists():
            raise ConnectorError(f"No file found at uploads/{raw}.")
        if not candidate.is_file():
            raise ConnectorError(f"uploads/{raw} is a directory, not a file.")

        suffix = candidate.suffix.lower()
        if self.suffixes and suffix not in self.suffixes:
            expected = ", ".join(sorted(self.suffixes))
            raise ConnectorError(f"Expected one of {expected}, but the file is '{suffix}'.")

        return candidate

    def test(self) -> TestOutcome:
        if not self.config.get("file_path"):
            return self._not_configured()

        started = time.perf_counter()
        try:
            path = self._resolve()
            size = path.stat().st_size
        except ConnectorError as exc:
            return TestOutcome(
                ok=False,
                status=ConnectorStatus.ERROR,
                message=exc.message,
                latency_ms=self._timed(started),
            )

        return TestOutcome(
            ok=True,
            status=ConnectorStatus.CONNECTED,
            message=f"Found {path.name} ({size / 1024:.1f} KB).",
            latency_ms=self._timed(started),
        )

    def list_tables(self) -> list[TableInfo]:
        path = self._resolve()
        frame = read_tabular(path, path.suffix.lower())
        return [
            TableInfo(
                schema_name="file",
                table_name=path.name,
                row_estimate=frame.height,
                columns=[
                    (name, str(dtype), frame[name].null_count() > 0)
                    for name, dtype in zip(frame.columns, frame.dtypes, strict=True)
                ],
            )
        ]

    def fetch(
        self, *, schema: str | None, table: str | None, query: str | None, limit: int
    ) -> pl.DataFrame:
        path = self._resolve()
        frame = read_tabular(path, path.suffix.lower())
        return frame.head(limit)


class CsvAdapter(FileAdapter):
    type = ConnectorType.CSV
    display_name = "CSV"
    suffixes = CSV_SUFFIXES
    form_fields = (
        FormField(
            "file_path",
            "File name",
            placeholder="sales_history.csv",
            help_text="Relative to the storage/uploads directory.",
        ),
    )


class ExcelAdapter(FileAdapter):
    type = ConnectorType.EXCEL
    display_name = "Excel"
    suffixes = EXCEL_SUFFIXES
    form_fields = (
        FormField(
            "file_path",
            "File name",
            placeholder="sales_history.xlsx",
            help_text="Relative to the storage/uploads directory.",
        ),
    )
