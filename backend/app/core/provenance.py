from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from functools import lru_cache

MODEL_VERSION = "2026.08.1"

FEATURE_VERSION = "2026.08.1"

DECISIVE_SETTINGS = (
    "forecast_max_folds",
    "metric_weight_wmape",
    "metric_weight_mase",
    "metric_weight_rmse",
    "interval_weight",
    "scenario_confidence",
    "divergence_sigmas",
    "ensemble_max_members",
    "ensemble_min_improvement",
    "tuning_max_evaluations",
    "tuning_min_validation_rows",
    "min_gbm_rows",
    "sarimax_order_p",
    "sarimax_order_d",
    "sarimax_order_q",
    "gbm_max_depth",
    "gbm_learning_rate",
    "fiscal_year_start_month",
)


@lru_cache(maxsize=1)
def code_version() -> str:
    stamped = os.environ.get("GIT_COMMIT") or os.environ.get("SOURCE_COMMIT")
    if stamped:
        return stamped.strip()[:40]

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"

    return result.stdout.strip()[:40] if result.returncode == 0 else "unknown"


def config_hash() -> str:
    from app.core.config import settings

    payload = {name: getattr(settings, name, None) for name in DECISIVE_SETTINGS}
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


@dataclass(slots=True, frozen=True)
class Provenance:
    code_version: str
    model_version: str
    feature_version: str
    config_hash: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code_version": self.code_version,
            "model_version": self.model_version,
            "feature_version": self.feature_version,
            "config_hash": self.config_hash,
        }

    def matches(self, other: Provenance) -> bool:
        return (
            self.model_version == other.model_version
            and self.feature_version == other.feature_version
            and self.config_hash == other.config_hash
        )


def current() -> Provenance:
    return Provenance(
        code_version=code_version(),
        model_version=MODEL_VERSION,
        feature_version=FEATURE_VERSION,
        config_hash=config_hash(),
    )
