"""Git status and ignore information for the sidebar (FR-29, FR-30).

GTK-free so parsing and lookups are unit tested. ``load_git_info`` runs ``git`` and
blocks, so the sidebar calls it from a worker thread, never from the main loop (NFR-1).

One ``git status --porcelain=v1 -z --ignored=traditional`` call yields everything:
changed files, untracked entries and ignored entries. ``traditional`` and the default
untracked mode report a wholly untracked or ignored directory as one entry, so a huge
``node_modules`` costs one line, not one per file.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

GIT_TIMEOUT_SECONDS = 20

# Status codes, in the order a directory shows the most important one of its contents.
CONFLICTED = "conflicted"
MODIFIED = "modified"
DELETED = "deleted"
ADDED = "added"
UNTRACKED = "untracked"
PRECEDENCE = (CONFLICTED, MODIFIED, DELETED, ADDED, UNTRACKED)

MARKERS = {
    CONFLICTED: "!",
    MODIFIED: "M",
    DELETED: "D",
    ADDED: "A",
    UNTRACKED: "?",
}

_CONFLICT_CODES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}


@dataclass
class GitInfo:
    root: str  # absolute path of the repository's top level
    status: dict[str, str] = field(default_factory=dict)  # path -> status, dirs included
    ignored: set[str] = field(default_factory=set)  # ignored files and directories
    untracked_dirs: set[str] = field(default_factory=set)  # wholly untracked directories

    def status_of(self, path: str) -> str | None:
        """Status of ``path``: its own, a parent directory's that is wholly untracked, or None."""
        found = self.status.get(path)
        if found is not None:
            return found
        parent = os.path.dirname(path)
        while len(parent) > len(self.root) and parent != os.path.dirname(parent):
            if parent in self.untracked_dirs:
                return UNTRACKED
            parent = os.path.dirname(parent)
        return None

    def is_ignored(self, path: str) -> bool:
        """Is ``path`` ignored, or inside an ignored directory?"""
        current = path
        while len(current) >= len(self.root):
            if current in self.ignored:
                return True
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        return False


def classify(code: str) -> str | None:
    """Map a two-letter porcelain code like ``" M"`` or ``"A "`` to a status."""
    if code in _CONFLICT_CODES:
        return CONFLICTED
    if code == "??":
        return UNTRACKED
    index, tree = code[0], code[1]
    if "D" in (index, tree):
        return DELETED
    if "M" in (index, tree) or index in "RCT" or tree in "RCT":
        return MODIFIED
    if index == "A":
        return ADDED
    return None


def _stronger(first: str | None, second: str) -> str:
    if first is None:
        return second
    return first if PRECEDENCE.index(first) <= PRECEDENCE.index(second) else second


def parse_status(output: bytes, root: str) -> GitInfo:
    """Parse ``git status --porcelain=v1 -z --ignored`` output for the repo at ``root``."""
    info = GitInfo(root=root)
    entries = output.decode("utf-8", errors="surrogateescape").split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        code, relative = entry[:2], entry[3:]
        if code[0] in "RC" or code[1] in "RC":
            index += 1  # a rename or copy lists its source path next
        directory = relative.endswith("/")
        path = os.path.normpath(os.path.join(root, relative))
        if code == "!!":
            info.ignored.add(path)
            continue
        status = classify(code)
        if status is None:
            continue
        info.status[path] = _stronger(info.status.get(path), status)
        if directory and status == UNTRACKED:
            info.untracked_dirs.add(path)
        # A directory shows the most important status of anything below it. A deleted
        # file is gone from the tree, so its directory is simply "modified".
        shown = MODIFIED if status == DELETED else status
        parent = os.path.dirname(path)
        while len(parent) >= len(root) and parent != os.path.dirname(parent):
            info.status[parent] = _stronger(info.status.get(parent), shown)
            if parent == root:
                break
            parent = os.path.dirname(parent)
    return info


def _git(directory: str, *args: str) -> bytes | None:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", LC_ALL="C")  # never take the index lock
    try:
        done = subprocess.run(
            ["git", "-C", directory, *args],
            capture_output=True,
            env=env,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("git %s failed in %s: %s", args, directory, exc)
        return None
    return done.stdout if done.returncode == 0 else None


def repository_root(directory: str) -> str | None:
    output = _git(directory, "rev-parse", "--show-toplevel")
    if not output:
        return None
    return os.path.normpath(output.decode("utf-8", errors="surrogateescape").strip())


def load_git_info(directory: str) -> GitInfo | None:
    """Status of the repository containing ``directory``, or None if there is none.

    Blocking: run it on a worker thread.
    """
    root = repository_root(directory)
    if root is None:
        return None
    output = _git(
        root, "status", "--porcelain=v1", "-z", "--ignored=traditional", "--untracked-files=normal"
    )
    if output is None:
        return None
    return parse_status(output, root)
