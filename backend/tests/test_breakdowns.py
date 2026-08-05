"""
Splitting a forecast by whatever the data is actually shaped like.

The dashboard used to ask every dataset about regions and categories. These
check that it now asks each dataset only about the columns that dataset has —
and that a dataset with none is told so rather than shown blank panels.
"""

from __future__ import annotations

import csv
import io
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.database.sample_data import HEADERS, generate_rows
from app.models.enums import RunStatus
from app.services import breakdown_service, dataset_service, forecast_service

GRAIN = ["region", "product_category"]


def _csv(rows: list[dict[str, object]], headers: list[str]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)  # type: ignore[arg-type]
    return buffer.getvalue().encode("utf-8")


async def _run(
    session: AsyncSession,
    rows: list[dict[str, object]],
    headers: list[str],
    *,
    grain: list[str] | None = None,
    name: str = "shape",
) -> uuid.UUID:
    dataset, _ = await dataset_service.create_from_upload(
        session, _csv(rows, headers), f"{name}.csv", name=name
    )
    await session.commit()

    run = await forecast_service.create_run(
        session, dataset_id=dataset.id, name=name, horizon=3, max_folds=1, group_by=grain
    )
    run_id = run.id
    await session.commit()

    assert await forecast_service.execute_run(run_id) is RunStatus.COMPLETED
    session.expire_all()
    return run_id


def _bare() -> tuple[list[dict[str, object]], list[str]]:
    """A date and a number. No dimensions at all — the shape with nothing to split."""
    months = sorted({str(row["order_date"]) for row in generate_rows()})
    totals: dict[str, float] = {}
    for row in generate_rows():
        totals[str(row["order_date"])] = totals.get(str(row["order_date"]), 0.0) + float(
            row["revenue"]  # type: ignore[arg-type]
        )
    return ([{"month": m, "signups": totals[m]} for m in months], ["month", "signups"])


async def test_a_dataset_with_no_dimensions_offers_no_breakdowns(session: AsyncSession) -> None:
    rows, headers = _bare()
    run_id = await _run(session, rows, headers, name="bare")

    run = await forecast_service.get_run(session, run_id)
    assert await breakdown_service.available(session, run) == []


async def test_a_grouped_run_offers_one_breakdown_per_grouping_column(
    session: AsyncSession,
) -> None:
    run_id = await _run(session, generate_rows(), list(HEADERS), grain=GRAIN, name="panel")

    run = await forecast_service.get_run(session, run_id)
    refs = await breakdown_service.available(session, run)

    by_column = {ref.column: ref for ref in refs}
    for column in GRAIN:
        assert column in by_column, f"{column} is part of the grain and must be offered"
        assert by_column[column].source == breakdown_service.FROM_SERIES
        assert by_column[column].cardinality == 5, "the sample panel has five of each"

    # Named as the customer named them, not as the code stores them.
    assert by_column["product_category"].label == "Product category"


async def test_a_breakdown_sums_across_every_other_column(session: AsyncSession) -> None:
    """
    Splitting a region-by-product run by product alone means adding the regions
    up. Reading one level of the tree would instead report region-and-product
    pairs under a product's name.
    """
    run_id = await _run(session, generate_rows(), list(HEADERS), grain=GRAIN, name="sums")
    run = await forecast_service.get_run(session, run_id)

    by_region = await breakdown_service.build(session, run, "region")
    by_product = await breakdown_service.build(session, run, "product_category")

    assert len(by_region.rows) == 5
    assert len(by_product.rows) == 5
    # Both are the same forecast seen from two sides, so both must total it.
    assert by_region.total == pytest.approx(by_product.total, rel=1e-6)
    assert sum(row.share for row in by_region.rows) == pytest.approx(100.0, abs=0.1)

    # And each is sorted largest first, which is the order a reader expects.
    values = [row.forecast for row in by_region.rows]
    assert values == sorted(values, reverse=True)


async def test_a_breakdown_closes_on_the_run_s_own_headline(session: AsyncSession) -> None:
    from app.schemas.dashboard import DashboardQuery
    from app.services import dashboard_service

    run_id = await _run(session, generate_rows(), list(HEADERS), grain=GRAIN, name="closes")
    run = await forecast_service.get_run(session, run_id)

    summary = await dashboard_service.summary(session, DashboardQuery(run_id=run_id))
    headline = next(card.value for card in summary.kpis if card.key == "total_forecast")

    for ref in summary.breakdowns:
        built = await breakdown_service.build(session, run, ref.column)
        assert built.total == pytest.approx(
            headline, rel=1e-6
        ), f"the {ref.label} split does not add up to the number on the card"


async def test_asking_for_a_column_this_run_has_not_got_is_refused(
    session: AsyncSession,
) -> None:
    rows, headers = _bare()
    run_id = await _run(session, rows, headers, name="refuses")
    run = await forecast_service.get_run(session, run_id)

    with pytest.raises(ValidationError, match="cannot be broken down"):
        await breakdown_service.build(session, run, "region")


async def test_the_summary_carries_the_splits_the_screen_should_draw(
    session: AsyncSession,
) -> None:
    from app.schemas.dashboard import DashboardQuery
    from app.services import dashboard_service

    run_id = await _run(session, generate_rows(), list(HEADERS), grain=GRAIN, name="carries")

    summary = await dashboard_service.summary(session, DashboardQuery(run_id=run_id))

    assert [ref.column for ref in summary.breakdowns][: len(GRAIN)] == GRAIN
    assert all(ref.cardinality > 1 for ref in summary.breakdowns if ref.source == "series")


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        ("product_category", "Product category"),
        ("warehouse", "Warehouse"),
        ("cost-centre", "Cost centre"),
        ("SKU", "SKU"),
        ("", ""),
    ],
)
def test_a_column_name_is_made_readable_without_being_rewritten(column: str, expected: str) -> None:
    assert breakdown_service.humanise(column) == expected
