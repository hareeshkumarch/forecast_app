"""Which optional forecasters this deployment can actually fit.

Two callers with opposite constraints, so there are two entry points:

* the fit path, running in a pool worker that is about to import Prophet
  anyway, asks :func:`prophet_availability` and pays the import in-process;
* the API, answering ``GET /api/health/capabilities`` for the model picker,
  asks :func:`optional_model_status`, which runs this module as a subprocess.

The split is not decoration. Importing Prophet costs ~95 MB of resident
memory, the fit pool is a ``spawn`` pool so nothing it loads is shared with
the parent, and the production container is capped at 1400 MB. Answering a
capabilities request must not permanently shrink the budget the fit stage
has to work in.

Nothing above stdlib is imported at module scope, and nothing from ``app`` is
imported at all — ``app.models.enums`` reaches ``app.models.__init__`` and
therefore SQLAlchemy, which the subprocess has no use for. Models are named
here by the string value of their :class:`~app.models.enums.ModelKind`.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path

logger = logging.getLogger(__name__)

#: `ModelKind.PROPHET.value`, spelled out to keep this module import-light.
PROPHET = "prophet"

#: The probe imports Prophet and builds a model. Cold, on a 2-vCPU instance
#: with the image freshly pulled, that is seconds rather than minutes — but
#: the API must not hang on it, so it is bounded.
PROBE_TIMEOUT_SECONDS = 120.0

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ModelAvailability:
    """Whether one model can be fitted here, and why not when it cannot.

    The two reason fields have different audiences and must not be merged.
    ``reason`` is shown in the dashboard, so it says what happened to the
    forecast. ``operator_hint`` carries the shell command or the underlying
    exception, and belongs in logs and in the health endpoint — telling
    somebody reading a forecast to run pip is noise they cannot act on.
    """

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
    """The real reason no Stan backend loaded, or None if that cannot be read.

    ``Prophet.__init__`` swallows each backend's exception at debug level and
    then trips over the attribute it never set, so what propagates is
    ``AttributeError: 'Prophet' object has no attribute 'stan_backend'`` —
    true, and useless. The actual cause is one level down. Reaching for it
    means touching Prophet internals, so every step here is optional: on any
    surprise the caller falls back to the exception it already has.
    """
    try:
        from prophet.models import StanBackendEnum

        first: str | None = None
        for backend in StanBackendEnum:
            try:
                StanBackendEnum.get_backend_class(backend.name)()
            except Exception as exc:  # reporting the reason, not handling it
                first = first or f"{backend.name} backend: {type(exc).__name__}: {exc}"
            else:
                return None
        return first
    except Exception:  # internals moved; the caller has a fallback
        return None


@cache
def prophet_availability() -> ModelAvailability:
    """Probe Prophet in this process. Cached — the answer cannot change here.

    Importing the package is not the test. A Prophet whose Stan backend will
    not load imports perfectly happily and fails at ``fit``, which is how a
    broken install reaches production looking like a working one: the model
    joins the roster, then loses every backtest to an exception. So the probe
    builds a model, which is what exercises the backend.
    """
    from importlib.util import find_spec

    status = _NOT_INSTALLED if find_spec("prophet") is None else _probe_construct()

    if not status.available:
        # Once per process, because of the cache. This is the line that turns
        # "Prophet is missing on the server" into something actionable.
        logger.warning("Prophet is unavailable: %s (%s)", status.reason, status.operator_hint)
    return status


def _probe_construct() -> ModelAvailability:
    import warnings

    # Prophet and cmdstanpy narrate at INFO on import and construction.
    logging.getLogger("prophet").setLevel(logging.CRITICAL)
    logging.getLogger("cmdstanpy").setLevel(logging.CRITICAL)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from prophet import Prophet

            Prophet()
    except Exception as exc:  # any failure to build a model means unavailable
        return _broken(_stan_backend_detail() or f"{type(exc).__name__}: {exc}")
    return ModelAvailability(model=PROPHET, available=True)


def optional_model_status() -> tuple[ModelAvailability, ...]:
    """The same probe, run out of process. Cached for the process lifetime.

    A failed probe is reported as unavailable rather than assumed working:
    listing a model the picker cannot actually run is the failure this whole
    module exists to stop.
    """
    return _optional_model_status()


@cache
def _optional_model_status() -> tuple[ModelAvailability, ...]:
    try:
        completed = subprocess.run(  # fixed argv, no shell
            [sys.executable, "-m", "app.forecasting.availability"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            cwd=_PACKAGE_ROOT,
            check=True,
        )
        rows = json.loads(completed.stdout)
        return tuple(ModelAvailability(**row) for row in rows)
    except Exception as exc:  # the probe is best-effort
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
