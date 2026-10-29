"""Names, descriptions and groups of the commands shown in the command palette.

GTK-free. Every action that has a default keybinding must be described here (a unit test
checks it), so a new action cannot silently be missing from the palette.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    action: str  # the key used in [keybindings] and as ``win.<action>``
    title: str
    description: str
    group: str


GROUPS = ("Panes", "Tabs", "View", "Sidebar", "Clipboard and search", "General")

COMMANDS: tuple[Command, ...] = (
    Command("split_right", "Split right", "New pane beside the current one", "Panes"),
    Command("split_down", "Split down", "New pane below the current one", "Panes"),
    Command("close_pane", "Close pane", "Close the focused pane", "Panes"),
    Command("zoom_pane", "Zoom pane", "Fill the window with this pane, and back", "Panes"),
    Command("focus_left", "Focus left", "Move focus to the pane on the left", "Panes"),
    Command("focus_right", "Focus right", "Move focus to the pane on the right", "Panes"),
    Command("focus_up", "Focus up", "Move focus to the pane above", "Panes"),
    Command("focus_down", "Focus down", "Move focus to the pane below", "Panes"),
    Command("resize_left", "Resize left", "Move the divider to the left", "Panes"),
    Command("resize_right", "Resize right", "Move the divider to the right", "Panes"),
    Command("resize_up", "Resize up", "Move the divider up", "Panes"),
    Command("resize_down", "Resize down", "Move the divider down", "Panes"),
    Command("new_tab", "New tab", "Open a new tab", "Tabs"),
    Command("next_tab", "Next tab", "Switch to the tab on the right", "Tabs"),
    Command("prev_tab", "Previous tab", "Switch to the tab on the left", "Tabs"),
    Command("zoom_in", "Zoom in", "Larger terminal text", "View"),
    Command("zoom_out", "Zoom out", "Smaller terminal text", "View"),
    Command("zoom_reset", "Reset zoom", "Back to the configured font size", "View"),
    Command("cycle_theme", "Cycle theme", "Switch to the next theme", "View"),
    Command("toggle_sidebar", "Toggle sidebar", "Show or hide the file tree", "Sidebar"),
    Command("focus_sidebar", "Focus sidebar", "Move the keyboard into the file tree", "Sidebar"),
    Command("copy", "Copy", "Copy the selection", "Clipboard and search"),
    Command("paste", "Paste", "Paste from the clipboard", "Clipboard and search"),
    Command("select_all", "Select all", "Select the whole scrollback", "Clipboard and search"),
    Command("search", "Search", "Search the scrollback", "Clipboard and search"),
    Command("reload_config", "Reload configuration", "Re-read config and themes", "General"),
    Command("settings", "Settings", "Change how Shellac looks and behaves", "General"),
    Command("command_palette", "Command palette", "This window", "General"),
)

# goto_tab_1..9 are one row in the palette ("Go to tab 1 to 9"), not nine.
GOTO_TAB_PREFIX = "goto_tab_"


def command_for(action: str) -> Command | None:
    return next((c for c in COMMANDS if c.action == action), None)


def matches(command: Command, query: str) -> bool:
    """Case-insensitive match of every word of ``query`` against the title, group or name."""
    haystack = f"{command.title} {command.description} {command.group} {command.action}".lower()
    return all(word in haystack for word in query.lower().split())
