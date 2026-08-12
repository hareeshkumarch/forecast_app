"""What produced a number, so the same number can be produced again.

A customer will challenge a figure, and the answer cannot be "that was what the
model said in March". Regenerating it exactly needs three things pinned: the
code that ran, the settings it ran under, and the data it ran on. The first two
live here; the third is the dataset snapshot the run already references.

`config_hash` covers the settings that change what a forecast decides, and
deliberately not the ones that change where it is stored or who can see it — a
database URL rotating must not make every historical run unreproducible.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from functools import lru_cache

#: Bumped by hand when a change alters the numbers a run produces. Distinct
#: from the commit: most commits do not move a forecast, and the ones that do
#: are the ones worth being able to point at.
MODEL_VERSION = "2026.08.1"

#: The shape of a built feature frame. Bumped when a feature is added, removed
#: or redefined, because a run scored under the old shape is not comparable.
FEATURE_VERSION = "2026.08.1"

#: The settings that change what a forecast decides. Anything absent from this
#: list can rotate freely without stranding old runs.
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
    """The commit this is running, or the release tag when there is no git.

    Resolved once. A container built from a tarball has no `.git`, so the
    environment variable is the deployment's way of saying what it shipped;
    "unknown" is reported rather than guessed at.
    """
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
    """A digest of the settings that change what a forecast decides."""
    from app.core.config import settings

    payload = {name: getattr(settings, name, None) for name in DECISIVE_SETTINGS}
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


@dataclass(slots=True, frozen=True)
class Provenance:
    """Everything needed to reproduce a run except the data itself."""

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
        """Whether a replay under `other` can be expected to give the same numbers."""
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
