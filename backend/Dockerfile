FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# One BLAS thread per process, and it is worth about three and a half times
# the speed of a model search.
#
# Left alone, OpenBLAS and OpenMP each start a thread per core inside every
# matrix operation. That pays on the large dense matrices those libraries are
# tuned for; a weekly time series is a few hundred numbers, so the work in
# each call is smaller than the cost of waking the threads to do it. With a
# pool worker per core already running its own fit, the threads then contend
# for the same cores and spend their time being switched rather than
# computing. Measured on a five-model search over five folds: 76 seconds
# unpinned, 22 seconds pinned.
#
# Set here rather than in the application because the pools are built when
# numpy is first imported — by then a variable set in Python is too late.
ENV OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1

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
