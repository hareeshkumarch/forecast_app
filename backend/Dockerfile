FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# libgomp1 is required by scikit-learn's HistGradientBoostingRegressor (OpenMP).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Prophet. Left out of requirements.txt because a plain `pip install -r
# requirements.txt` checkout should stay light, but a deployed image should
# have it: without this the roster silently drops to nine models and the
# dashboard reports Prophet as unavailable on every run.
#
# It is no longer expensive to include. Since 1.1 the manylinux wheels ship
# `prophet/stan_model/prophet_model.bin` already compiled, so there is no Stan
# build here and none on first use — the wheel is ~15 MB and the install adds
# ~200 MB with cmdstanpy and matplotlib behind it.
#
# Build a lean image with `--build-arg INSTALL_OPTIONAL_MODELS=false`; the
# engine detects what is present and reports the rest (see unavailable_models).
ARG INSTALL_OPTIONAL_MODELS=true
COPY requirements-optional.txt ./
RUN if [ "$INSTALL_OPTIONAL_MODELS" = "true" ]; then \
        pip install -r requirements-optional.txt \
        # Fit once, here. The wheel carries a compiled binary for one
        # architecture, and the failure mode when it cannot exec is not an
        # import error — `import prophet` succeeds and every fit fails at
        # runtime instead. Better to find that out during the build.
        && python -c "\
import logging, pandas as pd; \
logging.disable(logging.CRITICAL); \
from prophet import Prophet; \
Prophet().fit(pd.DataFrame({'ds': pd.date_range('2024-01-01', periods=12, freq='MS'), 'y': range(12)})); \
print('[build] prophet: stan backend OK')"; \
    else \
        echo "[build] prophet: skipped (INSTALL_OPTIONAL_MODELS=$INSTALL_OPTIONAL_MODELS)"; \
    fi

COPY . .

RUN sed -i 's/\r$//' ./entrypoint.sh && chmod +x ./entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
