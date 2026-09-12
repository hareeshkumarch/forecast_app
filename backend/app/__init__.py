import os

# Read straight from the environment rather than through Settings: this runs
# before numpy is imported, which is the only moment the BLAS pools can still
# be sized, and importing Settings here would pull numpy in first.
_requested = os.environ.get("FORECAST_BLAS_THREADS", "").strip()
_threads = _requested if _requested.isdigit() and int(_requested) > 0 else ""

for _variable in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    if _threads:
        os.environ[_variable] = _threads
    else:
        os.environ.setdefault(_variable, "1")

del _variable, _threads, _requested
