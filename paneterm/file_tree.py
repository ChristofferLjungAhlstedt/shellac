"""FileTree: the sidebar widget (section 5.4, FR-25..FR-35).

A thin GTK adapter over ``TreeModel`` (file_tree_model.py). The model decides what rows
exist; this module shows them, scans directories on worker threads, watches them with
``Gio.FileMonitor`` and turns user input into model calls.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from .config import SidebarConfig  # noqa: E402
from .file_icons import icon_name  # noqa: E402
from .file_tree_model import (  # noqa: E402
    Node,
    TreeModel,
    describe_error,
    list_directory,
    nearest_existing_dir,
)
from .git_status import MARKERS, GitInfo, load_git_info  # noqa: E402

log = logging.getLogger(__name__)

ICONS_DIR = Path(__file__).parent / "resources" / "icons"
SCAN_THREADS = 4
EVENT_DEBOUNCE_MS = 100  # wait this long after the last file system event before re-listing
CSS_CLASS = "paneterm-sidebar"
GIT_STATE_FILES = frozenset({"index", "HEAD", "packed-refs", "MERGE_HEAD"})
GIT_DEBOUNCE_MS = 300  # wait for a burst of changes to settle before asking git again
GIT_STATUSES = tuple(MARKERS)
MIN_NAME_LENGTH = 1

_CONTENT_EVENTS = {Gio.FileMonitorEvent.CHANGES_DONE_HINT}
_REFRESH_EVENTS = {
    Gio.FileMonitorEvent.CREATED,
    Gio.FileMonitorEvent.DELETED,
    Gio.FileMonitorEvent.RENAMED,
    Gio.FileMonitorEvent.MOVED_IN,
    Gio.FileMonitorEvent.MOVED_OUT,
}


def register_icons() -> None:
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.IconTheme.get_for_display(display).add_search_path(str(ICONS_DIR))


class RowItem(GObject.Object):
    """One row of the list: wraps a model ``Node``."""

    def __init__(self, node: Node) -> None:
        super().__init__()
        self.node = node
        self.row: _Row | None = None  # the widget currently showing this item


class _Row(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(spacing=4)
        self.add_css_class("paneterm-row")
        self.spacer = Gtk.Box()
        self.arrow = Gtk.Image(pixel_size=12)
        self.icon = Gtk.Image(pixel_size=16)
        self.label = Gtk.Label(xalign=0.0, hexpand=True, ellipsize=3)  # END
        self.marker = Gtk.Label(width_chars=2, xalign=0.5)
        self.marker.add_css_class("git-marker")
        for child in (self.spacer, self.arrow, self.icon, self.label, self.marker):
            self.append(child)
        self.item: RowItem | None = None

    def refresh(self, indent: int, git: GitInfo | None = None) -> None:
        item = self.item
        if item is None:
            return
        node = item.node
        entry = node.entry
        self.spacer.set_size_request(max(node.depth, 0) * indent, -1)
        if entry.is_dir:
            self.arrow.set_from_icon_name(
                "paneterm-chevron-down-symbolic"
                if node.expanded
                else "paneterm-chevron-right-symbolic"
            )
            self.arrow.set_opacity(1.0)
        else:
            self.arrow.set_from_icon_name("paneterm-chevron-right-symbolic")
            self.arrow.set_opacity(0.0)
        self.icon.set_from_icon_name(icon_name(entry, expanded=node.expanded))
        text = entry.name
        if node.error:
            text += f"  ({node.error})"
        elif node.loading and node.children is None:
            text += "  …"
        self.label.set_text(text)
        self.set_tooltip_text(entry.path)
        status = git.status_of(entry.path) if git is not None else None
        ignored = git is not None and git.is_ignored(entry.path)
        self.marker.set_text(
            ("•" if entry.is_dir else MARKERS[status]) if status in MARKERS else ""
        )
        for known in GIT_STATUSES:
            self.remove_css_class(f"git-{known}")
        if status is not None:
            self.add_css_class(f"git-{status}")
        for css, on in (
            ("ignored-entry", ignored),
            ("hidden-entry", entry.is_hidden),
            ("error-entry", bool(node.error) or entry.broken),
            ("directory", entry.is_dir),
        ):
            if on:
                self.add_css_class(css)
            else:
                self.remove_css_class(css)


class RowModel(GObject.Object, Gio.ListModel):
    """Exposes ``TreeModel.visible`` to a ``Gtk.ListView``."""

    def __init__(self, tree: TreeModel) -> None:
        super().__init__()
        self._tree = tree

    def do_get_item_type(self) -> GObject.GType:
        return RowItem.__gtype__

    def do_get_n_items(self) -> int:
        return len(self._tree.visible)

    def do_get_item(self, position: int) -> RowItem | None:
        if not 0 <= position < len(self._tree.visible):
            return None
        node = self._tree.visible[position]
        if node.ui is None:
            node.ui = RowItem(node)
        return node.ui

    def changed(self, position: int, removed: int, added: int) -> None:
        self.items_changed(position, removed, added)


class FileTree(Gtk.Box):
    """Sidebar: header (root, pin, up, hidden), filter entry, and the tree."""

    def __init__(
        self,
        config: SidebarConfig,
        *,
        on_activate: Callable[[Node], None],
        on_open_tab: Callable[[str], None],
        on_message: Callable[[str], None],
        on_leave: Callable[[], None],
        on_pin_changed: Callable[[bool], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class(CSS_CLASS)
        self._config = config
        self._on_activate = on_activate
        self._on_open_tab = on_open_tab
        self._on_message = on_message
        self._on_leave = on_leave
        self._on_pin_changed = on_pin_changed
        self._closed = False
        self._pending_select: str | None = None
        self._pending_expand: str | None = None
        self._git: GitInfo | None = None
        self._git_timer = 0
        self._git_running = False
        self._git_again = False
        self._hide_ignored = config.hide_gitignored
        self._git_monitor: tuple[Gio.FileMonitor, int] | None = None
        self._git_monitor_dir: str | None = None
        self._menu_node: Node | None = None
        self._monitors: dict[Node, tuple[Gio.FileMonitor, int]] = {}
        self._refresh_timers: dict[Node, int] = {}
        self._pool = ThreadPoolExecutor(
            max_workers=SCAN_THREADS, thread_name_prefix="paneterm-scan"
        )
        # Git can be slow in a big repository; its own thread keeps directory scans quick.
        self._git_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="paneterm-git")

        self.model = TreeModel(_Bridge(self), show_hidden=config.show_hidden)
        self.model.hidden_by = self._is_hidden_by_git
        self._rows = RowModel(self.model)
        self._selection = Gtk.SingleSelection(model=self._rows, autoselect=False, can_unselect=True)

        self._build_header()
        self._build_list()
        self._build_actions()

    # -- construction -------------------------------------------------------------------

    def _build_header(self) -> None:
        header = Gtk.Box(spacing=2)
        header.add_css_class("paneterm-sidebar-header")
        self._root_label = Gtk.Label(xalign=0.0, hexpand=True, ellipsize=2)  # MIDDLE
        self._root_label.add_css_class("heading")
        header.append(self._root_label)

        self._up_button = self._button("paneterm-up-symbolic", "Parent directory", self.go_up)
        self._hidden_button = Gtk.ToggleButton(
            icon_name="paneterm-eye-symbolic",
            tooltip_text="Show hidden files (H)",
            active=self._config.show_hidden,
        )
        self._hidden_button.add_css_class("flat")
        self._hidden_button.connect("toggled", lambda b: self.set_show_hidden(b.get_active()))
        self._pin_button = Gtk.ToggleButton(
            icon_name="paneterm-pin-symbolic", tooltip_text="Pin the tree to this directory"
        )
        self._pin_button.add_css_class("flat")
        self._pin_button.connect("toggled", self._pin_toggled)
        for button in (self._up_button, self._hidden_button, self._pin_button):
            header.append(button)
        self.append(header)

        self._filter = Gtk.SearchEntry(placeholder_text="Filter by name")
        self._filter.set_visible(False)
        self._filter.connect("search-changed", lambda e: self.model.set_filter(e.get_text()))
        self._filter.connect("activate", lambda _e: self._list.grab_focus())
        self._filter.connect("stop-search", lambda _e: self.close_filter(leave=True))
        self.append(self._filter)

    def _button(self, icon: str, tip: str, callback: Callable[[], None]) -> Gtk.Button:
        button = Gtk.Button(icon_name=icon, tooltip_text=tip)
        button.add_css_class("flat")
        button.connect("clicked", lambda _b: callback())
        return button

    def _build_list(self) -> None:
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_row)
        factory.connect("bind", self._bind_row)
        factory.connect("unbind", self._unbind_row)
        self._list = Gtk.ListView(
            model=self._selection, factory=factory, single_click_activate=False
        )
        self._list.add_css_class("paneterm-tree")
        self._list.connect("activate", self._row_activated)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key_pressed)
        self._list.add_controller(keys)

        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self._list)
        self._scroller = scroller
        self.append(scroller)

        self._menu_popover = Gtk.PopoverMenu.new_from_model(self._build_menu())
        self._menu_popover.set_has_arrow(False)
        self._menu_popover.set_parent(self)

    def _build_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        first = Gio.Menu()
        first.append("Open in New Tab", "tree.open_tab")
        first.append("Reveal in File Manager", "tree.reveal")
        second = Gio.Menu()
        second.append("Copy Path", "tree.copy_path")
        second.append("Copy Relative Path", "tree.copy_relative")
        third = Gio.Menu()
        third.append("New File…", "tree.new_file")
        third.append("New Folder…", "tree.new_folder")
        third.append("Rename…", "tree.rename")
        third.append("Move to Trash…", "tree.trash")
        for section in (first, second, third):
            menu.append_section(None, section)
        return menu

    def _build_actions(self) -> None:
        group = Gio.SimpleActionGroup()
        table: dict[str, Callable[[], None]] = {
            "open_tab": self._menu_open_tab,
            "reveal": self._menu_reveal,
            "copy_path": lambda: self._copy(self._target().path),
            "copy_relative": self._menu_copy_relative,
            "new_file": lambda: self._prompt_new(directory=False),
            "new_folder": lambda: self._prompt_new(directory=True),
            "rename": self._prompt_rename,
            "trash": self._confirm_trash,
        }
        for name, callback in table.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, cb=callback: cb())
            group.add_action(action)
        self.insert_action_group("tree", group)

    # -- rows ---------------------------------------------------------------------------

    def _setup_row(self, _factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        row = _Row()
        click = Gtk.GestureClick(button=1)
        click.connect("pressed", self._row_pressed, row)
        row.add_controller(click)
        menu = Gtk.GestureClick(button=3)
        menu.connect("pressed", self._row_menu, row)
        row.add_controller(menu)
        list_item.set_child(row)

    def _bind_row(self, _factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        row: _Row = list_item.get_child()
        item: RowItem = list_item.get_item()
        row.item = item
        item.row = row
        row.refresh(self._config.indent, self._git)

    def _unbind_row(self, _factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        row: _Row = list_item.get_child()
        if row.item is not None and row.item.row is row:
            row.item.row = None
        row.item = None

    def _row_pressed(
        self, gesture: Gtk.GestureClick, presses: int, _x: float, _y: float, row: _Row
    ) -> None:
        # A single click opens or closes a directory; a double click is left to "activate".
        if presses == 1 and row.item is not None and row.item.node.is_dir:
            self.model.toggle(row.item.node)

    def _row_menu(
        self, gesture: Gtk.GestureClick, _presses: int, x: float, y: float, row: _Row
    ) -> None:
        if row.item is None:
            return
        node = row.item.node
        index = self.model.index_of(node)
        if index is not None:
            self._selection.set_selected(index)
        point = row.translate_coordinates(self, x, y)
        rect = Gdk.Rectangle()
        rect.x, rect.y = (int(point[0]), int(point[1])) if point else (int(x), int(y))
        self._popup_menu(node, rect)

    def _popup_menu(self, node: Node, rect: Gdk.Rectangle | None = None) -> None:
        self._menu_node = node
        if rect is None:
            rect = Gdk.Rectangle()
            rect.x, rect.y, rect.width, rect.height = 8, 40, 1, 1
        rect.width = rect.height = 1
        self._menu_popover.set_pointing_to(rect)
        self._menu_popover.popup()

    def _row_activated(self, _view: Gtk.ListView, position: int) -> None:
        if 0 <= position < len(self.model.visible):
            self._on_activate(self.model.visible[position])

    def selected_node(self) -> Node | None:
        position = self._selection.get_selected()
        if position == Gtk.INVALID_LIST_POSITION or position >= len(self.model.visible):
            return None
        return self.model.visible[position]

    # -- keyboard (FR-34) ---------------------------------------------------------------

    def _key_pressed(
        self, _c: Gtk.EventControllerKey, keyval: int, _code: int, state: Gdk.ModifierType
    ) -> bool:
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            return False
        name = Gdk.keyval_name(keyval) or ""
        node = self.selected_node()
        if name == "Escape":
            if self._filter.get_text():
                self.close_filter(leave=False)
            self._on_leave()
            return True
        if name in ("slash",):
            self.open_filter()
            return True
        if name == "H":
            self._hidden_button.set_active(not self.model.show_hidden)
            return True
        if name == "p":
            self._pin_button.set_active(not self._pin_button.get_active())
            return True
        if name in ("minus", "BackSpace"):
            self.go_up()
            return True
        if name == "F5":
            self.model.refresh_all()
            self.schedule_git(immediately=True)
            return True
        if name == "I":
            self.set_hide_ignored(not self._hide_ignored)
            return True
        if node is None:
            return False
        if name in ("Right", "l"):
            if node.is_dir and not node.expanded:
                self.model.expand(node)
            elif node.is_dir and node.children:
                self._select_node(node.children[0])
            return True
        if name in ("Left", "h"):
            if node.is_dir and node.expanded:
                self.model.collapse(node)
            elif node.parent is not None and node.parent is not self.model.root:
                self._select_node(node.parent)
            return True
        if name == "F2":
            self._menu_node = node
            self._prompt_rename()
            return True
        if name == "Delete":
            self._menu_node = node
            self._confirm_trash()
            return True
        if name in ("Menu",) or (name == "F10" and state & Gdk.ModifierType.SHIFT_MASK):
            self._popup_menu(node)
            return True
        return False

    def open_filter(self) -> None:
        self._filter.set_visible(True)
        self._filter.grab_focus()

    def close_filter(self, *, leave: bool) -> None:
        self._filter.set_text("")
        self._filter.set_visible(False)
        self.model.set_filter("")
        if leave:
            self._on_leave()
        else:
            self._list.grab_focus()

    def focus_tree(self) -> None:
        self._list.grab_focus()
        if self._selection.get_selected() == Gtk.INVALID_LIST_POSITION and self.model.visible:
            self._selection.set_selected(0)

    def has_focus_inside(self) -> bool:
        root = self.get_root()
        focus = root.get_focus() if root is not None else None
        return focus is not None and (focus is self or focus.is_ancestor(self))

    def _select_node(self, node: Node) -> None:
        index = self.model.index_of(node)
        if index is not None:
            self._selection.set_selected(index)
            self._list.scroll_to(index, Gtk.ListScrollFlags.NONE, None)

    # -- public state -------------------------------------------------------------------

    @property
    def root_path(self) -> str | None:
        return self.model.root.path if self.model.root else None

    def set_root(self, path: str) -> None:
        if self._closed:
            return
        self._git = None  # the old root's colors must not flash on the new tree
        self.model.set_root(path)
        self.schedule_git(immediately=True)
        self._root_label.set_text(os.path.basename(path) or path)
        self._root_label.set_tooltip_text(path)
        parent = os.path.dirname(os.path.normpath(path))
        self._up_button.set_sensitive(parent != os.path.normpath(path))

    def go_up(self) -> None:
        root = self.root_path
        if root and os.path.dirname(root) != root:
            self.set_root(os.path.dirname(root))

    def reveal(self, path: str, *, expand: bool = False) -> bool:
        """Expand down to ``path`` and scroll to it; ``expand`` also opens ``path`` itself."""
        self._pending_expand = path if expand else None
        revealed = self.model.reveal(path)
        self._try_pending_expand()
        return revealed

    def _try_pending_expand(self) -> None:
        path = self._pending_expand
        if path is None:
            return
        node = self.model.node_for_path(path)
        if node is not None and node.alive and self.model.index_of(node) is not None:
            self._pending_expand = None
            if node.is_dir:
                self.model.expand(node)

    def set_show_hidden(self, show: bool) -> None:
        self.model.set_show_hidden(show)
        if self._hidden_button.get_active() != show:
            self._hidden_button.set_active(show)

    @property
    def pinned(self) -> bool:
        return self._pin_button.get_active()

    def _pin_toggled(self, button: Gtk.ToggleButton) -> None:
        self._on_pin_changed(button.get_active())

    def apply_config(self, config: SidebarConfig) -> None:
        indent_changed = config.indent != self._config.indent
        git_changed = (config.git_status, config.hide_gitignored) != (
            self._config.git_status,
            self._config.hide_gitignored,
        )
        self._config = config
        if git_changed:
            self._hide_ignored = config.hide_gitignored
            self._git = None
            self.model.refilter()
            self.schedule_git(immediately=True)
        elif indent_changed:
            self._rows.changed(0, len(self.model.visible), len(self.model.visible))

    # -- scanning and watching (the model's listener, see _Bridge) ------------------------

    def request_listing(self, node: Node, token: int) -> None:
        future = self._pool.submit(self._scan, node.path)
        future.add_done_callback(lambda f: GLib.idle_add(self._listing_done, node, token, f))
        self._node_changed(node)

    @staticmethod
    def _scan(path: str) -> object:
        try:
            return list_directory(path)
        except OSError as exc:
            return exc

    def _listing_done(self, node: Node, token: int, future: object) -> bool:
        if self._closed:
            return GLib.SOURCE_REMOVE
        result = future.result()  # type: ignore[attr-defined]
        self.model.apply_listing(node, result, token)
        self._node_changed(node)
        if node is self.model.root and isinstance(result, OSError) and node.alive:
            self._root_vanished(node.path, result)
        self._try_pending_select()
        self._try_pending_expand()
        return GLib.SOURCE_REMOVE

    def check_root(self) -> None:
        """Notice a vanished root. A directory still open elsewhere (a shell's cwd) sends no
        delete event, so the window calls this from its poll; the query is asynchronous."""
        root = self.root_path
        if root is None or self._closed:
            return

        def done(source: Gio.File, result: Gio.AsyncResult) -> None:
            try:
                source.query_info_finish(result)
            except GLib.Error as exc:
                if (
                    not self._closed
                    and self.root_path == root
                    and exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_FOUND)
                ):
                    self._root_vanished(root, FileNotFoundError())

        Gio.File.new_for_path(root).query_info_async(
            Gio.FILE_ATTRIBUTE_STANDARD_TYPE,
            Gio.FileQueryInfoFlags.NONE,
            GLib.PRIORITY_DEFAULT,
            None,
            done,
        )

    def _root_vanished(self, path: str, error: OSError) -> None:
        fallback = nearest_existing_dir(path)
        log.info("tree root %s unavailable (%s); using %s", path, describe_error(error), fallback)
        if fallback != path:
            self.set_root(fallback)

    def watch_changed(self, node: Node, watched: bool) -> None:
        if self._closed:
            return
        if watched:
            if node in self._monitors:
                return
            try:
                monitor = Gio.File.new_for_path(node.path).monitor_directory(
                    Gio.FileMonitorFlags.WATCH_MOVES, None
                )
            except GLib.Error as exc:
                log.warning("cannot watch %s: %s", node.path, exc.message)
                return
            handler = monitor.connect("changed", self._monitor_event, node)
            self._monitors[node] = (monitor, handler)
        else:
            entry = self._monitors.pop(node, None)
            if entry is not None:
                entry[0].disconnect(entry[1])
                entry[0].cancel()
            timer = self._refresh_timers.pop(node, None)
            if timer is not None:
                GLib.source_remove(timer)

    def _monitor_event(
        self,
        _m: Gio.FileMonitor,
        _f: Gio.File,
        _o: Gio.File | None,
        event: Gio.FileMonitorEvent,
        node: Node,
    ) -> None:
        if event in _CONTENT_EVENTS:
            self.schedule_git()  # a saved file changes its git status, not the listing
            return
        if event not in _REFRESH_EVENTS:
            return
        self.schedule_git()
        if node in self._refresh_timers:
            return
        self._refresh_timers[node] = GLib.timeout_add(EVENT_DEBOUNCE_MS, self._refresh_now, node)

    def _refresh_now(self, node: Node) -> bool:
        self._refresh_timers.pop(node, None)
        if not self._closed and node.alive:
            self.model.refresh(node)
        return GLib.SOURCE_REMOVE

    def rows_changed(self, position: int, removed: int, added: int) -> None:
        self._rows.changed(position, removed, added)

    def _node_changed(self, node: Node) -> None:
        item = node.ui
        if item is not None and item.row is not None:
            item.row.refresh(self._config.indent, self._git)

    def scroll_to(self, node: Node) -> None:
        self._select_node(node)

    # -- context menu actions (FR-33) -----------------------------------------------------

    def _target(self) -> Node:
        assert self._menu_node is not None
        return self._menu_node

    def _directory_of(self, node: Node) -> str:
        return node.path if node.is_dir else os.path.dirname(node.path)

    def _copy(self, text: str) -> None:
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(text)
            self._on_message("Copied")

    def _menu_copy_relative(self) -> None:
        root = self.root_path or "/"
        self._copy(os.path.relpath(self._target().path, root))

    def _menu_open_tab(self) -> None:
        self._on_open_tab(self._directory_of(self._target()))

    def _menu_reveal(self) -> None:
        launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(self._target().path))

        def done(source: Gtk.FileLauncher, result: Gio.AsyncResult) -> None:
            try:
                source.open_containing_folder_finish(result)
            except GLib.Error as exc:
                self._on_message(f"Cannot open the file manager: {exc.message}")

        launcher.open_containing_folder(self.get_root(), None, done)

    def _ask_name(
        self, title: str, body: str, initial: str, accept: str, callback: Callable[[str], None]
    ) -> None:
        dialog = Adw.AlertDialog(heading=title, body=body)
        entry = Gtk.Entry(text=initial, activates_default=True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("ok", accept)
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")
        dialog.set_close_response("cancel")

        def responded(_d: Adw.AlertDialog, response: str) -> None:
            if response == "ok":
                callback(entry.get_text().strip())

        dialog.connect("response", responded)
        dialog.present(self.get_root())
        entry.grab_focus()

    def _valid_name(self, name: str, directory: str) -> bool:
        if len(name) < MIN_NAME_LENGTH or "/" in name or name in (".", ".."):
            self._on_message("Not a valid name")
            return False
        if os.path.lexists(os.path.join(directory, name)):
            self._on_message(f"'{name}' already exists")
            return False
        return True

    def _prompt_new(self, *, directory: bool) -> None:
        parent = self._directory_of(self._target())
        kind = "folder" if directory else "file"

        def create(name: str) -> None:
            if not self._valid_name(name, parent):
                return
            target = Gio.File.new_for_path(os.path.join(parent, name))
            if directory:
                target.make_directory_async(GLib.PRIORITY_DEFAULT, None, self._folder_made, parent)
            else:
                target.create_async(
                    Gio.FileCreateFlags.NONE, GLib.PRIORITY_DEFAULT, None, self._file_made, parent
                )

        self._ask_name(f"New {kind}", f"Created in {parent}", "", "Create", create)

    def _file_made(self, source: Gio.File, result: Gio.AsyncResult, parent: str) -> None:
        try:
            source.create_finish(result).close(None)
        except GLib.Error as exc:
            self._on_message(f"Could not create: {exc.message}")
            return
        self._after_change(parent, source.get_path())

    def _folder_made(self, source: Gio.File, result: Gio.AsyncResult, parent: str) -> None:
        try:
            source.make_directory_finish(result)
        except GLib.Error as exc:
            self._on_message(f"Could not create: {exc.message}")
            return
        self._after_change(parent, source.get_path())

    def _prompt_rename(self) -> None:
        node = self._target()
        parent = os.path.dirname(node.path)

        def rename(name: str) -> None:
            if name == node.name or not self._valid_name(name, parent):
                return
            Gio.File.new_for_path(node.path).set_display_name_async(
                name, GLib.PRIORITY_DEFAULT, None, self._renamed, parent
            )

        self._ask_name("Rename", node.path, node.name, "Rename", rename)

    def _renamed(self, source: Gio.File, result: Gio.AsyncResult, parent: str) -> None:
        try:
            new = source.set_display_name_finish(result)
        except GLib.Error as exc:
            self._on_message(f"Could not rename: {exc.message}")
            return
        self._after_change(parent, new.get_path())

    def _confirm_trash(self) -> None:
        node = self._target()
        dialog = Adw.AlertDialog(
            heading="Move to Trash?", body=f"{node.name} will be moved to the trash."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("trash", "Move to Trash")
        dialog.set_response_appearance("trash", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")
        parent = os.path.dirname(node.path)

        def responded(_d: Adw.AlertDialog, response: str) -> None:
            if response != "trash":
                return

            def finished(source: Gio.File, result: Gio.AsyncResult) -> None:
                try:
                    source.trash_finish(result)
                except GLib.Error as exc:
                    self._on_message(f"Could not move to trash: {exc.message}")
                    return
                self._after_change(parent, None)

            Gio.File.new_for_path(node.path).trash_async(GLib.PRIORITY_DEFAULT, None, finished)

        dialog.connect("response", responded)
        dialog.present(self.get_root())

    def _after_change(self, parent: str, select: str | None) -> None:
        """Re-list right away (the monitor would too, a moment later) and select the result."""
        self._pending_select = select
        node = self.model.node_for_path(parent)
        if node is not None:
            self.model.refresh(node)

    def _try_pending_select(self) -> None:
        path = self._pending_select
        if path is None:
            return
        node = self.model.node_for_path(path)
        if node is not None and self.model.index_of(node) is not None:
            self._pending_select = None
            self._select_node(node)

    # -- git (FR-29, FR-30) -------------------------------------------------------------

    def _is_hidden_by_git(self, node: Node) -> bool:
        git = self._git
        return self._hide_ignored and git is not None and git.is_ignored(node.path)

    def set_hide_ignored(self, hide: bool) -> None:
        if hide != self._hide_ignored:
            self._hide_ignored = hide
            self.model.refilter()

    @property
    def hide_ignored(self) -> bool:
        return self._hide_ignored

    def schedule_git(self, *, immediately: bool = False) -> None:
        if self._closed or not self._config.git_status:
            return
        if self._git_timer:
            GLib.source_remove(self._git_timer)
        delay = 0 if immediately else GIT_DEBOUNCE_MS
        self._git_timer = GLib.timeout_add(delay, self._start_git)

    def _start_git(self) -> bool:
        self._git_timer = 0
        root = self.root_path
        if root is None or self._closed:
            return GLib.SOURCE_REMOVE
        if self._git_running:
            self._git_again = True  # one more run once the current one finishes
            return GLib.SOURCE_REMOVE
        self._git_running = True
        future = self._git_pool.submit(load_git_info, root)
        future.add_done_callback(lambda f: GLib.idle_add(self._git_done, root, f))
        return GLib.SOURCE_REMOVE

    def _git_done(self, root: str, future: object) -> bool:
        self._git_running = False
        if self._closed:
            return GLib.SOURCE_REMOVE
        try:
            info = future.result()  # type: ignore[attr-defined]
        except Exception:  # a git failure must never disturb the tree
            log.exception("git status failed")
            info = None
        if self.root_path == root:
            self._apply_git(info)
        if self._git_again:
            self._git_again = False
            self.schedule_git(immediately=True)
        return GLib.SOURCE_REMOVE

    def _apply_git(self, info: GitInfo | None) -> None:
        previous = self._git
        self._git = info
        self._watch_git_dir(info.root if info else None)
        if self._hide_ignored and (previous.ignored if previous else set()) != (
            info.ignored if info else set()
        ):
            self.model.refilter()
        for node in self.model.visible:
            self._node_changed(node)

    def _watch_git_dir(self, repo_root: str | None) -> None:
        """Watch ``.git`` so `git add`, `commit` or `checkout` in a shell update the colors."""
        directory = os.path.join(repo_root, ".git") if repo_root else None
        if directory == self._git_monitor_dir:
            return
        if self._git_monitor is not None:
            self._git_monitor[0].disconnect(self._git_monitor[1])
            self._git_monitor[0].cancel()
            self._git_monitor = None
        self._git_monitor_dir = directory
        if directory is None or not os.path.isdir(directory):
            return
        try:
            monitor = Gio.File.new_for_path(directory).monitor_directory(
                Gio.FileMonitorFlags.NONE, None
            )
        except GLib.Error as exc:
            log.warning("cannot watch %s: %s", directory, exc.message)
            return
        handler = monitor.connect("changed", self._git_dir_event)
        self._git_monitor = (monitor, handler)

    def _git_dir_event(self, _m: Gio.FileMonitor, file: Gio.File, _o: object, _e: object) -> None:
        if file.get_basename() in GIT_STATE_FILES:
            self.schedule_git()

    # -- lifecycle ----------------------------------------------------------------------

    def close(self) -> None:
        """Release monitors, timers and worker threads (NFR-4)."""
        if self._closed:
            return
        self._closed = True
        for node in list(self._monitors):
            self.watch_changed(node, False)
        for timer in self._refresh_timers.values():
            GLib.source_remove(timer)
        self._refresh_timers.clear()
        if self._git_timer:
            GLib.source_remove(self._git_timer)
            self._git_timer = 0
        self._watch_git_dir(None)
        self._menu_popover.unparent()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._git_pool.shutdown(wait=False, cancel_futures=True)


class _Bridge:
    """The model's ``Listener``, forwarding to the widget (keeps the widget API tidy)."""

    def __init__(self, tree: FileTree) -> None:
        self._tree = tree

    def rows_changed(self, position: int, removed: int, added: int) -> None:
        self._tree.rows_changed(position, removed, added)

    def node_changed(self, node: Node) -> None:
        self._tree._node_changed(node)

    def request_listing(self, node: Node, token: int) -> None:
        self._tree.request_listing(node, token)

    def watch_changed(self, node: Node, watched: bool) -> None:
        self._tree.watch_changed(node, watched)

    def scroll_to(self, node: Node) -> None:
        self._tree.scroll_to(node)
