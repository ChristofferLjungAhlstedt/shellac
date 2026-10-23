"""Install the launcher entry and icon so paneterm shows up in the application menu (M6).

pipx and pip install Python packages only; they cannot put a ``.desktop`` file or an icon
where the desktop looks for them. ``paneterm --install-desktop`` does that for the current
user (``~/.local/share``), and ``--uninstall-desktop`` removes it again. GTK-free.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import APP_ID, APP_NAME

ICON_SOURCE = Path(__file__).parent / "resources" / "icons" / "hicolor" / "scalable" / "apps"
ICON_FILE = f"{APP_ID}.svg"
DESKTOP_FILE = f"{APP_ID}.desktop"


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def quote_exec(argument: str) -> str:
    """Quote one argument for the ``Exec`` key (Desktop Entry spec: double quotes, escapes)."""
    if not argument or any(c in argument for c in " \t\n\"'\\><~|&;$*?#()`"):
        escaped = (
            argument.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("`", "\\`")
            .replace("$", "\\$")
        )
        return f'"{escaped}"'
    return argument


def exec_command() -> list[str]:
    """How the menu entry starts the app: the installed script, else this interpreter."""
    script = shutil.which(APP_NAME)
    if script:
        return [script]
    return [sys.executable, "-m", APP_NAME]


def desktop_entry(command: list[str]) -> str:
    exec_line = " ".join(quote_exec(part) for part in command)
    return f"""\
[Desktop Entry]
Type=Application
Version=1.5
Name={APP_NAME}
GenericName=Terminal Emulator
Comment=Terminal emulator with split panes, tabs and a file tree sidebar
Exec={exec_line}
Icon={APP_ID}
Terminal=false
StartupNotify=true
Categories=System;TerminalEmulator;Utility;GTK;
Keywords=terminal;shell;console;command line;prompt;
"""


def install(home: Path | None = None, command: list[str] | None = None) -> list[Path]:
    """Write the launcher and icon under ``home`` (default: the user's data directory)."""
    home = home or data_home()
    entry = home / "applications" / DESKTOP_FILE
    icon = home / "icons" / "hicolor" / "scalable" / "apps" / ICON_FILE
    entry.parent.mkdir(parents=True, exist_ok=True)
    icon.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(desktop_entry(command or exec_command()), encoding="utf-8")
    shutil.copyfile(ICON_SOURCE / ICON_FILE, icon)
    _refresh_caches(home)
    return [entry, icon]


def uninstall(home: Path | None = None) -> list[Path]:
    """Remove what ``install`` wrote. Returns the files that were removed."""
    home = home or data_home()
    removed = []
    for path in (
        home / "applications" / DESKTOP_FILE,
        home / "icons" / "hicolor" / "scalable" / "apps" / ICON_FILE,
    ):
        if path.exists():
            path.unlink()
            removed.append(path)
    _refresh_caches(home)
    return removed


def _refresh_caches(home: Path) -> None:
    """Best effort: desktops notice new launchers by themselves, this just makes it faster.

    The icon cache is deliberately left alone. Without a cache GTK scans the folder, but a
    cache we wrote for ``~/.local/share/icons/hicolor`` would hide icons other apps add there
    later without refreshing it.
    """
    if shutil.which("update-desktop-database"):
        subprocess.run(
            ["update-desktop-database", str(home / "applications")],
            check=False,
            capture_output=True,
            timeout=30,
        )
