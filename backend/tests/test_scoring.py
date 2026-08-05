"""
Scoring a forecast against what actually happened.

The setup throughout is the one this feature exists for: a run fitted on data
that stops partway through the panel, then scored against the same panel once
the rest of it has arrived. Because the tail is withheld rather than invented,
the actuals are real and the realized error is a number worth asserting on.

What these mostly check is the refusals. A metric that is confidently wrong is
worse than an absent one, and every way this could produce a confidently wrong
number — a half-finished period, a pooled tail, a series the source has never
heard of — has a test that says so.
"""

from __future__ import annotations

import base64
import csv
import io
import re
import uuid
import zlib
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.database.sample_data import HEADERS, generate_rows
from app.models.enums import MeasureAggregation, RunStatus
from app.services import dataset_service, forecast_service, scoring_service

GRAIN = ["region", "product_category"]
HORIZON = 3
#: One month more than the horizon is withheld, so the full panel carries data
#: *after* the last month the run forecast. Without that extra month the last
#: one could not be settled — nothing following it means nothing to prove it
#: finished — and the happy path would never reach a full horizon.
WITHHELD = HORIZON + 1


def _csv(rows: list[dict[str, object]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(HEADERS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)  # type: ignore[arg-type]
    return buffer.getvalue().encode("utf-8")


def _months() -> list[date]:
    return sorted({date.fromisoformat(str(row["order_date"])) for row in generate_rows()})


def _rows_through(last: date) -> list[dict[str, object]]:
    return [row for row in generate_rows() if date.fromisoformat(str(row["order_date"])) <= last]


async def _dataset(session: AsyncSession, rows: list[dict[str, object]], name: str) -> uuid.UUID:
    dataset, _profile = await dataset_service.create_from_upload(
        session, _csv(rows), f"{name}.csv", name=name
    )
    await session.commit()
    return dataset.id


async def _run_on(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    *,
    grain: list[str] | None = None,
    aggregation: MeasureAggregation = MeasureAggregation.SUM,
) -> uuid.UUID:
    run = await forecast_service.create_run(
        session,
        dataset_id=dataset_id,
        name="scored",
        horizon=HORIZON,
        max_folds=1,
        group_by=grain,
        aggregation=aggregation,
    )
    run_id = run.id
    await session.commit()

    assert await forecast_service.execute_run(run_id) is RunStatus.COMPLETED
    session.expire_all()
    return run_id


@pytest.fixture
async def truncated_and_full(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """A run's worth of history, and the same panel once the horizon has passed."""
    months = _months()
    cutoff = months[-(WITHHELD + 1)]

    partial = await _dataset(session, _rows_through(cutoff), "Through the cutoff")
    full = await _dataset(session, generate_rows(), "The whole panel")
    return partial, full


# ---------------------------------------------------------------- the happy path


async def test_a_run_is_scored_against_the_actuals_that_arrived_after_it(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    partial, full = truncated_and_full
    run_id = await _run_on(session, partial)

    card = await scoring_service.score_run(session, run_id, dataset_id=full)

    assert card.scored is True
    assert card.scored_periods == HORIZON, "every withheld month is settled in the full panel"
    assert card.pending_periods == 0
    assert card.source_dataset_id == full
    assert card.blocked_reason is None

    assert card.actual_total > 0
    assert card.wmape is not None and card.wmape >= 0
    assert card.mae is not None and card.mae >= 0
    assert card.bias is not None

    # How good the forecast was is not this test's business — the panel puts a
    # 34% promotion inside the horizon precisely so realized error can diverge
    # from backtest error. What is asserted is that the two sides of the
    # comparison are the same kind of number: a factor out here would mean the
    # windows are misaligned, which is the failure that looks like bad accuracy
    # and is not.
    assert 0.0 <= card.wmape < 100.0
    assert card.forecast_total == pytest.approx(card.actual_total, rel=0.5)


async def test_the_score_is_stored_on_the_run_it_describes(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    partial, full = truncated_and_full
    run_id = await _run_on(session, partial)

    card = await scoring_service.score_run(session, run_id, dataset_id=full)
    await session.commit()
    session.expire_all()

    run = await forecast_service.get_run(session, run_id)
    assert run.scored_at is not None
    assert run.scored_dataset_id == full
    assert run.scored_periods == card.scored_periods
    assert run.realized_wmape == pytest.approx(card.wmape)
    assert run.realized_bias == pytest.approx(card.bias)

    again = await scoring_service.stored_scorecard(session, run_id)
    assert again.wmape == pytest.approx(card.wmape)
    assert again.source_dataset_name == "The whole panel"
    assert again.blocked_reason is None


async def test_the_actuals_are_written_onto_the_points_they_belong_to(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    partial, full = truncated_and_full
    run_id = await _run_on(session, partial)

    await scoring_service.score_run(session, run_id, dataset_id=full)
    await session.commit()

    from app.models.enums import PointKind

    points = await forecast_service.points_for_run(session, run_id)
    scored = [p for p in points if p.kind is PointKind.FORECAST]

    assert scored, "the run forecast something"
    assert all(point.actual is not None for point in scored), "every settled point is graded"

    # And the graded actual is the panel's own number for that month.
    from app.datasets import queries

    dataset = await dataset_service.get_dataset(session, full)
    truth = queries.aggregate_series(
        __import__("pathlib").Path(dataset.parquet_path or ""),
        "order_date",
        "revenue",
        (await forecast_service.get_run(session, run_id)).frequency,
    )
    by_period = dict(zip(truth.periods, truth.values, strict=True))
    for point in scored:
        assert point.actual == pytest.approx(by_period[point.period], rel=1e-6)


async def test_coverage_says_whether_the_interval_kept_its_promise(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    partial, full = truncated_and_full
    run_id = await _run_on(session, partial)

    card = await scoring_service.score_run(session, run_id, dataset_id=full)

    assert card.coverage is not None
    # Every settled point either fell inside its band or it did not, so over a
    # three-period horizon the share can only be none, one, two or all of them.
    reachable = [caught * 100.0 / HORIZON for caught in range(HORIZON + 1)]
    assert any(card.coverage == pytest.approx(value) for value in reachable), card.coverage


# ------------------------------------------------------------------ the refusals


async def test_a_period_still_being_lived_through_is_not_scored(
    session: AsyncSession,
) -> None:
    """
    The one number that would be confidently wrong: a whole month's forecast
    against a fortnight of actuals reads as a collapse that never happened.
    """
    months = _months()
    cutoff = months[-(WITHHELD + 1)]
    partial = await _dataset(session, _rows_through(cutoff), "Through the cutoff")
    run_id = await _run_on(session, partial)

    # A source that reaches into the first forecast month but no further. The
    # panel stamps each month on its first day, so a mid-month row is the only
    # way to build a genuinely half-finished period.
    half = dict(generate_rows()[0])
    half["order_date"] = (months[-WITHHELD] + timedelta(days=13)).isoformat()
    stops_midway = await _dataset(session, [*_rows_through(cutoff), half], "Stops midway")

    card = await scoring_service.score_run(session, run_id, dataset_id=stops_midway)

    assert card.scored is False
    assert card.scored_periods == 0
    assert card.pending_periods == HORIZON
    assert card.wmape is None
    assert card.blocked_reason is not None and "Stops midway" in card.blocked_reason


async def test_a_source_that_stops_before_the_horizon_scores_nothing(
    session: AsyncSession,
) -> None:
    months = _months()
    cutoff = months[-(WITHHELD + 1)]
    partial = await _dataset(session, _rows_through(cutoff), "Through the cutoff")
    run_id = await _run_on(session, partial)

    card = await scoring_service.score_run(session, run_id, dataset_id=partial)

    assert card.scored is False
    assert card.wmape is None
    assert card.blocked_reason is not None


async def test_only_the_periods_that_have_finished_are_scored(
    session: AsyncSession,
) -> None:
    """A horizon settles a period at a time, and the card has to say so."""
    months = _months()
    cutoff = months[-(WITHHELD + 1)]
    partial = await _dataset(session, _rows_through(cutoff), "Through the cutoff")
    run_id = await _run_on(session, partial)

    one_month_on = await _dataset(session, _rows_through(months[-WITHHELD]), "One month on")
    card = await scoring_service.score_run(session, run_id, dataset_id=one_month_on)

    # The first forecast month is present but is the source's last, so it is
    # not settled; nothing earlier is left to settle. One more month would.
    assert card.scored_periods == 0
    assert card.pending_periods == HORIZON

    two_months_on = await _dataset(session, _rows_through(months[-WITHHELD + 1]), "Two months on")
    card = await scoring_service.score_run(session, run_id, dataset_id=two_months_on)

    assert card.scored_periods == 1, "the first month is settled once the second has data"
    assert card.pending_periods == HORIZON - 1
    assert card.wmape is not None


async def test_a_run_that_never_finished_cannot_be_scored(session: AsyncSession) -> None:
    months = _months()
    partial = await _dataset(session, _rows_through(months[-(WITHHELD + 1)]), "Partial")
    run = await forecast_service.create_run(session, dataset_id=partial, horizon=HORIZON)
    await session.commit()

    with pytest.raises(ValidationError):
        await scoring_service.score_run(session, run.id)


async def test_a_source_missing_the_run_s_columns_is_refused(session: AsyncSession) -> None:
    months = _months()
    partial = await _dataset(session, _rows_through(months[-(WITHHELD + 1)]), "Partial")
    run_id = await _run_on(session, partial, grain=GRAIN)

    stripped = [
        {key: value for key, value in row.items() if key != "product_category"}
        for row in generate_rows()
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=[h for h in HEADERS if h != "product_category"], lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(stripped)  # type: ignore[arg-type]

    dataset, _ = await dataset_service.create_from_upload(
        session, buffer.getvalue().encode("utf-8"), "narrow.csv", name="Missing a grain column"
    )
    await session.commit()

    with pytest.raises(ValidationError, match="product_category"):
        await scoring_service.score_run(session, run_id, dataset_id=dataset.id)


# ------------------------------------------------------------------- the grain


async def test_every_series_in_the_tree_is_scored_against_its_own_actuals(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    partial, full = truncated_and_full
    run_id = await _run_on(session, partial, grain=GRAIN)

    card = await scoring_service.score_run(session, run_id, dataset_id=full)

    assert card.scored_periods == HORIZON
    assert card.series, "a grouped run scores its tree, not only its top line"

    scored = [row for row in card.series if row.unscored_reason is None]
    assert {row.level for row in scored} == {0, 1, 2}
    assert all(row.wmape is not None for row in scored)
    assert all(row.actual_total is not None for row in scored)

    # A parent's actual is its children's, at every level — the same property
    # the forecast side of the tree already has.
    for level in (1, 2):
        assert sum(
            row.actual_total or 0.0 for row in scored if row.level == level
        ) == pytest.approx(
            next(row.actual_total for row in scored if row.level == 0), rel=1e-6
        ), f"level {level} actuals do not close on the total"


async def test_the_root_of_the_tree_is_scored_as_the_run_s_own_line(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """
    The root stores no curve of its own — that would be a second copy of the
    top line — so it is scored from the top line rather than reported as a
    series that forecast nothing.
    """
    partial, full = truncated_and_full
    run_id = await _run_on(session, partial, grain=GRAIN)

    card = await scoring_service.score_run(session, run_id, dataset_id=full)
    root = next(row for row in card.series if row.level == 0)

    assert root.unscored_reason is None
    assert root.wmape == pytest.approx(card.wmape)
    assert root.actual_total == pytest.approx(card.actual_total, rel=1e-6)


async def test_a_series_the_source_never_recorded_is_scored_as_a_real_zero(
    session: AsyncSession,
) -> None:
    """Under a sum, nothing recorded is nothing sold — which is a genuine miss."""
    months = _months()
    cutoff = months[-(WITHHELD + 1)]
    partial = await _dataset(session, _rows_through(cutoff), "Through the cutoff")
    run_id = await _run_on(session, partial, grain=["region"])

    # A panel the last region drops out of entirely after the cutoff.
    dropped = "Middle East & Africa"
    thinned = [
        row
        for row in generate_rows()
        if row["region"] != dropped or date.fromisoformat(str(row["order_date"])) <= cutoff
    ]
    source = await _dataset(session, thinned, "A region that stopped")

    card = await scoring_service.score_run(session, run_id, dataset_id=source)
    gone = next(row for row in card.series if row.label == dropped)

    assert gone.unscored_reason is None, "a sum can tell 'none' from 'unknown'"
    assert gone.actual_total == pytest.approx(0.0)
    assert gone.wmape is None, "wMAPE has no denominator when the actual is zero"


async def test_a_mean_run_will_not_call_a_missing_series_zero(session: AsyncSession) -> None:
    """
    An average of nothing is unknown, not zero — and scoring it as zero would
    manufacture a hundred-percent miss out of a gap in the data.
    """
    months = _months()
    cutoff = months[-(WITHHELD + 1)]
    partial = await _dataset(session, _rows_through(cutoff), "Through the cutoff")
    run_id = await _run_on(session, partial, grain=["region"], aggregation=MeasureAggregation.MEAN)

    dropped = "Middle East & Africa"
    thinned = [
        row
        for row in generate_rows()
        if row["region"] != dropped or date.fromisoformat(str(row["order_date"])) <= cutoff
    ]
    source = await _dataset(session, thinned, "A region that stopped")

    card = await scoring_service.score_run(session, run_id, dataset_id=source)
    gone = next(row for row in card.series if row.label == dropped)

    assert gone.unscored_reason == scoring_service.NOT_RECORDED
    assert gone.actual_total is None
    assert gone.wmape is None


async def test_a_combination_that_appeared_after_the_run_is_counted_not_hidden(
    session: AsyncSession,
) -> None:
    months = _months()
    cutoff = months[-(WITHHELD + 1)]
    partial = await _dataset(session, _rows_through(cutoff), "Through the cutoff")
    run_id = await _run_on(session, partial, grain=["product_category"])

    newcomer = [
        {**row, "product_category": "Product E"}
        for row in generate_rows()
        if date.fromisoformat(str(row["order_date"])) > cutoff
    ]
    source = await _dataset(session, [*generate_rows(), *newcomer], "With a new product")

    card = await scoring_service.score_run(session, run_id, dataset_id=source)

    assert card.unforecast_keys == 1, "the run never forecast Product E"
    assert all(row.label != "Product E" for row in card.series)
    # It still lands in the top line, which is what makes the count worth having.
    assert card.actual_total > sum(row.actual_total or 0.0 for row in card.series if row.level == 1)


# ---------------------------------------------------------- choosing the source


async def test_the_newest_dataset_that_covers_the_horizon_is_chosen(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    partial, full = truncated_and_full
    run_id = await _run_on(session, partial)

    card = await scoring_service.score_run(session, run_id)

    assert card.source_dataset_id == full, "the run's own dataset stops before the horizon"
    assert card.scored is True


async def test_a_run_with_nothing_to_score_against_says_so_rather_than_failing(
    session: AsyncSession,
) -> None:
    months = _months()
    partial = await _dataset(session, _rows_through(months[-(WITHHELD + 1)]), "Only this")
    run_id = await _run_on(session, partial)

    card = await scoring_service.score_run(session, run_id)

    assert card.scored is False
    assert card.wmape is None
    assert card.blocked_reason is not None and "No dataset" in card.blocked_reason

    unscored = await scoring_service.stored_scorecard(session, run_id)
    assert unscored.scored is False
    assert unscored.blocked_reason is not None and "Not scored yet" in unscored.blocked_reason


# ------------------------------------------------------------------ over the API


async def test_the_endpoint_scores_and_then_reports_what_it_stored(
    client: AsyncClient,
) -> None:
    months = _months()
    cutoff = months[-(WITHHELD + 1)]

    async def upload(rows: list[dict[str, object]], name: str) -> str:
        response = await client.post(
            "/api/datasets/upload",
            files={"file": (f"{name}.csv", _csv(rows), "text/csv")},
            data={"name": name},
        )
        assert response.status_code == 201, response.text
        return response.json()["dataset"]["id"]

    partial = await upload(_rows_through(cutoff), "Through the cutoff")
    await upload(generate_rows(), "The whole panel")

    started = await client.post(
        "/api/forecasts/run",
        json={"dataset_id": partial, "horizon": HORIZON, "max_folds": 1, "group_by": GRAIN},
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]

    async with client.stream("GET", f"/api/forecasts/{run_id}/events") as stream:
        async for _ in stream.aiter_lines():
            pass

    before = await client.get(f"/api/forecasts/{run_id}/score")
    assert before.status_code == 200, before.text
    assert before.json()["scored"] is False
    assert "Not scored yet" in before.json()["blocked_reason"]

    scored = await client.post(f"/api/forecasts/{run_id}/score", json={})
    assert scored.status_code == 200, scored.text
    body = scored.json()

    assert body["scored"] is True
    assert body["scored_periods"] == HORIZON
    assert body["source_dataset_name"] == "The whole panel"
    assert body["accuracy"] == pytest.approx(round(max(0.0, 100.0 - body["wmape"]), 2))
    assert body["currency"] is True, "revenue is money"
    assert body["series"], "the tree comes back worst first"

    ranked = [row["wmape"] for row in body["series"] if row["wmape"] is not None]
    assert ranked == sorted(ranked, reverse=True)

    after = await client.get(f"/api/forecasts/{run_id}/score")
    assert after.json()["wmape"] == pytest.approx(body["wmape"])

    # And the run itself now carries the realized number alongside the backtest one.
    detail = await client.get(f"/api/forecasts/{run_id}")
    assert detail.json()["realized_wmape"] == pytest.approx(body["wmape"])
    assert detail.json()["realized_accuracy"] == pytest.approx(body["accuracy"])


def _pdf_text(body: bytes) -> str:
    """
    The strings a PDF draws, without a PDF library.

    ReportLab writes each page as an ASCII85-then-Flate stream of text
    operators, and both codecs are in the standard library — worth the twelve
    lines to keep the report's own rendering under test without adding a
    dependency the deployment does not need.
    """
    drawn: list[bytes] = []
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", body, re.S):
        try:
            chunk = zlib.decompress(base64.a85decode(raw.rstrip(b"\r\n"), adobe=True))
        except Exception:
            continue
        drawn += [match.group(1) for match in re.finditer(rb"\(((?:\\.|[^\\()])*)\)", chunk)]
    return " ".join(part.decode("latin-1") for part in drawn)


async def test_the_report_gains_a_scorecard_once_the_run_has_one(
    client: AsyncClient,
) -> None:
    """
    The section is absent before scoring and present after, with the graded
    numbers in it. An empty "how it did" heading reads as a failure rather
    than as a horizon still running.
    """
    months = _months()
    cutoff = months[-(WITHHELD + 1)]

    async def upload(rows: list[dict[str, object]], name: str) -> str:
        response = await client.post(
            "/api/datasets/upload",
            files={"file": (f"{name}.csv", _csv(rows), "text/csv")},
            data={"name": name},
        )
        assert response.status_code == 201, response.text
        return response.json()["dataset"]["id"]

    partial = await upload(_rows_through(cutoff), "Through the cutoff")
    await upload(generate_rows(), "The whole panel")

    started = await client.post(
        "/api/forecasts/run",
        json={"dataset_id": partial, "horizon": HORIZON, "max_folds": 1},
    )
    run_id = started.json()["id"]
    async with client.stream("GET", f"/api/forecasts/{run_id}/events") as stream:
        async for _ in stream.aiter_lines():
            pass

    before = await client.get(f"/api/exports/{run_id}?format=pdf")
    assert before.status_code == 200
    assert "ACTUALLY DID" not in _pdf_text(before.content)

    card = (await client.post(f"/api/forecasts/{run_id}/score", json={})).json()
    assert card["scored"] is True

    after = await client.get(f"/api/exports/{run_id}?format=pdf")
    assert after.content.startswith(b"%PDF-")
    assert after.content.rstrip().endswith(b"%%EOF"), "a truncated PDF opens as damaged"

    rendered = _pdf_text(after.content)
    assert "HOW THIS FORECAST ACTUALLY DID" in rendered
    assert f"{card['scored_periods']} of {HORIZON}" in rendered
    assert f"{card['accuracy']:.1f}%" in rendered
    # And the backtest section still says which kind of number it is.
    assert "backtesting" in rendered


async def test_the_series_list_carries_the_realized_error_once_it_exists(
    client: AsyncClient,
) -> None:
    months = _months()
    cutoff = months[-(WITHHELD + 1)]

    async def upload(rows: list[dict[str, object]], name: str) -> str:
        response = await client.post(
            "/api/datasets/upload",
            files={"file": (f"{name}.csv", _csv(rows), "text/csv")},
            data={"name": name},
        )
        return response.json()["dataset"]["id"]

    partial = await upload(_rows_through(cutoff), "Through the cutoff")
    await upload(generate_rows(), "The whole panel")

    started = await client.post(
        "/api/forecasts/run",
        json={"dataset_id": partial, "horizon": HORIZON, "max_folds": 1, "group_by": ["region"]},
    )
    run_id = started.json()["id"]
    async with client.stream("GET", f"/api/forecasts/{run_id}/events") as stream:
        async for _ in stream.aiter_lines():
            pass

    await client.post(f"/api/forecasts/{run_id}/score", json={})

    rows = (await client.get(f"/api/forecasts/{run_id}/series", params={"limit": 50})).json()[
        "rows"
    ]
    leaves = [row for row in rows if row["level"] == 1]

    assert leaves
    assert all(row["scored_periods"] == HORIZON for row in leaves)
    assert all(row["realized_wmape"] is not None for row in leaves)
    assert all(row["realized_actual_total"] is not None for row in leaves)

    # The backtest number and the realized one are different measurements and
    # are kept apart; conflating them is the whole failure this guards against.
    assert any(row["realized_wmape"] != row["wmape"] for row in leaves if row["wmape"] is not None)


async def test_reading_a_scorecard_back_gives_what_computing_it_gave(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """
    A reload must not quietly lose half the answer. The first version dropped
    both the reach of the source and the whole per-series breakdown, so the
    panel said less after a refresh than it had a moment earlier.
    """
    partial, full = truncated_and_full
    run_id = await _run_on(session, partial, grain=["region"])

    computed = await scoring_service.score_run(session, run_id, dataset_id=full)
    await session.commit()
    session.expire_all()

    stored = await scoring_service.stored_scorecard(session, run_id)

    assert stored.covered_through == computed.covered_through
    assert stored.scored_periods == computed.scored_periods
    assert stored.horizon == computed.horizon
    assert stored.wmape == pytest.approx(computed.wmape)
    assert stored.coverage == pytest.approx(computed.coverage)
    assert stored.forecast_total == pytest.approx(computed.forecast_total, rel=1e-6)
    assert stored.actual_total == pytest.approx(computed.actual_total, rel=1e-6)

    assert {row.label for row in stored.series} == {row.label for row in computed.series}
    by_label = {row.label: row for row in computed.series}
    for row in stored.series:
        assert row.wmape == pytest.approx(by_label[row.label].wmape)
        assert row.actual_total == pytest.approx(by_label[row.label].actual_total)
        assert row.scored_periods == by_label[row.label].scored_periods


@pytest.mark.parametrize(
    ("coverage", "confidence", "held"),
    [
        (100.0, 0.8, True),
        (80.0, 0.8, True),
        (4 / 5 * 100.0, 0.8, True),  # exactly the promise, arrived at by division
        (2 / 3 * 100.0, 0.8, False),
        (0.0, 0.8, False),
        (None, 0.8, None),
        (50.0, None, None),
    ],
)
def test_the_interval_verdict_is_one_predicate_everywhere(
    coverage: float | None, confidence: float | None, held: bool | None
) -> None:
    """
    The report and the API were each deciding this, one with a float tolerance
    and one without — so a run could pass on screen and fail on paper.
    """
    from app.forecasting.metrics import intervals_held

    assert intervals_held(coverage, confidence) is held


async def test_the_dashboard_stops_showing_a_backtest_number_once_it_knows_better(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """
    The accuracy KPI has to say which kind of accuracy it is. Left as the
    backtest figure, a forecast that missed by a fifth reads as 97% accurate
    on the first screen anyone opens.
    """
    from app.schemas.dashboard import DashboardQuery
    from app.services import dashboard_service

    partial, full = truncated_and_full
    run_id = await _run_on(session, partial)

    async def card() -> object:
        summary = await dashboard_service.summary(session, DashboardQuery(run_id=run_id))
        return next(kpi for kpi in summary.kpis if kpi.key == "forecast_accuracy")

    before = await card()
    assert before.label == "Backtest Accuracy"  # type: ignore[attr-defined]

    scored = await scoring_service.score_run(session, run_id, dataset_id=full)
    await session.commit()
    session.expire_all()

    after = await card()
    assert after.label == "Accuracy vs Actual"  # type: ignore[attr-defined]
    assert after.value == pytest.approx(scored.accuracy_percent, abs=0.01)  # type: ignore[attr-defined]
    assert after.comparison_value == pytest.approx(before.value)  # type: ignore[attr-defined]
    assert after.comparison_label == "vs backtest"  # type: ignore[attr-defined]
