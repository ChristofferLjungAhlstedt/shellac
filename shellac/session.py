"""Session restore: tabs, split layouts and working directories as plain data.

GTK-free. ``capture_tab`` turns a ``PaneTree`` into a ``TabState``; ``replay`` rebuilds that
layout by calling a ``split`` callback, so the widget code and the unit tests share one
algorithm. ``session_to_data`` / ``session_from_data`` convert to and from the JSON document
kept in ``state.json`` (see ``state.py``).

Reading never raises: damaged or hostile data yields fewer tabs or ``None``, never an
exception, and is capped so a bad file cannot open hundreds of shells.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .pane_tree import MAX_RATIO, MIN_RATIO, Axis, Leaf, Node, PaneTree, Split

MAX_TABS = 64
MAX_PANES = 64  # per tab


@dataclass(frozen=True)
class PaneState:
    cwd: str | None  # None: unknown, the pane starts in the home directory


@dataclass(frozen=True)
class SplitState:
    axis: Axis
    ratio: float
    first: LayoutState
    second: LayoutState


LayoutState = PaneState | SplitState


@dataclass(frozen=True)
class TabState:
    layout: LayoutState
    focused: int = 0  # index into the panes in tree order
    zoomed: int | None = None


@dataclass(frozen=True)
class SessionState:
    tabs: tuple[TabState, ...]
    selected: int = 0  # index of the tab that was showing


# -- capture --------------------------------------------------------------------------------


def capture_tab(
    tree: PaneTree,
    cwd_of: Callable[[Any], str | None],
    keep: Callable[[Any], bool] = lambda _payload: True,
) -> TabState | None:
    """Snapshot one tab. Panes for which ``keep`` is false (an editor, say, which is a
    command rather than a shell) are left out and their split collapses. None if no pane
    is left."""
    kept: list[Leaf] = []

    def walk(node: Node) -> LayoutState | None:
        if isinstance(node, Leaf):
            if not keep(node.payload):
                return None
            kept.append(node)
            return PaneState(cwd_of(node.payload) or None)
        assert isinstance(node, Split)
        first, second = walk(node.first), walk(node.second)
        if first is None or second is None:
            return first or second
        return SplitState(node.axis, node.ratio, first, second)

    if tree.root is None:
        return None
    layout = walk(tree.root)
    if layout is None:
        return None
    focused = kept.index(tree.focused) if tree.focused in kept else 0
    zoomed = kept.index(tree.zoomed) if len(kept) > 1 and tree.zoomed in kept else None
    return TabState(layout, focused, zoomed)


# -- rebuild --------------------------------------------------------------------------------


def first_cwd(layout: LayoutState) -> str | None:
    """Directory of the leftmost/topmost pane: the one a new tab's first pane starts in."""
    while isinstance(layout, SplitState):
        layout = layout.first
    return layout.cwd


def pane_count(layout: LayoutState) -> int:
    if isinstance(layout, SplitState):
        return pane_count(layout.first) + pane_count(layout.second)
    return 1


SplitCallback = Callable[[Leaf, Axis, float, "str | None"], Leaf]


def replay(layout: LayoutState, leaf: Leaf, split: SplitCallback) -> None:
    """Grow ``leaf`` (already created in ``first_cwd(layout)``) into ``layout``.

    ``split(leaf, axis, ratio, cwd)`` must split ``leaf`` so that it stays the first child,
    and return the new second leaf. Each split is replayed in the leaf it divides, so the
    result has the same shape and the same pane order as the original.
    """
    if isinstance(layout, SplitState):
        new_leaf = split(leaf, layout.axis, layout.ratio, first_cwd(layout.second))
        replay(layout.first, leaf, split)
        replay(layout.second, new_leaf, split)


# -- JSON -----------------------------------------------------------------------------------


def session_to_data(session: SessionState) -> dict[str, Any]:
    return {
        "selected": session.selected,
        "tabs": [_tab_to_data(tab) for tab in session.tabs],
    }


def _tab_to_data(tab: TabState) -> dict[str, Any]:
    data: dict[str, Any] = {"layout": _layout_to_data(tab.layout), "focused": tab.focused}
    if tab.zoomed is not None:
        data["zoomed"] = tab.zoomed
    return data


def _layout_to_data(layout: LayoutState) -> dict[str, Any]:
    if isinstance(layout, PaneState):
        return {"cwd": layout.cwd} if layout.cwd else {}
    return {
        "axis": layout.axis.value,
        "ratio": layout.ratio,
        "first": _layout_to_data(layout.first),
        "second": _layout_to_data(layout.second),
    }


def session_from_data(data: object) -> SessionState | None:
    """Validate a decoded ``session`` value. None when there is nothing usable in it."""
    if not isinstance(data, dict):
        return None
    raw_tabs = data.get("tabs")
    if not isinstance(raw_tabs, list):
        return None
    tabs = [tab for raw in raw_tabs[:MAX_TABS] if (tab := _tab_from_data(raw)) is not None]
    if not tabs:
        return None
    return SessionState(tuple(tabs), _index(data.get("selected"), len(tabs)) or 0)


def _tab_from_data(data: object) -> TabState | None:
    if not isinstance(data, dict):
        return None
    budget = [MAX_PANES]
    layout = _layout_from_data(data.get("layout"), budget, MAX_PANES)
    if layout is None:
        return None
    count = pane_count(layout)
    zoomed = _index(data.get("zoomed"), count) if count > 1 else None
    return TabState(layout, _index(data.get("focused"), count) or 0, zoomed)


def _layout_from_data(data: object, budget: list[int], depth: int) -> LayoutState | None:
    if not isinstance(data, dict) or depth <= 0:
        return None
    if "axis" not in data:
        budget[0] -= 1
        if budget[0] < 0:
            return None
        cwd = data.get("cwd")
        return PaneState(cwd if isinstance(cwd, str) and cwd else None)
    try:
        axis = Axis(data["axis"])
    except ValueError:
        return None
    first = _layout_from_data(data.get("first"), budget, depth - 1)
    second = _layout_from_data(data.get("second"), budget, depth - 1) if first else None
    if first is None or second is None:
        return None
    ratio = data.get("ratio")
    if isinstance(ratio, bool) or not isinstance(ratio, int | float):
        ratio = 0.5
    return SplitState(axis, min(MAX_RATIO, max(MIN_RATIO, float(ratio))), first, second)


def _index(value: object, count: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < count:
        return None
    return value
