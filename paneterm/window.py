"""MainWindow: header bar, tab bar and one PaneContainer per tab (sections 4, 5.3)."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from . import APP_NAME  # noqa: E402
from .config import Config  # noqa: E402
from .pane_container import PaneContainer  # noqa: E402
from .pane_tree import Axis, Direction  # noqa: E402
from .shell import resolve_working_directory  # noqa: E402
from .theme import Theme  # noqa: E402

MAX_TAB_SHORTCUTS = 9


class MainWindow(Adw.ApplicationWindow):
    def __init__(
        self,
        app: Adw.Application,
        config: Config,
        theme: Theme,
        warnings: list[str] | None = None,
    ) -> None:
        super().__init__(
            application=app,
            title=APP_NAME,
            default_width=config.window.width,
            default_height=config.window.height,
        )
        self.add_css_class("paneterm")
        self._config = config
        self._theme = theme
        self._containers: dict[Adw.TabPage, PaneContainer] = {}

        self._tab_view = Adw.TabView()
        # Our own configurable accelerators replace the tab view's built-in ones.
        self._tab_view.set_shortcuts(Adw.TabViewShortcuts.NONE)
        self._tab_view.connect("notify::selected-page", self._on_selected_page_changed)
        self._tab_view.connect("page-detached", self._on_page_detached)

        self._tab_bar = Adw.TabBar()
        self._tab_bar.set_view(self._tab_view)
        self._tab_bar.set_autohide(config.tabs.autohide)

        new_tab_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New tab")
        new_tab_button.set_action_name("win.new_tab")
        header = Adw.HeaderBar()
        header.pack_start(new_tab_button)

        self._toasts = Adw.ToastOverlay()
        self._toasts.set_child(self._tab_view)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(self._tab_bar)
        toolbar.set_content(self._toasts)
        self.set_content(toolbar)

        self._setup_actions()
        self.new_tab()

        if warnings:
            # Shown once; the full list is in the log (FR-45).
            noun = "warning" if len(warnings) == 1 else "warnings"
            self.show_toast(f"{len(warnings)} configuration {noun}. See the log for details.")

        self.connect("map", lambda *_: self._focus_current())

    # -- config -------------------------------------------------------------------------

    def apply_config(self, config: Config, theme: Theme) -> None:
        """Apply a new config and theme to every pane in every tab at once (FR-38, FR-46).

        New tabs and panes created afterwards use these too.
        """
        self._config = config
        self._theme = theme
        self._tab_bar.set_autohide(config.tabs.autohide)
        for container in self._containers.values():
            container.apply_style(config, theme)

    # -- tabs ---------------------------------------------------------------------------

    def new_tab(self) -> PaneContainer:
        """Open a tab in the focused pane's directory (FR-22)."""
        current = self._current_container()
        cwd = None
        if current is not None and current.focused_pane is not None:
            cwd = current.focused_pane.current_directory()

        container = PaneContainer(
            self._config,
            self._theme,
            cwd=resolve_working_directory(cwd) if cwd else None,
            on_empty=self._on_container_empty,
            on_title_changed=self._on_container_title_changed,
        )
        page = self._tab_view.append(container.widget)
        page.set_title(container.title or APP_NAME)
        self._containers[page] = container
        self._tab_view.set_selected_page(page)
        return container

    def _current_container(self) -> PaneContainer | None:
        page = self._tab_view.get_selected_page()
        return self._containers.get(page) if page is not None else None

    def _focus_current(self) -> None:
        container = self._current_container()
        if container is not None and container.focused_pane is not None:
            container.focused_pane.grab_focus()

    def _on_container_empty(self, container: PaneContainer) -> None:
        # FR-15: the last pane of a tab closed, so the tab closes (and, as the last
        # tab, the window: see _on_page_detached).
        page = self._tab_view.get_page(container.widget)
        if page is not None:
            self._tab_view.close_page(page)

    def _on_container_title_changed(self, container: PaneContainer, title: str) -> None:
        page = self._tab_view.get_page(container.widget)
        if page is None:
            return
        page.set_title(title or APP_NAME)
        if page == self._tab_view.get_selected_page():
            self.set_title(title or APP_NAME)

    def _on_selected_page_changed(self, *_args: object) -> None:
        container = self._current_container()
        if container is not None:
            self.set_title(container.title or APP_NAME)
            container_pane = container.focused_pane
            if container_pane is not None:
                container_pane.grab_focus()

    def _on_page_detached(self, view: Adw.TabView, page: Adw.TabPage, _position: int) -> None:
        container = self._containers.pop(page, None)
        if container is not None:
            container.shutdown()
        if view.get_n_pages() == 0:
            self.close()

    def _select_tab_offset(self, offset: int) -> None:
        count = self._tab_view.get_n_pages()
        page = self._tab_view.get_selected_page()
        if count == 0 or page is None:
            return
        index = (self._tab_view.get_page_position(page) + offset) % count
        self._tab_view.set_selected_page(self._tab_view.get_nth_page(index))

    def _select_tab(self, index: int) -> None:
        if 0 <= index < self._tab_view.get_n_pages():
            self._tab_view.set_selected_page(self._tab_view.get_nth_page(index))

    # -- actions ------------------------------------------------------------------------

    def _setup_actions(self) -> None:
        def on_pane(method: str) -> Callable[[], None]:
            def run() -> None:
                pane = (c := self._current_container()) and c.focused_pane
                if pane is not None:
                    getattr(pane, method)()

            return run

        def on_container(call: Callable[[PaneContainer], object]) -> Callable[[], None]:
            def run() -> None:
                container = self._current_container()
                if container is not None:
                    call(container)

            return run

        self._add_action("copy", on_pane("copy"))
        self._add_action("paste", on_pane("paste"))
        self._add_action("cycle_theme", lambda: self.get_application().cycle_theme())
        self._add_action("reload_config", lambda: self.get_application().reload_config())
        self._add_action("new_tab", self.new_tab)
        self._add_action("next_tab", lambda: self._select_tab_offset(1))
        self._add_action("prev_tab", lambda: self._select_tab_offset(-1))
        for number in range(1, MAX_TAB_SHORTCUTS + 1):
            self._add_action(f"goto_tab_{number}", lambda n=number: self._select_tab(n - 1))

        # split_down stacks the new pane below (GTK vertical); split_right puts it beside.
        self._add_action("split_down", on_container(lambda c: c.split(Axis.VERTICAL)))
        self._add_action("split_right", on_container(lambda c: c.split(Axis.HORIZONTAL)))
        self._add_action("close_pane", on_container(lambda c: c.close_pane()))
        self._add_action("zoom_pane", on_container(lambda c: c.toggle_zoom()))
        for direction in Direction:
            self._add_action(
                f"focus_{direction.value}",
                on_container(lambda c, d=direction: c.focus_direction(d)),
            )
            self._add_action(
                f"resize_{direction.value}",
                on_container(lambda c, d=direction: c.resize(d)),
            )

    def _add_action(self, name: str, callback: Callable[[], object]) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", lambda *_: callback())
        self.add_action(action)

    def show_toast(self, message: str) -> None:
        self._toasts.add_toast(Adw.Toast.new(message))

    # -- lifecycle ----------------------------------------------------------------------

    def do_close_request(self) -> bool:
        # End every shell so nothing is left running after the window closes (M2 acceptance).
        for container in list(self._containers.values()):
            container.shutdown()
        self._containers.clear()
        return Adw.ApplicationWindow.do_close_request(self)
