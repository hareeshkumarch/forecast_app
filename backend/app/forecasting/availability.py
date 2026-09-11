from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path

logger = logging.getLogger(__name__)

PROPHET = "prophet"

PROBE_TIMEOUT_SECONDS = 120.0

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ModelAvailability:
    model: str
    available: bool
    reason: str | None = None
    operator_hint: str | None = None


_NOT_INSTALLED = ModelAvailability(
    model=PROPHET,
    available=False,
    reason="Prophet is not installed in this deployment, so it was not among the models tried.",
    operator_hint=(
        "Rebuild the backend image with --build-arg INSTALL_OPTIONAL_MODELS=true "
        "(the default), or install it into the running environment with "
        "`pip install -r requirements-optional.txt`."
    ),
)


def _broken(detail: str) -> ModelAvailability:
    return ModelAvailability(
        model=PROPHET,
        available=False,
        reason=(
            "Prophet is installed here but could not start, so it was not among "
            "the models tried. The other models are unaffected."
        ),
        operator_hint=(
            f"Prophet imports but cannot build a model: {detail}. This is usually the "
            "cmdstanpy pin — Prophet ships a CmdStan tree with no makefile in it, and "
            "cmdstanpy 1.3.0+ rejects it. See backend/requirements-optional.txt."
        ),
    )


def _stan_backend_detail() -> str | None:
    try:
        from prophet.models import StanBackendEnum

        first: str | None = None
        for backend in StanBackendEnum:
            try:
                StanBackendEnum.get_backend_class(backend.name)()
            except Exception as exc:
                first = first or f"{backend.name} backend: {type(exc).__name__}: {exc}"
            else:
                return None
        return first
    except Exception:
        return None


@cache
def prophet_availability() -> ModelAvailability:
    from importlib.util import find_spec

    status = _NOT_INSTALLED if find_spec("prophet") is None else _probe_construct()

    if not status.available:
        logger.warning("Prophet is unavailable: %s (%s)", status.reason, status.operator_hint)
    return status


def _probe_construct() -> ModelAvailability:
    import warnings

    logging.getLogger("prophet").setLevel(logging.CRITICAL)
    logging.getLogger("cmdstanpy").setLevel(logging.CRITICAL)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from prophet import Prophet

            Prophet()
    except Exception as exc:
        return _broken(_stan_backend_detail() or f"{type(exc).__name__}: {exc}")
    return ModelAvailability(model=PROPHET, available=True)


def optional_model_status() -> tuple[ModelAvailability, ...]:
    return _optional_model_status()


@cache
def _optional_model_status() -> tuple[ModelAvailability, ...]:
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "app.forecasting.availability"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            cwd=_PACKAGE_ROOT,
            check=True,
        )
        rows = json.loads(completed.stdout)
        return tuple(ModelAvailability(**row) for row in rows)
    except Exception as exc:
        logger.warning("Optional-model probe failed: %s: %s", type(exc).__name__, exc)
        return (
            ModelAvailability(
                model=PROPHET,
                available=False,
                reason=(
                    "Prophet could not be checked on this server, so it was not "
                    "among the models tried."
                ),
                operator_hint=(
                    f"`python -m app.forecasting.availability` failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
            ),
        )


def main() -> None:
    sys.stdout.write(json.dumps([asdict(prophet_availability())]))


if __name__ == "__main__":
    main()
