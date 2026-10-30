"""Load, validate and merge the TOML config (FR-44, FR-45).

GTK-free. A missing, partial or invalid file never raises: bad values are
replaced by their defaults and reported through ``LoadResult.warnings``.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from . import APP_NAME
from .keybindings import (
    DEFAULT_KEYBINDINGS,
    find_binding_conflicts,
    normalize_accelerator,
)


@dataclass
class GeneralConfig:
    shell: str = ""  # empty = $SHELL, then /bin/zsh, then /bin/bash
    login_shell: bool = True  # pass -l to the shell (FR-1 asks for a login shell)
    scrollback_lines: int = 10000
    confirm_close_running: bool = True
    clickable_urls: bool = True  # a click on a URL in the output opens it (FR-6)
    link_activation: str = "click"  # click | ctrl_click: what opens a link
    context_menu: bool = True  # right-click menu (Shift+right-click in mouse-aware programs)
    search_case_sensitive: bool = False  # starting state of the search bar's case toggle
    search_wrap_around: bool = True  # continue from the other end when a search runs out


@dataclass
class WindowConfig:
    width: int = 1000
    height: int = 640


@dataclass
class PanesConfig:
    resize_step: int = 40  # pixels moved by one keyboard resize (FR-17)


@dataclass
class TabsConfig:
    autohide: bool = True  # hide the tab bar while only one tab is open (FR-23)


@dataclass
class AppearanceConfig:
    theme: str = "catppuccin-mocha"
    follow_system_scheme: bool = False
    # Used instead of ``theme`` when follow_system_scheme is on.
    dark_theme: str = "catppuccin-mocha"
    light_theme: str = "one-light"
    font_family: str = "JetBrainsMono Nerd Font"
    font_size: float = 12.0
    opacity: float = 0.95
    padding: int = 8
    pane_spacing: int = 1
    focus_indicator: str = "border"  # border | dim | none
    cursor_shape: str = "block"  # block | ibeam | underline
    cursor_blink: bool = True
    zoom_scope: str = "pane"  # pane | window: what Ctrl+plus / Ctrl+minus resize (FR-8)
    zoom_step: float = 0.1  # font scale change per step


@dataclass
class SidebarConfig:
    visible: bool = True
    width: int = 260
    follow_cwd: bool = True
    show_hidden: bool = False
    # Dotfiles shown even while hidden files are hidden.
    always_show: list[str] = field(
        default_factory=lambda: [".gitignore", ".gitattributes", ".gitmodules", ".editorconfig"]
    )
    hide_gitignored: bool = False  # hide ignored entries instead of dimming them
    git_status: bool = True  # color and mark changed files; needs git installed
    # editor_split | editor_tab | command_split | command_tab | run | paste_path | desktop_open
    on_file_activate: str = "editor_split"
    file_command: str = ""  # for command_*: e.g. "bat --paging=always {path}"
    # Per-extension (or exact file name) command, used by editor_* and command_* modes:
    # open_with = { md = "glow -p {path}", py = "python {path}" }
    open_with: dict[str, str] = field(default_factory=dict)
    keep_pane_open: bool = True  # command_* and run: wait for Enter after the command ends
    on_dir_activate: str = "cd"  # cd | reroot
    file_type_icons: bool = True  # logos per language (JS, Dart, ...); false: generic icons
    indent: int = 16  # pixels of indentation per tree level
    editor: str = ""  # empty = $VISUAL, then $EDITOR, then nano/vim/vi
    editor_split_direction: str = "right"  # right | down
    reveal_in_root: bool = True  # follow mode scrolls to a directory inside the tree
    # instead of re-rooting the tree on it (section 8.4)


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    window: WindowConfig = field(default_factory=WindowConfig)
    panes: PanesConfig = field(default_factory=PanesConfig)
    tabs: TabsConfig = field(default_factory=TabsConfig)
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)
    sidebar: SidebarConfig = field(default_factory=SidebarConfig)
    keybindings: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_KEYBINDINGS))
    # Second, third... shortcut of an action; ``keybindings`` holds the first one.
    extra_bindings: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class LoadResult:
    config: Config
    warnings: list[str] = field(default_factory=list)
    path: Path | None = None


# Allowed values for string options, keyed by (section, option).
ENUMS: dict[tuple[str, str], frozenset[str]] = {
    ("general", "link_activation"): frozenset({"click", "ctrl_click"}),
    ("appearance", "focus_indicator"): frozenset({"border", "dim", "none"}),
    ("appearance", "cursor_shape"): frozenset({"block", "ibeam", "underline"}),
    ("appearance", "zoom_scope"): frozenset({"pane", "window"}),
    ("sidebar", "on_file_activate"): frozenset(
        {
            "editor_split",
            "editor_tab",
            "command_split",
            "command_tab",
            "run",
            "paste_path",
            "desktop_open",
        }
    ),
    ("sidebar", "on_dir_activate"): frozenset({"cd", "reroot"}),
    ("sidebar", "editor_split_direction"): frozenset({"right", "down"}),
}

# Inclusive numeric ranges, keyed by (section, option).
RANGES: dict[tuple[str, str], tuple[float, float]] = {
    ("general", "scrollback_lines"): (0, 1_000_000),
    ("window", "width"): (200, 10_000),
    ("window", "height"): (150, 10_000),
    ("panes", "resize_step"): (1, 1000),
    ("appearance", "font_size"): (4, 72),
    ("appearance", "opacity"): (0.0, 1.0),
    ("appearance", "padding"): (0, 200),
    ("appearance", "pane_spacing"): (0, 20),
    ("appearance", "zoom_step"): (0.01, 1.0),
    ("sidebar", "width"): (100, 1000),
    ("sidebar", "indent"): (4, 64),
}

_SECTIONS: dict[str, type] = {
    "general": GeneralConfig,
    "window": WindowConfig,
    "panes": PanesConfig,
    "tabs": TabsConfig,
    "appearance": AppearanceConfig,
    "sidebar": SidebarConfig,
}


def config_dir() -> Path:
    """``$XDG_CONFIG_HOME/<appname>`` (default ``~/.config/<appname>``)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.toml"


def user_themes_dir() -> Path:
    return config_dir() / "themes"


def _type_matches(value: Any, default: Any) -> bool:
    # bool is a subclass of int, so check it explicitly in both directions.
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(default, float):
        return isinstance(value, int | float) and not isinstance(value, bool)
    if isinstance(default, str):
        return isinstance(value, str)
    if isinstance(default, list):
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if isinstance(default, dict):
        return isinstance(value, dict) and all(
            isinstance(key, str) and isinstance(item, str) for key, item in value.items()
        )
    return False


def _build_section(name: str, cls: type, raw: Any, warnings: list[str]) -> Any:
    instance = cls()
    if raw is None:
        return instance
    if not isinstance(raw, dict):
        warnings.append(f"[{name}] must be a table; using defaults")
        return instance

    known = {f.name for f in fields(cls)}
    for key in raw:
        if key not in known:
            warnings.append(f"[{name}] unknown option '{key}' ignored")

    for f in fields(cls):
        if f.name not in raw:
            continue
        value = raw[f.name]
        default = getattr(instance, f.name)
        label = f"[{name}] {f.name}"

        if not _type_matches(value, default):
            warnings.append(
                f"{label}: expected {type(default).__name__}, got {type(value).__name__}; "
                f"using default {default!r}"
            )
            continue
        allowed = ENUMS.get((name, f.name))
        if allowed is not None and value not in allowed:
            warnings.append(
                f"{label}: {value!r} is not one of {sorted(allowed)}; using default {default!r}"
            )
            continue
        bounds = RANGES.get((name, f.name))
        if bounds is not None and not bounds[0] <= value <= bounds[1]:
            warnings.append(
                f"{label}: {value!r} is outside {bounds[0]}..{bounds[1]}; using default {default!r}"
            )
            continue
        # Keep floats as floats even if the user wrote an integer (font_size = 12).
        if isinstance(default, float):
            value = float(value)
        elif isinstance(value, list | dict):
            value = value.copy()  # never share the parsed TOML's own containers
        setattr(instance, f.name, value)
    return instance


def _build_keybindings(
    raw: Any, warnings: list[str]
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Primary accelerator per action, plus any additional ones.

    A value is one accelerator string, or a list of them: the first is the primary one.
    """
    bindings = dict(DEFAULT_KEYBINDINGS)
    extras: dict[str, list[str]] = {}
    if raw is None:
        return bindings, extras
    if not isinstance(raw, dict):
        warnings.append("[keybindings] must be a table; using defaults")
        return bindings, extras

    for action, value in raw.items():
        if action not in DEFAULT_KEYBINDINGS:
            warnings.append(f"[keybindings] unknown action '{action}' ignored")
            continue
        values = value if isinstance(value, list) else [value]
        if values == []:  # an explicitly empty list unbinds the action
            bindings.pop(action, None)
            continue
        valid = [v for v in values if isinstance(v, str) and normalize_accelerator(v) is not None]
        if len(valid) != len(values) or not valid:
            warnings.append(
                f"[keybindings] {action}: invalid accelerator {value!r}; "
                + (
                    "ignoring the invalid entries"
                    if valid
                    else f"using default {DEFAULT_KEYBINDINGS[action]!r}"
                )
            )
        if not valid:
            continue
        bindings[action] = valid[0]
        if valid[1:]:
            extras[action] = valid[1:]

    everything = {a: [first, *extras.get(a, [])] for a, first in bindings.items()}
    for first, second, accel in find_binding_conflicts(everything):
        warnings.append(f"[keybindings] '{first}' and '{second}' share the accelerator {accel!r}")
    return bindings, extras


def parse_config(data: dict[str, Any]) -> LoadResult:
    """Validate already-parsed TOML data and merge it over the defaults."""
    warnings: list[str] = []
    sections = {
        name: _build_section(name, cls, data.get(name), warnings) for name, cls in _SECTIONS.items()
    }
    for key in data:
        if key not in _SECTIONS and key != "keybindings":
            warnings.append(f"unknown section [{key}] ignored")
    bindings, extras = _build_keybindings(data.get("keybindings"), warnings)
    config = Config(**sections, keybindings=bindings, extra_bindings=extras)
    return LoadResult(config=config, warnings=warnings)


def load_config(path: Path | None = None) -> LoadResult:
    """Load the config file. Never raises; problems become warnings."""
    path = path or config_path()
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError:
        return LoadResult(config=Config(), path=path)
    except tomllib.TOMLDecodeError as exc:
        return LoadResult(
            config=Config(),
            warnings=[f"{path}: invalid TOML ({exc}); using defaults"],
            path=path,
        )
    except OSError as exc:
        return LoadResult(
            config=Config(),
            warnings=[f"{path}: cannot be read ({exc.strerror}); using defaults"],
            path=path,
        )
    result = parse_config(data)
    result.path = path
    return result
