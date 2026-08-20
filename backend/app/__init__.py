"""One BLAS thread per process, set before anything can import numpy.

The Dockerfile sets these too, and that is the copy that matters in
production — a variable exported before the interpreter starts is the only
version guaranteed to be read, because OpenBLAS and OpenMP size their thread
pools when they are first loaded.

This is the same thing for everywhere else: a developer running uvicorn
directly, a test run, a script. It sits in the package's __init__ because
that executes before any `app.*` module can be imported, which is the earliest
point inside the application that exists. Anything that imports numpy before
importing `app` is beyond its reach, and that is why it is not the only copy.

Why it matters at all: these libraries start a thread per core inside every
matrix operation, which pays on the large dense matrices they are tuned for.
A weekly time series is a few hundred numbers — the work in each call is
smaller than the cost of waking the threads to do it, and with one pool worker
per core already fitting a model, those threads contend for cores that are
already busy. Measured on a five-model search over five folds: 76 seconds
unpinned, 22 seconds pinned.
"""

import os

for _variable in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    # Never overridden: somebody who has set one has a reason, and a box with
    # cores to spare is a real one.
    os.environ.setdefault(_variable, "1")

del _variable
