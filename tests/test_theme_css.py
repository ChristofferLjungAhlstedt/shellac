from shellac.config import AppearanceConfig
from shellac.theme import (
    BUNDLED_THEMES_DIR,
    GIT_STATUS_PALETTE_INDEX,
    generate_css,
    load_theme_file,
)


def test_git_status_colors_come_from_each_themes_palette():
    for path in sorted(BUNDLED_THEMES_DIR.glob("*.toml")):
        theme = load_theme_file(path)
        css = generate_css(theme, AppearanceConfig())
        for name, index in GIT_STATUS_PALETTE_INDEX.items():
            assert f".git-{name} label {{ color: {theme.palette[index]}; }}" in css, (path, name)


def test_generated_css_braces_balance():
    for path in sorted(BUNDLED_THEMES_DIR.glob("*.toml")):
        css = generate_css(load_theme_file(path), AppearanceConfig())
        assert css.count("{") == css.count("}"), path.name
        assert "{{" not in css and "}}" not in css, path.name
