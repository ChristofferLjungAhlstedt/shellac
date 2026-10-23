"""Model for the file tree sidebar (FR-25..FR-28, section 8.4).

GTK-free so the tricky parts (lazy loading, live-update diffing, keeping the flattened
row list consistent, revealing a path) are unit tested without a display.

The model owns the tree of ``Node`` objects and ``visible``, the flat list of rows that
are currently shown, in order. It never touches the file system on its own: listing a
directory and watching it are delegated to a ``Listener``, which answers asynchronously
by calling ``apply_listing``. That keeps scanning off the UI thread (NFR-1).
"""

from __future__ import annotations

import bisect
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

# Up to this many added/removed entries are spliced in one by one; a bigger change is
# replaced as one block so the view does a single update.
INCREMENTAL_LIMIT = 50


@dataclass
class Entry:
    name: str
    path: str
    is_dir: bool
    is_symlink: bool = False
    broken: bool = False

    @property
    def is_hidden(self) -> bool:
        return self.name.startswith(".")

    @property
    def kind(self) -> tuple[bool, bool, bool]:
        return (self.is_dir, self.is_symlink, self.broken)


def sort_key(entry: Entry) -> tuple[bool, str, str]:
    """Directories first, then files, each case-insensitive alphabetical (FR-28)."""
    return (not entry.is_dir, entry.name.casefold(), entry.name)


def list_directory(path: str) -> list[Entry]:
    """Read one directory, sorted. Blocking: call it from a worker thread.

    Raises ``OSError`` if the directory itself cannot be read. A problem with a single
    entry never fails the whole listing.
    """
    entries: list[Entry] = []
    with os.scandir(path) as scan:
        for item in scan:
            try:
                is_symlink = item.is_symlink()
            except OSError:
                is_symlink = False
            try:
                is_dir = item.is_dir()
            except OSError:
                is_dir = False
            broken = is_symlink and not is_dir and not os.path.exists(item.path)
            entries.append(Entry(item.name, item.path, is_dir, is_symlink, broken))
    entries.sort(key=sort_key)
    return entries


def describe_error(error: BaseException) -> str:
    if isinstance(error, PermissionError):
        return "Permission denied"
    if isinstance(error, FileNotFoundError):
        return "No longer exists"
    if isinstance(error, NotADirectoryError):
        return "Not a directory"
    if isinstance(error, OSError):
        return error.strerror or str(error)
    return str(error)


def nearest_existing_dir(path: str) -> str:
    """The closest ancestor of ``path`` (or ``path`` itself) that is a directory."""
    current = os.path.normpath(path)
    while not os.path.isdir(current):
        parent = os.path.dirname(current)
        if parent == current:
            return current
        current = parent
    return current


class Node:
    """One file or directory. Plain Python object; ``ui`` is free for the GTK adapter."""

    __slots__ = (
        "alive",
        "children",
        "depth",
        "entry",
        "error",
        "expanded",
        "loading",
        "parent",
        "stale",
        "token",
        "ui",
        "watched",
    )

    def __init__(self, entry: Entry, parent: Node | None) -> None:
        self.entry = entry
        self.parent = parent
        self.depth = parent.depth + 1 if parent is not None else 0
        self.children: list[Node] | None = None  # None: not loaded yet
        self.expanded = False
        self.loading = False
        self.error: str | None = None
        self.alive = True
        self.token = 0
        self.watched = False
        self.stale = False  # changed while unwatched: re-list when watched again
        self.ui: Any = None

    @property
    def path(self) -> str:
        return self.entry.path

    @property
    def name(self) -> str:
        return self.entry.name

    @property
    def is_dir(self) -> bool:
        return self.entry.is_dir


class Listener(Protocol):
    """What the model needs from its owner (the GTK adapter, or a fake in tests)."""

    def rows_changed(self, position: int, removed: int, added: int) -> None:
        """``visible`` changed: ``removed`` rows at ``position`` became ``added`` rows."""

    def node_changed(self, node: Node) -> None:
        """A visible row's own state changed (expanded, error, ...); redraw it."""

    def request_listing(self, node: Node, token: int) -> None:
        """Start listing ``node`` and later call ``model.apply_listing(node, result, token)``."""

    def watch_changed(self, node: Node, watched: bool) -> None:
        """Start or stop watching ``node``'s directory for changes."""

    def scroll_to(self, node: Node) -> None:
        """Reveal, select and scroll to ``node``."""


class TreeModel:
    def __init__(self, listener: Listener, *, show_hidden: bool = False) -> None:
        self.listener = listener
        self.show_hidden = show_hidden
        self.filter_text = ""
        # Dotfile names shown even while hidden files are hidden (``.gitignore`` is a project
        # file, not clutter).
        self.always_shown: frozenset[str] = frozenset()
        # Optional extra rule that hides a node (the sidebar uses it for ignored files).
        self.hidden_by: Callable[[Node], bool] | None = None
        self.root: Node | None = None
        self.visible: list[Node] = []
        self._watched: set[Node] = set()
        self._reveal_path: str | None = None

    # ----- root -----

    def set_root(self, path: str) -> None:
        """Make ``path`` the root, dropping the previous tree and its watchers."""
        self._reveal_path = None
        self._teardown()
        previous = len(self.visible)
        self.visible = []
        if previous:
            self.listener.rows_changed(0, previous, 0)
        path = os.path.normpath(path)
        root = Node(Entry(os.path.basename(path) or path, path, True), None)
        root.depth = -1  # the root itself is not a row; its children are at depth 0
        root.expanded = True
        self.root = root
        self._set_watch(root, True)
        self._request(root)

    def _teardown(self) -> None:
        for node in list(self._watched):
            self._set_watch(node, False)
        if self.root is not None:
            stack = [self.root]
            while stack:
                current = stack.pop()
                current.alive = False
                stack.extend(current.children or ())
        self.root = None

    # ----- expanding and collapsing -----

    def expand(self, node: Node) -> None:
        if not node.alive or not node.entry.is_dir or node.expanded:
            return
        if self._is_loop(node):
            node.error = "Symbolic link loop"
            self.listener.node_changed(node)
            return
        node.expanded = True
        index = self.index_of(node)
        if self.filter_text:
            self._rebuild()
        elif index is not None and node.children:
            rows = self._flatten_children(node)
            self.visible[index + 1 : index + 1] = rows
            self._notify(index + 1, 0, len(rows))
        self.listener.node_changed(node)
        self._activate(node)
        self._request(node)

    def collapse(self, node: Node) -> None:
        if not node.alive or not node.expanded:
            return
        index = self.index_of(node)
        node.expanded = False
        if self.filter_text:
            self._rebuild()
        elif index is not None:
            count = self._block_len(index) - 1
            del self.visible[index + 1 : index + 1 + count]
            self._notify(index + 1, count, 0)
        self._deactivate(node)
        self.listener.node_changed(node)

    def toggle(self, node: Node) -> None:
        if node.expanded:
            self.collapse(node)
        else:
            self.expand(node)

    def _is_loop(self, node: Node) -> bool:
        """A symlink pointing back at one of its own ancestors would expand forever."""
        if not node.entry.is_symlink:
            return False
        target = os.path.realpath(node.path)
        ancestor = node.parent
        while ancestor is not None:
            if os.path.realpath(ancestor.path) == target:
                return True
            ancestor = ancestor.parent
        return False

    # ----- watching (FR-27: only expanded directories are watched) -----

    def _activate(self, node: Node) -> None:
        """Watch ``node`` and any nested directory that is expanded."""
        self._set_watch(node, True)
        for child in node.children or ():
            if not child.expanded:
                continue
            if child.stale:
                child.stale = False
                self._request(child)
            self._activate(child)

    def _deactivate(self, node: Node) -> None:
        """Stop watching ``node`` and everything expanded below it (FR-27)."""
        self._set_watch(node, False)
        node.stale = True
        for child in node.children or ():
            if child.expanded:
                self._deactivate(child)

    def _set_watch(self, node: Node, watched: bool) -> None:
        if node.watched == watched:
            return
        node.watched = watched
        if watched:
            self._watched.add(node)
        else:
            self._watched.discard(node)
        self.listener.watch_changed(node, watched)

    # ----- listing -----

    def refresh(self, node: Node | None = None) -> None:
        """Re-list ``node`` (default: the root), e.g. after a file system event."""
        node = node or self.root
        if node is not None and node.alive and node.expanded:
            self._request(node)

    def refresh_all(self) -> None:
        for node in list(self._watched):
            self.refresh(node)

    def _request(self, node: Node) -> None:
        node.token += 1  # answers to earlier requests for this node are now stale
        node.loading = True
        self.listener.request_listing(node, node.token)

    def apply_listing(self, node: Node, result: list[Entry] | BaseException, token: int) -> None:
        """Deliver the answer to a ``request_listing``. Stale answers are ignored."""
        if not node.alive or token != node.token:
            return
        node.loading = False
        if isinstance(result, BaseException):
            self._merge(node, [])
            node.error = describe_error(result)
            self.listener.node_changed(node)
        else:
            if node.error is not None:
                node.error = None
                self.listener.node_changed(node)
            self._merge(node, sorted(result, key=sort_key))
        self._continue_reveal()

    def _merge(self, node: Node, entries: list[Entry]) -> None:
        """Make ``node.children`` match ``entries``, keeping unchanged nodes as they are."""
        old = node.children or []
        old_by_name = {child.name: child for child in old}
        new_by_name = {entry.name: entry for entry in entries}

        # A name that vanished, or whose kind changed (file -> directory), is a removal
        # plus an insertion; everything else keeps its Node (and so its expanded state).
        removed = [
            child
            for child in old
            if child.name not in new_by_name or new_by_name[child.name].kind != child.entry.kind
        ]
        added = [
            entry
            for entry in entries
            if entry.name not in old_by_name or old_by_name[entry.name].entry.kind != entry.kind
        ]

        first_load = node.children is None
        for child in old:
            if child in removed:
                continue
            child.entry = new_by_name[child.name]

        displayed = node is self.root or (node.expanded and self.index_of(node) is not None)

        small = len(removed) + len(added) <= INCREMENTAL_LIMIT
        if displayed and not first_load and not self.filter_text and small:
            node.children = old
            self._merge_incrementally(node, removed, added)
            return

        removed_set = set(removed)
        kept = {child.name: child for child in old if child not in removed_set}
        node.children = [kept.get(e.name) or Node(e, node) for e in entries]
        for child in removed:
            self._drop(child)
        if self.filter_text:
            self._rebuild()
        elif displayed:
            self._replace_block(node)

    def _merge_incrementally(self, node: Node, removed: list[Node], added: list[Entry]) -> None:
        assert node.children is not None
        for child in removed:
            index = self.index_of(child)
            if index is not None:
                count = self._block_len(index)
                del self.visible[index : index + count]
                self._notify(index, count, 0)
            self._drop(child)
            node.children.remove(child)
        keys = [sort_key(child.entry) for child in node.children]
        for entry in added:
            position = bisect.bisect_left(keys, sort_key(entry))
            child = Node(entry, node)
            node.children.insert(position, child)
            keys.insert(position, sort_key(entry))
            if not self._shown(child):
                continue
            at = self._insert_index(node, position)
            self.visible.insert(at, child)
            self._notify(at, 0, 1)

    def _insert_index(self, parent: Node, position: int) -> int:
        """Where in ``visible`` the child at ``position`` of ``parent`` belongs."""
        assert parent.children is not None
        for sibling in reversed(parent.children[:position]):
            if not self._shown(sibling):
                continue
            index = self.index_of(sibling)
            if index is None:
                continue
            return index + self._block_len(index)
        if parent is self.root:
            return 0
        index = self.index_of(parent)
        if index is None:
            return 0
        return index + 1

    def _replace_block(self, node: Node) -> None:
        """Re-flatten everything below ``node`` in one splice."""
        if node is self.root:
            start, count = 0, len(self.visible)
        else:
            index = self.index_of(node)
            if index is None:
                return
            start, count = index + 1, self._block_len(index) - 1
        rows = self._flatten_children(node)
        self.visible[start : start + count] = rows
        self._notify(start, count, len(rows))

    def _drop(self, node: Node) -> None:
        """Remove a subtree from the model: stop its watchers and mark it dead."""
        stack = [node]
        while stack:
            current = stack.pop()
            current.alive = False
            self._set_watch(current, False)
            stack.extend(current.children or ())

    # ----- view options -----

    def set_show_hidden(self, show: bool) -> None:
        if show != self.show_hidden:
            self.show_hidden = show
            self._rebuild()

    def set_filter(self, text: str) -> None:
        """Show only entries whose name contains ``text`` (and their parents) (FR-34).

        Applies to directories that are already loaded: filtering never scans the disk.
        """
        if text != self.filter_text:
            self.filter_text = text
            self._rebuild()

    def refilter(self) -> None:
        """Re-evaluate which rows are shown after ``hidden_by`` would answer differently."""
        self._rebuild()

    def _shown(self, node: Node) -> bool:
        entry = node.entry
        if not (self.show_hidden or not entry.is_hidden or entry.name in self.always_shown):
            return False
        return self.hidden_by is None or not self.hidden_by(node)

    def _matches(self, node: Node) -> bool:
        return self.filter_text.casefold() in node.entry.name.casefold()

    def _flatten_children(self, parent: Node) -> list[Node]:
        if self.filter_text:
            return self._flatten_filtered(parent)
        rows: list[Node] = []
        self._flatten_into(parent, rows)
        return rows

    def _flatten_into(self, parent: Node, rows: list[Node]) -> None:
        for child in parent.children or ():
            if not self._shown(child):
                continue
            rows.append(child)
            if not child.expanded or not child.children:
                continue
            self._flatten_into(child, rows)

    def _flatten_filtered(self, parent: Node) -> list[Node]:
        rows: list[Node] = []
        for child in parent.children or ():
            if not self._shown(child):
                continue
            below = self._flatten_filtered(child) if child.children else []
            if not self._matches(child) and not below:
                continue
            rows.append(child)
            rows.extend(below)
        return rows

    def _rebuild(self) -> None:
        previous = len(self.visible)
        self.visible = self._flatten_children(self.root) if self.root is not None else []
        self._notify(0, previous, len(self.visible))

    def _notify(self, position: int, removed: int, added: int) -> None:
        if removed or added:
            self.listener.rows_changed(position, removed, added)

    # ----- lookup -----

    def index_of(self, node: Node) -> int | None:
        try:
            return self.visible.index(node)
        except ValueError:
            return None

    def _block_len(self, index: int) -> int:
        """Rows taken by the node at ``index`` plus everything shown below it."""
        depth = self.visible[index].depth
        end = index + 1
        while end < len(self.visible) and self.visible[end].depth > depth:
            end += 1
        return end - index

    def node_for_path(self, path: str) -> Node | None:
        """The loaded node for ``path``, if it has been loaded."""
        if self.root is None:
            return None
        path = os.path.normpath(path)
        if path == self.root.path:
            return self.root
        relative = os.path.relpath(path, self.root.path)
        if relative.startswith(".."):
            return None
        node: Node | None = self.root
        for part in relative.split(os.sep):
            node = next((c for c in node.children or () if c.name == part), None)
            if node is None:
                return None
        return node

    def contains(self, path: str) -> bool:
        """Is ``path`` the root or somewhere below it?"""
        if self.root is None:
            return False
        relative = os.path.relpath(os.path.normpath(path), self.root.path)
        return relative != ".." and not relative.startswith(".." + os.sep)

    # ----- reveal -----

    def reveal(self, path: str) -> bool:
        """Expand every directory down to ``path`` and ask the listener to scroll to it.

        Directories load asynchronously, so this continues as listings arrive. Returns
        False if ``path`` is outside the tree.
        """
        if not self.contains(path):
            return False
        self._reveal_path = os.path.normpath(path)
        self._continue_reveal()
        return True

    def _continue_reveal(self) -> None:
        if self._reveal_path is None or self.root is None:
            return
        relative = os.path.relpath(self._reveal_path, self.root.path)
        if relative == ".":
            self._reveal_path = None
            return
        node = self.root
        parts = relative.split(os.sep)
        for number, part in enumerate(parts, start=1):
            if self._reveal_path is None:
                return
            if node.children is None:
                return  # still loading; apply_listing calls us again
            child = next((c for c in node.children if c.name == part), None)
            if child is None or (number < len(parts) and not child.entry.is_dir):
                self._reveal_path = None  # gone, or not reachable: give up quietly
                return
            if number == len(parts):
                self._reveal_path = None
                self.listener.scroll_to(child)
                return
            if not child.expanded:
                self.expand(child)
                if child.children is None:
                    return
            node = child
