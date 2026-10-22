from pathlib import Path

import pytest

from paneterm.config import AppearanceConfig
from paneterm.theme import (
    BUNDLED_THEMES_DIR,
    DEFAULT_THEME,
    PALETTE_SIZE,
    ThemeError,
    available_theme_files,
    choose_theme_id,
    contrast_ratio,
    generate_css,
    get_theme,
    load_theme_file,
    next_theme_id,
    parse_theme,
    relative_luminance,
    theme_ids,
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


# -- M3: bundled themes, cycling, system scheme ------------------------------------------

BUNDLED_IDS = ["catppuccin-mocha", "gruvbox-dark", "nord", "one-light", "tokyo-night"]


def test_all_five_bundled_themes_are_present_and_load():
    assert [i for i in theme_ids(Path("/nonexistent")) if i in BUNDLED_IDS] == BUNDLED_IDS
    for theme_id in BUNDLED_IDS:
        assert load_theme_file(BUNDLED_THEMES_DIR / f"{theme_id}.toml").id == theme_id


@pytest.mark.parametrize("theme_id", BUNDLED_IDS)
def test_dark_flag_matches_the_background(theme_id: str):
    theme = load_theme_file(BUNDLED_THEMES_DIR / f"{theme_id}.toml")
    assert (relative_luminance(theme.background) < 0.5) == theme.dark


@pytest.mark.parametrize("theme_id", BUNDLED_IDS)
def test_bundled_themes_are_readable(theme_id: str):
    """NFR-6: body text must be clearly readable, and the colored ANSI entries
    (red..cyan, normal and bright) must stay distinguishable from the background."""
    theme = load_theme_file(BUNDLED_THEMES_DIR / f"{theme_id}.toml")
    assert contrast_ratio(theme.foreground, theme.background) >= 7.0
    assert contrast_ratio(theme.selection_foreground, theme.selection_background) >= 4.5
    for index in [*range(1, 7), *range(9, 15)]:
        ratio = contrast_ratio(theme.palette[index], theme.background)
        assert ratio >= 2.5, f"palette[{index}] {theme.palette[index]} only {ratio:.2f}:1"


def test_contrast_ratio_extremes():
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast_ratio("#777777", "#777777") == pytest.approx(1.0)


def test_theme_ids_include_user_themes(tmp_path: Path):
    (tmp_path / "mine.toml").write_text("")
    ids = theme_ids(tmp_path)
    assert "mine" in ids
    assert ids == sorted(ids)


def test_next_theme_id_cycles_and_wraps():
    ids = ["a", "b", "c"]
    assert next_theme_id("a", ids) == "b"
    assert next_theme_id("c", ids) == "a"
    assert next_theme_id("gone", ids) == "a"
    assert next_theme_id("x", []) == "x"


def test_choose_theme_id_without_following_uses_theme():
    appearance = AppearanceConfig(theme="nord", dark_theme="tokyo-night", light_theme="one-light")
    assert choose_theme_id(appearance, system_dark=True) == "nord"
    assert choose_theme_id(appearance, system_dark=None) == "nord"


def test_choose_theme_id_following_picks_by_system_scheme():
    appearance = AppearanceConfig(
        theme="nord",
        follow_system_scheme=True,
        dark_theme="tokyo-night",
        light_theme="one-light",
    )
    assert choose_theme_id(appearance, system_dark=True) == "tokyo-night"
    assert choose_theme_id(appearance, system_dark=False) == "one-light"
    # Unknown system preference: fall back to the plain theme setting.
    assert choose_theme_id(appearance, system_dark=None) == "nord"
