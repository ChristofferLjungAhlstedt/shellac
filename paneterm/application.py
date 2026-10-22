"""Application: config and theme loading, chrome CSS, accelerators (section 4.1)."""

from __future__ import annotations

import logging
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from . import APP_ID  # noqa: E402
from .config import load_config  # noqa: E402
from .theme import Theme, generate_css, get_theme  # noqa: E402
from .window import MainWindow  # noqa: E402

log = logging.getLogger(__name__)

# Actions the window implements, bound as ``win.<name>``. An action is only bound once
# the milestone that implements it has landed; the remaining configured bindings
# (toggle_sidebar, search, cycle_theme) are accepted but not registered yet.
IMPLEMENTED_ACTIONS = (
    "copy",
    "paste",
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
)
ACTION_TARGETS: dict[str, str] = {name: f"win.{name}" for name in IMPLEMENTED_ACTIONS}


class Application(Adw.Application):
    def __init__(self, config_file: Path | None = None) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

        result = load_config(config_file)
        self.config = result.config
        self.theme: Theme
        self.theme, theme_warnings = get_theme(self.config.appearance.theme)
        self.warnings = [*result.warnings, *theme_warnings]
        for warning in self.warnings:
            log.warning("config: %s", warning)

        self._css_provider: Gtk.CssProvider | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self._apply_chrome()
        self._register_accelerators()

    def do_activate(self) -> None:
        window = self.props.active_window
        if window is None:
            window = MainWindow(self, self.config, self.theme, self.warnings)
        window.present()

    # -- chrome -------------------------------------------------------------------------

    def _apply_chrome(self) -> None:
        """Load the theme's CSS at display level and pick light/dark (section 8.6)."""
        appearance = self.config.appearance
        manager = Adw.StyleManager.get_default()
        if appearance.follow_system_scheme:
            manager.set_color_scheme(Adw.ColorScheme.DEFAULT)
        else:
            manager.set_color_scheme(
                Adw.ColorScheme.FORCE_DARK if self.theme.dark else Adw.ColorScheme.FORCE_LIGHT
            )

        provider = Gtk.CssProvider()
        css = generate_css(self.theme, appearance)
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

    def _register_accelerators(self) -> None:
        for action, accel in self.config.keybindings.items():
            target = ACTION_TARGETS.get(action)
            if target is None:
                log.debug("no handler for '%s' yet; binding skipped", action)
                continue
            self.set_accels_for_action(target, [accel])
