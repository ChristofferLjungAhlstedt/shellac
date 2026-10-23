"""TerminalPane: wraps a ``Vte.Terminal`` running the user's shell (section 5.1)."""

from __future__ import annotations

import contextlib
import logging
import os
import signal
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Vte", "3.91")
from gi.repository import Gdk, GLib, Gtk, Pango, Vte  # noqa: E402

from .config import Config  # noqa: E402
from .links import URL_PATTERN, is_openable  # noqa: E402
from .shell import (  # noqa: E402
    build_environment,
    cwd_from_uri,
    read_proc_cwd,
    resolve_shell,
    resolve_working_directory,
)
from .terminal_actions import foreground_name, is_shell_idle  # noqa: E402
from .theme import Theme  # noqa: E402

log = logging.getLogger(__name__)

# Tried after the configured family; Pango picks the first one that is installed
# and finally falls back to the system monospace font (FR-39).
FALLBACK_FONT_FAMILIES = ("JetBrainsMono Nerd Font", "FiraCode Nerd Font", "Iosevka", "Monospace")

MIN_FONT_SCALE = 0.25
MAX_FONT_SCALE = 5.0

PCRE2_MULTILINE = 0x00000400  # VTE requires this flag on match regexes

DEFAULT_TITLE = "Terminal"
PANE_CSS_CLASS = "paneterm-pane"

_CURSOR_SHAPES = {
    "block": Vte.CursorShape.BLOCK,
    "ibeam": Vte.CursorShape.IBEAM,
    "underline": Vte.CursorShape.UNDERLINE,
}

PaneCallback = Callable[["TerminalPane"], None]


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
        argv: list[str] | None = None,
        on_exited: Callable[[TerminalPane, int], None] | None = None,
        on_title_changed: PaneCallback | None = None,
        on_focus: PaneCallback | None = None,
    ) -> None:
        self._on_exited = on_exited
        self._on_title_changed = on_title_changed
        self._on_focus = on_focus
        self._closed = False
        self.child_pid: int | None = None

        self.terminal = Vte.Terminal()
        self.terminal.set_hexpand(True)
        self.terminal.set_vexpand(True)

        # Vte.Terminal implements Gtk.Scrollable, so a ScrolledWindow gives us the scrollbar.
        self.widget = Gtk.ScrolledWindow()
        self.widget.add_css_class(PANE_CSS_CLASS)
        self.widget.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.widget.set_child(self.terminal)

        self._handlers = [
            self.terminal.connect("child-exited", self._handle_child_exited),
            self.terminal.connect("window-title-changed", self._handle_title_changed),
            self.terminal.connect("notify::current-directory-uri", self._handle_title_changed),
        ]
        self._focus_controller: Gtk.EventControllerFocus | None = Gtk.EventControllerFocus()
        self._focus_handler = self._focus_controller.connect("enter", self._handle_focus_enter)
        self.terminal.add_controller(self._focus_controller)

        self._clickable_urls = config.general.clickable_urls
        self._setup_links()

        self.apply_style(config, theme)
        self.runs_shell = argv is None  # False for a pane that runs one command, e.g. an editor
        self._spawn(config, cwd, argv)

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
        self._clickable_urls = config.general.clickable_urls

    # -- font zoom (FR-8) ---------------------------------------------------------------

    @property
    def font_scale(self) -> float:
        return self.terminal.get_font_scale()

    def set_font_scale(self, scale: float) -> None:
        self.terminal.set_font_scale(round(min(max(scale, MIN_FONT_SCALE), MAX_FONT_SCALE), 3))

    # -- clickable links (FR-6) ---------------------------------------------------------

    def _setup_links(self) -> None:
        self.terminal.set_allow_hyperlink(True)  # OSC 8 links
        regex = Vte.Regex.new_for_match(URL_PATTERN, -1, PCRE2_MULTILINE)
        tag = self.terminal.match_add_regex(regex, 0)
        self.terminal.match_set_cursor_name(tag, "pointer")
        self._click = Gtk.GestureClick(button=1)
        self._click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._click_handler = self._click.connect("pressed", self._handle_click)
        self.terminal.add_controller(self._click)

    def uri_at(self, x: float, y: float) -> str | None:
        link = self.terminal.check_hyperlink_at(x, y)
        if link:
            return link
        text, _tag = self.terminal.check_match_at(x, y)
        return text or None

    def _handle_click(self, gesture: Gtk.GestureClick, _presses: int, x: float, y: float) -> None:
        state = gesture.get_current_event_state()
        if not self._clickable_urls or not state & Gdk.ModifierType.CONTROL_MASK:
            return
        uri = self.uri_at(x, y)
        if not uri or not is_openable(uri):
            return
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)  # no selection starts from this click
        launcher = Gtk.UriLauncher.new(uri)
        launcher.launch(self.widget.get_root(), None, self._uri_launched)

    @staticmethod
    def _uri_launched(launcher: Gtk.UriLauncher, result: object) -> None:
        try:
            launcher.launch_finish(result)
        except GLib.Error as exc:
            log.warning("cannot open %s: %s", launcher.get_uri(), exc.message)

    # -- process ------------------------------------------------------------------------

    def _spawn(self, config: Config, cwd: str | None, command: list[str] | None) -> None:
        if command is not None:
            argv = command
        else:
            shell = resolve_shell(config.general.shell)
            argv = [shell, "-l"] if config.general.login_shell else [shell]
        self.terminal.spawn_async(
            Vte.PtyFlags.DEFAULT,
            resolve_working_directory(cwd),
            argv,
            build_environment(),
            GLib.SpawnFlags.SEARCH_PATH,  # lets a command name like "nano" resolve
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

    # -- state --------------------------------------------------------------------------

    def current_directory(self) -> str | None:
        """OSC 7 first, then ``/proc/<pid>/cwd`` (FR-9). Callers verify it still exists."""
        return cwd_from_uri(self.terminal.get_current_directory_uri()) or read_proc_cwd(
            self.child_pid
        )

    def display_title(self) -> str:
        """The title the shell set, else the directory name, else a generic label."""
        title = self.terminal.get_window_title()
        if title:
            return title
        cwd = self.current_directory()
        if cwd:
            return os.path.basename(cwd.rstrip("/")) or "/"
        return DEFAULT_TITLE

    def _handle_title_changed(self, *_args: object) -> None:
        if self._on_title_changed is not None:
            self._on_title_changed(self)

    def _handle_focus_enter(self, _controller: Gtk.EventControllerFocus) -> None:
        if self._on_focus is not None:
            self._on_focus(self)

    # -- sending input (section 8.5) -----------------------------------------------------

    def is_idle(self) -> bool:
        """True when this pane's shell is at a prompt, so typing a command is safe."""
        if not self.runs_shell or self.child_pid is None:
            return False
        pty = self.terminal.get_pty()
        return pty is not None and is_shell_idle(pty.get_fd(), self.child_pid)

    def busy_with(self) -> str | None:
        """Name of what is running in the foreground, for messages."""
        pty = self.terminal.get_pty()
        return foreground_name(pty.get_fd()) if pty is not None else None

    def send_text(self, text: str) -> None:
        """Type ``text`` into the terminal as if the user had. Callers check ``is_idle``."""
        self.terminal.feed_child(text.encode())

    # -- clipboard and focus ------------------------------------------------------------

    def copy(self) -> None:
        self.terminal.copy_clipboard_format(Vte.Format.TEXT)

    def paste(self) -> None:
        self.terminal.paste_clipboard()

    def paste_text(self, text: str) -> None:
        self.terminal.paste_text(text)

    def grab_focus(self) -> None:
        self.terminal.grab_focus()

    # -- cleanup ------------------------------------------------------------------------

    def close(self, *, terminate: bool = True) -> None:
        """Release handlers and end the shell, so a closed pane leaves nothing behind (NFR-4)."""
        if self._closed:
            return
        self._closed = True
        for handler in self._handlers:
            self.terminal.disconnect(handler)
        self._handlers.clear()
        # The controller's handler references this pane; disconnect it and drop the
        # controller, or pane and terminal would keep each other alive forever.
        if self._focus_controller is not None:
            self._focus_controller.disconnect(self._focus_handler)
            self.terminal.remove_controller(self._focus_controller)
            self._focus_controller = None
        self._on_exited = None
        self._on_title_changed = None
        self._on_focus = None
        self._click.disconnect(self._click_handler)
        self.terminal.remove_controller(self._click)
        if terminate and self.child_pid is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(self.child_pid, signal.SIGHUP)
            self.child_pid = None
