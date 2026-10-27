"""Which bundled icon a file tree row uses (FR-31).

GTK-free so the mapping is unit tested. The icons are shipped with the app
(``resources/icons``), so they never depend on a glyph font or the icon theme.
"""

from __future__ import annotations

import os

from .file_tree_model import Entry
from .file_type_icons import logo_name

ICON_PREFIX = "paneterm-"

CODE_EXTENSIONS = frozenset(
    [
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".rs",
        ".go",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cc",
        ".java",
        ".kt",
        ".rb",
        ".php",
        ".lua",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".css",
        ".scss",
        ".html",
        ".htm",
        ".xml",
        ".sql",
        ".nix",
        ".cs",
        ".swift",
        ".vim",
        ".el",
        ".hs",
        ".ml",
        ".zig",
    ]
)
TEXT_EXTENSIONS = frozenset(
    [
        ".md",
        ".markdown",
        ".txt",
        ".rst",
        ".org",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".ini",
        ".cfg",
        ".conf",
        ".log",
        ".csv",
        ".lock",
        ".env",
    ]
)
IMAGE_EXTENSIONS = frozenset(
    [".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico", ".tiff", ".avif", ".heic"]
)
ARCHIVE_EXTENSIONS = frozenset(
    [
        ".zip",
        ".tar",
        ".gz",
        ".tgz",
        ".bz2",
        ".xz",
        ".zst",
        ".7z",
        ".rar",
        ".deb",
        ".rpm",
        ".jar",
        ".whl",
        ".iso",
    ]
)


def file_kind(name: str) -> str:
    """Coarse category of a regular file, from its name."""
    extension = os.path.splitext(name)[1].lower()
    if extension in CODE_EXTENSIONS:
        return "code"
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in ARCHIVE_EXTENSIONS:
        return "archive"
    if extension in TEXT_EXTENSIONS or name.lower() in {"makefile", "license", "readme"}:
        return "text"
    return "file"


def icon_name(entry: Entry, *, expanded: bool = False, logos: bool = False) -> str:
    """Icon name for a row (without the ``-symbolic`` suffix handling: it is included)."""
    if entry.broken:
        kind = "broken"
    elif entry.is_dir:
        kind = "folder-open" if expanded else "folder"
    elif entry.is_symlink:
        kind = "link"
    else:
        logo = logo_name(entry.name) if logos else None
        if logo is not None:
            return logo
        kind = file_kind(entry.name)
    return f"{ICON_PREFIX}{kind}-symbolic"


ALL_ICON_NAMES = tuple(
    f"{ICON_PREFIX}{kind}-symbolic"
    for kind in (
        "folder",
        "folder-open",
        "file",
        "code",
        "text",
        "image",
        "archive",
        "link",
        "broken",
        "chevron-right",
        "chevron-down",
        "pin",
        "up",
        "eye",
        "sidebar",
        "plus",
        "close",
        "chevron-up",
    )
)
