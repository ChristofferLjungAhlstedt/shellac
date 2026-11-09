"""The dialog that starts or updates a workspace: a folder and a command for each pane.

The layout itself is arranged in the terminal (split, resize, close), then this dialog fills in
what each pane should do. The logic lives in ``workspace.py``; this is only the widgets.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .session import TabState  # noqa: E402
from .workspace import (  # noqa: E402
    Draft,
    PaneValues,
    build_tab,
    folder_text,
    pane_positions,
)

FOLDER_TITLE = "Folder (empty: this folder)"
COMMAND_TITLE = "Command to type when the pane opens"


class WorkspaceDialog(Adw.Dialog):
    def __init__(
        self,
        folder: str,
        draft: Draft,
        on_save: Callable[[TabState, bool], None],
    ) -> None:
        """``on_save(tab, edit_as_text)`` is called once the values are valid."""
        super().__init__(
            title="Update workspace" if draft.existing else "Start a workspace",
            content_width=560,
            content_height=640,
        )
        self._folder = folder
        self._draft = draft
        self._on_save = on_save
        self.folder_rows: list[Adw.EntryRow] = []
        self.command_rows: list[Adw.EntryRow] = []

        view = Adw.ToolbarView()
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        self.cancel_button = Gtk.Button(label="Cancel")
        self.cancel_button.connect("clicked", lambda _button: self.close())
        self.save_button = Gtk.Button(label="Update" if draft.existing else "Create")
        self.save_button.add_css_class("suggested-action")
        self.save_button.connect("clicked", lambda _button: self.save(edit_as_text=False))
        header.pack_start(self.cancel_button)
        header.pack_end(self.save_button)
        subtitle = os.path.basename(os.path.normpath(folder)) or folder
        header.set_title_widget(Adw.WindowTitle(title=self.get_title(), subtitle=subtitle))
        view.add_top_bar(header)

        page = Adw.PreferencesPage()
        intro = Adw.PreferencesGroup()
        intro.add(
            self._label(
                "Each pane opens in its own terminal when you open the workspace. Arrange the "
                "splits in the terminal first; here you choose where each pane starts and "
                "what it runs."
            )
        )
        if draft.note:
            note = self._label(draft.note)
            note.add_css_class("warning")
            intro.add(note)
        page.add(intro)

        positions = pane_positions(draft.shape.layout)
        for index, values in enumerate(draft.values):
            group = Adw.PreferencesGroup(title=f"Pane {index + 1}: {positions[index].lower()}")
            folder_row = Adw.EntryRow(title=FOLDER_TITLE, text=values.folder)
            choose = Gtk.Button.new_from_icon_name("folder-open-symbolic")
            choose.add_css_class("flat")
            choose.set_valign(Gtk.Align.CENTER)
            choose.set_tooltip_text("Choose a folder")
            choose.connect("clicked", self._choose_folder, folder_row)
            folder_row.add_suffix(choose)
            folder_row.connect("changed", self._clear_problem)
            command_row = Adw.EntryRow(title=COMMAND_TITLE, text=values.command)
            group.add(folder_row)
            group.add(command_row)
            page.add(group)
            self.folder_rows.append(folder_row)
            self.command_rows.append(command_row)

        extra = Adw.PreferencesGroup()
        self.edit_text_button = Gtk.Button(label="Save and Edit as Text")
        self.edit_text_button.add_css_class("flat")
        self.edit_text_button.set_halign(Gtk.Align.START)
        self.edit_text_button.set_tooltip_text(
            "Save the workspace and open the file, to add tabs or change anything by hand"
        )
        self.edit_text_button.connect("clicked", lambda _button: self.save(edit_as_text=True))
        extra.add(self.edit_text_button)
        page.add(extra)

        view.set_content(page)
        self.set_child(view)
        self.set_default_widget(self.save_button)
        self.set_focus(self.command_rows[0] if self.command_rows else None)

    @staticmethod
    def _label(text: str) -> Gtk.Label:
        label = Gtk.Label(label=text, wrap=True, xalign=0)
        label.set_margin_bottom(6)
        return label

    # -- values -------------------------------------------------------------------------

    def values(self) -> list[PaneValues]:
        return [
            PaneValues(folder.get_text(), command.get_text())
            for folder, command in zip(self.folder_rows, self.command_rows, strict=True)
        ]

    def save(self, *, edit_as_text: bool) -> bool:
        """Validate and hand the tab on; marks the folders that do not exist instead."""
        tab, problems = build_tab(self._draft.shape, self._folder, self.values())
        for index, row in enumerate(self.folder_rows):
            if index in problems:
                row.add_css_class("error")
                row.set_title(problems[index])
            else:
                self._clear_problem(row)
        if tab is None:
            return False
        self.close()
        self._on_save(tab, edit_as_text)
        return True

    def _clear_problem(self, row: Adw.EntryRow) -> None:
        row.remove_css_class("error")
        row.set_title(FOLDER_TITLE)

    def _choose_folder(self, _button: Gtk.Button, row: Adw.EntryRow) -> None:
        start = os.path.normpath(os.path.join(self._folder, os.path.expanduser(row.get_text())))
        chooser = Gtk.FileDialog(title="Choose a folder")
        if os.path.isdir(start):
            chooser.set_initial_folder(Gio.File.new_for_path(start))

        def chosen(dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                selected = dialog.select_folder_finish(result)
            except GLib.Error:
                return  # cancelled
            if selected is not None and selected.get_path():
                row.set_text(folder_text(selected.get_path(), self._folder))

        root = self.get_root()
        chooser.select_folder(root if isinstance(root, Gtk.Window) else None, None, chosen)
