from __future__ import annotations

from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

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
    "model_candidates": frozenset({"*"}),
    "forecast_metrics": frozenset({"*"}),
    "actual_observations": frozenset({"*"}),
}

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
        if not history.deleted:
            continue
        before = history.deleted[0]
        after = history.added[0] if history.added else None
        if before != after:
            changed.append(key)

    return changed


def guard(session: Session, _flush_context: Any, _instances: Any) -> None:
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
    if not event.contains(target, "before_flush", guard):
        event.listen(target, "before_flush", guard)
