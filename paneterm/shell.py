"""Shell and environment resolution for new panes (FR-1, FR-2, section 8.3).

GTK-free so it can be unit tested.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterable, Mapping
from pathlib import Path
from urllib.parse import unquote, urlparse

FALLBACK_SHELLS = ("/bin/zsh", "/bin/bash")
LAST_RESORT_SHELL = "/bin/sh"

# Always set for the child (FR-2). Inheriting TERM from whatever terminal launched
# us would advertise the wrong capabilities, so these are not taken from the parent.
TERM_VALUE = "xterm-256color"
COLORTERM_VALUE = "truecolor"


def _is_executable_file(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def resolve_shell(configured: str = "", env: Mapping[str, str] | None = None) -> str:
    """Pick the shell: config, then $SHELL, then /bin/zsh, then /bin/bash."""
    env = os.environ if env is None else env
    for candidate in (configured, env.get("SHELL", ""), *FALLBACK_SHELLS):
        if candidate and _is_executable_file(candidate):
            return candidate
    return LAST_RESORT_SHELL


def build_environment(base: Mapping[str, str] | None = None) -> list[str]:
    """Environment for the child as ``KEY=VALUE`` strings, as VTE expects."""
    env = dict(os.environ if base is None else base)
    env["TERM"] = TERM_VALUE
    env["COLORTERM"] = COLORTERM_VALUE
    return [f"{key}={value}" for key, value in env.items()]


def local_hostnames() -> set[str]:
    """Names this machine may report in an OSC 7 URI (the zsh snippet sends ``$HOST``)."""
    full = socket.gethostname().lower()
    return {"localhost", full, full.split(".")[0]}


def cwd_from_uri(uri: str | None, hostnames: Iterable[str] | None = None) -> str | None:
    """Local directory from a ``current-directory-uri`` value (OSC 7), or None.

    A URI naming another host is ignored: inside ``ssh``, the remote shell reports
    its own path, which must not be used as a local working directory.
    """
    if not uri:
        return None
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    host = (parsed.hostname or "").lower()
    names = hostnames if hostnames is not None else local_hostnames()
    allowed = {name.lower() for name in names} | {"localhost"}
    if host and host not in allowed:
        return None
    return unquote(parsed.path) or None


def read_proc_cwd(pid: int | None) -> str | None:
    """Fallback when OSC 7 is not available: the shell's cwd from ``/proc`` (FR-9)."""
    if pid is None:
        return None
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return None


def resolve_working_directory(preferred: str | None, home: str | None = None) -> str:
    """Return ``preferred`` if it is still an existing directory, else $HOME.

    Always verifies existence: a pane's cwd may have been deleted since it was recorded.
    """
    if preferred and os.path.isdir(preferred):
        return preferred
    return home or str(Path.home())
