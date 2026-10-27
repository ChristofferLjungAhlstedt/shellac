"""SearchBar: the small overlay for searching a terminal's scrollback (FR-7).

Uses VTE's own search (``search_set_regex`` / ``search_find_next`` / ``search_find_previous``),
so matches are highlighted by the terminal and the scrollback is never copied.
"""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Vte", "3.91")
from gi.repository import Gdk, GLib, Gtk, Vte  # noqa: E402

CSS_CLASS = "shellac-search"
PCRE2_CASELESS = 0x00000008
PCRE2_MULTILINE = 0x00000400  # VTE requires this flag on search regexes


class SearchBar(Gtk.Box):
    def __init__(
        self,
        *,
        case_sensitive: bool,
        wrap_around: bool,
        on_close: Callable[[], None],
    ) -> None:
        super().__init__(spacing=2)
        self.add_css_class(CSS_CLASS)
        self._on_close = on_close
        self._wrap_around = wrap_around
        self._terminal: Vte.Terminal | None = None

        self._entry = Gtk.SearchEntry(placeholder_text="Find in scrollback", width_chars=22)
        self._entry.connect("search-changed", lambda _e: self._update(first=True))
        self._entry.connect("activate", lambda _e: self.find(backwards=False))
        self._entry.connect("stop-search", lambda _e: self.close())
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key_pressed)
        self._entry.add_controller(keys)
        self.append(self._entry)

        self._previous = self._button(
            "shellac-chevron-up-symbolic", "Previous match (Shift+Enter)", False
        )
        self._next = self._button("shellac-chevron-down-symbolic", "Next match (Enter)", True)
        self._case = Gtk.ToggleButton(label="Aa", tooltip_text="Match case", active=case_sensitive)
        self._case.add_css_class("flat")
        self._case.connect("toggled", lambda _b: self._update(first=False))
        close = Gtk.Button(icon_name="shellac-close-symbolic", tooltip_text="Close (Escape)")
        close.add_css_class("flat")
        close.connect("clicked", lambda _b: self.close())
        for widget in (self._previous, self._next, self._case, close):
            self.append(widget)

    def _button(self, icon: str, tip: str, forwards: bool) -> Gtk.Button:
        button = Gtk.Button(icon_name=icon, tooltip_text=tip)
        button.add_css_class("flat")
        button.connect("clicked", lambda _b: self.find(backwards=not forwards))
        return button

    # -- use ----------------------------------------------------------------------------

    def open(self, terminal: Vte.Terminal) -> None:
        """Show the bar and search ``terminal``. Selected text becomes the search text."""
        if self._terminal is not None and self._terminal is not terminal:
            self._terminal.search_set_regex(None, 0)
        self._terminal = terminal
        self.set_visible(True)
        if terminal.get_has_selection():
            clipboard = terminal.get_display().get_primary_clipboard()
            clipboard.read_text_async(None, self._selection_read)
        self._entry.grab_focus()
        self._update(first=False)

    def _selection_read(self, clipboard: Gdk.Clipboard, result: object) -> None:
        try:
            text = clipboard.read_text_finish(result)
        except GLib.Error:
            return
        if text and "\n" not in text:
            self._entry.set_text(text)
            self._entry.select_region(0, -1)

    def close(self) -> None:
        terminal = self._terminal
        if terminal is not None:
            terminal.search_set_regex(None, 0)
        self._terminal = None
        self.set_visible(False)
        self._on_close()
        if terminal is not None:
            terminal.grab_focus()

    def find(self, *, backwards: bool) -> None:
        terminal = self._terminal
        if terminal is None or not self._entry.get_text():
            return
        if backwards:
            terminal.search_find_previous()
        else:
            terminal.search_find_next()

    # -- internals ----------------------------------------------------------------------

    def _update(self, *, first: bool) -> None:
        terminal = self._terminal
        if terminal is None:
            return
        text = self._entry.get_text()
        if not text:
            terminal.search_set_regex(None, 0)
            self._entry.remove_css_class("error")
            return
        flags = PCRE2_MULTILINE | (0 if self._case.get_active() else PCRE2_CASELESS)
        try:
            regex = Vte.Regex.new_for_search(GLib.regex_escape_string(text, -1), -1, flags)
        except GLib.Error:
            self._entry.add_css_class("error")
            return
        self._entry.remove_css_class("error")
        terminal.search_set_regex(regex, 0)
        terminal.search_set_wrap_around(self._wrap_around)
        if first:
            self.find(backwards=True)  # the newest match is the one at the bottom

    def _key_pressed(
        self, _c: Gtk.EventControllerKey, keyval: int, _code: int, state: Gdk.ModifierType
    ) -> bool:
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and state & Gdk.ModifierType.SHIFT_MASK:
            self.find(backwards=True)
            return True
        return False
