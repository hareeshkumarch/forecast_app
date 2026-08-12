from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"

REQUIRED_CALLERS: dict[str, tuple[str, ...]] = {
    "app/datasets/refusal.py": ("assess", "series_lengths_from"),
    "app/services/actuals_service.py": ("record", "restated_since", "series_key"),
    "app/services/accuracy_service.py": ("build", "headline"),
    "app/forecasting/routing.py": ("route",),
    "app/forecasting/calibration.py": ("realised_coverage", "calibrate"),
    "app/core/budget.py": ("admission", "RunTimings"),
    "app/core/provenance.py": ("current",),
    "app/models/append_only.py": ("install",),
}


def _aliases(tree: ast.AST) -> dict[str, str]:
    renamed: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            for alias in node.names:
                if alias.asname:
                    renamed[alias.asname] = alias.name.rsplit(".", 1)[-1]
    return renamed


def _called_names(tree: ast.AST) -> set[str]:
    renamed = _aliases(tree)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr
            if isinstance(func, ast.Attribute)
            else None
        )
        if called is None:
            continue
        names.add(called)
        if called in renamed:
            names.add(renamed[called])
    return names


@pytest.fixture(scope="module")
def calls_by_file() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(APP.rglob("*.py")):
        found[str(path.relative_to(APP.parent))] = _called_names(
            ast.parse(path.read_text(encoding="utf-8"))
        )
    return found


@pytest.fixture(scope="module")
def callers(calls_by_file: dict[str, set[str]]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = defaultdict(set)
    for module, names in calls_by_file.items():
        for name in names:
            index[name].add(module)
    return index


@pytest.mark.parametrize(("module", "entry_points"), sorted(REQUIRED_CALLERS.items()))
def test_every_correctness_module_is_reached_from_production_code(
    module: str, entry_points: tuple[str, ...], callers: dict[str, set[str]]
) -> None:
    assert (APP.parent / module).exists(), f"{module} is listed here but no longer exists"

    for entry_point in entry_points:
        elsewhere = callers.get(entry_point, set()) - {module}
        assert elsewhere, (
            f"{module}::{entry_point} has no caller anywhere under app/. "
            "Either wire it into a production path or delete it — a module that only "
            "its own tests reach is shelfware."
        )


def test_the_guard_would_notice_an_unreachable_entry_point(
    callers: dict[str, set[str]],
) -> None:
    assert callers.get("a_function_nothing_calls") is None
