"""MainWindow: header bar, tab bar and one PaneContainer per tab (sections 4, 5.3)."""

from __future__ import annotations

import contextlib
import os
import time
import weakref
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import APP_TITLE  # noqa: E402
from .close_confirm import Scope, close_dialog_text  # noqa: E402
from .command_palette import CommandPalette  # noqa: E402
from .command_watch import (  # noqa: E402
    CommandWatch,
    FinishedCommand,
    attention,
    notification_text,
)
from .config import Config  # noqa: E402
from .file_actions import Problem, plan_file_action  # noqa: E402
from .file_tree import FileTree, register_icons  # noqa: E402
from .file_tree_model import Node  # noqa: E402
from .keybindings import accelerator_tokens  # noqa: E402
from .pane_container import PaneContainer  # noqa: E402
from .pane_tree import Axis, Direction  # noqa: E402
from .search_bar import SearchBar  # noqa: E402
from .session import SessionState, first_cwd, panes_of  # noqa: E402
from .settings_window import SettingsWindow  # noqa: E402
from .shell import resolve_working_directory  # noqa: E402
from .state import MAX_WIDTH, MIN_WIDTH, load_state, save_state  # noqa: E402
from .terminal_actions import cd_command, path_text  # noqa: E402
from .terminal_pane import TerminalPane  # noqa: E402
from .theme import Theme  # noqa: E402
from .workspace import (  # noqa: E402
    WORKSPACE_FILE,
    Workspace,
    commands_in,
    confirm_text,
    parse_workspace,
    workspace_file,
    workspace_to_toml,
)

MAX_TAB_SHORTCUTS = 9
FOLLOW_DEBOUNCE_MS = 150  # wait for rapid directory changes to settle (section 8.4)
FOLLOW_POLL_MS = 1000  # fallback for shells that do not report their directory (OSC 7)
COMMAND_POLL_MS = 1000  # how often panes are checked for a command that has finished
STATE_SAVE_DELAY_MS = 400  # after the last sidebar resize


class MainWindow(Adw.ApplicationWindow):
    def __init__(
        self,
        app: Adw.Application,
        config: Config,
        theme: Theme,
        warnings: list[str] | None = None,
    ) -> None:
        saved = load_state()  # remembered size wins over the config's first-launch default
        super().__init__(
            application=app,
            title=APP_TITLE,
            default_width=saved.window_width or config.window.width,
            default_height=saved.window_height or config.window.height,
        )
        if saved.window_maximized:
            self.maximize()
        self.add_css_class("shellac")
        self._config = config
        self._saved_config = config
        self._theme = theme
        self._containers: dict[Adw.TabPage, PaneContainer] = {}
        self._follow_timer = 0
        self._state_timer = 0
        self._palette: CommandPalette | None = None
        self._settings: SettingsWindow | None = None
        self._last_followed: str | None = None
        self._font_scale = 1.0
        self._status_toast: Adw.Toast | None = None
        self._watches: weakref.WeakKeyDictionary[TerminalPane, CommandWatch] = (
            weakref.WeakKeyDictionary()
        )
        self._finished_ids: set[str] = set()  # desktop notifications still showing
        self._confirming_close = False  # a "still running" dialog is open
        self._close_confirmed = False  # the user agreed to close the window

        register_icons()
        self._state = saved
        visible = self._state.sidebar_visible
        self._sidebar_visible = config.sidebar.visible if visible is None else visible
        self._sidebar_width = self._state.sidebar_width or config.sidebar.width

        self._tab_view = Adw.TabView()
        # Our own configurable accelerators replace the tab view's built-in ones.
        self._tab_view.set_shortcuts(Adw.TabViewShortcuts.NONE)
        self._tab_view.connect("notify::selected-page", self._on_selected_page_changed)
        self._tab_view.connect("page-detached", self._on_page_detached)
        self._tab_view.connect("close-page", self._on_close_page)

        self._tab_bar = Adw.TabBar()
        self._tab_bar.set_view(self._tab_view)
        self._tab_bar.set_autohide(config.tabs.autohide)

        new_tab_button = Gtk.Button(tooltip_text="New tab")
        # Fall back to a text "+" if the bundled icon cannot be found (a stale install),
        # so the button is never invisible.
        if Gtk.IconTheme.get_for_display(self.get_display()).has_icon("shellac-plus-symbolic"):
            new_tab_button.set_icon_name("shellac-plus-symbolic")
        else:
            new_tab_button.set_label("+")
        new_tab_button.set_action_name("win.new_tab")
        sidebar_button = Gtk.Button(
            icon_name="shellac-sidebar-symbolic", tooltip_text="Toggle sidebar"
        )
        sidebar_button.set_action_name("win.toggle_sidebar")
        header = Adw.HeaderBar()
        header.pack_start(sidebar_button)
        header.pack_start(new_tab_button)
        # A visible way to find the palette again if its shortcut is forgotten.
        self._palette_button = Gtk.Button(icon_name="shellac-command-symbolic")
        self._palette_button.set_action_name("win.command_palette")
        self._update_palette_tooltip()
        header.pack_end(self._palette_button)
        self._settings_button = Gtk.Button(icon_name="shellac-settings-symbolic")
        self._settings_button.set_action_name("win.settings")
        self._update_settings_tooltip()
        header.pack_end(self._settings_button)

        self._toasts = Adw.ToastOverlay()
        self._toasts.set_child(self._tab_view)

        self._sidebar = FileTree(
            config.sidebar,
            on_activate=self._on_sidebar_activate,
            on_open_tab=lambda path: self.new_tab(cwd=path),
            on_open_workspace=self.open_workspace,
            on_save_workspace=self.save_workspace,
            on_message=self.show_toast,
            on_leave=self._focus_current,
            on_pin_changed=self._on_pin_changed,
        )
        self._sidebar.set_size_request(MIN_WIDTH, -1)
        self._sidebar.set_visible(self._sidebar_visible)
        self._sidebar.set_root(str(Path.home()))

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.append(self._tab_bar)
        self._toasts.set_vexpand(True)
        self._search = SearchBar(
            case_sensitive=config.general.search_case_sensitive,
            wrap_around=config.general.search_wrap_around,
            on_close=lambda: None,
        )
        self._search.set_visible(False)
        self._search.set_halign(Gtk.Align.END)
        self._search.set_valign(Gtk.Align.START)
        self._search.set_margin_top(8)
        self._search.set_margin_end(16)
        overlay = Gtk.Overlay()
        overlay.set_vexpand(True)
        overlay.set_child(self._toasts)
        overlay.add_overlay(self._search)
        right.append(overlay)

        self._paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._paned.set_start_child(self._sidebar)
        self._paned.set_end_child(right)
        self._paned.set_shrink_start_child(False)
        self._paned.set_resize_start_child(False)
        self._paned.set_shrink_end_child(False)
        self._paned.set_position(self._sidebar_width)
        self._paned.connect("notify::position", self._on_paned_moved)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self._paned)
        self.set_content(toolbar)

        self._setup_actions()
        if not (config.general.restore_session and self._restore_session(saved.session)):
            self.new_tab()

        if warnings:
            # Shown once; the full list is in the log (FR-45).
            noun = "warning" if len(warnings) == 1 else "warnings"
            self.show_toast(f"{len(warnings)} configuration {noun}. See the log for details.")

        self.connect("map", lambda *_: self._focus_current())
        self._poll_id = GLib.timeout_add(FOLLOW_POLL_MS, self._poll_follow)
        self._command_poll_id = GLib.timeout_add(COMMAND_POLL_MS, self._poll_commands)
        self.connect("notify::is-active", self._on_active_changed)
        self._schedule_follow()

    # -- config -------------------------------------------------------------------------

    def apply_config(self, config: Config, theme: Theme, saved: Config | None = None) -> None:
        """Apply a new config and theme to every pane in every tab at once (FR-38, FR-46).

        New tabs and panes created afterwards use these too.
        """
        self._config = config
        self._saved_config = saved or config  # without any live preview from the settings
        self._theme = theme
        self._tab_bar.set_autohide(config.tabs.autohide)
        self._update_palette_tooltip()
        self._update_settings_tooltip()
        if self._palette is not None:
            self._palette.set_bindings(self._application_bindings())
        if self._settings is not None:
            self._settings.set_config(self._saved_config)
            self._settings.sync_active_theme()
        self._sidebar.apply_config(config.sidebar)
        self._sidebar.set_show_hidden(config.sidebar.show_hidden)
        for container in self._containers.values():
            container.apply_style(config, theme)

    # -- tabs ---------------------------------------------------------------------------

    def new_tab(self, cwd: str | None = None, argv: list[str] | None = None) -> PaneContainer:
        """Open a tab in the focused pane's directory, or in ``cwd`` (FR-22).

        ``argv`` runs that command in the tab instead of a shell.
        """
        current = self._current_container()
        if cwd is None and current is not None and current.focused_pane is not None:
            cwd = current.focused_pane.current_directory()

        container = PaneContainer(
            self._config,
            self._theme,
            cwd=resolve_working_directory(cwd) if cwd else None,
            argv=argv,
            on_empty=self._on_container_empty,
            on_title_changed=self._on_container_title_changed,
        )
        page = self._tab_view.append(container.widget)
        page.set_title(container.title or APP_TITLE)
        self._containers[page] = container
        self._tab_view.set_selected_page(page)
        return container

    def _restore_session(self, session: SessionState | None) -> bool:
        """Reopen the saved tabs. Shells start fresh in their old directories; nothing that
        was running is restarted. Returns False if there was nothing to restore."""
        if session is None or not session.tabs:
            return False
        for tab in session.tabs:
            container = self.new_tab(cwd=first_cwd(tab.layout) or str(Path.home()))
            container.restore_layout(tab)
        self._select_tab(session.selected)
        # Building the other tabs queued focus grabs for their (hidden) panes. Idle callbacks
        # run in the order they were added, so this one runs last and the selected tab wins.
        GLib.idle_add(self._refocus_once)
        return True

    def _refocus_once(self) -> bool:
        self._focus_current()
        return GLib.SOURCE_REMOVE

    def _capture_session(self) -> SessionState | None:
        tabs = []
        selected = 0
        current = self._tab_view.get_selected_page()
        for index in range(self._tab_view.get_n_pages()):
            page = self._tab_view.get_nth_page(index)
            container = self._containers.get(page)
            tab = container.capture() if container is not None else None
            if tab is None:
                continue
            if page == current:
                selected = len(tabs)
            tabs.append(tab)
        return SessionState(tuple(tabs), selected) if tabs else None

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
        page.set_title(title or APP_TITLE)
        if page == self._tab_view.get_selected_page():
            self.set_title(title or APP_TITLE)
            self._schedule_follow()

    def _on_selected_page_changed(self, *_args: object) -> None:
        container = self._current_container()
        if container is not None:
            self.set_title(container.title or APP_TITLE)
            self._schedule_follow()
            self._clear_attention()
            container_pane = container.focused_pane
            if container_pane is not None:
                container_pane.grab_focus()

    # -- workspaces (.shellac.toml) -----------------------------------------------------------

    def open_workspace(self, folder: str) -> None:
        """Open the tabs and splits of ``folder``'s workspace file, typing each pane's command.

        The file can come from a repository you cloned, so when it would run commands they are
        listed and you are asked first.
        """
        path = workspace_file(folder)
        if path is None:
            self.show_toast(f"No {WORKSPACE_FILE} in that folder")
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.show_toast(
                f"Cannot read {WORKSPACE_FILE}: {getattr(exc, 'strerror', None) or exc}"
            )
            return
        result = parse_workspace(text, folder)
        if result.workspace is None:
            self.show_toast(f"Cannot open {WORKSPACE_FILE}: {result.error}")
            return
        workspace = result.workspace

        def start() -> None:
            self._start_workspace(workspace)
            if result.warnings:
                more = len(result.warnings) - 1
                suffix = f" (and {more} more)" if more else ""
                self.show_toast(f"{WORKSPACE_FILE}: {result.warnings[0]}{suffix}")

        commands = commands_in(workspace)
        if commands:
            heading, body = confirm_text(commands)
            self._ask(heading, body, "Run", start)
        else:
            start()

    def _start_workspace(self, workspace: Workspace) -> None:
        first_index = self._tab_view.get_n_pages()
        for tab in workspace.tabs:
            container = self.new_tab(cwd=first_cwd(tab.layout))
            container.restore_layout(tab)
            for pane, state in zip(container.panes(), panes_of(tab.layout), strict=False):
                if state.command:
                    pane.type_when_ready(state.command)
        self._select_tab(first_index)
        GLib.idle_add(self._refocus_once)  # the other new tabs queued focus grabs; see restore

    def save_workspace(self, folder: str) -> None:
        """Write the current tab's splits and directories to ``folder``'s workspace file."""
        container = self._current_container()
        tab = container.capture() if container is not None else None
        if tab is None:
            self.show_toast("Nothing to save in this tab")
            return
        path = os.path.join(folder, WORKSPACE_FILE)
        text = workspace_to_toml(tab, folder)

        def write() -> None:
            temporary = f"{path}.tmp"
            try:
                with open(temporary, "w", encoding="utf-8") as handle:
                    handle.write(text)
                os.replace(temporary, path)
            except OSError as exc:
                with contextlib.suppress(OSError):
                    os.unlink(temporary)
                self.show_toast(f"Cannot save {WORKSPACE_FILE}: {exc.strerror or exc}")
                return
            self.show_toast(f"Saved {WORKSPACE_FILE}")

        if os.path.exists(path):
            self._ask(
                "Replace the workspace?",
                f"This folder already has a {WORKSPACE_FILE}. Saving replaces it with the layout "
                "of this tab. Commands in the old file are not kept.",
                "Replace",
                write,
                destructive=True,
            )
        else:
            write()

    def _ask(
        self,
        heading: str,
        body: str,
        yes_label: str,
        on_yes: Callable[[], None],
        *,
        destructive: bool = False,
    ) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("yes", yes_label)
        appearance = (
            Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED
        )
        dialog.set_response_appearance("yes", appearance)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def answered(_dialog: Adw.AlertDialog, response: str) -> None:
            if response == "yes":
                on_yes()

        dialog.connect("response", answered)
        dialog.present(self)

    # -- finished commands (general.finished_*) ---------------------------------------------

    def _poll_commands(self) -> bool:
        general = self._config.general
        if not (general.finished_tab_marker or general.finished_notification):
            self._watches.clear()  # turning it on later must not report what ran meanwhile
            return GLib.SOURCE_CONTINUE
        now = time.monotonic()
        for page, container in list(self._containers.items()):
            for pane in container.panes():
                if not pane.runs_shell:
                    continue
                watch = self._watches.setdefault(pane, CommandWatch())
                running = pane.is_running_command()
                finished = watch.update(running, pane.busy_with() if running else None, now)
                if finished is not None and finished.seconds >= general.finished_after_seconds:
                    self._command_finished(page, finished)
        return GLib.SOURCE_CONTINUE

    def _command_finished(self, page: Adw.TabPage, finished: FinishedCommand) -> None:
        general = self._config.general
        who = attention(
            tab_selected=page == self._tab_view.get_selected_page(),
            window_active=self.is_active(),
            marker_on=general.finished_tab_marker,
            notification_on=general.finished_notification,
        )
        if who.mark_tab:
            page.set_needs_attention(True)
        if who.notify and (app := self.get_application()) is not None:
            title, body = notification_text(page.get_title(), finished)
            notification = Gio.Notification.new(title)
            notification.set_body(body)
            notification.set_default_action("app.present-window")
            ident = f"finished-{len(self._finished_ids)}-{int(time.monotonic() * 1000)}"
            self._finished_ids.add(ident)
            app.send_notification(ident, notification)

    def _clear_attention(self) -> None:
        page = self._tab_view.get_selected_page()
        if page is not None:
            page.set_needs_attention(False)

    def _on_active_changed(self, *_args: object) -> None:
        """Coming back to the window: the shown tab is attended to and old popups are stale."""
        if not self.is_active():
            return
        self._clear_attention()
        app = self.get_application()
        if app is not None:
            for ident in self._finished_ids:
                app.withdraw_notification(ident)
        self._finished_ids.clear()

    # -- closing with a program running (general.confirm_close_running) --------------------

    def _running_panes(self, panes: list[TerminalPane]) -> list[TerminalPane]:
        """The panes that closing would end a program in, or none if the setting is off."""
        if not self._config.general.confirm_close_running:
            return []
        return [p for p in panes if p.is_running_command()]

    def _confirm_close(
        self,
        scope: Scope,
        panes: list[TerminalPane],
        on_yes: Callable[[], None],
        on_no: Callable[[], None] | None = None,
    ) -> None:
        """Run ``on_yes`` now if nothing in ``panes`` is running a command (or the setting is
        off); otherwise ask first. ``on_no`` runs if the user keeps things open."""
        running = self._running_panes(panes)
        if not running:
            on_yes()
            return
        if self._confirming_close:  # one question at a time
            if on_no is not None:
                on_no()
            return
        heading, body = close_dialog_text(scope, [p.busy_with() for p in running])
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("keep", "Keep open")
        dialog.add_response("close", "Close")
        dialog.set_response_appearance("close", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("keep")
        dialog.set_close_response("keep")
        self._confirming_close = True

        def answered(_dialog: Adw.AlertDialog, response: str) -> None:
            self._confirming_close = False
            if response == "close":
                on_yes()
            elif on_no is not None:
                on_no()
            self._focus_current()

        dialog.connect("response", answered)
        dialog.present(self)

    def _close_focused_pane(self) -> None:
        container = self._current_container()
        pane = container.focused_pane if container is not None else None
        if container is None or pane is None:
            return
        if len(container.panes()) > 1:
            scope: Scope = "pane"
        elif self._tab_view.get_n_pages() > 1:
            scope = "tab"
        else:
            scope = "window"
        self._confirm_close(scope, [pane], lambda: container.close_pane(pane))

    def _on_close_page(self, view: Adw.TabView, page: Adw.TabPage) -> bool:
        container = self._containers.get(page)
        if container is None:
            return False  # let the tab view close it
        scope: Scope = "tab" if view.get_n_pages() > 1 else "window"
        panes = container.panes()
        if not self._running_panes(panes):
            return False
        self._confirm_close(
            scope,
            panes,
            on_yes=lambda: view.close_page_finish(page, True),
            on_no=lambda: view.close_page_finish(page, False),
        )
        return True

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

        self._add_action("search", self.open_search)
        self._add_action("command_palette", self.open_palette)
        self._add_action("settings", self.open_settings)
        self._add_action("zoom_in", lambda: self._zoom(+1))
        self._add_action("zoom_out", lambda: self._zoom(-1))
        self._add_action("zoom_reset", lambda: self._zoom(0))
        self._add_action("toggle_sidebar", self.toggle_sidebar)
        self._add_action("focus_sidebar", self.focus_sidebar)
        self._add_action("copy", on_pane("copy"))
        self._add_action("paste", on_pane("paste"))
        self._add_action("select_all", on_pane("select_all"))
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
        self._add_action("close_pane", self._close_focused_pane)
        self._add_action("zoom_pane", on_container(lambda c: c.toggle_zoom()))
        for direction in Direction:
            self._add_action(
                f"focus_{direction.value}",
                on_container(lambda c, d=direction: c.focus_direction(d)),
            )
            self._add_action(
                f"resize_{direction.value}",
                lambda d=direction: self._resize(d),
            )

    def _resize(self, direction: Direction) -> None:
        """Move a divider: the sidebar's while it has focus, else the focused pane's."""
        if self._sidebar.get_visible() and self._sidebar.has_focus_inside():
            if direction.axis is Axis.HORIZONTAL:
                step = self._config.panes.resize_step * direction.sign
                width = self._paned.get_position() + step
                self._paned.set_position(max(MIN_WIDTH, min(MAX_WIDTH, width)))
            return
        container = self._current_container()
        if container is not None:
            container.resize(direction)

    def _add_action(self, name: str, callback: Callable[[], object]) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", lambda *_: callback())
        self.add_action(action)

    # -- command palette -----------------------------------------------------------------

    def _update_palette_tooltip(self) -> None:
        accels = self._application_bindings().get("command_palette", [])
        shortcut = f" ({' + '.join(accelerator_tokens(accels[0]))})" if accels else ""
        self._palette_button.set_tooltip_text(f"Command palette{shortcut}")

    def _application_bindings(self) -> dict[str, list[str]]:
        app = self.get_application()
        return app.keybindings() if app is not None else {}

    def _update_settings_tooltip(self) -> None:
        accels = self._application_bindings().get("settings", [])
        shortcut = f" ({' + '.join(accelerator_tokens(accels[0]))})" if accels else ""
        self._settings_button.set_tooltip_text(f"Settings{shortcut}")

    def open_settings(self, page: str | None = None) -> None:
        """Show the settings window (created on first use, then reused)."""
        app = self.get_application()
        if app is None:
            return
        if self._settings is None:
            self._settings = SettingsWindow(
                self,
                self._saved_config,
                on_save=app.save_settings,
                on_preview=app.preview_theme,
                on_preview_appearance=app.preview_appearance,
                active_theme=app.active_theme,
                on_open_shortcuts=lambda: self.open_palette(edit=True),
            )
        self._settings.open(page)

    def open_palette(self, edit: bool = False) -> None:
        """Show the command palette (created on first use, then reused)."""
        app = self.get_application()
        if app is None:
            return
        if self._palette is None:
            self._palette = CommandPalette(
                self,
                self._application_bindings(),
                run=self._run_palette_action,
                on_change=app.save_keybindings,
            )
        self._palette.set_bindings(self._application_bindings())
        self._palette.open(edit=edit)

    def _run_palette_action(self, action: str) -> None:
        self.present()
        # Let the main window take focus first, so the action sees the right pane.
        GLib.idle_add(lambda: self.activate_action(f"win.{action}", None) and False)

    # -- search and zoom (FR-7, FR-8) ------------------------------------------------------

    def open_search(self) -> None:
        pane = self._focused_pane()
        if pane is not None:
            self._search.open(pane.terminal)

    def _zoom(self, direction: int) -> None:
        """Zoom in (+1), out (-1) or reset (0), on the focused pane or the whole window."""
        step = self._config.appearance.zoom_step
        window_wide = self._config.appearance.zoom_scope == "window"
        pane = self._focused_pane()
        if pane is None:
            return
        base = self._font_scale if window_wide else pane.font_scale
        scale = 1.0 if direction == 0 else base + direction * step
        if window_wide:
            self._font_scale = scale
            for container in self._containers.values():
                container.set_font_scale(scale)
        else:
            pane.set_font_scale(scale)

    # -- sidebar ------------------------------------------------------------------------

    def toggle_sidebar(self) -> None:
        """Show or hide the sidebar (FR-24). Focus goes back to the terminal when hiding."""
        self._set_sidebar_visible(not self._sidebar.get_visible())

    def focus_sidebar(self) -> None:
        if not self._sidebar.get_visible():
            self._set_sidebar_visible(True)
        self._sidebar.focus_tree()

    def _set_sidebar_visible(self, visible: bool) -> None:
        had_focus = self._sidebar.has_focus_inside()
        self._sidebar.set_visible(visible)
        self._sidebar_visible = visible
        if visible:
            self._paned.set_position(self._sidebar_width)
            self._schedule_follow()
        elif had_focus:
            self._focus_current()
        self._save_state_soon()

    def _on_paned_moved(self, *_args: object) -> None:
        if not self._sidebar.get_visible():
            return
        width = self._paned.get_position()
        if MIN_WIDTH <= width <= MAX_WIDTH and width != self._sidebar_width:
            self._sidebar_width = width
            self._save_state_soon()

    def _save_state_soon(self) -> None:
        if self._state_timer:
            GLib.source_remove(self._state_timer)
        self._state_timer = GLib.timeout_add(STATE_SAVE_DELAY_MS, self._save_state)

    def _save_state(self) -> bool:
        self._state_timer = 0
        # Re-read first: the application stores the chosen theme in the same file.
        state = self._state = load_state()
        state.sidebar_visible = self._sidebar_visible
        state.sidebar_width = self._sidebar_width
        state.window_maximized = self.is_maximized()
        # No tabs (the last shell exited) clears it, so the next start is a fresh one.
        restore = self._config.general.restore_session
        state.session = self._capture_session() if restore else None
        if not self.is_maximized() and not self.is_fullscreen():
            width, height = self.get_width(), self.get_height()
            if width > 0 and height > 0:
                state.window_width, state.window_height = width, height
        save_state(state)
        return GLib.SOURCE_REMOVE

    def _on_pin_changed(self, pinned: bool) -> None:
        if not pinned:
            self._last_followed = None
            self._schedule_follow()

    # -- follow mode (section 8.4) ------------------------------------------------------

    def _schedule_follow(self) -> None:
        if self._follow_timer:
            GLib.source_remove(self._follow_timer)
        self._follow_timer = GLib.timeout_add(FOLLOW_DEBOUNCE_MS, self._follow_now)

    def _poll_follow(self) -> bool:
        if self._sidebar.get_visible():
            self._sidebar.check_root()
        self._follow_now()
        return GLib.SOURCE_CONTINUE

    def _follow_now(self) -> bool:
        self._follow_timer = 0
        sidebar_config = self._config.sidebar
        if not sidebar_config.follow_cwd or self._sidebar.pinned:
            return GLib.SOURCE_REMOVE
        if not self._sidebar.get_visible():
            return GLib.SOURCE_REMOVE
        container = self._current_container()
        pane = container.focused_pane if container is not None else None
        cwd = pane.current_directory() if pane is not None else None
        if not cwd or not os.path.isdir(cwd):
            return GLib.SOURCE_REMOVE
        cwd = os.path.normpath(cwd)
        if cwd == self._last_followed and self._sidebar.root_path is not None:
            return GLib.SOURCE_REMOVE
        self._last_followed = cwd
        self._sidebar.set_git_hint(cwd)
        root = self._sidebar.root_path
        if (
            root
            and cwd != root
            and sidebar_config.reveal_in_root
            and self._sidebar.model.contains(cwd)
        ):
            self._sidebar.reveal(cwd, expand=True)
        elif cwd != root:
            self._sidebar.set_root(cwd)
        return GLib.SOURCE_REMOVE

    # -- activation (FR-32, section 8.5) ------------------------------------------------

    def _on_sidebar_activate(self, node: Node) -> None:
        if node.is_dir:
            self._activate_directory(node.path)
        else:
            self._activate_file(node.path)

    def _focused_pane(self):  # noqa: ANN202
        container = self._current_container()
        return container.focused_pane if container is not None else None

    def _activate_directory(self, path: str) -> None:
        if self._config.sidebar.on_dir_activate == "reroot":
            self._sidebar.set_root(path)
            return
        pane = self._focused_pane()
        if pane is None:
            return
        if not pane.is_idle():
            busy = pane.busy_with()
            what = f" ({busy} is running)" if busy else ""
            self.show_toast(f"Pane is busy{what}; not typing into it")
            return
        pane.send_text(cd_command(path))

    def _activate_file(self, path: str) -> None:
        plan = plan_file_action(path, self._config.sidebar)
        if isinstance(plan, Problem):
            self.show_toast(plan.message)
            return
        if plan.placement == "paste":
            pane = self._focused_pane()
            if pane is not None:
                pane.paste_text(path_text(path))
                pane.grab_focus()
        elif plan.placement == "desktop":
            launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(path))
            launcher.launch(self, None, self._launch_finished, launcher)
        elif plan.placement == "tab":
            self.new_tab(cwd=os.path.dirname(path), argv=plan.argv)
        else:
            container = self._current_container()
            if container is None:
                return
            axis = (
                Axis.VERTICAL
                if self._config.sidebar.editor_split_direction == "down"
                else Axis.HORIZONTAL
            )
            container.split(axis, argv=plan.argv, cwd=os.path.dirname(path))

    def _launch_finished(
        self, launcher: Gtk.FileLauncher, result: Gio.AsyncResult, _l: object
    ) -> None:
        try:
            launcher.launch_finish(result)
        except GLib.Error as exc:
            self.show_toast(f"Cannot open file: {exc.message}")

    def show_toast(self, message: str, *, replace_previous: bool = False) -> None:
        """Show a toast. ``replace_previous`` first removes the last one shown this way, so a
        quick series (switching themes) shows the newest message, not a queue of old ones."""
        toast = Adw.Toast.new(message)
        if replace_previous:
            if self._status_toast is not None:
                self._status_toast.dismiss()
            self._status_toast = toast
            toast.connect("dismissed", self._status_toast_dismissed)
        self._toasts.add_toast(toast)

    def _status_toast_dismissed(self, toast: Adw.Toast) -> None:
        if self._status_toast is toast:
            self._status_toast = None

    # -- lifecycle ----------------------------------------------------------------------

    def _close_after_confirm(self) -> None:
        self._close_confirmed = True
        self.close()

    def do_close_request(self) -> bool:
        if not self._close_confirmed:
            panes = [p for c in self._containers.values() for p in c.panes()]
            if self._running_panes(panes):
                self._confirm_close("window", panes, on_yes=self._close_after_confirm)
                return True  # stay open until the user answers
        for source in (self._follow_timer, self._poll_id, self._command_poll_id):
            if source:
                GLib.source_remove(source)
        self._follow_timer = self._poll_id = self._command_poll_id = 0
        if self._state_timer:
            GLib.source_remove(self._state_timer)
        self._save_state()  # also remembers the window size
        if self._palette is not None:
            self._palette.destroy()
            self._palette = None
        if self._settings is not None:
            self._settings.destroy()
            self._settings = None
        self._sidebar.close()
        # End every shell so nothing is left running after the window closes (M2 acceptance).
        for container in list(self._containers.values()):
            container.shutdown()
        self._containers.clear()
        return Adw.ApplicationWindow.do_close_request(self)
