"""
Getting a file open at all.

Everything the profiler does happens after the file has been read into columns,
and a surprising number of real uploads never got that far: a semicolon-
delimited CSV — which is what Excel writes anywhere the comma is the decimal
separator — arrived as a single column holding the whole line, and a sheet that
opened with a report title failed outright.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from app.datasets.ingest import read_tabular

DAYS = [date(2024, 1, 1) + timedelta(days=30 * i) for i in range(12)]


def _rows(separator: str) -> str:
    return "\n".join(f"{day}{separator}{1000 + index}" for index, day in enumerate(DAYS))


def _write(tmp_path: Path, name: str, body: str, encoding: str = "utf-8") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding=encoding)
    return path


@pytest.mark.parametrize(
    ("label", "name", "body"),
    [
        ("comma", "a.csv", f"date,revenue\n{_rows(',')}"),
        ("semicolon", "b.csv", f"date;revenue\n{_rows(';')}"),
        ("pipe", "c.csv", f"date|revenue\n{_rows('|')}"),
        ("tab", "d.tsv", f"date\trevenue\n{_rows(chr(9))}"),
        ("byte order mark", "e.csv", f"﻿date,revenue\n{_rows(',')}"),
        ("title above the header", "f.csv", f"Monthly Sales Report\n\ndate,revenue\n{_rows(',')}"),
        ("title above a semicolon header", "g.csv", f"Umsatzbericht\n\ndate;revenue\n{_rows(';')}"),
        ("blank rows at the end", "h.csv", f"date,revenue\n{_rows(',')}\n,\n,\n"),
    ],
)
def test_a_file_opens_whatever_wrote_it(tmp_path: Path, label: str, name: str, body: str) -> None:
    frame = read_tabular(_write(tmp_path, name, body), Path(name).suffix)

    assert list(frame.columns) == ["date", "revenue"], label
    assert frame.height == len(DAYS), label


@pytest.mark.parametrize("encoding", ["utf-8", "cp1252", "latin-1"])
def test_a_non_english_column_name_survives_its_encoding(tmp_path: Path, encoding: str) -> None:
    path = tmp_path / f"{encoding}.csv"
    path.write_bytes("date,région\n2024-01-01,100\n".encode(encoding))

    frame = read_tabular(path, ".csv")

    assert "région" in frame.columns


@pytest.mark.parametrize(
    ("label", "body"),
    [
        ("comma inside quotes", 'date,name\n2024-01-01,"Smith, John"\n2024-02-01,"Doe, Jane"\n'),
        (
            "semicolon inside quotes",
            'date;name\n2024-01-01;"Smith; John"\n2024-02-01;"Doe; Jane"\n',
        ),
    ],
)
def test_a_delimiter_inside_a_quoted_value_is_not_a_delimiter(
    tmp_path: Path, label: str, body: str
) -> None:
    frame = read_tabular(_write(tmp_path, "q.csv", body), ".csv")

    assert list(frame.columns) == ["date", "name"], label
    assert frame.height == 2, label
