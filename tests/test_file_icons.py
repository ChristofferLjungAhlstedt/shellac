from shellac.file_icons import ALL_ICON_NAMES, file_kind, icon_name
from shellac.file_tree_model import Entry


def test_directories_use_open_and_closed_icons():
    entry = Entry("src", "/x/src", True)
    assert icon_name(entry) == "shellac-folder-symbolic"
    assert icon_name(entry, expanded=True) == "shellac-folder-open-symbolic"


def test_files_are_classified_by_extension_case_insensitively():
    assert file_kind("main.PY") == "code"
    assert file_kind("photo.jpeg") == "image"
    assert file_kind("a.tar.gz") == "archive"
    assert file_kind("notes.md") == "text"
    assert file_kind("Makefile") == "text"
    assert file_kind("mystery") == "file"


def test_symlinks_and_broken_links():
    assert icon_name(Entry("l", "/l", False, True)) == "shellac-link-symbolic"
    assert icon_name(Entry("l", "/l", False, True, True)) == "shellac-broken-symbolic"
    # a link to a directory is still a directory
    assert icon_name(Entry("d", "/d", True, True)) == "shellac-folder-symbolic"


def test_every_icon_used_is_listed():
    for entry in (Entry("a.py", "/a.py", False), Entry("b", "/b", True)):
        assert icon_name(entry) in ALL_ICON_NAMES


def test_logos_by_extension_and_file_name():
    from shellac.file_type_icons import logo_name

    assert logo_name("app.js") == "shellac-ft-javascript"
    assert logo_name("main.DART") == "shellac-ft-dart"
    assert logo_name("Dockerfile") is not None
    assert logo_name("package.json") != logo_name("other.json")  # exact name wins
    assert logo_name("mystery.zzzz") is None
    assert logo_name("noextension") is None


def test_logos_are_optional_and_only_for_regular_files():
    js = Entry("app.js", "/app.js", False)
    assert icon_name(js, logos=True) == "shellac-ft-javascript"
    assert icon_name(js, logos=False) == "shellac-code-symbolic"
    assert icon_name(Entry("src.js", "/src.js", True), logos=True) == "shellac-folder-symbolic"
    assert icon_name(Entry("a.js", "/a.js", False, True, True), logos=True).endswith(
        "broken-symbolic"
    )


def test_every_logo_has_a_bundled_file():
    from pathlib import Path

    from shellac.file_type_icons import EXTENSION_ICONS, FILENAME_ICONS, ICON_PREFIX

    folder = Path(__file__).parent.parent / "shellac/resources/icons/hicolor/scalable/mimetypes"
    for name in {*EXTENSION_ICONS.values(), *FILENAME_ICONS.values()}:
        assert (folder / f"{ICON_PREFIX}{name}.svg").exists(), name
