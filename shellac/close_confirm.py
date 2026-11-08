"""Wording for the "something is still running" confirmation (``confirm_close_running``).

GTK-free so the text is unit tested. ``scope`` is what is being closed.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

Scope = Literal["pane", "tab", "window"]

MAX_NAMES = 3


def _quote(name: str) -> str:
    return f"“{name}”"


def _list_names(names: Sequence[str]) -> str:
    shown = [_quote(name) for name in names[:MAX_NAMES]]
    extra = len(names) - MAX_NAMES
    if extra > 0:
        shown.append(f"{extra} more")
    if len(shown) == 1:
        return shown[0]
    return ", ".join(shown[:-1]) + " and " + shown[-1]


def close_dialog_text(scope: Scope, names: Sequence[str | None]) -> tuple[str, str]:
    """Heading and body for closing ``scope`` while ``names`` are running.

    ``names`` holds one entry per running pane; None is a program whose name is not known.
    Repeated names are listed once.
    """
    heading = f"Close this {scope}?" if scope != "window" else "Close the window?"
    known = list(dict.fromkeys(name for name in names if name))
    unknown = sum(1 for name in names if not name)
    count = len(names)
    if count <= 1:
        what = _quote(known[0]) if known else "A program"
        where = {"pane": "this pane", "tab": "this tab", "window": "this window"}[scope]
        body = f"{what} is still running in {where}. Closing it ends the program."
    else:
        listed = _list_names(known) if known else ""
        if known and unknown:
            listed += f" and {unknown} other" + ("s" if unknown > 1 else "")
        elif not known:
            listed = ""
        tail = f": {listed}" if listed else ""
        body = f"{count} programs are still running in this {scope}{tail}. Closing ends them."
    return heading, body
