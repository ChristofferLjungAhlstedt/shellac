"""PaneContainer: mirrors one tab's ``PaneTree`` into GTK widgets (sections 4, 8.1).

The tree (``pane_tree.py``) is the source of truth and knows nothing about GTK.
Every layout change goes through a method here, which updates the tree first and then
makes the widget hierarchy match, so the two cannot drift apart.

Widget layout: an ``Adw.Bin`` holds the root node. A leaf is the pane's own widget; a
split is a ``Gtk.Paned`` whose two children are the nodes below it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .config import Config  # noqa: E402
from .pane_tree import (  # noqa: E402
    MAX_RATIO,
    MIN_RATIO,
    Axis,
    Direction,
    Leaf,
    Node,
    PaneTree,
    Rect,
    Split,
)
from .terminal_pane import TerminalPane  # noqa: E402
from .theme import Theme  # noqa: E402

log = logging.getLogger(__name__)

MULTI_CSS_CLASS = "paneterm-multi"  # on the container while more than one pane is visible
FOCUSED_CSS_CLASS = "focused"  # on the focused pane's widget

_ORIENTATION = {
    Axis.HORIZONTAL: Gtk.Orientation.HORIZONTAL,
    Axis.VERTICAL: Gtk.Orientation.VERTICAL,
}


class PaneContainer:
    def __init__(
        self,
        config: Config,
        theme: Theme,
        *,
        cwd: str | None = None,
        on_empty: Callable[[PaneContainer], None] | None = None,
        on_title_changed: Callable[[PaneContainer, str], None] | None = None,
    ) -> None:
        self._config = config
        self._theme = theme
        self._on_empty = on_empty
        self._on_title_changed = on_title_changed
        self._leaf_for_pane: dict[TerminalPane, Leaf] = {}
        self._paneds: dict[Split, Gtk.Paned] = {}
        self._paned_handlers: dict[Split, int] = {}
        self._shut_down = False

        self.widget = Adw.Bin()

        pane = self._create_pane(cwd)
        self.tree = PaneTree(pane)
        assert isinstance(self.tree.root, Leaf)
        self._leaf_for_pane[pane] = self.tree.root
        self.widget.set_child(pane.widget)
        self._update_style()

    # -- queries ------------------------------------------------------------------------

    @property
    def focused_pane(self) -> TerminalPane | None:
        leaf = self.tree.focused
        return leaf.payload if leaf is not None else None

    @property
    def title(self) -> str:
        pane = self.focused_pane
        return pane.display_title() if pane is not None else ""

    def panes(self) -> list[TerminalPane]:
        return [leaf.payload for leaf in self.tree.leaves()]

    # -- operations ---------------------------------------------------------------------

    def split(self, axis: Axis) -> TerminalPane | None:
        """Split the focused pane; the new pane starts in the same directory (FR-11..14)."""
        leaf = self.tree.focused
        if leaf is None or self._shut_down:
            return None
        old_pane: TerminalPane = leaf.payload
        new_pane = self._create_pane(old_pane.current_directory())

        new_leaf = self.tree.split(leaf, axis, new_pane)
        self._leaf_for_pane[new_pane] = new_leaf
        assert new_leaf.parent is not None
        paned = self._make_paned(new_leaf.parent)

        # A widget must leave its old parent before joining a new one. Putting the Paned
        # into the old pane's place unparents the old widget (we still hold a reference),
        # and the running shell is untouched.
        self._replace_in_parent(old_pane.widget, paned)
        paned.set_start_child(old_pane.widget)
        paned.set_end_child(new_pane.widget)

        self._sync_zoom()
        self._update_style()
        self._focus_later(new_pane)
        return new_pane

    def close_pane(self, pane: TerminalPane | None = None) -> None:
        """Close a pane (default: the focused one) and collapse the layout (FR-15)."""
        pane = pane or self.focused_pane
        leaf = self._leaf_for_pane.get(pane) if pane is not None else None
        if pane is None or leaf is None or self._shut_down:
            return
        was_focused = leaf is self.tree.focused
        parent = leaf.parent

        if parent is None:
            # The last pane: the tab goes away with it.
            self.widget.set_child(None)
            self.tree.close(leaf)
            del self._leaf_for_pane[pane]
            pane.close()
            leaf.payload = None
            if self._on_empty is not None:
                self._on_empty(self)
            return

        # Capture the widgets involved, then update the tree first.
        sibling_widget = self._widget_of(parent.other(leaf))
        paned = self._paneds.pop(parent)
        paned.disconnect(self._paned_handlers.pop(parent))
        self.tree.close(leaf)
        del self._leaf_for_pane[pane]

        # Move keyboard focus off the doomed widget before unparenting it; GTK 4 warns
        # when a paned loses the child that holds focus.
        survivor = self.focused_pane
        if was_focused and survivor is not None:
            survivor.grab_focus()

        paned.set_start_child(None)
        paned.set_end_child(None)
        self._replace_in_parent(paned, sibling_widget)

        pane.close()
        leaf.payload = None  # the detached leaf must not keep the pane alive (NFR-4)

        self._sync_zoom()
        self._update_style()

    def focus_direction(self, direction: Direction) -> None:
        """Move focus by on-screen geometry, using the panes' real widget bounds (FR-16)."""
        rects: dict[Leaf, Rect] = {}
        for leaf in self.tree.leaves():
            widget = leaf.payload.widget
            if not widget.get_mapped():
                continue
            ok, bounds = widget.compute_bounds(self.widget)
            if ok:
                rects[leaf] = Rect(
                    bounds.get_x(), bounds.get_y(), bounds.get_width(), bounds.get_height()
                )
        target = self.tree.find_neighbor(direction, rects)
        if target is not None:
            self.tree.set_focus(target)
            self._update_style()
            target.payload.grab_focus()

    def resize(self, direction: Direction) -> None:
        """Move the nearest divider by the configured step (FR-17)."""
        leaf = self.tree.focused
        if leaf is None or self.tree.zoomed is not None:
            return
        split = self.tree.resize_target(leaf, direction)
        if split is None:
            return
        paned = self._paneds[split]
        step = self._config.panes.resize_step
        paned.set_position(max(0, paned.get_position() + direction.sign * step))

    def toggle_zoom(self) -> None:
        """Maximize the focused pane, or restore. Other panes keep running (FR-18)."""
        self.tree.toggle_zoom()
        self._sync_zoom()
        self._update_style()

    def apply_style(self, config: Config, theme: Theme) -> None:
        self._config = config
        self._theme = theme
        for pane in self.panes():
            pane.apply_style(config, theme)

    def shutdown(self) -> None:
        """End every shell and drop all handlers. Safe to call more than once (NFR-4)."""
        if self._shut_down:
            return
        self._shut_down = True
        for split, paned in self._paneds.items():
            paned.disconnect(self._paned_handlers[split])
        for pane in list(self._leaf_for_pane):
            pane.close()
        self._leaf_for_pane.clear()
        self._paneds.clear()
        self._paned_handlers.clear()
        self._on_empty = None
        self._on_title_changed = None

    # -- pane callbacks -----------------------------------------------------------------

    def _create_pane(self, cwd: str | None) -> TerminalPane:
        return TerminalPane(
            self._config,
            self._theme,
            cwd=cwd,
            on_exited=self._pane_exited,
            on_title_changed=self._pane_title_changed,
            on_focus=self._pane_focused,
        )

    def _pane_exited(self, pane: TerminalPane, _status: int) -> None:
        # FR-3. Deferred: we are inside VTE's signal emission and are about to destroy it.
        GLib.idle_add(self._close_exited, pane)

    def _close_exited(self, pane: TerminalPane) -> bool:
        self.close_pane(pane)
        return GLib.SOURCE_REMOVE

    def _pane_focused(self, pane: TerminalPane) -> None:
        leaf = self._leaf_for_pane.get(pane)
        if leaf is None:
            return
        if self.tree.focused is not leaf:
            self.tree.set_focus(leaf)
            self._update_style()
        self._emit_title()

    def _pane_title_changed(self, pane: TerminalPane) -> None:
        if pane is self.focused_pane:
            self._emit_title()

    def _emit_title(self) -> None:
        if self._on_title_changed is not None:
            self._on_title_changed(self, self.title)

    # -- widget plumbing ----------------------------------------------------------------

    def _widget_of(self, node: Node) -> Gtk.Widget:
        if isinstance(node, Leaf):
            return node.payload.widget
        assert isinstance(node, Split)
        return self._paneds[node]

    def _replace_in_parent(self, old: Gtk.Widget, new: Gtk.Widget) -> None:
        """Put ``new`` where ``old`` is. ``old`` is left unparented."""
        parent = old.get_parent()
        if isinstance(parent, Gtk.Paned):
            if parent.get_start_child() == old:
                parent.set_start_child(new)
            else:
                parent.set_end_child(new)
        elif isinstance(parent, Adw.Bin):
            parent.set_child(new)
        else:
            raise RuntimeError(f"unexpected parent {parent!r}")

    def _make_paned(self, split: Split) -> Gtk.Paned:
        paned = Gtk.Paned(orientation=_ORIENTATION[split.axis])
        paned.set_resize_start_child(True)
        paned.set_resize_end_child(True)
        paned.set_shrink_start_child(False)
        paned.set_shrink_end_child(False)
        self._paneds[split] = paned
        self._paned_handlers[split] = paned.connect("notify::position", self._paned_moved, split)
        # The size is not known until the first layout pass; set 50/50 then (FR-14).
        paned.add_tick_callback(self._place_divider, split.ratio)
        return paned

    @staticmethod
    def _extent(paned: Gtk.Paned) -> int:
        if paned.get_orientation() == Gtk.Orientation.HORIZONTAL:
            return paned.get_width()
        return paned.get_height()

    def _place_divider(self, paned: Gtk.Paned, _clock: object, ratio: float) -> bool:
        extent = self._extent(paned)
        if extent <= 0:
            return GLib.SOURCE_CONTINUE
        paned.set_position(int(extent * ratio))
        return GLib.SOURCE_REMOVE

    def _paned_moved(self, paned: Gtk.Paned, _pspec: object, split: Split) -> None:
        extent = self._extent(paned)
        if extent > 0:
            split.ratio = min(MAX_RATIO, max(MIN_RATIO, paned.get_position() / extent))

    def _sync_zoom(self) -> None:
        """Make visibility match the tree's zoom state without reparenting anything."""
        for paned in self._paneds.values():
            paned.set_visible(True)
        for pane in self.panes():
            pane.widget.set_visible(True)

        node: Node | None = self.tree.zoomed
        while node is not None and node.parent is not None:
            self._widget_of(node.parent.other(node)).set_visible(False)
            node = node.parent

    def _update_style(self) -> None:
        multi = len(self._leaf_for_pane) > 1 and self.tree.zoomed is None
        if multi:
            self.widget.add_css_class(MULTI_CSS_CLASS)
        else:
            self.widget.remove_css_class(MULTI_CSS_CLASS)
        for leaf in self.tree.leaves():
            if leaf is self.tree.focused:
                leaf.payload.widget.add_css_class(FOCUSED_CSS_CLASS)
            else:
                leaf.payload.widget.remove_css_class(FOCUSED_CSS_CLASS)

    def _focus_later(self, pane: TerminalPane) -> None:
        """Focus once the widget has been mapped; a new pane cannot take focus before that."""

        def grab() -> bool:
            if pane in self._leaf_for_pane:
                pane.grab_focus()
            return GLib.SOURCE_REMOVE

        GLib.idle_add(grab)
