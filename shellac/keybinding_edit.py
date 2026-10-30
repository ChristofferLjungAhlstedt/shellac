"""Edit the ``[keybindings]`` table of a config file as text, keeping everything else.

A thin layer over ``config_edit``: shortcuts are written as one string, or a list of strings
for several, and an empty list means "no shortcut". ``None`` removes the entry (the default
applies again).
"""

from __future__ import annotations

from pathlib import Path

from .config_edit import apply_table_changes, format_value, save_text_changes

TABLE = "keybindings"


def _literal(accels: list[str] | None) -> str | None:
    if accels is None:
        return None
    return format_value(accels[0] if len(accels) == 1 else accels)


def apply_binding_changes(text: str, changes: dict[str, list[str] | None]) -> str | None:
    """Return ``text`` with the shortcuts in ``changes`` set.

    ``None`` removes the entry (back to the default); an empty list unbinds the action.
    Returns None when the file's layout is not one that is safe to edit.
    """
    entries = {action: _literal(accels) for action, accels in changes.items()}
    return apply_table_changes(text, TABLE, entries, refuse_subtables=True)


def save_binding_changes(path: Path, changes: dict[str, list[str] | None]) -> str | None:
    """Write the changes into the config file. Returns an error message, or None on success."""
    return save_text_changes(path, lambda text: apply_binding_changes(text, changes))
