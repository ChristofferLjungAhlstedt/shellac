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

import hashlib
import json
import os
import tomllib
from collections.abc import Iterator, Sequence
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


def resolve_workspace_argument(text: str, cwd: str | None = None) -> tuple[str | None, str | None]:
    """The folder for ``shellac --workspace TEXT``, as (absolute folder, None) or (None, error).

    ``TEXT`` is a project folder or its workspace file; relative paths start from ``cwd``."""
    path = os.path.expanduser(text)
    path = os.path.normpath(os.path.join(cwd or os.getcwd(), path))
    if os.path.basename(path) == WORKSPACE_FILE and os.path.isfile(path):
        path = os.path.dirname(path)
    if not os.path.isdir(path):
        return None, f"{text}: not a folder"
    if workspace_file(path) is None:
        return None, f"no {WORKSPACE_FILE} in {path}"
    return path, None


def commands_in(workspace: Workspace) -> list[str]:
    """Every command the workspace would type, in order."""
    return [pane.command for tab in workspace.tabs for pane in panes_of(tab.layout) if pane.command]


def confirm_text(commands: list[str], *, changed: bool = False) -> tuple[str, str]:
    """Heading and body for the question asked before a workspace runs commands.

    ``changed``: the workspace was trusted before, but its commands are not the same now."""
    shown = [f"• {command}" for command in commands[:MAX_COMMANDS_SHOWN]]
    if len(commands) > MAX_COMMANDS_SHOWN:
        shown.append(f"• and {len(commands) - MAX_COMMANDS_SHOWN} more")
    body = (
        "This workspace types the following into new terminals:\n\n"
        + "\n".join(shown)
        + "\n\nOnly continue if you trust this folder."
    )
    if changed:
        body = "The commands in this workspace have changed since you last trusted it.\n\n" + body
    return "Run these commands?", body


# -- trust ----------------------------------------------------------------------------------
#
# "Always run" remembers a workspace by the folder and by a fingerprint of its commands, so a
# file that later gains or changes a command (a pull that rewrote it, say) is asked about again.

MAX_TRUSTED = 200


def trust_key(folder: str) -> str:
    return os.path.realpath(folder)


def fingerprint(commands: list[str]) -> str:
    return hashlib.sha256("\0".join(commands).encode("utf-8")).hexdigest()


def trust_status(trusted: dict[str, str], folder: str, commands: list[str]) -> str:
    """ "trusted": run without asking; "changed": trusted once, commands differ now;
    "unknown": never trusted."""
    known = trusted.get(trust_key(folder))
    if known is None:
        return "unknown"
    return "trusted" if known == fingerprint(commands) else "changed"


def with_trust(trusted: dict[str, str], folder: str, commands: list[str]) -> dict[str, str]:
    """A copy of ``trusted`` that also trusts these commands; the oldest entries make room."""
    key = trust_key(folder)
    result = {k: v for k, v in trusted.items() if k != key}
    result[key] = fingerprint(commands)
    while len(result) > MAX_TRUSTED:
        del result[next(iter(result))]
    return result


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

HEADER = """\
# Shellac workspace for this folder.
#
# Open it from the sidebar: right-click this folder, then "Open Workspace".
# If it runs commands, Shellac lists them and asks first.
#
# Each [[tab]] is a tab. A tab (or pane) that has [[...pane]] tables inside it is split:
#   split = "right"        side by side ("down" stacks them instead)
#   ratio = 0.3            size of the first of two panes, between 0 and 1 (default 0.5)
#   dir   = "api"          folder for everything inside it
# A pane without panes inside it is one terminal:
#   dir   = "api"          folder to start in, relative to this folder ("~" and full paths work)
#   run   = "npm run dev"  command typed into it when it opens
#   focus = true           this pane gets the keyboard when the workspace opens
#
# Remove the leading "# " from a line to use it.

"""

FOOTER = """\
# To add another tab, add another [[tab]] at the end, for example:
#
# [[tab]]
# dir = "web"
# run = "git status"
"""

RUN_HINT = '# run = "command to type when this pane opens"'


def workspace_to_toml(tab: TabState, folder: str) -> str:
    """A workspace file for one tab: its splits, divider positions and directories, with a
    header and hints that explain how to change it by hand."""
    lines: list[str] = []
    _write_node(tab.layout, folder, "tab", lines, _Counter(tab.focused))
    return HEADER + "\n".join(lines).rstrip() + "\n\n" + FOOTER


class _Counter:
    """Numbers the panes in tree order as they are written, to mark the focused one."""

    def __init__(self, focused: int) -> None:
        self.focused = focused
        self.index = 0


def _text(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def folder_text(path: str | None, folder: str) -> str:
    """How a pane's directory reads in a workspace: relative to ``folder`` when inside it,
    empty for ``folder`` itself, otherwise the full path."""
    if not path:
        return ""
    path = os.path.normpath(path)
    folder = os.path.normpath(folder)
    if path == folder:
        return ""
    if path.startswith(folder + os.sep):
        return os.path.relpath(path, folder)
    return path


def _write_node(
    layout: LayoutState, folder: str, key: str, lines: list[str], counter: _Counter
) -> None:
    lines.append(f"[[{key}]]")
    if isinstance(layout, SplitState):
        lines.append(f"split = {_text(_AXIS_NAMES[layout.axis])}")
        if abs(layout.ratio - 0.5) > 0.001:
            lines.append(f"ratio = {round(layout.ratio, 3)}")
        lines.append("")
        _write_node(layout.first, folder, f"{key}.pane", lines, counter)
        _write_node(layout.second, folder, f"{key}.pane", lines, counter)
        return
    directory = folder_text(layout.cwd, folder)
    if directory:
        lines.append(f"dir = {_text(directory)}")
    if layout.command:
        lines.append(f"run = {_text(layout.command)}")
    else:
        lines.append(RUN_HINT)
    if counter.index == counter.focused and counter.focused != 0:
        lines.append("focus = true")
    counter.index += 1
    lines.append("")


# -- the editing dialog ---------------------------------------------------------------------


@dataclass(frozen=True)
class PaneValues:
    folder: str  # relative to the workspace folder, empty for the folder itself
    command: str


@dataclass(frozen=True)
class Draft:
    shape: TabState  # the splits and dividers to save
    values: tuple[PaneValues, ...]  # one per pane, in tree order
    existing: bool  # the folder already has a workspace file
    note: str | None  # something to tell the user before they save


def make_draft(current: TabState, folder: str, existing_text: str | None) -> Draft:
    """What the dialog starts with.

    The splits and dividers always come from the current tab. Folders and commands come from
    the existing workspace when it has the same number of panes (so updating the layout keeps
    what was set up), otherwise from the current tab, with no commands.
    """
    panes = panes_of(current.layout)
    from_tab = tuple(PaneValues(folder_text(pane.cwd, folder), "") for pane in panes)
    if existing_text is None:
        return Draft(current, from_tab, False, None)
    rewrite = "Saving rewrites the file from the settings below; comments you added are not kept."
    result = parse_workspace(existing_text, folder)
    if result.workspace is None:
        return Draft(
            current,
            from_tab,
            True,
            f"The existing file could not be read ({result.error}). {rewrite}",
        )
    notes = [rewrite]
    old = panes_of(result.workspace.tabs[0].layout)
    if len(old) == len(panes):
        values = tuple(PaneValues(folder_text(p.cwd, folder), p.command or "") for p in old)
    else:
        values = from_tab
        notes.insert(
            0,
            f"The layout has {len(panes)} panes and the saved workspace has {len(old)}, so "
            "folders and commands start from this tab.",
        )
    if len(result.workspace.tabs) > 1:
        notes.insert(0, f"The file has {len(result.workspace.tabs)} tabs; only this tab is kept.")
    return Draft(current, values, True, " ".join(notes))


def build_tab(
    shape: TabState, folder: str, values: Sequence[PaneValues]
) -> tuple[TabState | None, dict[int, str]]:
    """The tab to save, or the problems (pane number to message) that stop it."""
    problems: dict[int, str] = {}
    panes: list[PaneState] = []
    for index, value in enumerate(values):
        text = value.folder.strip()
        path = (
            folder if not text else os.path.normpath(os.path.join(folder, os.path.expanduser(text)))
        )
        if not os.path.isdir(path):
            problems[index] = f"{text} is not a folder"
        panes.append(PaneState(path, value.command.strip() or None))
    if problems:
        return None, problems
    replacements = iter(panes)
    return TabState(_with_panes(shape.layout, replacements), shape.focused), {}


def _with_panes(layout: LayoutState, panes: Iterator[PaneState]) -> LayoutState:
    if isinstance(layout, SplitState):
        first = _with_panes(layout.first, panes)
        return SplitState(layout.axis, layout.ratio, first, _with_panes(layout.second, panes))
    return next(panes)


def pane_positions(layout: LayoutState) -> list[str]:
    """Where each pane sits, for labels: "left", "top right", ... or "only pane"."""
    if not isinstance(layout, SplitState):
        return ["Only pane"]
    found: list[str] = []

    def walk(node: LayoutState, horizontal: str, vertical: str) -> None:
        if isinstance(node, SplitState):
            first, second = ("left", "right") if node.axis == Axis.HORIZONTAL else ("top", "bottom")
            for word, child in ((first, node.first), (second, node.second)):
                if node.axis == Axis.HORIZONTAL:
                    walk(child, word, vertical)
                else:
                    walk(child, horizontal, word)
            return
        found.append(" ".join(part for part in (vertical, horizontal) if part).capitalize())

    walk(layout, "", "")
    return found
