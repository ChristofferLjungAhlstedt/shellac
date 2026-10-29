"""Edit single entries of the user's config file as text, keeping everything else.

The config file belongs to the user, so saving a setting from the GUI must not reformat it,
drop comments or reorder anything. Only the lines of the changed keys are touched; new keys
are added at the end of their table, and a missing table is created at the end of the file.

GTK-free. The functions return None when the file's layout is one they will not guess at (for
example a table written as an inline ``name = { ... }``); the caller then tells the user to
edit the file by hand.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_HEADER_RE = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")

Value = bool | int | float | str | list[str]


def format_value(value: Value) -> str:
    """A TOML literal for ``value``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = repr(round(value, 6))
        return text if "." in text or "e" in text else text + ".0"
    if isinstance(value, str):
        return json.dumps(value)
    return "[" + ", ".join(json.dumps(item) for item in value) + "]"


def apply_table_changes(
    text: str,
    table: str,
    entries: Mapping[str, str | None],
    *,
    refuse_subtables: bool = False,
) -> str | None:
    """Set ``key = literal`` lines in ``[table]``; a ``None`` literal removes the key.

    ``entries`` maps key -> an already formatted TOML literal. The result is checked to still
    be valid TOML; if it is not, or the layout is not supported, None is returned.
    """
    lines = text.splitlines()
    if any(re.match(rf"^\s*{re.escape(table)}\s*=", line) for line in lines):
        return None

    start = end = None
    for number, line in enumerate(lines):
        header = _HEADER_RE.match(line)
        if header is None:
            continue
        name = header.group(1)
        if refuse_subtables and name.startswith(table + "."):
            return None
        if start is None and name == table and not line.lstrip().startswith("[["):
            start = number
        elif start is not None and end is None:
            end = number
    if start is not None and end is None:
        end = len(lines)

    if start is None:
        body = [f"{key} = {literal}" for key, literal in entries.items() if literal is not None]
        if not body:
            return text
        prefix = [*lines, ""] if lines and lines[-1].strip() else lines
        lines = [*prefix, f"[{table}]", *body]
    else:
        assert end is not None
        section = lines[start + 1 : end]
        appended: list[str] = []
        for key, literal in entries.items():
            index = _find_entry(section, key)
            replacement = [] if literal is None else [f"{key} = {literal}"]
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
        if any(literal is None for literal in entries.values()) and not any(
            line.strip() for line in section
        ):
            # Nothing is left in the table: drop its header, and the blank lines before it.
            head = lines[:start]
            while head and not head[-1].strip():
                head.pop()
            tail = lines[end:]
            lines = [*head, "", *tail] if head and tail else [*head, *tail]
        else:
            lines = [*lines[: start + 1], *section, *lines[end:]]

    result = "\n".join(lines) + "\n"
    if not result.strip():
        result = ""
    try:
        tomllib.loads(result)
    except tomllib.TOMLDecodeError:
        return None
    return result


def apply_setting_changes(text: str, changes: Mapping[tuple[str, str], Any]) -> str | None:
    """Apply ``{(table, key): value}`` changes; a value of None removes the key."""
    tables: dict[str, dict[str, str | None]] = {}
    for (table, key), value in changes.items():
        tables.setdefault(table, {})[key] = None if value is None else format_value(value)
    for table, entries in tables.items():
        updated = apply_table_changes(text, table, entries)
        if updated is None:
            return None
        text = updated
    return text


def _find_entry(section: list[str], key: str) -> tuple[int, int] | None:
    """First and last line index of ``key = ...`` (arrays may span lines)."""
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
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


def save_text_changes(path: Path, updater: Any) -> str | None:
    """Read ``path``, apply ``updater(text) -> new text | None`` and write it atomically.

    Returns an error message, or None on success.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    except OSError as exc:
        return f"cannot read {path.name}: {exc.strerror}"
    updated = updater(text)
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


def save_setting_changes(path: Path, changes: Mapping[tuple[str, str], Any]) -> str | None:
    return save_text_changes(path, lambda text: apply_setting_changes(text, changes))
