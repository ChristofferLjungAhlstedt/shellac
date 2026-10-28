"""Application: config and theme lifecycle, chrome CSS, accelerators, live reload (section 4.1).

The application owns the current ``Config`` and ``Theme`` and is the only place that
changes them. ``_apply()`` pushes the result to the chrome (CSS) and to every window,
which pushes it to every pane, so a theme or config change updates everything at once.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID  # noqa: E402
from .config import Config, config_dir, config_path, load_config, user_themes_dir  # noqa: E402
from .file_tree import register_icons  # noqa: E402
from .keybinding_edit import save_binding_changes  # noqa: E402
from .keybindings import ACCELERATOR_ALIASES, all_bindings  # noqa: E402
from .state import load_state, save_state  # noqa: E402
from .theme import (  # noqa: E402
    Theme,
    choose_theme_id,
    generate_css,
    get_theme,
    next_theme_id,
    theme_basis,
    theme_ids,
)
from .window import MainWindow  # noqa: E402

log = logging.getLogger(__name__)

# Actions the window implements, bound as ``win.<name>``. An action is only bound once
# the milestone that implements it has landed; the remaining configured bindings
#
IMPLEMENTED_ACTIONS = (
    "copy",
    "paste",
    "select_all",
    "split_down",
    "split_right",
    "close_pane",
    "zoom_pane",
    "focus_left",
    "focus_right",
    "focus_up",
    "focus_down",
    "resize_left",
    "resize_right",
    "resize_up",
    "resize_down",
    "new_tab",
    "next_tab",
    "prev_tab",
    *(f"goto_tab_{n}" for n in range(1, 10)),
    "cycle_theme",
    "reload_config",
    "toggle_sidebar",
    "focus_sidebar",
    "search",
    "zoom_in",
    "zoom_out",
    "zoom_reset",
    "command_palette",
)
ACTION_TARGETS: dict[str, str] = {name: f"win.{name}" for name in IMPLEMENTED_ACTIONS}

# Editors save in bursts (write, rename, chmod...). Wait this long after the last event.
RELOAD_DEBOUNCE_MS = 250

_IGNORED_MONITOR_EVENTS = {
    Gio.FileMonitorEvent.ATTRIBUTE_CHANGED,
    Gio.FileMonitorEvent.PRE_UNMOUNT,
    Gio.FileMonitorEvent.UNMOUNTED,
}


class Application(Adw.Application):
    def __init__(self, config_file: Path | None = None) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self._config_file = config_file

        # Real values are set in do_startup, once Adwaita is initialised and the system
        # color scheme can be queried.
        self.config = Config()
        self.theme: Theme
        self.warnings: list[str] = []

        self._theme_override: str | None = None  # set by cycle_theme, cleared by a reload
        self._override_basis = ""  # the config's theme settings when it was set
        self._last_self_write = -1e9  # when the palette last saved shortcuts to the config
        self._css_provider: Gtk.CssProvider | None = None
        self._monitors: list[Gio.FileMonitor] = []
        self._reload_source = 0
        self._reload_keeps_override = True

    # -- lifecycle ----------------------------------------------------------------------

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        register_icons()  # also lets an uninstalled checkout find its own icon
        Gtk.Window.set_default_icon_name(APP_ID)
        self._load_config()
        self._restore_saved_theme()
        self._apply()
        self._register_accelerators()
        Adw.StyleManager.get_default().connect("notify::dark", self._on_system_scheme_changed)
        self._watch_files()

    def do_activate(self) -> None:
        window = self.props.active_window
        if window is None:
            window = MainWindow(self, self.config, self.theme, self.warnings)
        window.present()

    def do_shutdown(self) -> None:
        if self._reload_source:
            GLib.source_remove(self._reload_source)
            self._reload_source = 0
        for monitor in self._monitors:
            monitor.cancel()
        self._monitors.clear()
        Adw.Application.do_shutdown(self)

    # -- config and theme state ---------------------------------------------------------

    def _following_system(self) -> bool:
        return self.config.appearance.follow_system_scheme and self._theme_override is None

    def _load_config(self) -> None:
        """Read the config file and pick the theme. Never raises (FR-45)."""
        result = load_config(self._config_file)
        self.config = result.config
        self.warnings = list(result.warnings)
        self._resolve_theme()
        for warning in self.warnings:
            log.warning("config: %s", warning)

    def _restore_saved_theme(self) -> None:
        """Bring back the theme picked in the last session, if the config still agrees."""
        state = load_state()
        if state.theme is None or state.theme_basis != theme_basis(self.config.appearance):
            return
        if state.theme not in theme_ids():
            return
        self._theme_override = state.theme
        self._override_basis = state.theme_basis
        self._resolve_theme()

    def _remember_theme(self) -> None:
        """Store (or clear) the runtime theme choice in the state file, not in the config."""
        state = load_state()
        if self._theme_override is None:
            state.theme = state.theme_basis = None
        else:
            state.theme = self._theme_override
            state.theme_basis = theme_basis(self.config.appearance)
        save_state(state)

    def _resolve_theme(self) -> None:
        """Choose and load the theme: a runtime override, the system's, or the config's."""
        appearance = self.config.appearance
        manager = Adw.StyleManager.get_default()
        if self._theme_override is not None:
            theme_id = self._theme_override
        elif appearance.follow_system_scheme:
            # Let the system decide first, so ``get_dark`` reports its real preference.
            manager.set_color_scheme(Adw.ColorScheme.DEFAULT)
            theme_id = choose_theme_id(appearance, manager.get_dark())
        else:
            theme_id = appearance.theme
        self.theme, theme_warnings = get_theme(theme_id)
        self.warnings.extend(theme_warnings)

    def _apply(self) -> None:
        """Push the current config and theme to the chrome and to every window."""
        self._apply_chrome()
        for window in self.get_windows():
            if isinstance(window, MainWindow):
                window.apply_config(self.config, self.theme)

    def _apply_chrome(self) -> None:
        """Load the theme's CSS at display level and pick light/dark (section 8.6)."""
        manager = Adw.StyleManager.get_default()
        if not self._following_system():
            manager.set_color_scheme(
                Adw.ColorScheme.FORCE_DARK if self.theme.dark else Adw.ColorScheme.FORCE_LIGHT
            )

        provider = Gtk.CssProvider()
        css = generate_css(self.theme, self.config.appearance)
        if hasattr(provider, "load_from_string"):  # GTK 4.12+
            provider.load_from_string(css)
        else:
            provider.load_from_data(css.encode())

        display = Gdk.Display.get_default()
        if self._css_provider is not None:
            Gtk.StyleContext.remove_provider_for_display(display, self._css_provider)
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self._css_provider = provider

    def _on_system_scheme_changed(self, *_args: object) -> None:
        # Only relevant while following: our own FORCE_* calls also fire this signal.
        if self._following_system():
            self._resolve_theme()
            self._apply()

    # -- runtime actions ----------------------------------------------------------------

    def cycle_theme(self) -> None:
        """Switch to the next theme at runtime, everywhere at once (FR-38).

        The choice lasts until the config is reloaded. While following the system color
        scheme this pauses following, because a forced scheme hides the system's value.
        """
        was_following = self._following_system()
        self._theme_override = next_theme_id(self.theme.id, theme_ids())
        self._override_basis = theme_basis(self.config.appearance)
        self.warnings = []
        self._resolve_theme()
        self._remember_theme()
        self._apply()
        message = f"Theme: {self.theme.name}"
        if was_following:
            message += " (not following the system until the config is reloaded)"
        self._notify(message, self.warnings)

    def reload_config(
        self, *, keep_override: bool = False, soft: bool = False, quiet: bool = False
    ) -> None:
        """Re-read config, themes and keybindings and apply them (FR-46).

        A theme picked at runtime is dropped unless ``keep_override``. With ``soft`` it is
        dropped only if the config's own theme settings changed, so saving an unrelated
        setting (or a shortcut from the palette) leaves the picked theme alone.
        """
        if not keep_override and not soft:
            self._theme_override = None
            self._remember_theme()
        self._load_config()
        if (
            soft
            and not keep_override
            and self._theme_override is not None
            and theme_basis(self.config.appearance) != self._override_basis
        ):
            self._theme_override = None
            self._remember_theme()
            self._resolve_theme()
        self._apply()
        self._register_accelerators()
        if quiet and not self.warnings:
            return
        self._notify("Configuration reloaded", self.warnings)

    def save_keybindings(self, changes: dict[str, list[str] | None]) -> str | None:
        """Write shortcut changes into the config file; the file watcher then reloads it.

        Returns an error message, or None on success. Only the changed lines are touched.
        """
        error = save_binding_changes(Path(self._config_file or config_path()), changes)
        if error is None:
            self._last_self_write = time.monotonic()
        return error

    def keybindings(self) -> dict[str, list[str]]:
        return all_bindings(self.config.keybindings, self.config.extra_bindings)

    def _notify(self, message: str, warnings: list[str]) -> None:
        """Show one toast: the warnings count if there are any, else ``message``."""
        for warning in warnings:
            log.warning("config: %s", warning)
        if warnings:
            noun = "warning" if len(warnings) == 1 else "warnings"
            message = f"{len(warnings)} configuration {noun}: {warnings[0]}"
            if len(warnings) > 1:
                message += " (see the log for the rest)"
        window = self.props.active_window
        if isinstance(window, MainWindow):
            window.show_toast(message, replace_previous=True)

    # -- accelerators -------------------------------------------------------------------

    def _register_accelerators(self) -> None:
        # Clear first, so a binding the user removed or moved does not linger after a reload.
        for target in ACTION_TARGETS.values():
            self.set_accels_for_action(target, [])
        for action, accels in self.keybindings().items():
            target = ACTION_TARGETS.get(action)
            if target is None:
                log.debug("no handler for '%s' yet; binding skipped", action)
                continue
            self.set_accels_for_action(target, [*accels, *ACCELERATOR_ALIASES.get(action, ())])

    # -- live reload --------------------------------------------------------------------

    def _watch_files(self) -> None:
        """Watch the config file and the user themes directory (FR-46).

        Directories are watched rather than the file itself, because many editors save by
        writing a temporary file and renaming it over the original. The default config and
        themes directories are created first so there is always something to watch; they
        also show users where themes go.
        """
        config_file = Path(self._config_file or config_path())
        if self._config_file is None:
            for directory in (config_dir(), user_themes_dir()):
                try:
                    directory.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    log.warning("cannot create %s: %s", directory, exc.strerror)

        # (directory, only this file name or None for any *.toml, keeps a theme override)
        targets = (
            (config_file.parent, config_file.name, False),  # editing config resets an override
            (user_themes_dir(), None, True),  # editing a theme keeps it
        )
        for directory, only_name, keep_override in targets:
            if not directory.is_dir():
                continue
            try:
                monitor = Gio.File.new_for_path(str(directory)).monitor_directory(
                    Gio.FileMonitorFlags.WATCH_MOVES, None
                )
            except GLib.Error as exc:
                log.warning("cannot watch %s for changes: %s", directory, exc.message)
                continue
            monitor.connect("changed", self._on_files_changed, only_name, keep_override)
            self._monitors.append(monitor)

    def _on_files_changed(
        self,
        _monitor: Gio.FileMonitor,
        file: Gio.File,
        other: Gio.File | None,
        event: Gio.FileMonitorEvent,
        only_name: str | None,
        keep_override: bool,
    ) -> None:
        if event in _IGNORED_MONITOR_EVENTS:
            return
        # A rename reports both names: ``file`` is the old one and ``other`` the new one.
        names = {f.get_basename() or "" for f in (file, other) if f is not None}
        if only_name is not None:
            relevant = only_name in names
        else:
            relevant = any(name.endswith(".toml") for name in names)  # not swap files etc.
        if not relevant:
            return
        # A config edit wins over a theme-file edit if both land in one debounce window.
        self._reload_keeps_override = self._reload_keeps_override and keep_override
        if not self._reload_source:
            self._reload_source = GLib.timeout_add(RELOAD_DEBOUNCE_MS, self._run_debounced_reload)

    def _run_debounced_reload(self) -> bool:
        self._reload_source = 0
        keep, self._reload_keeps_override = self._reload_keeps_override, True
        log.debug("config files changed; reloading")
        quiet = time.monotonic() - self._last_self_write < 3.0
        self.reload_config(keep_override=keep, soft=True, quiet=quiet)
        return GLib.SOURCE_REMOVE
