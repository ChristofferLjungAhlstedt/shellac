"""What the settings window shows: pages, groups and fields (GTK-free).

Every field points at one option of the config (``section`` + ``key``); its type, allowed values
and range come from ``config`` so the window and the file validation can never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from .config import ENUMS, RANGES, Config

BOOL, INT, FLOAT, CHOICE, TEXT, THEME, FONT = (
    "bool",
    "int",
    "float",
    "choice",
    "text",
    "theme",
    "font",
)


@dataclass(frozen=True)
class Field:
    section: str
    key: str
    label: str
    description: str = ""
    kind: str = ""  # filled in from the config's default value when left empty
    labels: dict[str, str] = field(default_factory=dict)  # choice value -> shown text
    step: float = 0.0
    digits: int = 0
    placeholder: str = ""
    needs: tuple[str, str] | None = None  # (section, key) of a bool that must be on
    needs_off: bool = False  # ...or must be off

    @property
    def path(self) -> tuple[str, str]:
        return (self.section, self.key)

    @property
    def choices(self) -> list[str]:
        order = list(self.labels)
        extra = sorted(ENUMS.get(self.path, frozenset()) - set(order))
        return [*order, *extra]

    @property
    def bounds(self) -> tuple[float, float] | None:
        return RANGES.get(self.path)


@dataclass(frozen=True)
class Group:
    title: str
    fields: tuple[Field, ...]
    description: str = ""


@dataclass(frozen=True)
class Page:
    id: str
    title: str
    icon: str
    groups: tuple[Group, ...] = ()


def _kind(section: str, key: str, given: str) -> str:
    if given:
        return given
    if (section, key) in ENUMS:
        return CHOICE
    default = getattr(getattr(Config(), section), key)
    if isinstance(default, bool):
        return BOOL
    if isinstance(default, int):
        return INT
    if isinstance(default, float):
        return FLOAT
    return TEXT


def _f(
    section: str, key: str, label: str, description: str = "", kind: str = "", **extra: Any
) -> Field:
    return Field(section, key, label, description, _kind(section, key, kind), **extra)


APPEARANCE = Page(
    "appearance",
    "Appearance",
    "shellac-eye-symbolic",
    (
        Group(
            "Theme",
            (
                _f("appearance", "theme", "Theme", "Previewed live while you choose.", THEME),
                _f(
                    "appearance",
                    "follow_system_scheme",
                    "Follow the system color scheme",
                    "Switch between a dark and a light theme with the desktop.",
                ),
                _f(
                    "appearance",
                    "dark_theme",
                    "Dark theme",
                    "Used when the system is dark.",
                    THEME,
                    needs=("appearance", "follow_system_scheme"),
                ),
                _f(
                    "appearance",
                    "light_theme",
                    "Light theme",
                    "Used when the system is light.",
                    THEME,
                    needs=("appearance", "follow_system_scheme"),
                ),
            ),
        ),
        Group(
            "Text",
            (
                _f("appearance", "font_family", "Font", "A monospace font family.", FONT),
                _f("appearance", "font_size", "Font size", "In points.", step=0.5, digits=1),
                _f(
                    "appearance",
                    "cursor_shape",
                    "Cursor shape",
                    labels={"block": "Block", "ibeam": "I-beam", "underline": "Underline"},
                ),
                _f("appearance", "cursor_blink", "Blinking cursor"),
            ),
        ),
        Group(
            "Window",
            (
                _f(
                    "appearance",
                    "opacity",
                    "Background opacity",
                    "1 is solid; lower lets the desktop show through.",
                    step=0.05,
                    digits=2,
                ),
                _f("appearance", "padding", "Padding", "Space around the text, in pixels."),
                _f("appearance", "pane_spacing", "Space between panes", "In pixels."),
                _f(
                    "appearance",
                    "focus_indicator",
                    "Focused pane",
                    "How the active pane stands out.",
                    labels={"border": "Border", "dim": "Dim the others", "none": "Nothing"},
                ),
            ),
        ),
        Group(
            "Zoom",
            (
                _f(
                    "appearance",
                    "zoom_scope",
                    "Zoom affects",
                    labels={"pane": "The focused pane", "window": "The whole window"},
                ),
                _f(
                    "appearance",
                    "zoom_step",
                    "Zoom step",
                    "Font scale change per step.",
                    step=0.01,
                    digits=2,
                ),
            ),
        ),
    ),
)

TERMINAL = Page(
    "terminal",
    "Terminal",
    "shellac-code-symbolic",
    (
        Group(
            "Shell",
            (
                _f(
                    "general",
                    "shell",
                    "Shell",
                    "Empty uses your login shell.",
                    placeholder="/bin/bash",
                ),
                _f("general", "login_shell", "Start as a login shell"),
                _f(
                    "general",
                    "scrollback_lines",
                    "Scrollback",
                    "Lines kept per terminal; 0 turns it off.",
                    step=100,
                ),
            ),
        ),
        Group(
            "Links",
            (
                _f("general", "clickable_urls", "Clickable links"),
                _f(
                    "general",
                    "link_activation",
                    "Open links with",
                    labels={"click": "A click", "ctrl_click": "Ctrl + click"},
                    needs=("general", "clickable_urls"),
                ),
            ),
        ),
        Group(
            "Behavior",
            (
                _f(
                    "general",
                    "context_menu",
                    "Right-click menu",
                    "Off passes right-clicks to programs.",
                ),
                _f("general", "search_case_sensitive", "Case-sensitive search"),
                _f("general", "search_wrap_around", "Search wraps around"),
                _f("tabs", "autohide", "Hide the tab bar with one tab"),
                _f(
                    "panes",
                    "resize_step",
                    "Pane resize step",
                    "Pixels moved by the resize shortcuts.",
                    step=10,
                ),
            ),
        ),
    ),
)

SIDEBAR = Page(
    "sidebar",
    "Sidebar",
    "shellac-sidebar-symbolic",
    (
        Group(
            "Tree",
            (
                _f("sidebar", "follow_cwd", "Follow the terminal's directory"),
                _f("sidebar", "reveal_in_root", "Reveal instead of re-rooting"),
                _f("sidebar", "show_hidden", "Show hidden files"),
                _f("sidebar", "hide_gitignored", "Hide ignored files", "Off dims them instead."),
                _f("sidebar", "git_status", "Show git status"),
                _f("sidebar", "file_type_icons", "Language icons", "Off uses generic icons."),
                _f("sidebar", "indent", "Indentation", "Pixels per level."),
            ),
        ),
        Group(
            "Opening",
            (
                _f(
                    "sidebar",
                    "on_file_activate",
                    "Opening a file",
                    labels={
                        "editor_split": "Editor in a split",
                        "editor_tab": "Editor in a new tab",
                        "command_split": "Command in a split",
                        "command_tab": "Command in a new tab",
                        "run": "Run it",
                        "paste_path": "Paste the path",
                        "desktop_open": "Default application",
                    },
                ),
                _f(
                    "sidebar",
                    "file_command",
                    "Command",
                    "For the command options. {path} is the file.",
                    placeholder="bat --paging=always {path}",
                ),
                _f(
                    "sidebar",
                    "editor",
                    "Editor",
                    "Empty uses $VISUAL, then $EDITOR.",
                    placeholder="nvim",
                ),
                _f(
                    "sidebar",
                    "editor_split_direction",
                    "Editor split goes",
                    labels={"right": "Right", "down": "Down"},
                ),
                _f("sidebar", "keep_pane_open", "Keep the pane open after a command"),
                _f(
                    "sidebar",
                    "on_dir_activate",
                    "Opening a folder",
                    labels={"cd": "Change directory", "reroot": "Make it the tree root"},
                ),
            ),
        ),
    ),
)

PAGES: tuple[Page, ...] = (APPEARANCE, TERMINAL, SIDEBAR)
KEYBINDINGS_PAGE_ID = "keybindings"


def all_fields() -> list[Field]:
    return [f for page in PAGES for group in page.groups for f in group.fields]


def default_value(item: Field) -> Any:
    return getattr(getattr(Config(), item.section), item.key)


def current_value(config: Config, item: Field) -> Any:
    return getattr(getattr(config, item.section), item.key)


def coerce(item: Field, value: Any) -> Any:
    """Make a widget's value fit the option's type (spin buttons hand out floats)."""
    if item.kind == INT:
        return int(round(value))
    if item.kind == FLOAT:
        return round(float(value), 4)
    if item.kind == TEXT:
        return str(value).strip()
    return value


def values_from_config(config: Config) -> dict[tuple[str, str], Any]:
    """Every field's current value, keyed by (section, key)."""
    return {item.path: current_value(config, item) for item in all_fields()}


def defaults() -> dict[tuple[str, str], Any]:
    return {item.path: default_value(item) for item in all_fields()}


def changes_from_draft(
    saved: dict[tuple[str, str], Any], draft: dict[tuple[str, str], Any]
) -> dict[tuple[str, str], Any]:
    """Entries to write: a value that equals the default removes its line (None)."""
    out: dict[tuple[str, str], Any] = {}
    known = {f.path: f for f in all_fields()}
    for path, value in draft.items():
        item = known[path]
        value = coerce(item, value)
        if value == coerce(item, saved[path]):
            continue
        out[path] = None if value == default_value(item) else value
    return out


def is_enabled(item: Field, values: dict[tuple[str, str], Any]) -> bool:
    if item.needs is None:
        return True
    on = bool(values[item.needs])
    return not on if item.needs_off else on


def validate_schema() -> list[str]:
    """Problems between the schema and the config definition (used by the tests)."""
    problems: list[str] = []
    config = Config()
    seen: set[tuple[str, str]] = set()
    for item in all_fields():
        if item.path in seen:
            problems.append(f"{item.path} listed twice")
        seen.add(item.path)
        section = getattr(config, item.section, None)
        if section is None or item.key not in {f.name for f in fields(section)}:
            problems.append(f"{item.path} is not a config option")
            continue
        if item.kind == CHOICE:
            unknown = set(item.labels) - ENUMS.get(item.path, frozenset())
            if unknown or item.path not in ENUMS:
                problems.append(f"{item.path} has bad choices {sorted(unknown)}")
        if item.kind in (INT, FLOAT) and item.bounds is None:
            problems.append(f"{item.path} has no range")
        if item.needs is not None and item.needs not in {f.path for f in all_fields()}:
            problems.append(f"{item.path} depends on unknown {item.needs}")
    return problems
