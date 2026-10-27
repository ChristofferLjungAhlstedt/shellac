import configparser
from pathlib import Path

from shellac import APP_ID
from shellac.desktop import (
    DESKTOP_FILE,
    ICON_FILE,
    desktop_entry,
    install,
    quote_exec,
    uninstall,
)


def parse(text: str) -> dict[str, str]:
    parser = configparser.RawConfigParser()
    parser.optionxform = str  # keep key case
    parser.read_string(text)
    return dict(parser["Desktop Entry"])


def test_entry_has_the_required_keys():
    entry = parse(desktop_entry(["/usr/bin/shellac"]))
    assert entry["Type"] == "Application"
    assert entry["Name"] == "Shellac"
    assert entry["Exec"] == "/usr/bin/shellac"
    assert entry["Icon"] == APP_ID
    assert entry["Terminal"] == "false"
    assert "TerminalEmulator" in entry["Categories"].split(";")
    assert entry["Categories"].endswith(";")


def test_exec_quotes_paths_with_spaces_and_specials():
    assert quote_exec("/usr/bin/shellac") == "/usr/bin/shellac"
    assert quote_exec("/home/me/my venv/bin/python") == '"/home/me/my venv/bin/python"'
    assert quote_exec('a"b') == '"a\\"b"'
    assert quote_exec("$HOME/x") == '"\\$HOME/x"'
    entry = parse(desktop_entry(["/home/me/my venv/bin/python", "-m", "shellac"]))
    assert entry["Exec"] == '"/home/me/my venv/bin/python" -m shellac'


def test_install_and_uninstall_round_trip(tmp_path: Path):
    written = install(tmp_path, command=["/usr/bin/shellac"])
    desktop = tmp_path / "applications" / DESKTOP_FILE
    icon = tmp_path / "icons" / "hicolor" / "scalable" / "apps" / ICON_FILE
    assert set(written) == {desktop, icon}
    assert desktop.read_text().startswith("[Desktop Entry]")
    assert icon.read_text().lstrip().startswith("<svg")
    install(tmp_path, command=["/usr/bin/shellac"])  # twice is fine
    assert set(uninstall(tmp_path)) == {desktop, icon}
    assert not desktop.exists() and not icon.exists()
    assert uninstall(tmp_path) == []


def test_desktop_file_name_matches_the_application_id():
    # Wayland shells match a window to its launcher by this name.
    assert f"{APP_ID}.desktop" == DESKTOP_FILE
