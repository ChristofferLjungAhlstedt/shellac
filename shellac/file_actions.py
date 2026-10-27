"""What activating a file in the sidebar does (FR-32), decided without any GTK.

``plan_file_action`` turns a file path and the ``[sidebar]`` settings into a ``Plan`` the
window carries out, or a ``Problem`` it shows as a toast. Commands are run as an argument
list (never through a shell), so a file name can not inject anything.
"""

from __future__ import annotations

import os
import shlex
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from .config import SidebarConfig
from .terminal_actions import editor_argv

Placement = Literal["split", "tab", "paste", "desktop"]

# Printed after a command ends, so its output stays readable until the user closes the pane.
HOLD_SCRIPT = (
    '"$@"; status=$?; printf "\\n[%s exited with status %d. Press Enter to close] " "$1" "$status";'
    " read -r _"
)


@dataclass(frozen=True)
class Plan:
    placement: Placement
    argv: list[str] | None = None  # the command to run; None for paste / desktop


@dataclass(frozen=True)
class Problem:
    message: str


def open_with_command(name: str, table: Mapping[str, str]) -> str | None:
    """The ``[sidebar.open_with]`` entry for a file: its exact name, else its extension."""
    for key in (name, name.lower()):
        if key in table:
            return table[key]
    extension = os.path.splitext(name)[1].lower()
    for key in (extension.lstrip("."), extension):
        if key and key in table:
            return table[key]
    return None


def build_argv(
    template: str, path: str, env: Mapping[str, str] | None = None
) -> list[str] | Problem:
    """Split ``template`` into arguments and fill in ``{path}``, ``{dir}`` and ``{name}``.

    ``path`` is appended when the template does not mention it, so ``"vim"`` works.
    """
    try:
        parts = shlex.split(template)
    except ValueError as exc:
        return Problem(f"Invalid command {template!r}: {exc}")
    if not parts:
        return Problem("The command is empty")
    mentions_path = any("{path}" in part for part in parts)
    values = {
        "{path}": path,
        "{dir}": os.path.dirname(path),
        "{name}": os.path.basename(path),
    }
    argv = []
    for part in parts:
        for token, value in values.items():
            part = part.replace(token, value)
        argv.append(part)
    if not mentions_path:
        argv.append(path)
    env = os.environ if env is None else env
    if shutil.which(argv[0], path=env.get("PATH")) is None:
        return Problem(f"'{argv[0]}' was not found")
    return argv


def hold_open(argv: list[str]) -> list[str]:
    """Wrap ``argv`` so the pane waits for Enter after the command ends."""
    return ["/bin/sh", "-c", HOLD_SCRIPT, "shellac", *argv]


def plan_file_action(
    path: str, config: SidebarConfig, env: Mapping[str, str] | None = None
) -> Plan | Problem:
    mode = config.on_file_activate
    if mode == "paste_path":
        return Plan("paste")
    if mode == "desktop_open":
        return Plan("desktop")

    placement: Placement = "tab" if mode.endswith("_tab") else "split"
    name = os.path.basename(path)

    if mode == "run":
        if not (os.path.isfile(path) and os.access(path, os.X_OK)):
            return Problem(f"{name} is not executable (chmod +x to run it)")
        return Plan("split", _held([path], config))

    template = open_with_command(name, config.open_with)
    if mode.startswith("command"):
        template = template or config.file_command
        if not template:
            return Problem("Set [sidebar] file_command, or an [sidebar.open_with] entry")
        built = build_argv(template, path, env)
        if isinstance(built, Problem):
            return built
        return Plan(placement, _held(built, config))

    # editor_split / editor_tab: an open_with entry wins, then the configured editor.
    if template:
        built = build_argv(template, path, env)
        return built if isinstance(built, Problem) else Plan(placement, built)
    argv = editor_argv(path, config.editor, env)
    if argv is None:
        return Problem("No editor found. Set [sidebar] editor or $EDITOR")
    return Plan(placement, argv)


def _held(argv: list[str], config: SidebarConfig) -> list[str]:
    return hold_open(argv) if config.keep_pane_open else argv
