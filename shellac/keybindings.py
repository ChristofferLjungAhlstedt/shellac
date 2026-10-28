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
    "select_all": "<Ctrl><Shift>a",
    "search": "<Ctrl><Shift>f",
    "zoom_in": "<Ctrl>plus",
    "zoom_out": "<Ctrl>minus",
    "zoom_reset": "<Ctrl>0",
    "cycle_theme": "<Ctrl><Shift>p",
    "reload_config": "<Ctrl><Shift>r",
    "command_palette": "<Ctrl><Shift>space",
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


_KEY_LABELS = {
    "left": "←",
    "right": "→",
    "up": "↑",
    "down": "↓",
    "page_up": "PgUp",
    "page_down": "PgDn",
    "return": "Enter",
    "escape": "Esc",
    "backspace": "⌫",
    "tab": "Tab",
    "space": "Space",
    "plus": "+",
    "minus": "−",
    "equal": "=",
    "comma": ",",
    "period": ".",
    "slash": "/",
    "backslash": "\\",
    "grave": "`",
    "home": "Home",
    "end": "End",
    "insert": "Ins",
    "delete": "Del",
    "kp_add": "Num +",
    "kp_subtract": "Num −",
}

_MODIFIER_LABELS = (("control", "Ctrl"), ("shift", "Shift"), ("alt", "Alt"), ("super", "Super"))


def accelerator_tokens(accel: str) -> list[str]:
    """Split an accelerator into display labels: ``<Ctrl><Shift>o`` -> Ctrl, Shift, O.

    Used to draw each key as its own keycap. A malformed accelerator comes back as one token.
    """
    normalized = normalize_accelerator(accel)
    if normalized is None:
        return [accel]
    modifiers, key = normalized
    tokens = [label for name, label in _MODIFIER_LABELS if name in modifiers]
    if "meta" in modifiers:
        tokens.append("Meta")
    if key in _KEY_LABELS:
        tokens.append(_KEY_LABELS[key])
    elif key.startswith("kp_") and len(key) > 3:
        tokens.append("Num " + key[3:].upper())
    elif len(key) == 1:
        tokens.append(key.upper())
    else:
        tokens.append(key.upper() if key[0] == "f" and key[1:].isdigit() else key.capitalize())
    return tokens


def is_safe_binding(accel: str) -> bool:
    """A binding must not steal plain typing: it needs a modifier, or be a function key."""
    normalized = normalize_accelerator(accel)
    if normalized is None:
        return False
    modifiers, key = normalized
    if modifiers - {"shift"}:
        return True
    return key[0] == "f" and key[1:].isdigit()


def canonical_accelerator(accel: str) -> str | None:
    """Rewrite as ``<Ctrl><Shift><Alt>key`` (our style), or None if malformed."""
    normalized = normalize_accelerator(accel)
    if normalized is None:
        return None
    modifiers, key = normalized
    names = {
        "control": "<Ctrl>",
        "shift": "<Shift>",
        "alt": "<Alt>",
        "super": "<Super>",
        "meta": "<Meta>",
    }
    prefix = "".join(text for name, text in names.items() if name in modifiers)
    # Keep the key's original capitalization rules: GTK key names such as Page_Down are
    # case-sensitive, single letters are lowercase.
    original = _MODIFIER_RE.sub("", accel.strip())
    return prefix + (key if len(key) == 1 else original)


def all_bindings(primary: dict[str, str], extra: dict[str, list[str]]) -> dict[str, list[str]]:
    """Every accelerator of every action, primary first. An unbound action maps to ``[]``."""
    return {
        action: [primary[action], *extra.get(action, [])] if action in primary else []
        for action in DEFAULT_KEYBINDINGS
    }


def find_binding_conflicts(bindings: dict[str, list[str]]) -> list[tuple[str, str, str]]:
    """(first action, second action, accelerator) for each shared accelerator."""
    seen: dict[tuple[frozenset[str], str], str] = {}
    found: list[tuple[str, str, str]] = []
    for action, accels in bindings.items():
        for accel in accels:
            normalized = normalize_accelerator(accel)
            if normalized is None:
                continue
            owner = seen.get(normalized)
            if owner is None:
                seen[normalized] = action
            elif owner != action:
                found.append((owner, action, accel))
    return found


def owner_of(accel: str, bindings: dict[str, list[str]], *, ignore: str = "") -> str | None:
    """The action (other than ``ignore``) that already uses ``accel``."""
    wanted = normalize_accelerator(accel)
    if wanted is None:
        return None
    for action, accels in bindings.items():
        if action != ignore and any(normalize_accelerator(a) == wanted for a in accels):
            return action
    return None


def with_key(accel: str, key: str) -> str:
    """The same modifiers as ``accel`` with a different key: ``<Alt>x`` + ``3`` -> ``<Alt>3``."""
    end = accel.rfind(">")
    return accel[: end + 1] + key
