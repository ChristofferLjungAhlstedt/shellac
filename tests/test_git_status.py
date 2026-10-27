import shutil
import subprocess
from pathlib import Path

import pytest

from shellac.git_status import (
    ADDED,
    CONFLICTED,
    DELETED,
    MODIFIED,
    UNTRACKED,
    classify,
    load_git_info,
    parse_status,
)

ROOT = "/repo"


def parse(*entries: str):
    return parse_status("\0".join(entries).encode() + b"\0", ROOT)


def test_classify():
    assert classify(" M") == MODIFIED
    assert classify("M ") == MODIFIED
    assert classify("MM") == MODIFIED
    assert classify("A ") == ADDED
    assert classify("AM") == MODIFIED
    assert classify(" D") == DELETED
    assert classify("D ") == DELETED
    assert classify("R ") == MODIFIED
    assert classify("??") == UNTRACKED
    assert classify("UU") == CONFLICTED
    assert classify("AA") == CONFLICTED
    assert classify("  ") is None


def test_files_and_ancestor_directories():
    info = parse(" M src/app/main.py", "?? notes.txt")
    assert info.status_of("/repo/src/app/main.py") == MODIFIED
    assert info.status_of("/repo/src/app") == MODIFIED
    assert info.status_of("/repo/src") == MODIFIED
    assert info.status_of("/repo") == MODIFIED
    assert info.status_of("/repo/notes.txt") == UNTRACKED
    assert info.status_of("/repo/other.txt") is None


def test_directory_shows_the_most_important_status_below_it():
    info = parse("?? d/new.txt", "A  d/added.txt", " M d/changed.txt")
    assert info.status_of("/repo/d") == MODIFIED
    info = parse("?? d/new.txt", "A  d/added.txt")
    assert info.status_of("/repo/d") == ADDED


def test_deleted_file_marks_its_directory_modified():
    info = parse(" D gone/file.txt")
    assert info.status_of("/repo/gone/file.txt") == DELETED
    assert info.status_of("/repo/gone") == MODIFIED


def test_rename_consumes_the_source_path():
    info = parse("R  new name.txt", "old name.txt", " M after.txt")
    assert info.status_of("/repo/new name.txt") == MODIFIED
    assert info.status_of("/repo/old name.txt") is None
    assert info.status_of("/repo/after.txt") == MODIFIED


def test_untracked_directory_covers_everything_inside_it():
    info = parse("?? newdir/")
    assert info.status_of("/repo/newdir") == UNTRACKED
    assert info.status_of("/repo/newdir/deep/file") == UNTRACKED
    assert info.status_of("/repo/newdirx") is None


def test_ignored_entries_and_their_contents():
    info = parse("!! node_modules/", "!! build.log")
    assert info.is_ignored("/repo/node_modules")
    assert info.is_ignored("/repo/node_modules/x/y.js")
    assert info.is_ignored("/repo/build.log")
    assert not info.is_ignored("/repo/node_modules2")
    assert not info.is_ignored("/repo/src")
    assert info.status_of("/repo/node_modules") is None


def test_paths_with_spaces_and_unicode_survive_nul_separation():
    info = parse(" M dir with space/ö file.txt")
    assert info.status_of("/repo/dir with space/ö file.txt") == MODIFIED


def test_empty_output():
    info = parse_status(b"", ROOT)
    assert info.status == {} and info.ignored == set()


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def run(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=a@b", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@needs_git
def test_real_repository(tmp_path: Path):
    run(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
    (tmp_path / "tracked.txt").write_text("one")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "inner.txt").write_text("one")
    run(tmp_path, "add", ".")
    run(tmp_path, "commit", "-qm", "first")

    (tmp_path / "tracked.txt").write_text("two")
    (tmp_path / "sub" / "inner.txt").unlink()
    (tmp_path / "new.txt").write_text("x")
    (tmp_path / "staged.txt").write_text("x")
    run(tmp_path, "add", "staged.txt")
    (tmp_path / "debug.log").write_text("x")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "out.o").write_text("x")

    info = load_git_info(str(tmp_path / "sub"))  # asked from a subdirectory
    assert info is not None
    root = str(tmp_path.resolve())
    assert info.root == root
    assert info.status_of(f"{root}/tracked.txt") == MODIFIED
    assert info.status_of(f"{root}/sub/inner.txt") == DELETED
    assert info.status_of(f"{root}/sub") == MODIFIED
    assert info.status_of(f"{root}/new.txt") == UNTRACKED
    assert info.status_of(f"{root}/staged.txt") == ADDED
    assert info.is_ignored(f"{root}/debug.log")
    assert info.is_ignored(f"{root}/build/out.o")


@needs_git
def test_outside_a_repository(tmp_path: Path):
    assert load_git_info(str(tmp_path)) is None


def test_missing_directory_is_not_an_error(tmp_path: Path):
    assert load_git_info(str(tmp_path / "missing")) is None
