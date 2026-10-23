"""Action name -> accelerator mapping, plus conflict detection (FR-47).

This module is GTK-free so it can be unit tested without a display.
Accelerators use GTK syntax, e.g. ``<Ctrl><Shift>c``.
"""

from __future__ import annotations

import re

# Defaults from the spec's example config. Actions are only *wired up* once the
# milestone that implements them lands (see ACTION_TARGETS in application.py).
DEFAULT_KEYBINDINGS: dict[str, str] = {
    "split_down": "<Ctrl><Shift>o",
    "split_right": "<Ctrl><Shift>e",
    "close_pane": "<Ctrl><Shift>w",
    "new_tab": "<Ctrl><Shift>t",
    "toggle_sidebar": "<Ctrl><Shift>b",
    "focus_sidebar": "<Ctrl><Alt>b",
    "zoom_pane": "<Ctrl><Shift>z",
    "focus_left": "<Ctrl><Alt>Left",
    "focus_right": "<Ctrl><Alt>Right",
    "focus_up": "<Ctrl><Alt>Up",
    "focus_down": "<Ctrl><Alt>Down",
    "resize_left": "<Ctrl><Shift><Alt>Left",
    "resize_right": "<Ctrl><Shift><Alt>Right",
    "resize_up": "<Ctrl><Shift><Alt>Up",
    "resize_down": "<Ctrl><Shift><Alt>Down",
    "next_tab": "<Ctrl>Page_Down",
    "prev_tab": "<Ctrl>Page_Up",
    **{f"goto_tab_{n}": f"<Alt>{n}" for n in range(1, 10)},
    "copy": "<Ctrl><Shift>c",
    "paste": "<Ctrl><Shift>v",
    "search": "<Ctrl><Shift>f",
    "zoom_in": "<Ctrl>plus",
    "zoom_out": "<Ctrl>minus",
    "zoom_reset": "<Ctrl>0",
    "cycle_theme": "<Ctrl><Shift>p",
    "reload_config": "<Ctrl><Shift>r",
}

# Extra accelerators bound next to the configured one. "plus" needs Shift on most layouts,
# so the unshifted key and the keypad also work.
ACCELERATOR_ALIASES: dict[str, tuple[str, ...]] = {
    "zoom_in": ("<Ctrl>equal", "<Ctrl>KP_Add"),
    "zoom_out": ("<Ctrl>KP_Subtract",),
    "zoom_reset": ("<Ctrl>KP_0",),
}

_MODIFIER_RE = re.compile(r"<([^<>]+)>")

_MODIFIER_ALIASES = {
    "ctrl": "control",
    "control": "control",
    "primary": "control",
    "shift": "shift",
    "alt": "alt",
    "mod1": "alt",
    "super": "super",
    "mod4": "super",
    "meta": "meta",
}


def normalize_accelerator(accel: str) -> tuple[frozenset[str], str] | None:
    """Return a canonical (modifiers, key) pair, or None if ``accel`` is malformed.

    ``<Ctrl><Shift>o`` and ``<Shift><Control>O`` normalize to the same value, so
    they are detected as the same binding.
    """
    text = accel.strip()
    if not text:
        return None
    modifiers: set[str] = set()
    for name in _MODIFIER_RE.findall(text):
        canonical = _MODIFIER_ALIASES.get(name.lower())
        if canonical is None:
            return None
        modifiers.add(canonical)
    key = _MODIFIER_RE.sub("", text)
    if not key or "<" in key or ">" in key or " " in key:
        return None
    return frozenset(modifiers), key.lower()


def find_conflicts(bindings: dict[str, str]) -> list[tuple[str, str]]:
    """Return pairs of action names that share the same accelerator."""
    seen: dict[tuple[frozenset[str], str], str] = {}
    conflicts: list[tuple[str, str]] = []
    for action, accel in bindings.items():
        normalized = normalize_accelerator(accel)
        if normalized is None:
            continue
        if normalized in seen:
            conflicts.append((seen[normalized], action))
        else:
            seen[normalized] = action
    return conflicts
