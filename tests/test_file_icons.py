from paneterm.file_icons import ALL_ICON_NAMES, file_kind, icon_name
from paneterm.file_tree_model import Entry


def test_directories_use_open_and_closed_icons():
    entry = Entry("src", "/x/src", True)
    assert icon_name(entry) == "paneterm-folder-symbolic"
    assert icon_name(entry, expanded=True) == "paneterm-folder-open-symbolic"


def test_files_are_classified_by_extension_case_insensitively():
    assert file_kind("main.PY") == "code"
    assert file_kind("photo.jpeg") == "image"
    assert file_kind("a.tar.gz") == "archive"
    assert file_kind("notes.md") == "text"
    assert file_kind("Makefile") == "text"
    assert file_kind("mystery") == "file"


def test_symlinks_and_broken_links():
    assert icon_name(Entry("l", "/l", False, True)) == "paneterm-link-symbolic"
    assert icon_name(Entry("l", "/l", False, True, True)) == "paneterm-broken-symbolic"
    # a link to a directory is still a directory
    assert icon_name(Entry("d", "/d", True, True)) == "paneterm-folder-symbolic"


def test_every_icon_used_is_listed():
    for entry in (Entry("a.py", "/a.py", False), Entry("b", "/b", True)):
        assert icon_name(entry) in ALL_ICON_NAMES
