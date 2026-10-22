"""Themes and chrome CSS generation (FR-36, FR-37, FR-44, section 8.6).

GTK-free: colors are plain ``#rrggbb`` strings here and are converted to
``Gdk.RGBA`` at the point of use. This keeps theme parsing and CSS generation
unit-testable without a display.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .config import AppearanceConfig, user_themes_dir

DEFAULT_THEME = "catppuccin-mocha"
BUNDLED_THEMES_DIR = Path(__file__).parent / "resources" / "themes"

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
PALETTE_SIZE = 16


class ThemeError(ValueError):
    """A theme file is missing, unreadable or malformed."""


@dataclass(frozen=True)
class Theme:
    id: str  # file stem, e.g. "catppuccin-mocha"
    name: str  # display name
    dark: bool
    foreground: str
    background: str
    cursor: str
    selection_background: str
    selection_foreground: str
    palette: tuple[str, ...]
    accent: str
    sidebar_background: str
    sidebar_foreground: str
    tabbar_background: str
    divider: str


def _color(table: dict, key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not _HEX_RE.match(value):
        raise ThemeError(f"{where}.{key} must be a color like '#rrggbb', got {value!r}")
    return value.lower()


def parse_theme(theme_id: str, data: dict) -> Theme:
    terminal = data.get("terminal")
    ui = data.get("ui")
    if not isinstance(terminal, dict):
        raise ThemeError("missing [terminal] table")
    if not isinstance(ui, dict):
        raise ThemeError("missing [ui] table")

    palette = terminal.get("palette")
    if not isinstance(palette, list) or len(palette) != PALETTE_SIZE:
        raise ThemeError(f"terminal.palette must list exactly {PALETTE_SIZE} colors")
    for index, entry in enumerate(palette):
        if not isinstance(entry, str) or not _HEX_RE.match(entry):
            raise ThemeError(f"terminal.palette[{index}] must be '#rrggbb', got {entry!r}")

    dark = data.get("dark", True)
    if not isinstance(dark, bool):
        raise ThemeError("'dark' must be true or false")

    return Theme(
        id=theme_id,
        name=str(data.get("name") or theme_id),
        dark=dark,
        foreground=_color(terminal, "foreground", "terminal"),
        background=_color(terminal, "background", "terminal"),
        cursor=_color(terminal, "cursor", "terminal"),
        selection_background=_color(terminal, "selection_background", "terminal"),
        selection_foreground=_color(terminal, "selection_foreground", "terminal"),
        palette=tuple(p.lower() for p in palette),
        accent=_color(ui, "accent", "ui"),
        sidebar_background=_color(ui, "sidebar_background", "ui"),
        sidebar_foreground=_color(ui, "sidebar_foreground", "ui"),
        tabbar_background=_color(ui, "tabbar_background", "ui"),
        divider=_color(ui, "divider", "ui"),
    )


def load_theme_file(path: Path) -> Theme:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ThemeError(f"{path}: {exc}") from exc
    try:
        return parse_theme(path.stem, data)
    except ThemeError as exc:
        raise ThemeError(f"{path}: {exc}") from exc


def available_theme_files(user_dir: Path | None = None) -> dict[str, Path]:
    """Map theme id -> file. User themes override bundled ones of the same name."""
    user_dir = user_dir if user_dir is not None else user_themes_dir()
    found: dict[str, Path] = {}
    for directory in (BUNDLED_THEMES_DIR, user_dir):
        if directory.is_dir():
            for path in sorted(directory.glob("*.toml")):
                found[path.stem] = path
    return found


def get_theme(name: str, user_dir: Path | None = None) -> tuple[Theme, list[str]]:
    """Resolve ``name`` to a theme. Never raises: falls back to the default theme.

    Returns the theme plus any warnings to surface to the user.
    """
    files = available_theme_files(user_dir)
    warnings: list[str] = []

    if name not in files:
        warnings.append(f"theme '{name}' not found; using '{DEFAULT_THEME}'")
        name = DEFAULT_THEME
    try:
        return load_theme_file(files[name]), warnings
    except (ThemeError, KeyError) as exc:
        warnings.append(f"could not load theme '{name}': {exc}; using '{DEFAULT_THEME}'")

    # The bundled default is shipped with the app, so a failure here is a packaging bug.
    return load_theme_file(BUNDLED_THEMES_DIR / f"{DEFAULT_THEME}.toml"), warnings


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _rgba(color: str, alpha: float = 1.0) -> str:
    r, g, b = hex_to_rgb(color)
    return f"rgba({r}, {g}, {b}, {alpha:.3f})"


def generate_css(theme: Theme, appearance: AppearanceConfig) -> str:
    """Application chrome CSS built from a theme's UI colors (section 8.6).

    Uses libadwaita's named colors so the stock widgets pick up the theme, plus a
    few rules for our own widgets. Colors only ever come from the theme.
    """
    window_bg = _rgba(theme.background, appearance.opacity)
    return f"""\
@define-color accent_bg_color {theme.accent};
@define-color accent_color {theme.accent};
@define-color window_bg_color {theme.background};
@define-color window_fg_color {theme.foreground};
@define-color headerbar_bg_color {theme.tabbar_background};
@define-color headerbar_fg_color {theme.foreground};
@define-color headerbar_border_color {theme.divider};
@define-color sidebar_bg_color {theme.sidebar_background};
@define-color sidebar_fg_color {theme.sidebar_foreground};

window.paneterm {{
  background-color: {window_bg};
}}

window.paneterm headerbar {{
  background-color: {theme.tabbar_background};
  color: {theme.foreground};
  box-shadow: none;
}}

vte-terminal {{
  padding: {appearance.padding}px;
}}
"""
