"""The command palette: every command with its shortcuts, and an editor for them.

A small window that can stay open next to the terminal as a reference. The pen button
enlarges it and makes the shortcuts editable: click one to record a new key combination,
add a second shortcut with "+", remove one with its cross, or restore the default.
Edits are collected as a draft: nothing is written until Save is pressed, Cancel throws the
draft away, Reset puts every default back into the draft, and leaving with unsaved changes
asks first. Saving goes through the ``on_change`` callback, which edits the user's config file.
"""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from .commands import COMMANDS, GOTO_TAB_PREFIX, GROUPS, Command, matches  # noqa: E402
from .keybindings import (  # noqa: E402
    DEFAULT_KEYBINDINGS,
    accelerator_tokens,
    canonical_accelerator,
    is_safe_binding,
    owner_of,
    with_key,
)

COMPACT_SIZE = (460, 600)
EDIT_SIZE = (740, 720)
GOTO_ACTIONS = tuple(f"{GOTO_TAB_PREFIX}{n}" for n in range(1, 10))

# (accelerator list per action, or None to restore the default) -> error message or None
ChangeCallback = Callable[[dict[str, list[str] | None]], "str | None"]


def keycaps(accel: str, last: str | None = None) -> Gtk.Box:
    """One shortcut drawn as a row of key-shaped labels (``last`` replaces the final key)."""
    box = Gtk.Box(spacing=3, valign=Gtk.Align.CENTER)
    box.add_css_class("keycaps")
    tokens = accelerator_tokens(accel)
    if last is not None:
        tokens[-1] = last
    for token in tokens:
        label = Gtk.Label(label=token)
        label.add_css_class("keycap")
        box.append(label)
    return box


class CommandPalette(Adw.Window):
    def __init__(
        self,
        parent: Gtk.Window,
        bindings: dict[str, list[str]],
        run: Callable[[str], None],
        on_change: ChangeCallback,
    ) -> None:
        super().__init__(transient_for=parent, modal=False, hide_on_close=True)
        self.add_css_class("shellac-palette")
        self._saved = {a: list(v) for a, v in bindings.items()}
        self._draft = {a: list(v) for a, v in bindings.items()}
        self._leaving = False  # set while closing after the user chose Save or Discard
        self._run = run
        self._on_change = on_change
        self._editing = False
        self._ignore_toggle = False
        self._pinned = False
        self._capture: tuple[str, int | None] | None = None  # (action, index or None = add)
        self._pending: tuple[str, int | None, str] | None = None  # awaiting "Replace"
        self._rows: list[tuple[Gtk.ListBoxRow, Command]] = []
        self.set_title("Commands")
        self.set_default_size(*COMPACT_SIZE)

        self._search = Gtk.SearchEntry(placeholder_text="Search commands", hexpand=True)
        self._search.connect("search-changed", self._on_search_changed)
        self._search.connect("activate", self._on_search_activate)
        search_keys = Gtk.EventControllerKey()
        search_keys.connect("key-pressed", self._on_search_key)
        self._search.add_controller(search_keys)
        search_box = Gtk.Box(margin_start=12, margin_end=12, margin_top=4, margin_bottom=8)
        search_box.append(self._search)

        self._edit_button = Gtk.ToggleButton(
            icon_name="shellac-pen-symbolic", tooltip_text="Edit shortcuts"
        )
        self._edit_button.connect("toggled", self._on_edit_toggled)
        self._pin_button = Gtk.ToggleButton(
            icon_name="shellac-pin-symbolic", tooltip_text="Keep this window open after running"
        )
        self._pin_button.connect("toggled", lambda b: setattr(self, "_pinned", b.get_active()))
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Commands", subtitle=""))
        header.pack_start(self._edit_button)
        header.pack_end(self._pin_button)

        self._banner = Adw.Banner(title="", button_label="Replace")
        self._banner.connect("button-clicked", self._on_banner_button)

        self._list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self._list.add_css_class("palette-list")
        self._list.set_header_func(self._header)
        self._list.set_filter_func(self._filter)
        self._list.connect("row-activated", self._on_row_activated)
        self._scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._scroller.set_child(self._list)

        self._hint = Gtk.Label(
            label="Click a shortcut, then press the new keys. "
            "Esc cancels, Backspace removes the shortcut. Nothing changes until you press Save.",
            wrap=True,
            xalign=0.0,
            margin_start=16,
            margin_end=16,
            margin_top=10,
            margin_bottom=2,
        )
        self._hint.add_css_class("dim-label")
        self._hint.add_css_class("caption")
        self._reset_all = Gtk.Button(label="Reset", tooltip_text="Put every default shortcut back")
        self._reset_all.add_css_class("destructive-action")
        self._reset_all.add_css_class("flat")
        self._reset_all.connect("clicked", lambda *_: self._reset_everything())
        self._cancel = Gtk.Button(label="Cancel", tooltip_text="Discard your changes")
        self._cancel.connect("clicked", lambda *_: self._cancel_editing())
        self._save = Gtk.Button(label="Save", tooltip_text="Write the changes to config.toml")
        self._save.add_css_class("suggested-action")
        self._save.connect("clicked", lambda *_: self._save_draft())
        buttons = Gtk.Box(spacing=8, margin_start=12, margin_end=12, margin_top=8, margin_bottom=12)
        buttons.append(self._reset_all)
        buttons.append(Gtk.Box(hexpand=True))
        buttons.append(self._cancel)
        buttons.append(self._save)
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        footer.add_css_class("palette-footer")
        footer.append(self._hint)
        footer.append(buttons)
        self._hint_revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_UP, child=footer
        )

        self._empty = Adw.StatusPage(
            icon_name="shellac-command-symbolic",
            title="No matching commands",
            description="Try another word.",
            vexpand=True,
            visible=False,
        )

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(search_box)
        content.append(self._banner)
        content.append(self._scroller)
        content.append(self._empty)
        content.append(self._hint_revealer)

        self._toasts = Adw.ToastOverlay()
        self._toasts.set_child(content)
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self._toasts)
        self.set_content(view)

        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)

        self._build()

    # -- public ---------------------------------------------------------------------------

    def open(self, *, edit: bool = False) -> None:
        """Show the palette; ``edit`` opens it straight in the shortcut editor."""
        self.present()
        if edit and not self._editing:
            self._enter_mode(True)
        self._search.grab_focus()

    def set_bindings(self, bindings: dict[str, list[str]]) -> None:
        """The config changed (or a save landed): the saved shortcuts are now ``bindings``.

        Unsaved edits in the draft are kept; otherwise the draft follows the saved state.
        """
        was_dirty = self._dirty()
        self._saved = {a: list(v) for a, v in bindings.items()}
        if not was_dirty:
            self._draft = {a: list(v) for a, v in bindings.items()}
        self._pending = None
        self._banner.set_revealed(False)
        self._build()

    # -- draft state ----------------------------------------------------------------------

    def _changes(self) -> dict[str, list[str] | None]:
        """What Save must write: only actions whose draft differs from the saved state."""
        changes: dict[str, list[str] | None] = {}
        for action, accels in self._draft.items():
            if accels == self._saved.get(action, []):
                continue
            changes[action] = None if accels == [DEFAULT_KEYBINDINGS[action]] else list(accels)
        return changes

    def _dirty(self) -> bool:
        return bool(self._changes())

    # -- building the list ----------------------------------------------------------------

    def _build(self) -> None:
        adjustment = self._scroller.get_vadjustment()
        position = adjustment.get_value()
        while (row := self._list.get_first_child()) is not None:
            self._list.remove(row)
        self._rows.clear()
        ordered = sorted(COMMANDS, key=lambda c: GROUPS.index(c.group))
        for command in ordered:
            row = self._make_row(command)
            self._list.append(row)
            self._rows.append((row, command))
            if command.action == "prev_tab":
                goto = self._goto_row()
                if goto is not None:
                    self._list.append(goto)
                    self._rows.append((goto, _GOTO_COMMAND))
        self._save.set_sensitive(self._dirty())
        self._list.invalidate_filter()
        self._select_first_visible()
        GLib.idle_add(adjustment.set_value, position)

    def _title_box(self, title: str, action: str) -> Gtk.Box:
        """The command's name, with a "Custom" badge when its shortcut is not the default."""
        box = Gtk.Box(spacing=8)
        label = Gtk.Label(label=title, xalign=0.0)
        label.add_css_class("palette-title")
        box.append(label)
        if self._differs_from_default(action):
            badge = Gtk.Label(label="Custom", valign=Gtk.Align.CENTER)
            badge.add_css_class("custom-badge")
            badge.set_tooltip_text(f"Not the default shortcut. {self._default_text(action)}")
            box.append(badge)
        return box

    def _default_text(self, action: str) -> str:
        if action == GOTO_ACTIONS[0]:
            tokens = accelerator_tokens(DEFAULT_KEYBINDINGS[action])
            tokens[-1] = "1–9"
        else:
            tokens = accelerator_tokens(DEFAULT_KEYBINDINGS[action])
        return "Default: " + " + ".join(tokens)

    def _make_row(self, command: Command) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow(activatable=not self._editing)
        row.add_css_class("palette-row")
        box = Gtk.Box(spacing=16, margin_start=16, margin_end=12, margin_top=9, margin_bottom=9)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        title = self._title_box(command.title, command.action)
        description = Gtk.Label(label=command.description, xalign=0.0, ellipsize=3)
        description.add_css_class("dim-label")
        description.add_css_class("caption")
        text.append(title)
        text.append(description)
        box.append(text)

        # Several shortcuts stack, one per line, so a row never gets crowded. The "+" button
        # sits at the end of the last line; the lines above leave room for it, so the keys
        # stay aligned.
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER)
        column.set_halign(Gtk.Align.END)
        accels = self._draft.get(command.action, [])
        lines: list[Gtk.Widget] = [
            self._pill(command.action, index, accel) for index, accel in enumerate(accels)
        ]
        if self._editing:
            if self._capture == (command.action, None):
                lines.append(self._capturing_pill())
                last_extra: Gtk.Widget | None = None
            else:
                last_extra = self._add_button(command.action)
        else:
            last_extra = None
            if not accels:
                none = Gtk.Label(label="Not set")
                none.add_css_class("dim-label")
                none.add_css_class("caption")
                lines.append(none)
        gap = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        if last_extra is not None:
            gap.add_widget(last_extra)
        for number, widget in enumerate(lines):
            line = Gtk.Box(spacing=4, halign=Gtk.Align.END)
            line.append(widget)
            if self._editing and last_extra is not None:
                if number == len(lines) - 1:
                    line.append(last_extra)
                    last_extra = None
                else:
                    spacer = Gtk.Box()
                    gap.add_widget(spacer)
                    line.append(spacer)
            column.append(line)
        if last_extra is not None:  # no shortcut yet: just the "+"
            line = Gtk.Box(halign=Gtk.Align.END)
            line.append(last_extra)
            column.append(line)
        shortcuts = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        shortcuts.append(column)
        if self._editing and self._differs_from_default(command.action):
            shortcuts.append(self._reset_button(command.action))
        box.append(shortcuts)
        row.set_child(box)
        return row

    def _goto_row(self) -> Gtk.ListBoxRow | None:
        """One row for the nine "go to tab" shortcuts: they share their modifiers."""
        action = GOTO_ACTIONS[0]
        row = Gtk.ListBoxRow(activatable=False)
        row.add_css_class("palette-row")
        box = Gtk.Box(spacing=16, margin_start=16, margin_end=12, margin_top=9, margin_bottom=9)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        title = self._title_box(_GOTO_COMMAND.title, action)
        note = (
            "Press a modifier plus a digit (for example Alt+1) to set it for tabs 1 to 9"
            if self._editing
            else _GOTO_COMMAND.description
        )
        description = Gtk.Label(label=note, xalign=0.0, ellipsize=3)
        description.add_css_class("dim-label")
        description.add_css_class("caption")
        text.append(title)
        text.append(description)
        box.append(text)

        shortcuts = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        first = self._draft.get(action, [])
        if first:
            if self._editing:
                shortcuts.append(self._goto_pill(first[0]))
            else:
                shortcuts.append(keycaps(first[0], last="1–9"))
        elif not self._editing:
            none = Gtk.Label(label="Not set")
            none.add_css_class("dim-label")
            none.add_css_class("caption")
            shortcuts.append(none)
        if self._editing:
            if self._capture == (action, None):
                shortcuts.append(self._capturing_pill())
            elif not first:
                shortcuts.append(self._add_button(action))
            if self._differs_from_default(action):
                shortcuts.append(self._reset_button(action))
        box.append(shortcuts)
        row.set_child(box)
        return row

    def _goto_pill(self, accel: str) -> Gtk.Widget:
        action = GOTO_ACTIONS[0]
        pill = Gtk.Box(spacing=0, valign=Gtk.Align.CENTER)
        pill.add_css_class("binding-pill")
        if self._capture == (action, 0):
            pill.add_css_class("capturing")
            label = Gtk.Label(label="Press keys…")
            label.add_css_class("capture-label")
            pill.append(label)
        else:
            button = Gtk.Button(child=keycaps(accel, last="1–9"), tooltip_text="Click to change")
            button.add_css_class("flat")
            button.connect("clicked", lambda *_: self._start_capture(action, 0))
            pill.append(button)
        remove = Gtk.Button(icon_name="shellac-close-symbolic", tooltip_text="Remove")
        remove.add_css_class("flat")
        remove.add_css_class("circular")
        remove.add_css_class("pill-remove")
        remove.connect("clicked", lambda *_: self._remove(action, 0))
        pill.append(remove)
        return pill

    def _pill(self, action: str, index: int, accel: str) -> Gtk.Widget:
        if not self._editing:
            return keycaps(accel)
        pill = Gtk.Box(spacing=0, valign=Gtk.Align.CENTER)
        pill.add_css_class("binding-pill")
        if self._capture == (action, index):
            pill.add_css_class("capturing")
            label = Gtk.Label(label="Press keys…")
            label.add_css_class("capture-label")
            pill.append(label)
        else:
            button = Gtk.Button(child=keycaps(accel), tooltip_text="Click to change")
            button.add_css_class("flat")
            button.connect("clicked", lambda *_: self._start_capture(action, index))
            pill.append(button)
        remove = Gtk.Button(icon_name="shellac-close-symbolic", tooltip_text="Remove")
        remove.add_css_class("flat")
        remove.add_css_class("circular")
        remove.add_css_class("pill-remove")
        remove.connect("clicked", lambda *_: self._remove(action, index))
        pill.append(remove)
        return pill

    def _capturing_pill(self) -> Gtk.Widget:
        pill = Gtk.Box(valign=Gtk.Align.CENTER)
        pill.add_css_class("binding-pill")
        pill.add_css_class("capturing")
        label = Gtk.Label(label="Press keys…")
        label.add_css_class("capture-label")
        pill.append(label)
        return pill

    def _add_button(self, action: str) -> Gtk.Widget:
        button = Gtk.Button(icon_name="shellac-plus-symbolic", tooltip_text="Add another shortcut")
        button.add_css_class("flat")
        button.add_css_class("circular")
        button.add_css_class("add-binding")
        button.set_valign(Gtk.Align.CENTER)
        button.connect("clicked", lambda *_: self._start_capture(action, None))
        return button

    def _reset_button(self, action: str) -> Gtk.Widget:
        button = Gtk.Button(
            icon_name="shellac-reset-symbolic",
            tooltip_text=f"Restore the default. {self._default_text(action)}",
        )
        button.add_css_class("flat")
        button.add_css_class("circular")
        button.set_valign(Gtk.Align.CENTER)
        button.connect("clicked", lambda *_: self._reset(action))
        return button

    def _differs_from_default(self, action: str) -> bool:
        if action == GOTO_ACTIONS[0]:
            return any(self._draft.get(a) != [DEFAULT_KEYBINDINGS[a]] for a in GOTO_ACTIONS)
        return self._draft.get(action, []) != [DEFAULT_KEYBINDINGS[action]]

    def _header(self, row: Gtk.ListBoxRow, before: Gtk.ListBoxRow | None) -> None:
        group = self._group_of(row)
        if before is not None and self._group_of(before) == group:
            row.set_header(None)
            return
        label = Gtk.Label(label=group.upper(), xalign=0.0)
        label.add_css_class("palette-group")
        row.set_header(label)

    def _group_of(self, row: Gtk.ListBoxRow) -> str:
        for candidate, command in self._rows:
            if candidate is row:
                return command.group
        return ""

    # -- search ---------------------------------------------------------------------------

    def _filter(self, row: Gtk.ListBoxRow) -> bool:
        query = self._search.get_text().strip()
        if not query:
            return True
        return any(candidate is row and matches(c, query) for candidate, c in self._rows)

    def _visible_rows(self) -> list[Gtk.ListBoxRow]:
        return [
            row for row, command in self._rows if self._filter(row) and command is not _GOTO_COMMAND
        ]

    def _select_first_visible(self) -> None:
        rows = self._visible_rows()
        if rows:
            self._list.select_row(rows[0])
        else:
            self._list.unselect_all()
        self._empty.set_visible(not rows and bool(self._search.get_text().strip()))
        self._scroller.set_visible(bool(rows) or not self._search.get_text().strip())

    def _on_search_changed(self, *_args: object) -> None:
        self._list.invalidate_filter()
        self._select_first_visible()

    def _on_search_activate(self, *_args: object) -> None:
        row = self._list.get_selected_row()
        if row is not None and not self._editing:
            self._run_row(row)

    def _on_search_key(
        self, _c: Gtk.EventControllerKey, keyval: int, _code: int, _state: Gdk.ModifierType
    ) -> bool:
        step = {Gdk.KEY_Down: 1, Gdk.KEY_Up: -1}.get(keyval)
        if step is None:
            return False
        rows = self._visible_rows()
        current = self._list.get_selected_row()
        if not rows:
            return True
        index = rows.index(current) if current in rows else -1
        target = rows[max(0, min(len(rows) - 1, index + step))]
        self._list.select_row(target)
        target.grab_focus()
        self._search.grab_focus()
        return True

    # -- running --------------------------------------------------------------------------

    def _on_row_activated(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        if not self._editing:
            self._run_row(row)

    def _run_row(self, row: Gtk.ListBoxRow) -> None:
        command = next((c for candidate, c in self._rows if candidate is row), None)
        if command is None or command is _GOTO_COMMAND or command.action == "command_palette":
            return
        if not self._pinned:
            self.close()
        self._run(command.action)

    # -- editing --------------------------------------------------------------------------

    def _on_edit_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._ignore_toggle:
            return
        if not button.get_active() and self._dirty():
            self._set_edit_button(True)  # stay in edit mode until the user decides
            self._confirm_leaving(then=lambda: self._enter_mode(False))
            return
        self._enter_mode(button.get_active())

    def _set_edit_button(self, active: bool) -> None:
        self._ignore_toggle = True
        self._edit_button.set_active(active)
        self._ignore_toggle = False

    def _enter_mode(self, editing: bool) -> None:
        self._set_edit_button(editing)
        self._editing = editing
        self._capture = None
        self._pending = None
        self._banner.set_revealed(False)
        self._draft = {a: list(v) for a, v in self._saved.items()}
        self._hint_revealer.set_reveal_child(editing)
        width, height = EDIT_SIZE if editing else COMPACT_SIZE
        self.set_default_size(width, height)
        self._build()

    def _cancel_editing(self) -> None:
        self._enter_mode(False)

    def _confirm_leaving(self, then: Callable[[], None]) -> None:
        count = len(self._changes())
        noun = "shortcut" if count == 1 else "shortcuts"
        dialog = Adw.AlertDialog(
            heading="Unsaved changes",
            body=f"You changed {count} {noun} without saving. "
            "If you leave now, the changes are lost.",
        )
        dialog.add_response("keep", "Keep editing")
        dialog.add_response("discard", "Discard")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("keep")

        def answered(_dialog: Adw.AlertDialog, response: str) -> None:
            saved = response == "save" and self._save_draft(leave=False)
            if response == "discard" or saved:
                then()

        dialog.connect("response", answered)
        dialog.present(self)

    def do_close_request(self) -> bool:
        if self._editing and self._dirty() and not self._leaving:
            self._confirm_leaving(then=self._close_now)
            return True
        self._reset_on_hide()
        return Adw.Window.do_close_request(self)

    def _close_now(self) -> None:
        self._leaving = True
        self.close()
        self._leaving = False

    def _reset_on_hide(self) -> None:
        """Next time the palette opens it starts compact, with no half-finished edit."""
        if self._editing:
            self._enter_mode(False)
        self._capture = None
        self._search.set_text("")

    def _start_capture(self, action: str, index: int | None) -> None:
        self._capture = (action, index)
        self._banner.set_revealed(False)
        self._pending = None
        self._build()
        self.grab_focus()

    def _cancel_capture(self) -> None:
        if self._capture is not None:
            self._capture = None
            self._build()

    def _on_key_pressed(
        self, controller: Gtk.EventControllerKey, keyval: int, _code: int, state: Gdk.ModifierType
    ) -> bool:
        if self._capture is None:
            if keyval == Gdk.KEY_Escape:
                if self._banner.get_revealed():
                    self._banner.set_revealed(False)
                    self._pending = None
                else:
                    self.close()
                return True
            return False

        action, index = self._capture
        if keyval in _MODIFIER_KEYVALS:
            return True
        if keyval == Gdk.KEY_Escape:
            self._cancel_capture()
            return True
        mask = Gtk.accelerator_get_default_mod_mask()
        mods = state & mask
        if keyval in (Gdk.KEY_BackSpace, Gdk.KEY_Delete) and not mods:
            self._capture = None
            if index is None:
                self._build()
            else:
                self._remove(action, index)
            return True

        event = controller.get_current_event()
        matched, match_keyval, match_mods = (
            event.get_match() if event is not None else (False, keyval, mods)
        )
        if not matched:
            match_keyval, match_mods = keyval, mods
        name = Gtk.accelerator_name(match_keyval, match_mods & mask)
        accel = canonical_accelerator(name or "")
        if accel is None:
            return True
        if not is_safe_binding(accel):
            self._say("Add Ctrl, Alt or Super: a plain key would stop you typing.")
            return True
        self._capture = None
        if action == GOTO_ACTIONS[0]:
            self._assign_goto(accel)
        else:
            self._assign(action, index, accel)
        return True

    def _assign(self, action: str, index: int | None, accel: str) -> None:
        current = list(self._draft.get(action, []))
        owner = owner_of(accel, self._draft, ignore=action)
        if accel in current and (index is None or current.index(accel) != index):
            self._say("That shortcut is already on this command.")
            self._build()
            return
        if owner is not None:
            self._pending = (action, index, accel)
            self._banner.set_title(
                f"{' + '.join(accelerator_tokens(accel))} is used by {_title(owner)}."
            )
            self._banner.set_revealed(True)
            self._build()
            return
        self._commit(action, index, accel, take_from=None)

    def _assign_goto(self, accel: str) -> None:
        """Give tabs 1 to 9 the pressed modifiers: ``<Alt>x`` -> ``<Alt>1`` ... ``<Alt>9``."""
        wanted = {f"{GOTO_TAB_PREFIX}{n}": with_key(accel, str(n)) for n in range(1, 10)}
        if not is_safe_binding(wanted[GOTO_ACTIONS[0]]):
            self._say("Add Ctrl, Alt or Super: a plain digit would stop you typing.")
            self._build()
            return
        others = {a: v for a, v in self._draft.items() if a not in wanted}
        for new in wanted.values():
            owner = owner_of(new, others)
            if owner is not None:
                self._pending = (GOTO_ACTIONS[0], None, accel)
                self._banner.set_title(
                    f"{' + '.join(accelerator_tokens(new))} is used by {_title(owner)}."
                )
                self._banner.set_revealed(True)
                self._build()
                return
        self._apply_goto(wanted, take_from=())

    def _apply_goto(self, wanted: dict[str, str], take_from: tuple[str, ...]) -> None:
        for action, new in wanted.items():
            self._draft[action] = [new]
        for owner in take_from:
            self._draft[owner] = [a for a in self._draft.get(owner, []) if a not in wanted.values()]
        self._build()

    def _on_banner_button(self, *_args: object) -> None:
        if self._pending is None:
            return
        action, index, accel = self._pending
        self._pending = None
        self._banner.set_revealed(False)
        if action == GOTO_ACTIONS[0]:
            wanted = {f"{GOTO_TAB_PREFIX}{n}": with_key(accel, str(n)) for n in range(1, 10)}
            others = {a: v for a, v in self._draft.items() if a not in wanted}
            owners = tuple(
                dict.fromkeys(o for n in wanted.values() if (o := owner_of(n, others)) is not None)
            )
            self._apply_goto(wanted, take_from=owners)
            return
        owner = owner_of(accel, self._draft, ignore=action)
        self._commit(action, index, accel, take_from=owner)

    def _commit(self, action: str, index: int | None, accel: str, take_from: str | None) -> None:
        mine = list(self._draft.get(action, []))
        if index is None or index >= len(mine):
            mine.append(accel)
        else:
            mine[index] = accel
        self._draft[action] = mine
        if take_from is not None:
            self._draft[take_from] = [
                a for a in self._draft.get(take_from, []) if owner_of(a, {action: [accel]}) is None
            ]
        self._build()

    def _remove(self, action: str, index: int) -> None:
        if action == GOTO_ACTIONS[0]:
            for each in GOTO_ACTIONS:
                self._draft[each] = []
            self._build()
            return
        mine = list(self._draft.get(action, []))
        if 0 <= index < len(mine):
            del mine[index]
        self._draft[action] = mine
        self._build()

    def _reset(self, action: str) -> None:
        targets = GOTO_ACTIONS if action == GOTO_ACTIONS[0] else (action,)
        for each in targets:
            self._draft[each] = [DEFAULT_KEYBINDINGS[each]]
        self._build()

    def _reset_everything(self) -> None:
        self._draft = {a: [d] for a, d in DEFAULT_KEYBINDINGS.items()}
        self._pending = None
        self._banner.set_revealed(False)
        self._build()

    def _save_draft(self, *, leave: bool = True) -> bool:
        """Write the draft to the config file. Returns True if it was saved."""
        changes = self._changes()
        if not changes:
            return True
        error = self._on_change(changes)
        if error is not None:
            self._say(error)
            return False
        self._saved = {a: list(v) for a, v in self._draft.items()}
        self._toasts.add_toast(Adw.Toast(title="Saved to config.toml", timeout=2))
        if leave:
            self._enter_mode(False)
        else:
            self._build()
        return True

    def _say(self, message: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=message, timeout=3))


_GOTO_COMMAND = Command(f"{GOTO_TAB_PREFIX}1", "Go to tab", "Jump straight to tab 1 to 9", "Tabs")

_MODIFIER_KEYVALS = {
    Gdk.KEY_Shift_L,
    Gdk.KEY_Shift_R,
    Gdk.KEY_Control_L,
    Gdk.KEY_Control_R,
    Gdk.KEY_Alt_L,
    Gdk.KEY_Alt_R,
    Gdk.KEY_Super_L,
    Gdk.KEY_Super_R,
    Gdk.KEY_Meta_L,
    Gdk.KEY_Meta_R,
    Gdk.KEY_ISO_Level3_Shift,
    Gdk.KEY_Caps_Lock,
    Gdk.KEY_Num_Lock,
}


def _title(action: str) -> str:
    return next((c.title for c in COMMANDS if c.action == action), action)
