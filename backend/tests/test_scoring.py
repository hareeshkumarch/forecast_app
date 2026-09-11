from __future__ import annotations

import base64
import csv
import io
import json
import re
import uuid
import zlib
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.database.sample_data import HEADERS, generate_rows
from app.models.enums import MeasureAggregation, PointKind, RunStatus
from app.services import actuals_service as actuals
from app.services import dataset_service, forecast_service, scoring_service

GRAIN = ["region", "product_category"]
HORIZON = 3
RESTATEMENT_FACTOR = 1.1
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


def _scaled(factor: float) -> list[dict[str, object]]:
    return [{**row, "revenue": float(row["revenue"]) * factor} for row in generate_rows()]  # type: ignore[arg-type]


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
    months = _months()
    cutoff = months[-(WITHHELD + 1)]

    partial = await _dataset(session, _rows_through(cutoff), "Through the cutoff")
    full = await _dataset(session, generate_rows(), "The whole panel")
    return partial, full


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
    reachable = [caught * 100.0 / HORIZON for caught in range(HORIZON + 1)]
    assert any(card.coverage == pytest.approx(value) for value in reachable), card.coverage


async def test_scoring_records_the_reading_it_graded_against(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    partial, full = truncated_and_full
    run_id = await _run_on(session, partial)
    run = await forecast_service.get_run(session, run_id)

    card = await scoring_service.score_run(session, run_id, dataset_id=full)
    await session.commit()

    assert card.readings_recorded == HORIZON

    believed = await actuals.current(session, run.dataset_id)
    points = await forecast_service.points_for_run(session, run_id)
    graded = {
        p.period: p.actual
        for p in points
        if p.actual is not None and p.series_id is None and p.kind is PointKind.FORECAST
    }

    assert {period for _, period in believed} == set(graded)
    for period, value in graded.items():
        assert believed[(actuals.TOTAL_KEY, period)] == pytest.approx(value)


async def test_scoring_the_same_panel_again_records_no_second_reading(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    partial, full = truncated_and_full
    run_id = await _run_on(session, partial)

    await scoring_service.score_run(session, run_id, dataset_id=full)
    await session.commit()
    again = await scoring_service.score_run(session, run_id, dataset_id=full)
    await session.commit()

    assert again.readings_recorded == 0, "an unchanged number is not a restatement"


async def test_a_restated_actual_is_appended_beside_the_first_reading(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    partial, full = truncated_and_full
    run_id = await _run_on(session, partial)
    run = await forecast_service.get_run(session, run_id)

    first = await scoring_service.score_run(session, run_id, dataset_id=full)
    await session.commit()

    restated = await _dataset(session, _scaled(RESTATEMENT_FACTOR), "The panel, restated")
    second = await scoring_service.score_run(session, run_id, dataset_id=restated)
    await session.commit()

    assert second.readings_recorded == first.readings_recorded

    period = min(period for _, period in await actuals.current(session, run.dataset_id))
    history = await actuals.revisions(session, run.dataset_id, actuals.TOTAL_KEY, period)

    assert len(history) == 2, "the first reading survives the restatement"
    assert history[1].value == pytest.approx(history[0].value * RESTATEMENT_FACTOR, rel=1e-6)
    assert [row.source_dataset_id for row in history] == [full, restated]

    as_first_read = await actuals.current(session, run.dataset_id, as_of=history[0].revised_at)
    assert as_first_read[(actuals.TOTAL_KEY, period)] == pytest.approx(history[0].value)
    assert first.actual_total == pytest.approx(second.actual_total / RESTATEMENT_FACTOR, rel=1e-6)


async def test_a_grouped_run_records_a_reading_per_combination(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    partial, full = truncated_and_full
    run_id = await _run_on(session, partial, grain=GRAIN)
    run = await forecast_service.get_run(session, run_id)

    await scoring_service.score_run(session, run_id, dataset_id=full)
    await session.commit()

    believed = await actuals.current(session, run.dataset_id)
    keys = {key for key, _ in believed}

    assert actuals.TOTAL_KEY in keys, "the top line is recorded alongside the combinations"
    combinations = keys - {actuals.TOTAL_KEY}
    assert combinations, "a grouped run records each combination it scored"
    assert all(set(json.loads(key)) == set(GRAIN) for key in combinations)


async def test_a_period_still_being_lived_through_is_not_scored(
    session: AsyncSession,
) -> None:
    months = _months()
    cutoff = months[-(WITHHELD + 1)]
    partial = await _dataset(session, _rows_through(cutoff), "Through the cutoff")
    run_id = await _run_on(session, partial)

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
    months = _months()
    cutoff = months[-(WITHHELD + 1)]
    partial = await _dataset(session, _rows_through(cutoff), "Through the cutoff")
    run_id = await _run_on(session, partial)

    one_month_on = await _dataset(session, _rows_through(months[-WITHHELD]), "One month on")
    card = await scoring_service.score_run(session, run_id, dataset_id=one_month_on)

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

    for level in (1, 2):
        assert sum(
            row.actual_total or 0.0 for row in scored if row.level == level
        ) == pytest.approx(
            next(row.actual_total for row in scored if row.level == 0), rel=1e-6
        ), f"level {level} actuals do not close on the total"


async def test_the_root_of_the_tree_is_scored_as_the_run_s_own_line(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
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
    months = _months()
    cutoff = months[-(WITHHELD + 1)]
    partial = await _dataset(session, _rows_through(cutoff), "Through the cutoff")
    run_id = await _run_on(session, partial, grain=["region"])

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
    assert card.actual_total > sum(row.actual_total or 0.0 for row in card.series if row.level == 1)


async def test_the_newest_dataset_that_covers_the_horizon_is_chosen(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    partial, full = truncated_and_full
    run_id = await _run_on(session, partial)

    card = await scoring_service.score_run(session, run_id)

    assert card.source_dataset_id == full, "the run's own dataset stops before the horizon"
    assert card.scored is True


def _scaled(factor: float) -> list[dict[str, object]]:
    return [{**row, "revenue": float(row["revenue"]) * factor} for row in generate_rows()]  # type: ignore[arg-type]


async def test_a_newer_file_at_a_different_scale_is_not_this_run_s_data(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    partial, full = truncated_and_full
    run_id = await _run_on(session, partial)

    stranger = await _dataset(session, _scaled(40.0), "Somebody else entirely")

    card = await scoring_service.score_run(session, run_id)

    assert card.source_dataset_id == full, "the newest file disagrees with the run's own history"
    assert card.source_dataset_id != stranger
    assert card.scored is True


async def test_a_file_a_fraction_of_the_size_is_refused_too(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    partial, full = truncated_and_full
    run_id = await _run_on(session, partial)

    await _dataset(session, _scaled(1 / 40), "A fortieth of the business")

    card = await scoring_service.score_run(session, run_id)

    assert card.source_dataset_id == full


async def test_a_restatement_is_still_the_same_data(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    partial, _full = truncated_and_full
    run_id = await _run_on(session, partial)

    restated = await _dataset(session, _scaled(1.04), "The panel, restated")

    card = await scoring_service.score_run(session, run_id)

    assert card.source_dataset_id == restated, "4% is a correction, not another business"
    assert card.scored is True


async def test_a_file_holding_only_the_new_periods_is_still_usable(
    session: AsyncSession,
) -> None:
    months = _months()
    cutoff = months[-(WITHHELD + 1)]

    partial = await _dataset(session, _rows_through(cutoff), "Through the cutoff")
    run_id = await _run_on(session, partial)

    after = [row for row in generate_rows() if date.fromisoformat(str(row["order_date"])) > cutoff]
    only_new = await _dataset(session, after, "Just what happened since")

    card = await scoring_service.score_run(session, run_id)

    assert card.source_dataset_id == only_new
    assert card.scored is True


async def test_a_file_recording_nothing_where_the_run_recorded_something_is_refused(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    partial, full = truncated_and_full
    run_id = await _run_on(session, partial)

    await _dataset(session, _scaled(0.0), "Nothing ever happened")

    card = await scoring_service.score_run(session, run_id)

    assert card.source_dataset_id == full
    assert card.actual_total > 0


async def test_a_run_whose_only_candidates_contradict_it_says_which_way(
    session: AsyncSession,
) -> None:
    months = _months()
    partial = await _dataset(session, _rows_through(months[-(WITHHELD + 1)]), "Through the cutoff")
    run_id = await _run_on(session, partial)

    await _dataset(session, _scaled(40.0), "Somebody else entirely")

    choice = await scoring_service.choose_source(
        session, await forecast_service.get_run(session, run_id)
    )
    assert choice.dataset is None
    assert choice.contradicting == 1

    card = await scoring_service.score_run(session, run_id)

    assert card.scored is False
    assert card.blocked_reason is not None
    assert "compare like with like" in card.blocked_reason
    assert "Upload a refresh" in card.blocked_reason


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

    assert isinstance(body["drifted"], bool)
    assert body["tracking_signal"] is None or isinstance(body["tracking_signal"], int | float)
    assert body["series"], "the tree comes back worst first"

    ranked = [row["wmape"] for row in body["series"] if row["wmape"] is not None]
    assert ranked == sorted(ranked, reverse=True)

    after = await client.get(f"/api/forecasts/{run_id}/score")
    assert after.json()["wmape"] == pytest.approx(body["wmape"])

    detail = await client.get(f"/api/forecasts/{run_id}")
    assert detail.json()["realized_wmape"] == pytest.approx(body["wmape"])
    assert detail.json()["realized_accuracy"] == pytest.approx(body["accuracy"])


def _pdf_text(body: bytes) -> str:
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

    assert any(row["realized_wmape"] != row["wmape"] for row in leaves if row["wmape"] is not None)


async def test_reading_a_scorecard_back_gives_what_computing_it_gave(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
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
        (4 / 5 * 100.0, 0.8, True),
        (2 / 3 * 100.0, 0.8, False),
        (0.0, 0.8, False),
        (None, 0.8, None),
        (50.0, None, None),
    ],
)
def test_the_interval_verdict_is_one_predicate_everywhere(
    coverage: float | None, confidence: float | None, held: bool | None
) -> None:
    from app.forecasting.metrics import intervals_held

    assert intervals_held(coverage, confidence) is held


async def test_the_dashboard_stops_showing_a_backtest_number_once_it_knows_better(
    session: AsyncSession, truncated_and_full: tuple[uuid.UUID, uuid.UUID]
) -> None:
    from app.schemas.dashboard import DashboardQuery
    from app.services import dashboard_service

    partial, full = truncated_and_full
    run_id = await _run_on(session, partial)

    async def card() -> object:
        summary = await dashboard_service.summary(session, DashboardQuery(run_id=run_id))
        return next(kpi for kpi in summary.kpis if kpi.key == "forecast_accuracy")

    before = await card()
    assert before.label == "Expected Accuracy"  # type: ignore[attr-defined]

    scored = await scoring_service.score_run(session, run_id, dataset_id=full)
    await session.commit()
    session.expire_all()

    after = await card()
    assert after.label == "Actual Accuracy"  # type: ignore[attr-defined]
    assert after.value == pytest.approx(scored.accuracy_percent, abs=0.01)  # type: ignore[attr-defined]
    assert after.comparison_value == pytest.approx(before.value)  # type: ignore[attr-defined]
    assert after.comparison_label == "vs expected"  # type: ignore[attr-defined]

    async def error_card() -> object:
        summary = await dashboard_service.summary(session, DashboardQuery(run_id=run_id))
        return next(kpi for kpi in summary.kpis if kpi.key == "weighted_mape")

    graded = await error_card()
    assert graded.label == "Actual Error"  # type: ignore[attr-defined]
    assert graded.value == pytest.approx(scored.wmape, abs=0.01)  # type: ignore[attr-defined]
    assert graded.delta_display.endswith(" pts")  # type: ignore[attr-defined]


def _card(**kwargs: object) -> scoring_service.Scorecard:
    defaults: dict[str, object] = {
        "run_id": uuid.uuid4(),
        "scored_periods": 6,
        "forecast_total": 1000.0,
        "actual_total": 1000.0,
        "mae": 50.0,
        "wmape": 5.0,
    }
    return scoring_service.Scorecard(**{**defaults, **kwargs})  # type: ignore[arg-type]


def test_a_run_whose_misses_cancel_out_is_not_drifting() -> None:
    card = _card(forecast_total=1000.0, actual_total=1000.0, mae=50.0, wmape=5.0)

    assert card.tracking_signal == 0.0
    assert card.is_drifted is False


def test_a_run_that_missed_the_same_way_every_period_is_drifting() -> None:
    card = _card(forecast_total=1300.0, actual_total=1000.0, mae=50.0, wmape=5.0)

    assert card.tracking_signal == 6.0
    assert card.is_drifted is True


def test_under_forecasting_drifts_the_same_as_over_forecasting() -> None:
    card = _card(forecast_total=700.0, actual_total=1000.0, mae=50.0, wmape=5.0)

    assert card.tracking_signal == -6.0
    assert card.is_drifted is True


def test_a_run_simply_far_out_drifts_even_without_a_one_sided_bias() -> None:
    card = _card(forecast_total=1000.0, actual_total=1000.0, mae=50.0, wmape=80.0)

    assert card.tracking_signal == 0.0
    assert card.is_drifted is True


def test_an_unscored_run_has_no_tracking_signal_to_report() -> None:
    assert _card(scored_periods=0).tracking_signal is None
    assert _card(mae=0.0).tracking_signal is None
    assert _card(mae=None).tracking_signal is None
