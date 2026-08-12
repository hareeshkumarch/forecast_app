"""Columns that record what was claimed, and may never be rewritten.

A forecast is a claim made at a point in time. Scoring it against what happened
afterwards is only meaningful if the row still says what it said when it was
issued, so the columns carrying the claim are frozen once written. A re-run
produces a new run_id and both runs stay.

This is enforced rather than documented because the failure is invisible. An
upsert on a re-run leaves the accuracy numbers looking fine — better, usually —
and there is nothing in the data afterwards to show that the history was
rewritten.

What arrives *later* is a different thing and is allowed: the actual for a
period that has since finished, and the realised error computed from it, are
facts the run did not have and could not have had. They are recorded beside the
claim, never over it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

#: Per table, the columns that carry what was claimed at issue time. Anything
#: not listed here is a later-arriving fact and may be written once the period
#: it describes has finished.
FROZEN_COLUMNS: dict[str, frozenset[str]] = {
    "forecast_points": frozenset(
        {
            "run_id",
            "series_id",
            "period",
            "kind",
            "forecast",
            "lower_bound",
            "upper_bound",
            "best_case",
            "base_case",
            "worst_case",
        }
    ),
    "forecast_series": frozenset(
        {
            "run_id",
            "parent_id",
            "level",
            "key",
            "label",
            "model",
            "wmape",
            "mase",
            "accuracy",
            "accuracy_measured",
            "folds",
            "forecast_total",
        }
    ),
    # Nothing writes to these after the run that produced them, and nothing
    # should: they are the backtest as it stood when the winner was picked.
    "model_candidates": frozenset({"*"}),
    "forecast_metrics": frozenset({"*"}),
}

#: Tables whose rows may not be deleted individually. A whole run going away
#: through its parent's cascade is a different operation and stays allowed.
NO_INDIVIDUAL_DELETE: frozenset[str] = frozenset(FROZEN_COLUMNS)


class AppendOnlyViolation(RuntimeError):
    """Raised when something tries to rewrite an issued forecast."""


def _table_of(instance: object) -> str | None:
    table = getattr(instance, "__table__", None)
    name = getattr(table, "name", None)
    return name if isinstance(name, str) else None


def _describe(instance: object, column: str | None = None) -> str:
    table = _table_of(instance) or type(instance).__name__
    identifier = getattr(instance, "id", None)
    suffix = f".{column}" if column else ""
    return f"{table}{suffix}" + (f" (id={identifier})" if identifier else "")


def _rewritten_columns(instance: object, frozen: frozenset[str]) -> list[str]:
    """Frozen columns whose value this flush would change.

    Setting a column to the value it already holds is not a rewrite — SQLAlchemy
    marks the attribute dirty on assignment, so the old and new values have to
    be compared rather than trusted.
    """
    state = inspect(instance, raiseerr=False)
    changed: list[str] = []
    if state is None:
        return changed

    for attribute in state.attrs:
        key = attribute.key
        if "*" not in frozen and key not in frozen:
            continue
        history = attribute.history
        if not history.has_changes():
            continue
        # `deleted` holds the loaded value; an insert has no loaded value, and
        # is not a rewrite of anything.
        if not history.deleted:
            continue
        before = history.deleted[0]
        after = history.added[0] if history.added else None
        if before != after:
            changed.append(key)

    return changed


def guard(session: Session, _flush_context: Any, _instances: Any) -> None:
    """Refuse a flush that would rewrite or remove an issued forecast."""
    offenders: list[str] = []

    for instance in session.dirty:
        table = _table_of(instance)
        frozen = FROZEN_COLUMNS.get(table or "")
        if frozen is None:
            continue
        offenders.extend(
            f"UPDATE {_describe(instance, column)}"
            for column in _rewritten_columns(instance, frozen)
        )

    for instance in session.deleted:
        if _table_of(instance) in NO_INDIVIDUAL_DELETE:
            offenders.append(f"DELETE {_describe(instance)}")

    if offenders:
        raise AppendOnlyViolation(
            "Issued forecasts are append-only and cannot be rewritten: "
            + "; ".join(sorted(offenders))
            + ". A re-run must create a new run_id instead. Recording an actual "
            "that has since arrived, or the realised error computed from it, is "
            "not a rewrite and is allowed."
        )


def install(target: Any = Session) -> None:
    """Attach the guard to every ORM session in the process.

    Registered against `Session` itself rather than a sessionmaker: an
    `AsyncSession` drives a plain `Session` underneath, and the async factory
    exposes no handle on it. Migrations run through Alembic's `op`, not the
    ORM, so they are unaffected.
    """
    if not event.contains(target, "before_flush", guard):
        event.listen(target, "before_flush", guard)
