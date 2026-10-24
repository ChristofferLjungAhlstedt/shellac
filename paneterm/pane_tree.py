"""Layout tree for the panes of one tab (sections 4.2, 8.1, 8.2).

GTK-free on purpose: all the error-prone split/close/focus logic lives here and is
unit tested headlessly. ``pane_container.py`` mirrors this tree into widgets.

Naming follows GTK's orientation, which is easy to get backwards:

* ``Axis.HORIZONTAL``: the two children sit side by side (a "vertical split",
  the new pane appears to the right: ``split_right``).
* ``Axis.VERTICAL``: the two children are stacked top/bottom (a "horizontal
  split", the new pane appears below: ``split_down``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

MIN_RATIO = 0.05
MAX_RATIO = 0.95


class Axis(Enum):
    HORIZONTAL = "horizontal"  # children side by side
    VERTICAL = "vertical"  # children stacked


class Direction(Enum):
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"

    @property
    def axis(self) -> Axis:
        return Axis.HORIZONTAL if self in (Direction.LEFT, Direction.RIGHT) else Axis.VERTICAL

    @property
    def sign(self) -> int:
        return -1 if self in (Direction.LEFT, Direction.UP) else 1


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height


class Node:
    """Base class. Identity-hashed, so nodes can key dictionaries."""

    def __init__(self) -> None:
        self.parent: Split | None = None


class Leaf(Node):
    """One pane. ``payload`` is whatever the owner attaches (the TerminalPane in the app)."""

    def __init__(self, payload: Any = None) -> None:
        super().__init__()
        self.payload = payload


class Split(Node):
    def __init__(self, axis: Axis, first: Node, second: Node, ratio: float = 0.5) -> None:
        super().__init__()
        self.axis = axis
        self.first = first
        self.second = second
        self.ratio = ratio  # fraction of the space given to ``first``
        first.parent = self
        second.parent = self

    def other(self, child: Node) -> Node:
        if child is self.first:
            return self.second
        if child is self.second:
            return self.first
        raise ValueError("not a child of this split")

    def replace_child(self, old: Node, new: Node) -> None:
        if old is self.first:
            self.first = new
        elif old is self.second:
            self.second = new
        else:
            raise ValueError("not a child of this split")
        new.parent = self


class PaneTree:
    """The layout of one tab. All structural changes go through these methods."""

    def __init__(self, payload: Any = None) -> None:
        first = Leaf(payload)
        self.root: Node | None = first
        self.focused: Leaf | None = first
        self.zoomed: Leaf | None = None
        self._recent: list[Leaf] = [first]  # most recently focused first

    # -- queries ------------------------------------------------------------------------

    @property
    def is_empty(self) -> bool:
        return self.root is None

    def leaves(self) -> list[Leaf]:
        """All leaves in tree order (first child before second)."""
        found: list[Leaf] = []

        def walk(node: Node) -> None:
            if isinstance(node, Leaf):
                found.append(node)
            elif isinstance(node, Split):
                walk(node.first)
                walk(node.second)

        if self.root is not None:
            walk(self.root)
        return found

    def _require(self, leaf: Leaf) -> None:
        node: Node = leaf
        while node.parent is not None:
            node = node.parent
        if node is not self.root:
            raise ValueError("leaf is not part of this tree")

    # -- focus --------------------------------------------------------------------------

    def set_focus(self, leaf: Leaf) -> None:
        self._require(leaf)
        self.focused = leaf
        if leaf in self._recent:
            self._recent.remove(leaf)
        self._recent.insert(0, leaf)

    # -- structure ----------------------------------------------------------------------

    def split(self, leaf: Leaf, axis: Axis, payload: Any = None) -> Leaf:
        """Split ``leaf``: it stays first, the new pane is second and takes focus (FR-14)."""
        self._require(leaf)
        new_leaf = Leaf(payload)
        parent = leaf.parent
        split = Split(axis, leaf, new_leaf)  # re-parents ``leaf`` to the split
        if parent is None:
            self.root = split
        else:
            parent.replace_child(leaf, split)
        self.zoomed = None
        self.set_focus(new_leaf)
        return new_leaf

    def close(self, leaf: Leaf) -> Leaf | None:
        """Remove ``leaf`` and collapse its parent split (FR-15).

        Returns the leaf that holds focus afterwards, or None if the tree is now empty
        (the caller should then close the tab). Focus only moves if ``leaf`` had it.
        """
        self._require(leaf)
        was_focused = leaf is self.focused
        if leaf in self._recent:
            self._recent.remove(leaf)
        if self.zoomed is leaf:
            self.zoomed = None

        parent = leaf.parent
        if parent is None:
            self.root = None
            self.focused = None
            self.zoomed = None
            self._recent.clear()
            return None

        sibling = parent.other(leaf)
        grandparent = parent.parent
        if grandparent is None:
            self.root = sibling
            sibling.parent = None
        else:
            grandparent.replace_child(parent, sibling)
        started_first = parent.first is leaf
        leaf.parent = None
        parent.parent = None

        if len(self.leaves()) == 1:
            self.zoomed = None
        if was_focused:
            # Go back to the pane that had focus before this one; fall back to the
            # neighbour that took over the freed space.
            previous = next((leaf for leaf in self._recent if leaf.parent is not None), None)
            if previous is None:
                previous = self._nearest_leaf(sibling, from_start=started_first)
            self.set_focus(previous)
        return self.focused

    @staticmethod
    def _nearest_leaf(node: Node, *, from_start: bool) -> Leaf:
        """The leaf in ``node`` closest to where a removed neighbor used to be."""
        while isinstance(node, Split):
            node = node.first if from_start else node.second
        assert isinstance(node, Leaf)
        return node

    def toggle_zoom(self) -> Leaf | None:
        """Maximize the focused pane, or restore. A single pane has nothing to zoom."""
        if self.zoomed is not None:
            self.zoomed = None
        elif self.focused is not None and len(self.leaves()) > 1:
            self.zoomed = self.focused
        return self.zoomed

    # -- geometry -----------------------------------------------------------------------

    def compute_rects(self, width: float, height: float) -> dict[Leaf, Rect]:
        """Pane rectangles implied by the split ratios (ignores divider thickness)."""
        rects: dict[Leaf, Rect] = {}

        def walk(node: Node, x: float, y: float, w: float, h: float) -> None:
            if isinstance(node, Leaf):
                rects[node] = Rect(x, y, w, h)
            elif isinstance(node, Split):
                if node.axis is Axis.HORIZONTAL:
                    first_w = w * node.ratio
                    walk(node.first, x, y, first_w, h)
                    walk(node.second, x + first_w, y, w - first_w, h)
                else:
                    first_h = h * node.ratio
                    walk(node.first, x, y, w, first_h)
                    walk(node.second, x, y + first_h, w, h - first_h)

        if self.zoomed is not None:
            return {self.zoomed: Rect(0, 0, width, height)}
        if self.root is not None:
            walk(self.root, 0, 0, width, height)
        return rects

    def find_neighbor(
        self,
        direction: Direction,
        rects: dict[Leaf, Rect],
        origin: Leaf | None = None,
        tolerance: float = 2.0,
    ) -> Leaf | None:
        """Nearest pane in ``direction`` by on-screen geometry, not tree order (FR-16).

        ``rects`` are the panes' on-screen rectangles (real widget bounds in the app).
        Candidates must lie in that direction and overlap the origin on the other
        axis. Ties for distance go to the most recently focused pane (section 8.2).
        """
        origin = origin or self.focused
        if origin is None or origin not in rects:
            return None
        here = rects[origin]

        best: list[tuple[float, float, Leaf]] = []  # (gap, overlap, leaf)
        for leaf, rect in rects.items():
            if leaf is origin:
                continue
            if direction is Direction.RIGHT:
                gap = rect.x - here.right
                overlap = min(rect.bottom, here.bottom) - max(rect.y, here.y)
            elif direction is Direction.LEFT:
                gap = here.x - rect.right
                overlap = min(rect.bottom, here.bottom) - max(rect.y, here.y)
            elif direction is Direction.DOWN:
                gap = rect.y - here.bottom
                overlap = min(rect.right, here.right) - max(rect.x, here.x)
            else:
                gap = here.y - rect.bottom
                overlap = min(rect.right, here.right) - max(rect.x, here.x)
            if gap < -tolerance or overlap <= 0:
                continue
            best.append((gap, overlap, leaf))

        if not best:
            return None
        nearest = min(gap for gap, _, _ in best)
        tied = [(overlap, leaf) for gap, overlap, leaf in best if gap <= nearest + tolerance]

        def recency(entry: tuple[float, Leaf]) -> tuple[int, float]:
            overlap, leaf = entry
            rank = self._recent.index(leaf) if leaf in self._recent else len(self._recent)
            return rank, -overlap

        return min(tied, key=recency)[1]

    # -- resizing -----------------------------------------------------------------------

    def resize_target(self, leaf: Leaf, direction: Direction) -> Split | None:
        """The split whose divider a resize in ``direction`` should move (FR-17).

        That is the nearest ancestor splitting along the matching axis. Moving it right
        or down grows the first child; left or up shrinks it.
        """
        self._require(leaf)
        node: Node = leaf
        while node.parent is not None:
            if node.parent.axis is direction.axis:
                return node.parent
            node = node.parent
        return None

    def resize(self, leaf: Leaf, direction: Direction, delta: float) -> Split | None:
        """Move the target divider by ``delta`` (a fraction of the split), clamped."""
        split = self.resize_target(leaf, direction)
        if split is not None:
            ratio = split.ratio + direction.sign * abs(delta)
            split.ratio = min(MAX_RATIO, max(MIN_RATIO, ratio))
        return split
