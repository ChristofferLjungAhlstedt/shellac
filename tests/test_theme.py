from pathlib import Path

import pytest

from paneterm.config import AppearanceConfig
from paneterm.theme import (
    BUNDLED_THEMES_DIR,
    DEFAULT_THEME,
    PALETTE_SIZE,
    ThemeError,
    available_theme_files,
    generate_css,
    get_theme,
    load_theme_file,
    parse_theme,
)


def _theme_data(**overrides):
    data = {
        "name": "Test",
        "dark": True,
        "terminal": {
            "foreground": "#ffffff",
            "background": "#000000",
            "cursor": "#ffffff",
            "selection_background": "#333333",
            "selection_foreground": "#ffffff",
            "palette": ["#000000"] * PALETTE_SIZE,
        },
        "ui": {
            "accent": "#0000ff",
            "sidebar_background": "#111111",
            "sidebar_foreground": "#eeeeee",
            "tabbar_background": "#222222",
            "divider": "#444444",
        },
    }
    data.update(overrides)
    return data


def test_bundled_default_theme_loads():
    theme = load_theme_file(BUNDLED_THEMES_DIR / f"{DEFAULT_THEME}.toml")
    assert theme.id == DEFAULT_THEME
    assert theme.name == "Catppuccin Mocha"
    assert theme.dark is True
    assert len(theme.palette) == PALETTE_SIZE


def test_parse_theme_lowercases_colors():
    data = _theme_data()
    data["terminal"]["foreground"] = "#ABCDEF"
    assert parse_theme("t", data).foreground == "#abcdef"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["terminal"].update(foreground="red"),
        lambda d: d["terminal"].update(palette=["#000000"] * 15),
        lambda d: d["terminal"].update(palette=["#000000"] * 15 + ["nope"]),
        lambda d: d["ui"].pop("accent"),
        lambda d: d.pop("terminal"),
        lambda d: d.update(dark="yes"),
    ],
)
def test_malformed_themes_raise_theme_error(mutate):
    data = _theme_data()
    mutate(data)
    with pytest.raises(ThemeError):
        parse_theme("t", data)


def test_user_theme_overrides_bundled_of_same_name(tmp_path: Path):
    (tmp_path / f"{DEFAULT_THEME}.toml").write_text(
        (BUNDLED_THEMES_DIR / f"{DEFAULT_THEME}.toml").read_text().replace("Mocha", "Custom")
    )
    files = available_theme_files(tmp_path)
    assert files[DEFAULT_THEME].parent == tmp_path
    theme, warnings = get_theme(DEFAULT_THEME, tmp_path)
    assert theme.name == "Catppuccin Custom"
    assert warnings == []


def test_unknown_theme_falls_back_with_warning(tmp_path: Path):
    theme, warnings = get_theme("does-not-exist", tmp_path)
    assert theme.id == DEFAULT_THEME
    assert len(warnings) == 1


def test_broken_user_theme_falls_back_with_warning(tmp_path: Path):
    (tmp_path / "broken.toml").write_text("this is not toml [")
    theme, warnings = get_theme("broken", tmp_path)
    assert theme.id == DEFAULT_THEME
    assert len(warnings) == 1
    assert "could not load" in warnings[0]


def test_generated_css_uses_theme_colors_and_config():
    theme = load_theme_file(BUNDLED_THEMES_DIR / f"{DEFAULT_THEME}.toml")
    css = generate_css(theme, AppearanceConfig(padding=12, opacity=0.5))
    assert theme.accent in css
    assert theme.tabbar_background in css
    assert "padding: 12px" in css
    assert "0.500" in css
