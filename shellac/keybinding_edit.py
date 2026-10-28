"""Edit the ``[keybindings]`` table of a config file as text, keeping everything else.

The config file belongs to the user, so saving a shortcut from the GUI must not reformat it,
drop comments or reorder anything. Only the lines of the changed actions are touched (or
appended to the ``[keybindings]`` table, which is created at the end if it is missing).

GTK-free. ``apply_binding_changes`` returns None when the file's layout is one it will not
guess at (for example ``keybindings`` as an inline table); the caller then tells the user to
edit the file by hand.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

_HEADER_RE = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")
_INLINE_RE = re.compile(r"^\s*keybindings\s*=")


def format_value(accels: list[str]) -> str:
    """``"<Ctrl>a"`` for one shortcut, ``["<Ctrl>a", "<Alt>b"]`` for several, ``[]`` for none."""
    if len(accels) == 1:
        return json.dumps(accels[0])
    return "[" + ", ".join(json.dumps(a) for a in accels) + "]"


def apply_binding_changes(text: str, changes: dict[str, list[str] | None]) -> str | None:
    """Return ``text`` with the shortcuts in ``changes`` set.

    ``None`` removes the entry (back to the default); an empty list unbinds the action.

    The result is checked to still be valid TOML; if it is not, or the file's layout is not
    supported, None is returned and nothing should be written.
    """
    lines = text.splitlines()
    if any(_INLINE_RE.match(line) for line in lines):
        return None

    start = end = None
    for number, line in enumerate(lines):
        header = _HEADER_RE.match(line)
        if header is None:
            continue
        name = header.group(1)
        if name.startswith("keybindings."):
            return None
        if start is None and name == "keybindings" and not line.lstrip().startswith("[["):
            start = number
        elif start is not None and end is None:
            end = number
    if start is not None and end is None:
        end = len(lines)

    if start is None:
        body = [f"{action} = {format_value(a)}" for action, a in changes.items() if a is not None]
        if not body:
            return text
        prefix = lines + [""] if lines and lines[-1].strip() else lines
        lines = [*prefix, "[keybindings]", *body]
    else:
        assert end is not None
        section = lines[start + 1 : end]
        appended: list[str] = []
        for action, accels in changes.items():
            index = _find_entry(section, action)
            replacement = [] if accels is None else [f"{action} = {format_value(accels)}"]
            if index is None:
                appended.extend(replacement)
                continue
            first, last = index
            section[first : last + 1] = replacement
        # New entries go after the last real line of the table, before trailing blanks.
        insert_at = len(section)
        while insert_at and not section[insert_at - 1].strip():
            insert_at -= 1
        section[insert_at:insert_at] = appended
        lines = [*lines[: start + 1], *section, *lines[end:]]

    result = "\n".join(lines) + "\n"
    try:
        tomllib.loads(result)
    except tomllib.TOMLDecodeError:
        return None
    return result


def _find_entry(section: list[str], action: str) -> tuple[int, int] | None:
    """First and last line index of ``action = ...`` (arrays may span lines)."""
    pattern = re.compile(rf"^\s*{re.escape(action)}\s*=")
    for number, line in enumerate(section):
        if not pattern.match(line):
            continue
        last = number
        depth = _bracket_balance(line)
        while depth > 0 and last + 1 < len(section):
            last += 1
            depth += _bracket_balance(section[last])
        return number, last
    return None


def _bracket_balance(line: str) -> int:
    """Open minus close square brackets outside quotes and comments."""
    balance = 0
    quote = ""
    for char in line:
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#":
            break
        elif char == "[":
            balance += 1
        elif char == "]":
            balance -= 1
    return balance


def save_binding_changes(path: Path, changes: dict[str, list[str] | None]) -> str | None:
    """Write the changes into the config file. Returns an error message, or None on success."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    except OSError as exc:
        return f"cannot read {path.name}: {exc.strerror}"
    updated = apply_binding_changes(text, changes)
    if updated is None:
        return f"{path.name} has a layout I will not edit automatically; please edit it by hand"
    temporary = path.with_suffix(".toml.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(updated, encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        return f"cannot save {path.name}: {exc.strerror}"
    return None
