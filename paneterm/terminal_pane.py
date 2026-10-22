"""TerminalPane: wraps a ``Vte.Terminal`` running the user's shell (section 5.1)."""

from __future__ import annotations

import logging
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Vte", "3.91")
from gi.repository import Gdk, GLib, Gtk, Pango, Vte  # noqa: E402

from .config import Config  # noqa: E402
from .shell import build_environment, resolve_shell, resolve_working_directory  # noqa: E402
from .theme import Theme  # noqa: E402

log = logging.getLogger(__name__)

# Tried after the configured family; Pango picks the first one that is installed
# and finally falls back to the system monospace font (FR-39).
FALLBACK_FONT_FAMILIES = ("JetBrainsMono Nerd Font", "FiraCode Nerd Font", "Iosevka", "Monospace")

_CURSOR_SHAPES = {
    "block": Vte.CursorShape.BLOCK,
    "ibeam": Vte.CursorShape.IBEAM,
    "underline": Vte.CursorShape.UNDERLINE,
}


def _rgba(color: str, alpha: float = 1.0) -> Gdk.RGBA:
    rgba = Gdk.RGBA()
    if not rgba.parse(color):
        raise ValueError(f"cannot parse color {color!r}")
    rgba.alpha = alpha
    return rgba


def font_family_list(configured: str) -> str:
    """Comma-separated family list: configured first, then fallbacks, without duplicates."""
    families: list[str] = []
    for family in (configured, *FALLBACK_FONT_FAMILIES):
        if family and family not in families:
            families.append(family)
    return ",".join(families)


class TerminalPane:
    """One terminal. ``widget`` is what gets placed in the layout."""

    def __init__(
        self,
        config: Config,
        theme: Theme,
        *,
        cwd: str | None = None,
        on_exited: Callable[[TerminalPane, int], None] | None = None,
        on_title_changed: Callable[[TerminalPane, str], None] | None = None,
    ) -> None:
        self._on_exited = on_exited
        self._on_title_changed = on_title_changed
        self.child_pid: int | None = None

        self.terminal = Vte.Terminal()
        self.terminal.set_hexpand(True)
        self.terminal.set_vexpand(True)

        # Vte.Terminal implements Gtk.Scrollable, so a ScrolledWindow gives us the scrollbar.
        self.widget = Gtk.ScrolledWindow()
        self.widget.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.widget.set_child(self.terminal)

        self._handlers = [
            self.terminal.connect("child-exited", self._handle_child_exited),
            self.terminal.connect("window-title-changed", self._handle_title_changed),
        ]

        self.apply_style(config, theme)
        self._spawn(config, cwd)

    # -- appearance ---------------------------------------------------------------------

    def apply_style(self, config: Config, theme: Theme) -> None:
        """Apply font, colors, cursor and scrollback (FR-4)."""
        appearance = config.appearance

        font = Pango.FontDescription()
        font.set_family(font_family_list(appearance.font_family))
        font.set_size(int(appearance.font_size * Pango.SCALE))
        self.terminal.set_font(font)

        # Opacity applies to the terminal background only, never to text (FR-40).
        self.terminal.set_colors(
            _rgba(theme.foreground),
            _rgba(theme.background, appearance.opacity),
            [_rgba(color) for color in theme.palette],
        )
        self.terminal.set_color_cursor(_rgba(theme.cursor))
        self.terminal.set_color_highlight(_rgba(theme.selection_background))
        self.terminal.set_color_highlight_foreground(_rgba(theme.selection_foreground))

        self.terminal.set_cursor_shape(_CURSOR_SHAPES[appearance.cursor_shape])
        self.terminal.set_cursor_blink_mode(
            Vte.CursorBlinkMode.ON if appearance.cursor_blink else Vte.CursorBlinkMode.OFF
        )
        self.terminal.set_scrollback_lines(config.general.scrollback_lines)

    # -- process ------------------------------------------------------------------------

    def _spawn(self, config: Config, cwd: str | None) -> None:
        shell = resolve_shell(config.general.shell)
        argv = [shell, "-l"] if config.general.login_shell else [shell]
        self.terminal.spawn_async(
            Vte.PtyFlags.DEFAULT,
            resolve_working_directory(cwd),
            argv,
            build_environment(),
            GLib.SpawnFlags.DEFAULT,
            None,  # child_setup
            None,  # child_setup_data
            -1,  # timeout
            None,  # cancellable
            self._handle_spawned,
        )

    def _handle_spawned(self, _terminal: Vte.Terminal, pid: int, error: GLib.Error | None) -> None:
        if error is not None:
            log.error("failed to start shell: %s", error.message)
            self.terminal.feed(f"\r\nFailed to start shell: {error.message}\r\n".encode())
            return
        self.child_pid = pid
        log.debug("spawned shell, pid %d", pid)

    def _handle_child_exited(self, _terminal: Vte.Terminal, status: int) -> None:
        log.debug("child exited with status %d", status)
        self.child_pid = None
        if self._on_exited is not None:
            self._on_exited(self, status)

    def _handle_title_changed(self, terminal: Vte.Terminal) -> None:
        if self._on_title_changed is not None:
            self._on_title_changed(self, terminal.get_window_title() or "")

    # -- clipboard and focus ------------------------------------------------------------

    def copy(self) -> None:
        self.terminal.copy_clipboard_format(Vte.Format.TEXT)

    def paste(self) -> None:
        self.terminal.paste_clipboard()

    def grab_focus(self) -> None:
        self.terminal.grab_focus()

    # -- cleanup ------------------------------------------------------------------------

    def close(self) -> None:
        """Disconnect handlers so a closed pane can be garbage collected (NFR-4)."""
        for handler in self._handlers:
            self.terminal.disconnect(handler)
        self._handlers.clear()
        self._on_exited = None
        self._on_title_changed = None
