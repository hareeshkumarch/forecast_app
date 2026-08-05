from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]

# Below this the segment forecasts carry no information about the split, so
# falling back to the historical shares is more honest than scaling noise.
MIN_RECONCILABLE_TOTAL = 1e-9


def reconcile_to_total(
    segment_forecasts: list[FloatArray],
    total_forecast: FloatArray,
    shares: list[float],
) -> list[FloatArray]:
    """
    Scales independently forecast segments so they add up to the top line.

    The total is forecast directly and is the more reliable of the two —
    aggregation cancels noise that each segment carries on its own — so it is
    kept, and the segments supply the split. Each segment keeps its own shape:
    one growing while another shrinks stays visible, which is exactly what a
    proportional split of the total could never express.

    Where the segments sum to nothing in a period there is no split to take, so
    the historical shares stand in.
    """
    if not segment_forecasts:
        return []

    stacked = np.vstack([np.asarray(f, dtype=float) for f in segment_forecasts])
    total = np.asarray(total_forecast, dtype=float)

    # A negative segment forecast would invert the split, so clip before
    # apportioning and let the total carry the sign.
    stacked = np.clip(stacked, 0.0, None)
    column_sums = stacked.sum(axis=0)

    fallback = np.asarray(shares, dtype=float).reshape(-1, 1)
    if fallback.sum() > 0:
        fallback = fallback / fallback.sum()
    else:
        fallback = np.full((stacked.shape[0], 1), 1.0 / stacked.shape[0])

    usable = column_sums > MIN_RECONCILABLE_TOTAL
    weights = np.where(usable, stacked / np.where(usable, column_sums, 1.0), fallback)

    return list(weights * total)


def bottom_up(segment_forecasts: list[FloatArray]) -> FloatArray:
    """The total implied by the segments, for reporting how far it sits from the direct one."""
    if not segment_forecasts:
        return np.zeros(0)
    return np.vstack([np.asarray(f, dtype=float) for f in segment_forecasts]).sum(axis=0)


def coherence_gap(segment_forecasts: list[FloatArray], total_forecast: FloatArray) -> float:
    """
    How far the segments' own sum sits from the directly forecast total, as a
    fraction of the total. A large gap means the two levels disagree about
    where the business is going, which is worth surfacing rather than hiding
    behind the rescale.
    """
    if not segment_forecasts:
        return 0.0

    implied = bottom_up(segment_forecasts).sum()
    direct = float(np.asarray(total_forecast, dtype=float).sum())
    if abs(direct) < MIN_RECONCILABLE_TOTAL:
        return 0.0
    return float(abs(implied - direct) / abs(direct))


@dataclass(slots=True)
class Node:
    """A series in the tree, with whatever has been forecast for it so far."""

    key: dict[str, str]
    label: str
    level: int
    children: list[Node] = field(default_factory=list)

    #: The independently produced forecast, before reconciliation.
    forecast: FloatArray | None = None
    #: Historical share of its parent, used where a forecast is unavailable.
    share: float = 0.0
    #: Filled by `reconcile_tree`.
    reconciled: FloatArray | None = None

    @property
    def is_leaf(self) -> bool:
        return not self.children


def build_tree(
    leaves: list[tuple[dict[str, str], str, FloatArray, float]],
    group_by: list[str],
) -> Node:
    """
    Assembles the parent levels implied by the grouping order.

    Grouping by ["region", "sku"] gives a total, one node per region, and one
    per region-and-sku. Intermediate levels exist so the split can be applied
    a level at a time, which is what keeps a region's own trend from being
    overwritten by its children's.
    """
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


def _roll_up(node: Node) -> None:
    """A parent's own forecast and share are the sum of its children's."""
    if node.is_leaf:
        return

    for child in node.children:
        _roll_up(child)

    available = [c.forecast for c in node.children if c.forecast is not None]
    if available and node.forecast is None:
        node.forecast = bottom_up(available)
    node.share = sum(c.share for c in node.children) or node.share


def reconcile_tree(root: Node, total: FloatArray) -> None:
    """
    Pushes a known total down the tree, one level at a time.

    Each level's children are reconciled to their own parent rather than to the
    grand total, so a node keeps the shape its own forecast gave it while every
    level still adds up to the one above.
    """
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
            node.children, reconcile_to_total(paths, node.reconciled, shares), strict=True
        ):
            child.reconciled = path

        queue.extend(node.children)


def walk(node: Node) -> Iterator[Node]:
    """Every node, parents before children."""
    yield node
    for child in node.children:
        yield from walk(child)
