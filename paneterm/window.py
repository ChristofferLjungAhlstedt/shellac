"""MainWindow: header bar plus the terminal area (section 4)."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio  # noqa: E402

from . import APP_NAME  # noqa: E402
from .config import Config  # noqa: E402
from .terminal_pane import TerminalPane  # noqa: E402
from .theme import Theme  # noqa: E402


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

        # M1 has a single pane. M2 replaces this with the tab view and pane tree.
        self.pane = TerminalPane(
            config,
            theme,
            on_exited=self._on_pane_exited,
            on_title_changed=self._on_pane_title_changed,
        )

        self._toasts = Adw.ToastOverlay()
        self._toasts.set_child(self.pane.widget)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(self._toasts)
        self.set_content(toolbar)

        self._add_action("copy", lambda *_: self.pane.copy())
        self._add_action("paste", lambda *_: self.pane.paste())

        if warnings:
            # Shown once; the full list is in the log (FR-45).
            noun = "warning" if len(warnings) == 1 else "warnings"
            self.show_toast(f"{len(warnings)} configuration {noun}. See the log for details.")

        self.connect("map", lambda *_: self.pane.grab_focus())

    def show_toast(self, message: str) -> None:
        self._toasts.add_toast(Adw.Toast.new(message))

    def _add_action(self, name: str, callback) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)

    def _on_pane_exited(self, _pane: TerminalPane, _status: int) -> None:
        # FR-3: the last pane exiting closes the window.
        self.close()

    def _on_pane_title_changed(self, _pane: TerminalPane, title: str) -> None:
        self.set_title(title or APP_NAME)

    def do_close_request(self) -> bool:
        self.pane.close()
        return Adw.ApplicationWindow.do_close_request(self)
