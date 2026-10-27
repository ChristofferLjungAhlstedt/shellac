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


def theme_ids(user_dir: Path | None = None) -> list[str]:
    """All selectable theme ids (bundled and user), sorted."""
    return sorted(available_theme_files(user_dir))


def next_theme_id(current: str, ids: list[str]) -> str:
    """The theme after ``current``, wrapping around (FR-38).

    An unknown ``current`` (say, its file was just deleted) starts from the first one.
    """
    if not ids:
        return current
    if current not in ids:
        return ids[0]
    return ids[(ids.index(current) + 1) % len(ids)]


def theme_basis(appearance: AppearanceConfig) -> str:
    """The config's theme settings as one string.

    A theme picked at runtime is only restored while this is unchanged, so editing
    ``theme``, ``dark_theme`` or ``light_theme`` in the config takes effect.
    """
    return "|".join(
        (
            appearance.theme,
            appearance.dark_theme,
            appearance.light_theme,
            str(appearance.follow_system_scheme),
        )
    )


def choose_theme_id(appearance: AppearanceConfig, system_dark: bool | None) -> str:
    """Which theme the config asks for (FR-43).

    With ``follow_system_scheme`` the system's dark/light preference picks between
    ``dark_theme`` and ``light_theme``; otherwise ``theme`` is used as written.
    """
    if appearance.follow_system_scheme and system_dark is not None:
        return appearance.dark_theme if system_dark else appearance.light_theme
    return appearance.theme


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


def relative_luminance(color: str) -> float:
    """WCAG relative luminance of a ``#rrggbb`` color (0 = black, 1 = white)."""

    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in hex_to_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(first: str, second: str) -> float:
    """WCAG contrast ratio between two colors, from 1 (identical) to 21."""
    a, b = relative_luminance(first), relative_luminance(second)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


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

window.shellac {{
  background-color: {window_bg};
}}

window.shellac headerbar {{
  background-color: {theme.tabbar_background};
  color: {theme.foreground};
  box-shadow: none;
}}

vte-terminal {{
  padding: {appearance.padding}px;
}}

/* Thin visible divider between panes (FR-41). */
paned > separator {{
  min-width: {appearance.pane_spacing}px;
  min-height: {appearance.pane_spacing}px;
  background-color: {theme.divider};
  background-image: none;
}}
{_sidebar_css(theme)}{_palette_css(theme)}{_focus_indicator_css(theme, appearance)}"""


# Which palette entry colors each git status. Taken from the theme, so every theme reads well.
GIT_STATUS_PALETTE_INDEX = {
    "conflicted": 5,  # magenta
    "modified": 3,  # yellow
    "deleted": 1,  # red
    "added": 2,  # green
    "untracked": 6,  # cyan
}


def _git_status_css(theme: Theme) -> str:
    return "\n".join(
        f".shellac-sidebar .git-{name} label {{ color: {theme.palette[index]}; }}"
        for name, index in GIT_STATUS_PALETTE_INDEX.items()
    )


def _palette_css(theme: Theme) -> str:
    """The command palette: keycaps, shortcut pills and group headings."""
    return f"""
.shellac-palette .palette-list {{
  background: transparent;
}}

.shellac-palette .palette-row {{
  border-radius: 10px;
  margin: 1px 8px;
  transition: background-color 120ms ease;
}}

.shellac-palette .palette-row:hover {{
  background-color: alpha(currentColor, 0.05);
}}

.shellac-palette .palette-row:selected {{
  background-color: alpha({theme.accent}, 0.16);
}}

.shellac-palette .palette-title {{
  font-weight: 600;
}}

.shellac-palette .palette-group {{
  font-size: 0.72em;
  font-weight: 700;
  letter-spacing: 0.08em;
  opacity: 0.55;
  margin: 14px 18px 4px 18px;
}}

.shellac-palette .keycap {{
  font-size: 0.82em;
  font-weight: 600;
  min-width: 1.15em;
  padding: 2px 7px;
  border-radius: 6px;
  background-color: alpha(currentColor, 0.09);
  border: 1px solid alpha(currentColor, 0.16);
  border-bottom-width: 2px;
}}

.shellac-palette .binding-pill {{
  border-radius: 9px;
  padding: 1px 2px 1px 2px;
  background-color: alpha(currentColor, 0.05);
  border: 1px solid alpha(currentColor, 0.12);
}}

.shellac-palette .binding-pill button.flat {{
  min-height: 0;
  min-width: 0;
  padding: 2px 4px;
  border-radius: 7px;
}}

.shellac-palette .binding-pill .pill-remove {{
  padding: 3px;
  opacity: 0.55;
}}

.shellac-palette .binding-pill .pill-remove:hover {{
  opacity: 1;
  color: {theme.palette[1]};
}}

.shellac-palette .binding-pill.capturing {{
  border-color: {theme.accent};
  background-color: alpha({theme.accent}, 0.14);
}}

.shellac-palette .capture-label {{
  color: {theme.accent};
  font-weight: 600;
  font-size: 0.9em;
  padding: 3px 10px;
}}

.shellac-palette .palette-footer {{
  border-top: 1px solid alpha(currentColor, 0.1);
  background-color: alpha(currentColor, 0.03);
}}

.shellac-palette .add-binding {{
  opacity: 0.6;
}}

.shellac-palette .add-binding:hover {{
  opacity: 1;
}}
"""


def _sidebar_css(theme: Theme) -> str:
    return f"""
.shellac-sidebar {{
  background-color: {theme.sidebar_background};
  color: {theme.sidebar_foreground};
}}
.shellac-sidebar listview, .shellac-sidebar .shellac-tree {{
  background: transparent;
  color: {theme.sidebar_foreground};
}}
.shellac-sidebar .shellac-tree > row {{
  padding: 1px 4px;
  min-height: 24px;
  border-radius: 4px;
}}
.shellac-sidebar .shellac-tree > row:hover {{
  background-color: {_rgba(theme.sidebar_foreground, 0.08)};
}}
.shellac-sidebar .shellac-tree > row:selected {{
  background-color: {_rgba(theme.accent, 0.35)};
  color: {theme.sidebar_foreground};
}}
.shellac-sidebar .hidden-entry {{ opacity: 0.6; }}
.shellac-sidebar .ignored-entry {{ opacity: 0.45; }}
.shellac-sidebar .git-marker {{ font-size: 0.85em; font-weight: bold; }}
{_git_status_css(theme)}
.shellac-sidebar .error-entry label {{ font-style: italic; opacity: 0.7; }}
.shellac-sidebar-header {{ padding: 4px 6px; }}
.shellac-search {{
  background-color: {theme.sidebar_background};
  color: {theme.sidebar_foreground};
  border: 1px solid {theme.divider};
  border-radius: 8px;
  padding: 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
}}
.shellac-search entry, .shellac-search button {{ color: {theme.sidebar_foreground}; }}
.shellac-sidebar button, .shellac-sidebar entry, .shellac-sidebar image {{
  color: {theme.sidebar_foreground};
}}
"""


def _focus_indicator_css(theme: Theme, appearance: AppearanceConfig) -> str:
    """Rules marking the focused pane (FR-19). Only applies while several panes are visible."""
    if appearance.focus_indicator == "border":
        # An outline is drawn over the content and never changes the pane's size.
        return f"""
.shellac-multi .shellac-pane.focused {{
  outline: 1px solid {theme.accent};
  outline-offset: -1px;
}}
"""
    if appearance.focus_indicator == "dim":
        return """
.shellac-multi .shellac-pane:not(.focused) {
  opacity: 0.7;
}
"""
    return ""
