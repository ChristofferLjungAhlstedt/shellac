"""Remembered UI state, kept apart from the user's config (FR-24).

The config file is the user's to edit; the app must never rewrite it. What the user
changes by clicking (sidebar visibility and width) is stored here instead, in
``$XDG_STATE_HOME/paneterm/state.json``. Values in this file win over the config's
``[sidebar] visible`` / ``width``, which act as the defaults for a first launch.

GTK-free. Reading never raises; a missing or damaged file just means "no state".
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from . import APP_NAME

log = logging.getLogger(__name__)

MIN_WIDTH = 100
MAX_WIDTH = 1000


@dataclass
class UiState:
    sidebar_visible: bool | None = None  # None: never saved, use the config default
    sidebar_width: int | None = None


def state_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / APP_NAME / "state.json"


def load_state(path: Path | None = None) -> UiState:
    path = path or state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return UiState()
    sidebar = data.get("sidebar") if isinstance(data, dict) else None
    if not isinstance(sidebar, dict):
        return UiState()

    visible = sidebar.get("visible")
    width = sidebar.get("width")
    if not isinstance(width, int) or isinstance(width, bool) or not MIN_WIDTH <= width <= MAX_WIDTH:
        width = None
    return UiState(
        sidebar_visible=visible if isinstance(visible, bool) else None,
        sidebar_width=width,
    )


def save_state(state: UiState, path: Path | None = None) -> bool:
    """Write the state atomically. Returns False (and logs) if it could not be saved."""
    path = path or state_path()
    sidebar: dict[str, object] = {}
    if state.sidebar_visible is not None:
        sidebar["visible"] = state.sidebar_visible
    if state.sidebar_width is not None:
        sidebar["width"] = state.sidebar_width
    temporary = path.with_suffix(".json.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps({"sidebar": sidebar}, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        log.warning("cannot save state to %s: %s", path, exc.strerror)
        return False
    return True
