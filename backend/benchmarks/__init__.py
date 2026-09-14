# Importing `app` sets the BLAS thread variables, and it has to happen before numpy
# is first imported or the pools are already sized. A package __init__ runs before
# the module body, which an import inside accuracy.py cannot guarantee against isort.
import app  # noqa: F401
