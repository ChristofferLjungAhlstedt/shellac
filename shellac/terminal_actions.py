"""Helpers for sending commands from the sidebar into panes (section 8.5, FR-32).

GTK-free so the safety rules (quoting, idle detection) are unit tested.
"""

from __future__ import annotations

import os
import shlex
import shutil
from collections.abc import Mapping

# Tried when neither the config nor $VISUAL / $EDITOR names an editor.
FALLBACK_EDITORS = ("nano", "vim", "vi")


def cd_command(path: str) -> str:
    """A ``cd`` line for the shell, safely quoted. ``--`` guards paths starting with ``-``."""
    return f"cd -- {shlex.quote(path)}\n"


def path_text(path: str) -> str:
    """A path ready to be typed into a command line: quoted, with a trailing space."""
    return f"{shlex.quote(path)} "


def editor_argv(
    path: str,
    configured: str = "",
    env: Mapping[str, str] | None = None,
) -> list[str] | None:
    """Command that opens ``path`` in the user's editor, or None if none is installed.

    Order: the ``[sidebar] editor`` setting, ``$VISUAL``, ``$EDITOR``, then nano/vim/vi.
    The setting may include arguments (``code -w``).
    """
    env = os.environ if env is None else env
    search_path = env.get("PATH")  # look programs up where the editor will run
    for candidate in (configured, env.get("VISUAL", ""), env.get("EDITOR", "")):
        if not candidate.strip():
            continue
        try:
            parts = shlex.split(candidate)
        except ValueError:
            continue  # unbalanced quotes: ignore and try the next source
        if parts and shutil.which(parts[0], path=search_path):
            return [*parts, path]
    for name in FALLBACK_EDITORS:
        found = shutil.which(name, path=search_path)
        if found:
            return [found, path]
    return None


def foreground_pgid(pty_fd: int) -> int | None:
    try:
        return os.tcgetpgrp(pty_fd)
    except OSError:
        return None


def is_shell_idle(pty_fd: int, shell_pid: int | None) -> bool:
    """Is the shell itself, not a command it started, in the foreground of the terminal?

    The shell leads its own process group, so when it sits at a prompt the terminal's
    foreground group is the shell's pid. While a command runs the group is that
    command's. This is a heuristic: it cannot see a half-typed line or a nested shell
    (which looks idle), and a ``cd`` is then simply typed into that shell.
    """
    if shell_pid is None:
        return False
    return foreground_pgid(pty_fd) == shell_pid


def foreground_name(pty_fd: int) -> str | None:
    """Name of the foreground process (for a "pane is busy" message)."""
    pgid = foreground_pgid(pty_fd)
    if pgid is None:
        return None
    try:
        with open(f"/proc/{pgid}/comm") as handle:
            return handle.read().strip() or None
    except OSError:
        return None
