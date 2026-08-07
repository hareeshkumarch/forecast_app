"""
What-if simulation on a finished run, and the two paths beside it that had
never actually executed.

A simulation is only worth the name if the levers mean something. The ones
here do: a driver moves the total by its own share of the movement the run
measured, and a driver this run never found is refused rather than quietly
scaling everything. The rest of the module covers the treatments and helpers
that reach the same code from other directions.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date

import numpy as np
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.database.sample_data import HEADERS, generate_rows
from app.forecasting.decomposition import forecast_attribution
from app.models.entities import ForecastDriver
from app.models.enums import ForecastFrequency, OutlierTreatment, RunStatus
from app.services import dataset_service, forecast_service

HORIZON = 3


def _csv() -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(HEADERS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(generate_rows())  # type: ignore[arg-type]
    return buffer.getvalue().encode("utf-8")


async def _completed_run(
    session: AsyncSession,
    *,
    outlier_treatment: OutlierTreatment = OutlierTreatment.NONE,
) -> uuid.UUID:
    dataset, _profile = await dataset_service.create_from_upload(
        session, _csv(), "sim.csv", name="sim"
    )
    await session.commit()

    run = await forecast_service.create_run(
        session,
        dataset_id=dataset.id,
        name="simulated",
        horizon=HORIZON,
        max_folds=1,
        outlier_treatment=outlier_treatment,
    )
    run_id = run.id
    await session.commit()

    assert await forecast_service.execute_run(run_id) is RunStatus.COMPLETED
    session.expire_all()
    return run_id


@pytest.fixture
async def run_id(session: AsyncSession) -> uuid.UUID:
    return await _completed_run(session)


async def test_a_simulation_with_no_levers_pulled_returns_the_forecast_itself(
    session: AsyncSession, run_id: uuid.UUID
) -> None:
    result = await forecast_service.simulate_what_if(session, run_id)

    assert result["baseline_total"] == pytest.approx(result["simulated_total"])
    assert result["total_delta"] == pytest.approx(0.0)
    assert result["points"], "a completed run has forecast points to simulate"
    for point in result["points"]:
        assert point["simulated_forecast"] == pytest.approx(point["baseline_forecast"])


async def test_the_volume_multiplier_scales_the_total_by_exactly_what_it_says(
    session: AsyncSession, run_id: uuid.UUID
) -> None:
    base = await forecast_service.simulate_what_if(session, run_id)
    lifted = await forecast_service.simulate_what_if(session, run_id, volume_multiplier=1.25)

    assert lifted["simulated_total"] == pytest.approx(base["baseline_total"] * 1.25)
    assert lifted["total_delta_pct"] == pytest.approx(25.0, abs=0.01)


async def test_a_shift_and_a_multiplier_compound_rather_than_fight(
    session: AsyncSession, run_id: uuid.UUID
) -> None:
    result = await forecast_service.simulate_what_if(
        session, run_id, volume_multiplier=2.0, target_shift_pct=10.0
    )
    baseline = result["baseline_total"]

    assert result["simulated_total"] == pytest.approx(baseline * 2.0 * 1.1)


async def test_a_driver_moves_the_total_by_its_own_share_of_the_movement(
    session: AsyncSession, run_id: uuid.UUID
) -> None:
    # A driver holding 40% of the impact should carry 40% of what is asked of it:
    # doubling it lifts the total by 40%, not by 100%.
    session.add(
        ForecastDriver(run_id=run_id, driver="promotions", impact_value=1.0, impact_pct=40.0)
    )
    await session.commit()

    result = await forecast_service.simulate_what_if(
        session, run_id, driver_multipliers={"promotions": 2.0}
    )

    assert result["simulated_total"] == pytest.approx(result["baseline_total"] * 1.4)


async def test_a_driver_with_no_measured_impact_moves_nothing(
    session: AsyncSession, run_id: uuid.UUID
) -> None:
    session.add(ForecastDriver(run_id=run_id, driver="weather", impact_value=0.0, impact_pct=0.0))
    await session.commit()

    result = await forecast_service.simulate_what_if(
        session, run_id, driver_multipliers={"weather": 5.0}
    )

    assert result["simulated_total"] == pytest.approx(result["baseline_total"])


async def test_a_driver_this_run_never_found_is_refused_not_silently_applied(
    session: AsyncSession, run_id: uuid.UUID
) -> None:
    with pytest.raises(ValidationError) as raised:
        await forecast_service.simulate_what_if(
            session, run_id, driver_multipliers={"made_up_column": 5.0}
        )

    assert "made_up_column" in str(raised.value)


async def test_a_run_that_never_completed_cannot_be_simulated(session: AsyncSession) -> None:
    dataset, _profile = await dataset_service.create_from_upload(
        session, _csv(), "pending.csv", name="pending"
    )
    await session.commit()
    run = await forecast_service.create_run(
        session, dataset_id=dataset.id, name="pending", horizon=HORIZON, max_folds=1
    )
    await session.commit()

    with pytest.raises(ValidationError):
        await forecast_service.simulate_what_if(session, run.id)


async def test_the_bands_are_carried_through_the_simulation(
    session: AsyncSession, run_id: uuid.UUID
) -> None:
    result = await forecast_service.simulate_what_if(session, run_id, volume_multiplier=2.0)

    for point in result["points"]:
        low = point["simulated_lower_bound"]
        high = point["simulated_upper_bound"]
        if low is None or high is None:
            continue
        assert low <= point["simulated_forecast"] <= high

    assert result["simulated_worst_case_total"] <= result["simulated_best_case_total"]


async def test_the_endpoint_simulates_and_reports_what_it_computed(
    client: AsyncClient, run_id: uuid.UUID
) -> None:
    response = await client.post(
        f"/api/forecasts/{run_id}/simulate", json={"volume_multiplier": 1.5}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run_id"] == str(run_id)
    assert body["simulated_total"] == pytest.approx(body["baseline_total"] * 1.5)
    assert len(body["points"]) == HORIZON


async def test_the_endpoint_refuses_a_multiplier_outside_its_range(
    client: AsyncClient, run_id: uuid.UUID
) -> None:
    response = await client.post(
        f"/api/forecasts/{run_id}/simulate", json={"driver_multipliers": {"promotions": 1e308}}
    )

    assert response.status_code == 422, response.text


async def test_a_run_asked_to_winsorise_actually_runs(session: AsyncSession) -> None:
    # The service passed a keyword `winsorise` does not accept, so choosing this
    # treatment raised TypeError before the forecast ever started.
    run_id = await _completed_run(session, outlier_treatment=OutlierTreatment.WINSORISE)

    run = await forecast_service.get_run(session, run_id)
    assert run.status is RunStatus.COMPLETED


def test_attribution_splits_the_projection_into_parts_that_add_up() -> None:
    history = np.array([100.0 + 5.0 * i for i in range(36)])
    forecast = np.array([280.0, 285.0, 290.0])

    parts = forecast_attribution(forecast, history, ForecastFrequency.MONTHLY)

    assert sum(parts.values()) == pytest.approx(100.0, abs=0.05)
    assert parts["trend_pct"] > 0.0, "a rising history should attribute some of it to trend"


def test_attribution_survives_a_history_full_of_gaps() -> None:
    history = np.array([100.0, np.nan, 110.0, np.nan, 120.0, 130.0] * 4)
    forecast = np.array([140.0, 150.0])

    parts = forecast_attribution(forecast, history, ForecastFrequency.MONTHLY)

    assert sum(parts.values()) == pytest.approx(100.0, abs=0.05)


def test_attribution_of_nothing_is_all_baseline() -> None:
    empty: np.ndarray = np.array([])
    assert forecast_attribution(empty, np.array([1.0, 2.0]), ForecastFrequency.MONTHLY) == {
        "baseline_pct": 100.0,
        "trend_pct": 0.0,
        "seasonality_pct": 0.0,
    }


def test_a_driver_projection_lands_on_the_same_steps_a_gap_free_one_does() -> None:
    from app.forecasting.drivers import DriverLink, DriverPanel

    # Both series carry the same +1.0 step; the second just has a hole in it.
    # Fitting on compressed positions used to pull the projection off the grid.
    straight = np.array([10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0])
    gapped = np.array([10.0, 11.0, np.nan, 13.0, 14.0, 15.0, 16.0, 17.0])

    def project(values: np.ndarray) -> np.ndarray:
        panel = DriverPanel(
            links=[DriverLink(name="price", lag=1, strength=0.5)], series={"price": values}
        )
        return panel.project_future(3, ForecastFrequency.MONTHLY).series["price"]

    assert project(straight)[-3:] == pytest.approx([18.0, 19.0, 20.0])
    assert project(gapped)[-3:] == pytest.approx([18.0, 19.0, 20.0])
    assert project(gapped).size == gapped.size + 3


def test_a_driver_projection_of_nothing_changes_nothing() -> None:
    from app.forecasting.drivers import DriverPanel

    panel = DriverPanel(links=[], series={})
    assert panel.project_future(5, ForecastFrequency.MONTHLY).series == {}


async def test_the_simulated_points_come_back_in_period_order(
    session: AsyncSession, run_id: uuid.UUID
) -> None:
    result = await forecast_service.simulate_what_if(session, run_id)

    periods = [point["period"] for point in result["points"]]
    assert all(isinstance(period, date) for period in periods)
    assert periods == sorted(periods)
