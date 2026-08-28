"""
The settings surface.

These knobs decide what the platform *concludes*, not just how it is wired, so
a typo in a deployment's environment should stop the boot rather than quietly
change a forecast. Each test here is one way that could go wrong: a value out
of range, a set of weights that ranks nothing, or a documented variable that no
longer exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"

#: Documented in .env.example but read by docker-compose or the frontend rather
#: than by Settings, so they have no field to match.
NOT_SETTINGS = {
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_PORT",
    "BACKEND_PORT",
    "FRONTEND_PORT",
    "NEXT_PUBLIC_API_BASE_URL",
    "REDIS_PORT",
    "WORKER_CONCURRENCY",
    "RUN_SEED_ON_STARTUP",
}


def _documented_variables() -> set[str]:
    pattern = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)
    return set(pattern.findall(ENV_EXAMPLE.read_text()))


def _setting_names() -> set[str]:
    names = set()
    for name, field in Settings.model_fields.items():
        names.add(name.upper())
        if field.alias:
            names.add(field.alias.upper())
    return names


def test_every_documented_variable_still_maps_to_a_setting() -> None:
    # .env.example is the only place these are discoverable, so it drifting out
    # of step with Settings is the same as not documenting them at all.
    documented = _documented_variables() - NOT_SETTINGS
    orphaned = sorted(documented - _setting_names())

    assert not orphaned, f".env.example documents variables Settings no longer has: {orphaned}"


def test_the_forecasting_knobs_are_all_documented() -> None:
    # The wiring settings (database URLs, Supabase, storage) are covered in prose
    # above; these are the ones that change what a forecast decides.
    decisive = {
        "FORECAST_MAX_FOLDS",
        "METRIC_WEIGHT_WMAPE",
        "METRIC_WEIGHT_MASE",
        "METRIC_WEIGHT_RMSE",
        "INTERVAL_WEIGHT",
        "SCENARIO_CONFIDENCE",
        "DIVERGENCE_SIGMAS",
        "TUNING_MAX_EVALUATIONS",
        "TUNING_MIN_VALIDATION_ROWS",
        "ENSEMBLE_MAX_MEMBERS",
        "ENSEMBLE_MIN_IMPROVEMENT",
        "MIN_GBM_ROWS",
        "API_MAX_PAGE_SIZE",
        "DRIFT_TRACKING_SIGNAL_LIMIT",
        "DRIFT_WMAPE_LIMIT",
    }
    missing = sorted(decisive - _documented_variables())

    assert not missing, f"settings that change a forecast but are undocumented: {missing}"


def test_metric_weights_that_rank_nothing_are_refused() -> None:
    with pytest.raises(ValidationError, match="cannot all be zero"):
        Settings(
            metric_weight_wmape=0.0,
            metric_weight_mase=0.0,
            metric_weight_rmse=0.0,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scenario_confidence", 1.0),
        ("scenario_confidence", 0.0),
        ("interval_weight", -0.1),
        ("metric_weight_wmape", 1.5),
        ("forecast_max_folds", 0),
        ("forecast_model_concurrency", 0),
        ("ensemble_max_members", 1),
        ("ensemble_min_improvement", 1.0),
        ("divergence_sigmas", 0.0),
        ("gbm_learning_rate", 0.0),
        ("api_max_page_size", 0),
        ("tuning_min_validation_rows", 1),
        ("llm_temperature", 2.5),
        ("insight_accuracy_warning", 101.0),
        ("default_horizon_monthly", 0),
        ("drift_tracking_signal_limit", 0.0),
        ("drift_wmape_limit", 101.0),
    ],
)
def test_a_value_outside_its_range_stops_the_boot(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_the_defaults_are_the_ones_the_platform_shipped_with() -> None:
    # These were module constants before they became settings. If a default
    # drifts, every forecast changes without anyone choosing that.
    settings = Settings()

    assert settings.metric_weight_wmape == 0.50
    assert settings.metric_weight_mase == 0.30
    assert settings.metric_weight_rmse == 0.20
    assert settings.interval_weight == 0.15
    assert settings.scenario_confidence == 0.95
    assert settings.divergence_sigmas == 12.0
    assert settings.ensemble_max_members == 4
    assert settings.ensemble_min_improvement == 0.02
    assert settings.tuning_max_evaluations == 24
    assert settings.tuning_min_validation_rows == 6
    assert settings.min_gbm_rows == 8
    assert settings.api_max_page_size == 200
    assert settings.forecast_model_concurrency == 2


def test_the_metric_weights_property_matches_its_fields() -> None:
    settings = Settings(metric_weight_wmape=0.6, metric_weight_mase=0.3, metric_weight_rmse=0.1)

    assert settings.metric_weights == {"wmape": 0.6, "mase": 0.3, "rmse": 0.1}


def test_the_scoring_rule_quotes_the_weights_actually_in_force() -> None:
    from app.forecasting.selection import scoring_rule

    rule = scoring_rule({"wmape": 0.9, "smape": 0.1}, 0.4)

    assert "0.90*norm(wMAPE)" in rule
    assert "0.40*norm(Winkler)" in rule


def test_the_scoring_rule_spells_each_metric_the_way_it_is_written() -> None:
    # These names are read by people. wMAPE is not WMAPE, and upper-casing the
    # dictionary key was enough to change what the metrics endpoint reported.
    from app.forecasting.selection import scoring_rule

    assert "norm(wMAPE)" in scoring_rule()
    assert "norm(MASE)" in scoring_rule()
    assert "norm(RMSE)" in scoring_rule()
    # sMAPE is still displayed beside the others; it just never carries weight.
    assert "norm(sMAPE)" not in scoring_rule()
    assert "norm(sMAPE)" in scoring_rule({"smape": 1.0})
    assert "norm(MAE)" in scoring_rule({"mae": 1.0})
