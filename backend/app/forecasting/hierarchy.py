from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]

MIN_RECONCILABLE_TOTAL = 1e-9


def all_non_negative(histories: Iterable[Sequence[float] | FloatArray]) -> bool:
    for history in histories:
        values = np.asarray(history, dtype=float)
        finite = values[np.isfinite(values)]
        if finite.size and float(finite.min()) < 0.0:
            return False
    return True


def reconcile_to_total(
    segment_forecasts: list[FloatArray],
    total_forecast: FloatArray,
    shares: list[float],
    *,
    non_negative: bool = True,
) -> list[FloatArray]:
    """Scale segment paths so they add to the total the top line forecast.

    `non_negative` says whether a negative segment is a modelling artefact or a
    real part of the business. Clipping unconditionally is what turns a returns
    line of -40 into 0 and quietly rescales its siblings to cover the
    difference: the breakdown still adds to the total, so nothing looks wrong,
    and every figure in it is off.
    """
    if not segment_forecasts:
        return []

    stacked = np.vstack([np.asarray(f, dtype=float) for f in segment_forecasts])
    total = np.asarray(total_forecast, dtype=float)

    if non_negative:
        stacked = np.clip(stacked, 0.0, None)
    column_sums = stacked.sum(axis=0)

    fallback = np.asarray(shares, dtype=float).reshape(-1, 1)
    weight_total = float(fallback.sum())
    if abs(weight_total) > MIN_RECONCILABLE_TOTAL:
        fallback = fallback / weight_total
    else:
        fallback = np.full((stacked.shape[0], 1), 1.0 / stacked.shape[0])

    usable = np.abs(column_sums) > MIN_RECONCILABLE_TOTAL
    weights = np.where(usable, stacked / np.where(usable, column_sums, 1.0), fallback)

    return list(weights * total)


def bottom_up(segment_forecasts: list[FloatArray]) -> FloatArray:
    if not segment_forecasts:
        return np.zeros(0)
    return np.vstack([np.asarray(f, dtype=float) for f in segment_forecasts]).sum(axis=0)


def coherence_gap(segment_forecasts: list[FloatArray], total_forecast: FloatArray) -> float:
    if not segment_forecasts:
        return 0.0

    implied = bottom_up(segment_forecasts).sum()
    direct = float(np.asarray(total_forecast, dtype=float).sum())
    if abs(direct) < MIN_RECONCILABLE_TOTAL:
        return 0.0
    return float(abs(implied - direct) / abs(direct))


@dataclass(slots=True)
class Node:
    key: dict[str, str]
    label: str
    level: int
    children: list[Node] = field(default_factory=list)

    forecast: FloatArray | None = None
    share: float = 0.0
    reconciled: FloatArray | None = None

    @property
    def is_leaf(self) -> bool:
        return not self.children


def build_tree(
    leaves: list[tuple[dict[str, str], str, FloatArray, float]],
    group_by: list[str],
) -> Node:
    root = Node(key={}, label="Total", level=0)
    index: dict[tuple[str, ...], Node] = {(): root}

    for key, label, forecast, share in leaves:
        path: tuple[str, ...] = ()
        parent = root

        for depth, column in enumerate(group_by, start=1):
            path = (*path, key.get(column, "(none)"))
            node = index.get(path)
            if node is None:
                node = Node(
                    key=dict(zip(group_by[:depth], path, strict=True)),
                    label=SEPARATOR.join(path),
                    level=depth,
                )
                index[path] = node
                parent.children.append(node)
            parent = node

        parent.forecast = forecast
        parent.share = share
        parent.label = label

    _roll_up(root)
    return root


SEPARATOR = " · "


def leaf_depth(group_by: list[str] | None) -> int:
    return len(group_by or [])


def _roll_up(node: Node) -> None:
    if node.is_leaf:
        return

    for child in node.children:
        _roll_up(child)

    available = [c.forecast for c in node.children if c.forecast is not None]
    if available and node.forecast is None:
        node.forecast = bottom_up(available)
    node.share = sum(c.share for c in node.children) or node.share


def reconcile_tree(root: Node, total: FloatArray, *, non_negative: bool = True) -> None:
    root.reconciled = np.asarray(total, dtype=float)

    queue = [root]
    while queue:
        node = queue.pop(0)
        if node.is_leaf or node.reconciled is None:
            continue

        paths = [
            child.forecast if child.forecast is not None else node.reconciled * child.share
            for child in node.children
        ]
        shares = [child.share for child in node.children]

        for child, path in zip(
            node.children,
            reconcile_to_total(paths, node.reconciled, shares, non_negative=non_negative),
            strict=True,
        ):
            child.reconciled = path

        queue.extend(node.children)


def walk(node: Node) -> Iterator[Node]:
    yield node
    for child in node.children:
        yield from walk(child)
