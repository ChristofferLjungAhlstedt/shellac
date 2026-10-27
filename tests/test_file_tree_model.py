import copy
import os
import random
from pathlib import Path

import pytest

from shellac.file_tree_model import (
    INCREMENTAL_LIMIT,
    Entry,
    Node,
    TreeModel,
    describe_error,
    list_directory,
    nearest_existing_dir,
    sort_key,
)

ROOT = "/r"


class FakeFS:
    """A fake file system: nested dicts are directories, None is a file."""

    def __init__(self, tree: dict):
        self.tree = {ROOT: copy.deepcopy(tree)}
        self.errors: dict[str, BaseException] = {}

    def _dir(self, path: str):
        node = self.tree[ROOT]
        rel = os.path.relpath(path, ROOT)
        if rel != ".":
            for part in rel.split(os.sep):
                node = node[part]
        return node

    def list(self, path: str):
        if path in self.errors:
            return self.errors[path]
        try:
            directory = self._dir(path)
        except KeyError:
            return FileNotFoundError(path)
        return [
            Entry(name, os.path.join(path, name), isinstance(kind, dict))
            for name, kind in directory.items()
        ]

    def add(self, path: str, kind=None):
        parent = self._dir(os.path.dirname(path))
        parent[os.path.basename(path)] = {} if kind == "dir" else None

    def remove(self, path: str):
        del self._dir(os.path.dirname(path))[os.path.basename(path)]


class Recorder:
    """Listener that mirrors the row list from the splices it is told about."""

    def __init__(self, fs: FakeFS):
        self.fs = fs
        self.model: TreeModel
        self.requests: list[tuple[Node, int]] = []
        self.watched: set[str] = set()
        self.scrolled: list[Node] = []
        self.changed: list[Node] = []
        self.splices: list[tuple[int, int, int]] = []
        self.mirror: list[str] = []
        self.auto = False

    def rows_changed(self, position, removed, added):
        self.splices.append((position, removed, added))
        fresh = [n.path for n in self.model.visible[position : position + added]]
        self.mirror[position : position + removed] = fresh

    def node_changed(self, node):
        self.changed.append(node)

    def request_listing(self, node, token):
        if self.auto:
            self.model.apply_listing(node, self.fs.list(node.path), token)
        else:
            self.requests.append((node, token))

    def watch_changed(self, node, watched):
        (self.watched.add if watched else self.watched.discard)(node.path)

    def scroll_to(self, node):
        self.scrolled.append(node)

    def settle(self):
        while self.requests:
            node, token = self.requests.pop(0)
            self.model.apply_listing(node, self.fs.list(node.path), token)

    def check(self):
        assert self.mirror == [n.path for n in self.model.visible]


def build(tree: dict, *, auto=True, **kwargs):
    fs = FakeFS(tree)
    rec = Recorder(fs)
    rec.auto = auto
    model = TreeModel(rec, **kwargs)
    rec.model = model
    model.set_root(ROOT)
    return model, rec, fs


def names(model: TreeModel) -> list[str]:
    return [("  " * n.depth) + n.name for n in model.visible]


def node(model: TreeModel, path: str) -> Node:
    found = model.node_for_path(os.path.join(ROOT, path))
    assert found is not None, path
    return found


SAMPLE = {
    "src": {"app.py": None, "util": {"helpers.py": None}, "Zed.py": None},
    "docs": {"index.md": None},
    "README.md": None,
    "Makefile": None,
    ".git": {"HEAD": None},
    ".env": None,
    "beta.txt": None,
}


# -- sorting and loading ---------------------------------------------------------------


def test_sort_directories_first_then_case_insensitive():
    entries = [
        Entry("b.txt", "/b.txt", False),
        Entry("Zeta", "/Zeta", True),
        Entry("alpha", "/alpha", True),
        Entry("A.txt", "/A.txt", False),
    ]
    assert [e.name for e in sorted(entries, key=sort_key)] == ["alpha", "Zeta", "A.txt", "b.txt"]


def test_equal_names_ignoring_case_are_ordered_deterministically():
    a, b = Entry("readme", "/readme", False), Entry("README", "/README", False)
    assert sorted([a, b], key=sort_key) == sorted([b, a], key=sort_key)


def test_set_root_lists_only_the_root_and_hides_dotfiles():
    model, rec, _ = build(SAMPLE, auto=False)
    assert rec.watched == {ROOT}
    assert [n.path for n, _ in rec.requests] == [ROOT]
    rec.settle()
    assert names(model) == ["docs", "src", "beta.txt", "Makefile", "README.md"]
    assert [n.path for n, _ in rec.requests] == []  # subdirectories are not scanned
    rec.check()


def test_hidden_toggle_shows_dotfiles_in_order():
    model, rec, _ = build(SAMPLE)
    model.set_show_hidden(True)
    assert names(model) == [".git", "docs", "src", ".env", "beta.txt", "Makefile", "README.md"]
    rec.check()
    model.set_show_hidden(False)
    assert ".git" not in names(model)
    rec.check()


def test_expand_is_lazy_and_loads_once_per_expand():
    model, rec, _ = build(SAMPLE, auto=False)
    rec.settle()
    src = node(model, "src")
    assert src.children is None
    model.expand(src)
    assert [n.path for n, _ in rec.requests] == [f"{ROOT}/src"]
    assert rec.watched == {ROOT, f"{ROOT}/src"}
    rec.settle()
    assert names(model)[:5] == ["docs", "src", "  util", "  app.py", "  Zed.py"]
    rec.check()


def test_collapse_removes_rows_and_releases_watchers_including_nested():
    model, rec, _ = build(SAMPLE)
    model.expand(node(model, "src"))
    model.expand(node(model, "src/util"))
    assert rec.watched == {ROOT, f"{ROOT}/src", f"{ROOT}/src/util"}
    model.collapse(node(model, "src"))
    assert rec.watched == {ROOT}
    assert "helpers.py" not in " ".join(names(model))
    rec.check()


def test_reexpanding_restores_nested_state_and_relists_it():
    model, rec, fs = build(SAMPLE)
    model.expand(node(model, "src"))
    model.expand(node(model, "src/util"))
    model.collapse(node(model, "src"))
    fs.add(f"{ROOT}/src/util/new.py")  # changes while hidden are not watched
    model.expand(node(model, "src"))
    assert names(model)[:7] == [
        "docs",
        "src",
        "  util",
        "    helpers.py",
        "    new.py",
        "  app.py",
        "  Zed.py",
    ]
    assert f"{ROOT}/src/util" in rec.watched
    rec.check()


# -- live updates ----------------------------------------------------------------------


def test_new_file_is_inserted_at_its_sorted_position_with_one_splice():
    model, rec, fs = build(SAMPLE)
    rec.splices.clear()
    fs.add(f"{ROOT}/c.txt")
    model.refresh()
    rec.settle()
    assert names(model) == ["docs", "src", "beta.txt", "c.txt", "Makefile", "README.md"]
    assert rec.splices == [(3, 0, 1)]
    rec.check()


def test_removed_directory_takes_its_expanded_rows_and_watchers_with_it():
    model, rec, fs = build(SAMPLE)
    model.expand(node(model, "src"))
    model.expand(node(model, "src/util"))
    src = node(model, "src")
    rec.splices.clear()
    fs.remove(f"{ROOT}/src")
    model.refresh()
    assert not src.alive
    assert names(model) == ["docs", "beta.txt", "Makefile", "README.md"]
    assert rec.splices == [(1, 5, 0)]
    assert rec.watched == {ROOT}
    rec.check()


def test_rename_is_a_removal_plus_an_insertion():
    model, rec, fs = build(SAMPLE)
    fs.remove(f"{ROOT}/beta.txt")
    fs.add(f"{ROOT}/zzz.txt")
    model.refresh()
    assert names(model) == ["docs", "src", "Makefile", "README.md", "zzz.txt"]
    rec.check()


def test_unchanged_nodes_keep_identity_and_expanded_state():
    model, _, fs = build(SAMPLE)
    model.expand(node(model, "src"))
    src = node(model, "src")
    fs.add(f"{ROOT}/other.txt")
    model.refresh()
    assert node(model, "src") is src
    assert src.expanded
    assert node(model, "src/app.py").alive


def test_file_replaced_by_directory_of_same_name_is_swapped():
    model, rec, fs = build({"thing": None, "z": None})
    fs.remove(f"{ROOT}/thing")
    fs.add(f"{ROOT}/thing", "dir")
    model.refresh()
    assert node(model, "thing").is_dir
    assert names(model) == ["thing", "z"]
    rec.check()


def test_stale_listing_answers_are_ignored():
    model, rec, fs = build(SAMPLE, auto=False)
    rec.settle()
    model.refresh()
    model.refresh()
    first, second = rec.requests
    fs.add(f"{ROOT}/late.txt")
    model.apply_listing(first[0], [], first[1])  # old answer, would empty the tree
    assert model.visible
    model.apply_listing(second[0], fs.list(ROOT), second[1])
    assert "late.txt" in names(model)


def test_large_change_replaces_the_block_in_a_single_splice():
    model, rec, fs = build({"d": {}, "f": None})
    for i in range(INCREMENTAL_LIMIT + 10):
        fs.add(f"{ROOT}/file{i:03}.txt")
    rec.splices.clear()
    model.refresh()
    assert len(rec.splices) == 1
    assert len(model.visible) == INCREMENTAL_LIMIT + 10 + 2
    rec.check()


def test_listing_error_marks_the_node_and_clears_children():
    model, rec, fs = build(SAMPLE)
    model.expand(node(model, "docs"))
    docs = node(model, "docs")
    fs.errors[f"{ROOT}/docs"] = PermissionError(13, "Permission denied")
    model.refresh(docs)
    assert docs.error == "Permission denied"
    assert docs.children == []
    assert "index.md" not in " ".join(names(model))
    del fs.errors[f"{ROOT}/docs"]
    model.refresh(docs)
    assert docs.error is None
    assert "index.md" in " ".join(names(model))
    rec.check()


def test_disappearing_directory_reports_not_found():
    model, _, fs = build(SAMPLE)
    model.expand(node(model, "docs"))
    docs = node(model, "docs")
    del fs.tree[ROOT]["docs"]
    model.refresh(docs)
    assert docs.error == "No longer exists"


def test_changes_in_a_collapsed_directory_do_not_touch_rows():
    model, rec, fs = build(SAMPLE)
    model.expand(node(model, "src"))
    model.collapse(node(model, "src"))
    rec.splices.clear()
    model.refresh(node(model, "src"))  # not expanded: nothing happens
    assert rec.splices == []


# -- reveal ----------------------------------------------------------------------------


def test_reveal_expands_ancestors_as_listings_arrive():
    model, rec, _ = build(SAMPLE, auto=False)
    rec.settle()
    assert model.reveal(f"{ROOT}/src/util/helpers.py")
    rec.settle()
    assert [n.path for n in rec.scrolled] == [f"{ROOT}/src/util/helpers.py"]
    assert "    helpers.py" in names(model)
    rec.check()


def test_reveal_works_while_the_root_is_still_loading():
    model, rec, _ = build(SAMPLE, auto=False)
    assert model.reveal(f"{ROOT}/src")
    rec.settle()
    assert [n.name for n in rec.scrolled] == ["src"]


def test_reveal_outside_the_root_is_refused():
    model, rec, _ = build(SAMPLE)
    assert not model.reveal("/elsewhere/x")
    assert not model.reveal("/rr/x")  # a sibling that merely shares a prefix
    assert model.contains(f"{ROOT}/src")
    assert model.contains(ROOT)


def test_reveal_of_a_missing_path_gives_up_quietly():
    model, rec, _ = build(SAMPLE)
    assert model.reveal(f"{ROOT}/src/nope/deeper")
    assert rec.scrolled == []


def test_reveal_with_synchronous_listener_scrolls_exactly_once():
    model, rec, _ = build(SAMPLE, auto=True)
    model.reveal(f"{ROOT}/src/util/helpers.py")
    assert len(rec.scrolled) == 1


# -- filter ----------------------------------------------------------------------------


def test_filter_shows_matches_and_their_parents_only():
    model, rec, _ = build(SAMPLE)
    model.expand(node(model, "src"))
    model.expand(node(model, "src/util"))
    model.set_filter("help")
    assert names(model) == ["src", "  util", "    helpers.py"]
    rec.check()
    model.set_filter("")
    assert "docs" in names(model)
    rec.check()


def test_filter_is_case_insensitive_and_does_not_scan_the_disk():
    model, rec, _ = build(SAMPLE, auto=False)
    rec.settle()
    rec.requests.clear()
    model.set_filter("READ")
    assert names(model) == ["README.md"]
    assert rec.requests == []


def test_filter_survives_live_updates():
    model, rec, fs = build(SAMPLE)
    model.set_filter("txt")
    fs.add(f"{ROOT}/new.txt")
    model.refresh()
    assert names(model) == ["beta.txt", "new.txt"]
    rec.check()


# -- roots, loops, helpers --------------------------------------------------------------


def test_set_root_releases_everything_and_ignores_late_answers():
    model, rec, _ = build(SAMPLE, auto=False)
    rec.settle()
    model.expand(node(model, "src"))
    old_root, old_src = model.root, node(model, "src")
    late = list(rec.requests)
    model.set_root(f"{ROOT}/docs")
    rec.check()
    assert model.visible == []
    assert rec.watched == {f"{ROOT}/docs"}
    assert not old_root.alive and not old_src.alive
    for stale_node, token in late:
        model.apply_listing(stale_node, [Entry("ghost", "/ghost", False)], token)
    assert model.visible == []


def test_symlink_loop_is_detected_instead_of_expanding_forever(tmp_path: Path):
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "loop").symlink_to(tmp_path / "real")
    fs = FakeFS({})
    rec = Recorder(fs)
    model = TreeModel(rec)
    rec.model = model
    model.set_root(str(tmp_path))
    model.apply_listing(model.root, list_directory(str(tmp_path)), model.root.token)
    real = model.visible[0]
    model.expand(real)
    model.apply_listing(real, list_directory(real.path), real.token)
    loop = real.children[0]
    assert loop.entry.is_symlink and loop.is_dir
    model.expand(loop)
    assert not loop.expanded
    assert loop.error == "Symbolic link loop"


def test_symlink_to_directory_elsewhere_expands_normally(tmp_path: Path):
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "f.txt").write_text("x")
    (tmp_path / "link").symlink_to(tmp_path / "target")
    entries = {e.name: e for e in list_directory(str(tmp_path))}
    assert entries["link"].is_dir and entries["link"].is_symlink and not entries["link"].broken


def test_list_directory_real_files(tmp_path: Path):
    (tmp_path / "b.txt").write_text("")
    (tmp_path / "A").mkdir()
    (tmp_path / "broken").symlink_to(tmp_path / "missing")
    listing = list_directory(str(tmp_path))
    assert [e.name for e in listing] == ["A", "b.txt", "broken"]
    assert listing[2].is_symlink and listing[2].broken and not listing[2].is_dir
    assert listing[0].is_dir


def test_list_directory_propagates_errors_for_the_directory_itself(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        list_directory(str(tmp_path / "gone"))


def test_describe_error():
    assert describe_error(PermissionError(13, "x")) == "Permission denied"
    assert describe_error(FileNotFoundError()) == "No longer exists"
    assert describe_error(OSError(5, "Input/output error")) == "Input/output error"


def test_nearest_existing_dir(tmp_path: Path):
    deep = tmp_path / "a" / "b"
    assert nearest_existing_dir(str(deep)) == str(tmp_path)
    (tmp_path / "a").mkdir()
    assert nearest_existing_dir(str(deep)) == str(tmp_path / "a")
    assert nearest_existing_dir(str(tmp_path)) == str(tmp_path)


def test_very_long_and_unusual_names_are_just_names():
    long_name = "x" * 250 + ".txt"
    model, rec, _ = build({long_name: None, "näme ü.txt": None, "with space": {}})
    assert long_name in [n.name for n in model.visible]
    rec.check()


# -- randomized consistency ------------------------------------------------------------


@pytest.mark.parametrize("seed", range(6))
def test_random_operations_keep_rows_consistent(seed: int):
    rng = random.Random(seed)
    tree = {
        "a": {"a1": None, "a2": {"deep": None, ".hid": None}},
        "b": {},
        ".dot": {"x": None},
        "f1": None,
        "F2": None,
    }
    model, rec, fs = build(tree)
    counter = 0

    def all_nodes():
        stack = list(model.root.children or [])
        found = []
        while stack:
            n = stack.pop()
            found.append(n)
            stack.extend(n.children or [])
        return [n for n in found if n.alive]

    def all_dirs():
        return [Path(p) for p in _fs_dirs(fs)]

    for _ in range(300):
        action = rng.choice(
            [
                "expand",
                "expand",
                "collapse",
                "add_file",
                "add_dir",
                "remove",
                "hidden",
                "filter",
                "refresh",
            ]
        )
        nodes = [n for n in all_nodes() if n.is_dir]
        if action == "expand" and nodes:
            model.expand(rng.choice(nodes))
        elif action == "collapse" and nodes:
            model.collapse(rng.choice(nodes))
        elif action in ("add_file", "add_dir"):
            dirs = [str(p) for p in all_dirs()]
            counter += 1
            name = rng.choice(["m", "N", ".h", "z", "A"]) + str(counter)
            fs.add(os.path.join(rng.choice(dirs), name), "dir" if action == "add_dir" else None)
            model.refresh_all()
        elif action == "remove":
            paths = [p for p in _fs_paths(fs) if p != ROOT]
            if paths:
                fs.remove(rng.choice(paths))
                model.refresh_all()
        elif action == "hidden":
            model.set_show_hidden(not model.show_hidden)
        elif action == "filter":
            model.set_filter(rng.choice(["", "", "1", "a", "z"]))
        else:
            model.refresh_all()

        rec.check()
        assert model.visible == model._flatten_children(model.root), action
        assert rec.watched == {n.path for n in model._watched}


def _fs_paths(fs: FakeFS):
    paths = []

    def walk(path, directory):
        for name, kind in directory.items():
            child = os.path.join(path, name)
            paths.append(child)
            if isinstance(kind, dict):
                walk(child, kind)

    walk(ROOT, fs.tree[ROOT])
    return paths


def _fs_dirs(fs: FakeFS):
    dirs = [ROOT]
    for path in _fs_paths(fs):
        try:
            if isinstance(fs._dir(path), dict):
                dirs.append(path)
        except KeyError:
            pass
    return dirs
