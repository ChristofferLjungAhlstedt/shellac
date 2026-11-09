"""Saved layouts ("workspaces"): a ``.shellac.toml`` in a project folder.

GTK-free. The file describes tabs, splits and the command each pane starts with, and is opened
from the sidebar's folder menu::

    [[tab]]
    split = "right"            # how this tab's panes sit: "right" (side by side) or "down"
    [[tab.pane]]
    run = "nvim ."             # typed into the new shell
    [[tab.pane]]
    split = "down"             # a pane with panes of its own is split again
    ratio = 0.7                # share of the first of two panes (default 0.5)
    [[tab.pane.pane]]
    run = "npm run dev"
    [[tab.pane.pane]]
    dir = "logs"               # relative to the folder holding the file; "~" and absolute work

A table without ``pane`` entries is one terminal (``dir``, ``run``, ``focus``). ``dir`` on a
split or tab is the default for everything inside it. More than two panes in a split share the
space equally. Parsing never raises: a damaged file gives an error message, an odd value gives
a warning and its default.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from typing import Any

from .pane_tree import MAX_RATIO, MIN_RATIO, Axis
from .session import MAX_PANES, MAX_TABS, LayoutState, PaneState, SplitState, TabState, panes_of

WORKSPACE_FILE = ".shellac.toml"
MAX_DEPTH = 16
MAX_COMMANDS_SHOWN = 8

_AXES = {"right": Axis.HORIZONTAL, "down": Axis.VERTICAL}
_AXIS_NAMES = {axis: name for name, axis in _AXES.items()}


@dataclass(frozen=True)
class Workspace:
    tabs: tuple[TabState, ...]


@dataclass(frozen=True)
class WorkspaceResult:
    workspace: Workspace | None
    warnings: tuple[str, ...] = ()
    error: str | None = None


def workspace_file(folder: str) -> str | None:
    path = os.path.join(folder, WORKSPACE_FILE)
    return path if os.path.isfile(path) else None


def commands_in(workspace: Workspace) -> list[str]:
    """Every command the workspace would type, in order."""
    return [pane.command for tab in workspace.tabs for pane in panes_of(tab.layout) if pane.command]


def confirm_text(commands: list[str]) -> tuple[str, str]:
    """Heading and body for the question asked before a workspace runs commands."""
    shown = [f"• {command}" for command in commands[:MAX_COMMANDS_SHOWN]]
    if len(commands) > MAX_COMMANDS_SHOWN:
        shown.append(f"• and {len(commands) - MAX_COMMANDS_SHOWN} more")
    body = (
        "This workspace types the following into new terminals:\n\n"
        + "\n".join(shown)
        + "\n\nOnly continue if you trust this folder."
    )
    return "Run these commands?", body


# -- reading --------------------------------------------------------------------------------


class _Reader:
    def __init__(self, folder: str) -> None:
        self.folder = folder
        self.warnings: list[str] = []
        self.panes = 0

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def directory(self, value: object, inherited: str, where: str) -> str:
        if value is None:
            return inherited
        if not isinstance(value, str) or not value.strip():
            self.warn(f"{where}: dir must be a text")
            return inherited
        path = os.path.normpath(os.path.join(self.folder, os.path.expanduser(value.strip())))
        if not os.path.isdir(path):
            self.warn(f"{where}: {value} is not a folder, using {inherited}")
            return inherited
        return path

    def node(self, data: object, inherited: str, where: str, depth: int) -> LayoutState | None:
        if not isinstance(data, dict):
            self.warn(f"{where}: expected a table")
            return None
        if depth > MAX_DEPTH:
            self.warn(f"{where}: panes are nested too deeply")
            return None
        here = self.directory(data.get("dir"), inherited, where)
        children = data.get("pane")
        if children is None:
            return self.leaf(data, here, where)
        if not isinstance(children, list):
            self.warn(f"{where}: pane must be a list of tables")
            return self.leaf(data, here, where)
        layouts = [
            layout
            for index, child in enumerate(children, 1)
            if (layout := self.node(child, here, f"{where}.pane {index}", depth + 1)) is not None
        ]
        if not layouts:
            self.warn(f"{where}: no usable panes, showing one terminal")
            return self.leaf(data, here, where)
        if len(layouts) == 1:
            return layouts[0]
        return self.split(data, layouts, where)

    def leaf(self, data: dict[str, Any], directory: str, where: str) -> LayoutState | None:
        self.panes += 1
        if self.panes > MAX_PANES:
            return None
        command = data.get("run")
        if command is not None and not (isinstance(command, str) and command.strip()):
            self.warn(f"{where}: run must be a text")
            command = None
        return PaneState(directory, command.strip() if isinstance(command, str) else None)

    def split(self, data: dict[str, Any], layouts: list[LayoutState], where: str) -> LayoutState:
        name = data.get("split", "right")
        axis = _AXES.get(name) if isinstance(name, str) else None
        if axis is None:
            self.warn(f'{where}: split must be "right" or "down", using "right"')
            axis = Axis.HORIZONTAL
        ratio = data.get("ratio")
        if ratio is not None:
            if len(layouts) != 2:
                self.warn(f"{where}: ratio only applies to two panes, ignored")
                ratio = None
            elif isinstance(ratio, bool) or not isinstance(ratio, int | float):
                self.warn(f"{where}: ratio must be a number, using 0.5")
                ratio = None
        return _fold(axis, layouts, None if ratio is None else float(ratio))


def _fold(axis: Axis, layouts: list[LayoutState], ratio: float | None) -> LayoutState:
    """n panes as nested splits, each giving the first pane an equal share of what is left."""
    if len(layouts) == 1:
        return layouts[0]
    share = ratio if ratio is not None else 1 / len(layouts)
    share = min(MAX_RATIO, max(MIN_RATIO, share))
    return SplitState(axis, share, layouts[0], _fold(axis, layouts[1:], None))


def parse_workspace(text: str, folder: str) -> WorkspaceResult:
    """Read the contents of a workspace file belonging to ``folder``."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return WorkspaceResult(None, error=str(exc))
    raw_tabs = data.get("tab")
    if not isinstance(raw_tabs, list) or not raw_tabs:
        return WorkspaceResult(None, error="no [[tab]] found")
    reader = _Reader(folder)
    tabs: list[TabState] = []
    for index, raw in enumerate(raw_tabs[:MAX_TABS], 1):
        reader.panes = 0
        layout = reader.node(raw, folder, f"tab {index}", 0)
        if layout is None:
            continue
        if reader.panes > MAX_PANES:
            return WorkspaceResult(None, error=f"tab {index} has more than {MAX_PANES} panes")
        focused = next(
            (
                position
                for position, pane in enumerate(_leaf_tables(raw))
                if pane.get("focus") is True
            ),
            0,
        )
        tabs.append(TabState(layout, min(focused, len(panes_of(layout)) - 1)))
    if len(raw_tabs) > MAX_TABS:
        reader.warn(f"only the first {MAX_TABS} tabs are used")
    if not tabs:
        return WorkspaceResult(None, tuple(reader.warnings), "no usable [[tab]] found")
    return WorkspaceResult(Workspace(tuple(tabs)), tuple(reader.warnings))


def _leaf_tables(node: Any, depth: int = 0) -> list[dict[str, Any]]:
    """The tables that became panes, in the order the layout has them."""
    if not isinstance(node, dict) or depth > MAX_DEPTH:
        return []
    children = node.get("pane")
    if not isinstance(children, list):
        return [node]
    found = [leaf for child in children for leaf in _leaf_tables(child, depth + 1)]
    return found or [node]


# -- writing --------------------------------------------------------------------------------


def workspace_to_toml(tab: TabState, folder: str) -> str:
    """A workspace file for one tab: its splits, divider positions and directories.

    Commands are not known, so none are written; the header says how to add them.
    """
    lines = [
        "# Shellac workspace. Open it from the sidebar: right-click this folder, then",
        '# "Open Workspace". Add  run = "command"  to a pane to type that command when it opens.',
        "",
    ]
    _write_node(tab.layout, folder, "tab", lines)
    return "\n".join(lines).rstrip() + "\n"


def _text(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _relative(path: str | None, folder: str) -> str | None:
    if not path:
        return None
    path = os.path.normpath(path)
    folder = os.path.normpath(folder)
    if path == folder:
        return None
    if path.startswith(folder + os.sep):
        return os.path.relpath(path, folder)
    return path


def _write_node(layout: LayoutState, folder: str, key: str, lines: list[str]) -> None:
    lines.append(f"[[{key}]]")
    if isinstance(layout, SplitState):
        lines.append(f"split = {_text(_AXIS_NAMES[layout.axis])}")
        if abs(layout.ratio - 0.5) > 0.001:
            lines.append(f"ratio = {round(layout.ratio, 3)}")
        lines.append("")
        _write_node(layout.first, folder, f"{key}.pane", lines)
        _write_node(layout.second, folder, f"{key}.pane", lines)
        return
    directory = _relative(layout.cwd, folder)
    if directory:
        lines.append(f"dir = {_text(directory)}")
    if layout.command:
        lines.append(f"run = {_text(layout.command)}")
    lines.append("")
