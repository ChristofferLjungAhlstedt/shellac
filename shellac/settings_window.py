"""The settings window: every option that makes sense to change from a GUI.

Edits are a draft. Nothing is applied or written until Save is pressed; Cancel throws the
draft away, Reset puts every default into the draft, and leaving with unsaved changes asks
first. The one exception is the theme, which is previewed live while it is being chosen and
returns to the saved theme if the draft is dropped. Saving goes through ``on_save``, which
edits only the changed lines of the user's config file.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, Gdk, Gtk, Pango  # noqa: E402

from .config import Config  # noqa: E402
from .settings_schema import (  # noqa: E402
    BOOL,
    CHOICE,
    FLOAT,
    FONT,
    INT,
    KEYBINDINGS_PAGE_ID,
    PAGES,
    TEXT,
    THEME,
    Field,
    all_fields,
    changes_from_draft,
    coerce,
    default_value,
    defaults,
    is_enabled,
    values_from_config,
)
from .theme import get_theme, theme_ids  # noqa: E402

Path = tuple[str, str]
THEME_PATH: Path = ("appearance", "theme")
SIZE = (860, 680)


def _is_monospace(item: Any) -> bool:
    """Font dialog filter. At family level the items are families, otherwise faces."""
    family = item if hasattr(item, "is_monospace") else item.get_family()
    return bool(family.is_monospace())


_OWN_SPIN_ICONS = {
    "value-increase-symbolic": "shellac-plus-symbolic",
    "value-decrease-symbolic": "shellac-minus-symbolic",
    "list-add-symbolic": "shellac-plus-symbolic",
    "list-remove-symbolic": "shellac-minus-symbolic",
}


def _use_own_spin_icons(widget: Gtk.Widget) -> None:
    """Give a spin row's +/- buttons Shellac's own icons.

    The buttons ask the desktop icon theme for ``value-increase-symbolic`` and friends; some
    themes ship versions of those that draw nothing, so the buttons look empty.
    """
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Image):
            own = _OWN_SPIN_ICONS.get(child.get_icon_name() or "")
            if own is not None:
                child.set_from_icon_name(own)
        _use_own_spin_icons(child)
        child = child.get_next_sibling()


class SettingsWindow(Adw.Window):
    def __init__(
        self,
        parent: Gtk.Window,
        config: Config,
        *,
        on_save: Callable[[dict[Path, Any]], str | None],
        on_preview: Callable[[str | None], None],
        on_preview_appearance: Callable[[dict[str, Any] | None], None],
        active_theme: Callable[[], tuple[str, bool]],
        on_open_shortcuts: Callable[[], None],
    ) -> None:
        super().__init__(title="Settings", transient_for=parent, modal=False, hide_on_close=True)
        self.add_css_class("shellac-settings")
        self.set_default_size(*SIZE)
        self._on_save = on_save
        self._on_preview = on_preview
        self._on_preview_appearance = on_preview_appearance
        self._active_theme = active_theme
        self._on_open_shortcuts = on_open_shortcuts
        self._saved = values_from_config(config)
        self._saved[THEME_PATH] = self._effective_theme(config)
        self._draft = dict(self._saved)
        self._syncing = False
        self._leaving = False
        self._setters: dict[Path, Callable[[Any], None]] = {}
        self._rows: dict[Path, Gtk.Widget] = {}
        self._reset_buttons: dict[Path, Gtk.Button] = {}
        self._themes = self._theme_choices()

        self._stack = Gtk.Stack(
            hexpand=True, vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE
        )
        self._nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self._nav.add_css_class("navigation-sidebar")
        self._nav_ids: list[str] = []
        for page in PAGES:
            self._add_page(page.id, page.title, page.icon, self._build_page(page))
        self._add_page(
            KEYBINDINGS_PAGE_ID, "Keybindings", "shellac-command-symbolic", self._build_shortcuts()
        )
        self._nav.connect("row-selected", self._on_nav_selected)
        nav_scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, width_request=210, child=self._nav
        )
        nav_scroller.add_css_class("settings-nav")

        body = Gtk.Box()
        body.append(nav_scroller)
        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        body.append(self._stack)

        self._count = Gtk.Label(xalign=0.0, hexpand=True, label="")
        self._count.add_css_class("dim-label")
        self._reset_all = Gtk.Button(label="Reset", tooltip_text="Put every default back")
        self._reset_all.add_css_class("flat")
        self._reset_all.add_css_class("error")
        self._reset_all.connect("clicked", lambda *_: self._reset_everything())
        self._cancel = Gtk.Button(label="Cancel", tooltip_text="Discard your changes and close")
        self._cancel.connect("clicked", lambda *_: self._cancel_clicked())
        self._save = Gtk.Button(label="Save", tooltip_text="Write the changes to config.toml")
        self._save.add_css_class("suggested-action")
        self._save.connect("clicked", lambda *_: self._save_draft())
        footer = Gtk.Box(spacing=8, margin_start=12, margin_end=12, margin_top=8, margin_bottom=12)
        footer.append(self._reset_all)
        footer.append(self._count)
        footer.append(self._cancel)
        footer.append(self._save)
        footer_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        footer_frame.add_css_class("settings-footer")
        footer_frame.append(footer)

        self._toasts = Adw.ToastOverlay(child=body)
        view = Adw.ToolbarView(content=self._toasts)
        view.add_top_bar(Adw.HeaderBar(title_widget=Adw.WindowTitle(title="Settings", subtitle="")))
        view.add_bottom_bar(footer_frame)
        self.set_content(view)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        self._nav.select_row(self._nav.get_row_at_index(0))
        self._refresh()

    # -- building -----------------------------------------------------------------------

    @staticmethod
    def _theme_choices() -> list[tuple[str, str]]:
        choices = []
        for theme_id in theme_ids():
            try:
                choices.append((theme_id, get_theme(theme_id)[0].name))
            except Exception:  # a broken user theme must not break the window
                choices.append((theme_id, theme_id))
        return choices

    def _add_page(self, page_id: str, title: str, icon: str, content: Gtk.Widget) -> None:
        self._stack.add_named(content, page_id)
        box = Gtk.Box(spacing=10, margin_top=8, margin_bottom=8, margin_start=6, margin_end=6)
        box.append(Gtk.Image(icon_name=icon))
        box.append(Gtk.Label(label=title, xalign=0.0))
        row = Gtk.ListBoxRow(child=box)
        row.page_id = page_id  # type: ignore[attr-defined]
        self._nav.append(row)
        self._nav_ids.append(page_id)

    def _on_nav_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is not None:
            self._stack.set_visible_child_name(row.page_id)  # type: ignore[attr-defined]

    def _build_page(self, page: Any) -> Gtk.Widget:
        prefs = Adw.PreferencesPage()
        for group in page.groups:
            adw_group = Adw.PreferencesGroup(title=group.title, description=group.description)
            for item in group.fields:
                adw_group.add(self._build_row(item))
            prefs.add(adw_group)
        return prefs

    def _build_shortcuts(self) -> Gtk.Widget:
        prefs = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Keybindings")
        row = Adw.ActionRow(title="Edit shortcuts", activatable=True)
        button = Gtk.Button(label="Open the editor", valign=Gtk.Align.CENTER)
        button.add_css_class("suggested-action")
        button.connect("clicked", lambda *_: self._on_open_shortcuts())
        row.add_suffix(button)
        row.connect("activated", lambda *_: self._on_open_shortcuts())
        group.add(row)
        prefs.add(group)
        return prefs

    def _build_row(self, item: Field) -> Gtk.Widget:
        builders = {
            BOOL: self._switch_row,
            INT: self._spin_row,
            FLOAT: self._spin_row,
            CHOICE: self._combo_row,
            THEME: self._combo_row,
            TEXT: self._text_row,
            FONT: self._font_row,
        }
        row, setter = builders[item.kind](item)
        reset = Gtk.Button(
            icon_name="shellac-reset-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text="Restore the default",
        )
        reset.add_css_class("flat")
        reset.add_css_class("circular")
        reset.connect("clicked", lambda *_: self._set(item.path, default_value(item)))
        row.add_suffix(reset)
        self._reset_buttons[item.path] = reset
        self._setters[item.path] = setter
        self._rows[item.path] = row
        self._syncing = True
        try:
            setter(self._draft[item.path])
        finally:
            self._syncing = False
        return row

    def _changed(self, item: Field, value: Any) -> None:
        if not self._syncing:
            self._set(item.path, value, push=False)

    def _switch_row(self, item: Field) -> tuple[Adw.PreferencesRow, Callable[[Any], None]]:
        row = Adw.SwitchRow(title=item.label, subtitle=item.description)
        row.connect("notify::active", lambda r, _p: self._changed(item, r.get_active()))
        return row, lambda value: row.set_active(bool(value))

    def _spin_row(self, item: Field) -> tuple[Adw.PreferencesRow, Callable[[Any], None]]:
        low, high = item.bounds or (0, 1_000_000)
        step = item.step or 1
        adjustment = Gtk.Adjustment(
            value=low, lower=low, upper=high, step_increment=step, page_increment=step * 10
        )
        row = Adw.SpinRow(
            title=item.label, subtitle=item.description, adjustment=adjustment, digits=item.digits
        )
        _use_own_spin_icons(row)
        row.connect("notify::value", lambda r, _p: self._changed(item, r.get_value()))
        return row, lambda value: row.set_value(float(value))

    def _combo_row(self, item: Field) -> tuple[Adw.PreferencesRow, Callable[[Any], None]]:
        if item.kind == THEME:
            values = [theme_id for theme_id, _name in self._themes]
            shown = [name for _id, name in self._themes]
        else:
            values = item.choices
            shown = [item.labels.get(v, v.replace("_", " ").capitalize()) for v in values]
        row = Adw.ComboRow(
            title=item.label, subtitle=item.description, model=Gtk.StringList.new(shown)
        )

        def selected(r: Adw.ComboRow, _p: object) -> None:
            index = r.get_selected()
            if 0 <= index < len(values):
                self._changed(item, values[index])

        def setter(value: Any) -> None:
            if value not in values:  # a theme file that has gone missing
                values.append(value)
                row.get_model().append(str(value))
            row.set_selected(values.index(value))

        row.connect("notify::selected", selected)
        return row, setter

    def _text_row(self, item: Field) -> tuple[Adw.PreferencesRow, Callable[[Any], None]]:
        row = Adw.ActionRow(title=item.label, subtitle=item.description)
        entry = Gtk.Entry(
            valign=Gtk.Align.CENTER, width_chars=26, placeholder_text=item.placeholder
        )
        entry.connect("changed", lambda e: self._changed(item, e.get_text()))
        row.add_suffix(entry)
        row.set_activatable_widget(entry)
        return row, lambda value: entry.set_text(str(value)) if entry.get_text() != value else None

    def _font_row(self, item: Field) -> tuple[Adw.PreferencesRow, Callable[[Any], None]]:
        row = Adw.ActionRow(title=item.label, subtitle=item.description)
        dialog = Gtk.FontDialog(title="Choose a font")
        dialog.set_filter(Gtk.CustomFilter.new(_is_monospace))
        button = Gtk.FontDialogButton(
            dialog=dialog, valign=Gtk.Align.CENTER, level=Gtk.FontLevel.FAMILY
        )

        def picked(b: Gtk.FontDialogButton, _p: object) -> None:
            desc = b.get_font_desc()
            family = desc.get_family() if desc is not None else None
            if family:
                self._changed(item, family)

        button.connect("notify::font-desc", picked)
        row.add_suffix(button)

        def setter(value: Any) -> None:
            button.set_font_desc(Pango.FontDescription.from_string(str(value)))

        return row, setter

    # -- draft --------------------------------------------------------------------------

    def _changes(self) -> dict[Path, Any]:
        return changes_from_draft(self._saved, self._draft)

    def _dirty(self) -> bool:
        return bool(self._changes())

    def _set(self, path: Path, value: Any, *, push: bool = True) -> None:
        """Change one draft value; ``push`` also moves its widget (reset buttons, Reset)."""
        self._draft[path] = value
        if push:
            self._syncing = True
            try:
                self._setters[path](value)
            finally:
                self._syncing = False
        if path == THEME_PATH:
            self._preview_theme()
        if path[0] == "appearance":
            self._preview_appearance()
        self._refresh()

    def _preview_theme(self) -> None:
        chosen = self._draft[THEME_PATH]
        self._on_preview(None if chosen == self._saved[THEME_PATH] else chosen)

    def _preview_appearance(self) -> None:
        """Show every changed appearance option right away (nothing is saved)."""
        known = {f.path: f for f in all_fields()}
        shown = {
            path[1]: coerce(known[path], value)
            for path, value in self._draft.items()
            if path[0] == "appearance"
            and path != THEME_PATH
            and coerce(known[path], value) != coerce(known[path], self._saved[path])
        }
        self._on_preview_appearance(shown or None)

    def sync_active_theme(self) -> None:
        """Make the theme row show the theme in effect, e.g. after Ctrl+Shift+P cycled it.

        While following the system color scheme the row keeps showing the configured theme.
        """
        theme_id, following = self._active_theme()
        if following:
            return
        if theme_id == self._draft[THEME_PATH]:
            return  # nothing changed, or this is the preview of the row's own choice
        # The theme changed from outside (Ctrl+Shift+P, or a preview just ended): follow it.
        self._saved[THEME_PATH] = self._draft[THEME_PATH] = theme_id
        self._syncing = True
        try:
            self._setters[THEME_PATH](theme_id)
        finally:
            self._syncing = False
        self._refresh()

    def _refresh(self) -> None:
        """Update which rows are usable, the per-row reset buttons and the footer."""
        by_path = {f.path: f for page in PAGES for g in page.groups for f in g.fields}
        for path, item in by_path.items():
            if path not in self._rows:  # still building the pages
                return
            self._rows[path].set_sensitive(is_enabled(item, self._draft))
            # Hidden, not removed: the button keeps its place so nothing else moves.
            differs = coerce(item, self._draft[path]) != coerce(item, default_value(item))
            button = self._reset_buttons[path]
            button.set_opacity(1.0 if differs else 0.0)
            button.set_can_target(differs)
            button.set_can_focus(differs)
        count = len(self._changes())
        if count:
            noun = "change" if count == 1 else "changes"
            self._count.set_label(f"{count} unsaved {noun}")
        else:
            self._count.set_label("Nothing is written until you press Save")
        self._save.set_sensitive(count > 0)
        self._cancel.set_label("Cancel" if count else "Close")
        self._reset_all.set_sensitive(self._draft != defaults())

    def _reset_everything(self) -> None:
        for path, value in defaults().items():
            self._set(path, value)

    def _effective_theme(self, config: Config) -> str:
        theme_id, following = self._active_theme()
        return config.appearance.theme if following else theme_id

    def set_config(self, config: Config) -> None:
        """The config on disk changed (a save landed, or the file was edited elsewhere)."""
        was_dirty = self._dirty()
        previous = self._saved.get(THEME_PATH)
        self._saved = values_from_config(config)
        if previous is not None and not self._active_theme()[1]:
            # Not following the system: the row's baseline is the theme in effect, which
            # ``sync_active_theme`` keeps up to date. A preview must not move it.
            self._saved[THEME_PATH] = previous
        if not was_dirty:
            self._draft = dict(self._saved)
            self._syncing = True
            try:
                for path, setter in self._setters.items():
                    setter(self._draft[path])
            finally:
                self._syncing = False
        self._refresh()

    # -- leaving ------------------------------------------------------------------------

    def _discard(self) -> None:
        self._draft = dict(self._saved)
        self._syncing = True
        try:
            for path, setter in self._setters.items():
                setter(self._draft[path])
        finally:
            self._syncing = False
        self._on_preview(None)
        self._on_preview_appearance(None)
        self.sync_active_theme()
        self._refresh()

    def _cancel_clicked(self) -> None:
        self._discard()
        self.close()

    def _save_draft(self, *, close: bool = False) -> bool:
        changes = self._changes()
        if not changes:
            return True
        error = self._on_save(changes)
        if error is not None:
            self._toasts.add_toast(Adw.Toast.new(error))
            return False
        self._saved = {**self._saved, **{p: coerce_value(p, v) for p, v in self._draft.items()}}
        self._refresh()
        self._toasts.add_toast(Adw.Toast.new("Settings saved"))
        if close:
            self.close()
        return True

    def _confirm_leaving(self) -> None:
        count = len(self._changes())
        noun = "setting" if count == 1 else "settings"
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
            if response == "discard":
                self._discard()
                self._close_now()
            elif response == "save" and self._save_draft():
                self._close_now()

        dialog.connect("response", answered)
        dialog.present(self)

    def _close_now(self) -> None:
        self._leaving = True
        self.close()
        self._leaving = False

    def do_close_request(self) -> bool:
        if self._dirty() and not self._leaving:
            self._confirm_leaving()
            return True
        if self._dirty():
            self._discard()
        return Adw.Window.do_close_request(self)

    def _on_key(
        self, _c: Gtk.EventControllerKey, keyval: int, _code: int, _state: Gdk.ModifierType
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def open(self, page_id: str | None = None) -> None:
        if page_id in self._nav_ids:
            self._nav.select_row(self._nav.get_row_at_index(self._nav_ids.index(page_id)))
        self.present()


def coerce_value(path: Path, value: Any) -> Any:
    from .settings_schema import all_fields

    item = next(f for f in all_fields() if f.path == path)
    return coerce(item, value)
