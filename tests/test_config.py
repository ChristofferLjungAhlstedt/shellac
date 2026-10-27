from pathlib import Path

from shellac.config import Config, config_path, load_config, parse_config
from shellac.keybindings import DEFAULT_KEYBINDINGS


def test_missing_file_gives_defaults_without_warnings(tmp_path: Path):
    result = load_config(tmp_path / "nope.toml")
    assert result.config == Config()
    assert result.warnings == []


def test_empty_file_gives_defaults(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("")
    result = load_config(path)
    assert result.config == Config()
    assert result.warnings == []


def test_partial_file_merges_over_defaults(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('[appearance]\ntheme = "nord"\nfont_size = 14\n')
    result = load_config(path)
    assert result.warnings == []
    assert result.config.appearance.theme == "nord"
    assert result.config.appearance.font_size == 14.0
    assert isinstance(result.config.appearance.font_size, float)
    assert result.config.appearance.padding == Config().appearance.padding
    assert result.config.general == Config().general


def test_invalid_toml_falls_back_to_defaults(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("[appearance\ntheme = ")
    result = load_config(path)
    assert result.config == Config()
    assert len(result.warnings) == 1
    assert "invalid TOML" in result.warnings[0]


def test_wrong_type_warns_and_uses_default():
    result = parse_config({"appearance": {"padding": "lots", "cursor_blink": 1}})
    assert result.config.appearance.padding == Config().appearance.padding
    assert result.config.appearance.cursor_blink is Config().appearance.cursor_blink
    assert len(result.warnings) == 2


def test_bool_is_not_accepted_as_int():
    result = parse_config({"appearance": {"padding": True}})
    assert result.config.appearance.padding == Config().appearance.padding
    assert len(result.warnings) == 1


def test_enum_typo_warns_and_uses_default():
    result = parse_config({"appearance": {"cursor_shape": "blok"}})
    assert result.config.appearance.cursor_shape == "block"
    assert "not one of" in result.warnings[0]


def test_out_of_range_warns_and_uses_default():
    result = parse_config({"appearance": {"opacity": 1.5}, "general": {"scrollback_lines": -1}})
    assert result.config.appearance.opacity == Config().appearance.opacity
    assert result.config.general.scrollback_lines == Config().general.scrollback_lines
    assert len(result.warnings) == 2


def test_integer_accepted_for_float_option():
    result = parse_config({"appearance": {"opacity": 1}})
    assert result.warnings == []
    assert result.config.appearance.opacity == 1.0


def test_unknown_keys_and_sections_warn_but_do_not_fail():
    result = parse_config({"appearance": {"colour": "red"}, "mystery": {}})
    assert result.config == Config()
    assert len(result.warnings) == 2


def test_non_table_section_warns():
    result = parse_config({"general": 5})
    assert result.config.general == Config().general
    assert "must be a table" in result.warnings[0]


def test_keybinding_override_and_unknown_action():
    result = parse_config({"keybindings": {"copy": "<Ctrl><Alt>c", "teleport": "<Ctrl>t"}})
    assert result.config.keybindings["copy"] == "<Ctrl><Alt>c"
    assert result.config.keybindings["paste"] == DEFAULT_KEYBINDINGS["paste"]
    assert any("unknown action 'teleport'" in w for w in result.warnings)


def test_invalid_keybinding_falls_back_to_default():
    result = parse_config({"keybindings": {"copy": "<Bogus>c"}})
    assert result.config.keybindings["copy"] == DEFAULT_KEYBINDINGS["copy"]
    assert len(result.warnings) == 1


def test_keybinding_conflict_is_reported():
    result = parse_config({"keybindings": {"copy": "<Ctrl><Shift>v"}})
    assert any("share the accelerator" in w for w in result.warnings)


def test_defaults_are_not_shared_between_instances():
    a, b = Config(), Config()
    a.keybindings["copy"] = "<Ctrl>x"
    assert b.keybindings["copy"] == DEFAULT_KEYBINDINGS["copy"]


def test_config_path_honours_xdg_config_home(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_path() == tmp_path / "shellac" / "config.toml"


def test_list_and_table_options_are_validated_and_copied():
    from shellac.config import SidebarConfig, parse_config

    result = parse_config({"sidebar": {"always_show": [".env", ".gitignore"]}})
    assert result.config.sidebar.always_show == [".env", ".gitignore"]
    assert result.warnings == []

    result = parse_config({"sidebar": {"always_show": [".env", 5]}})
    assert result.config.sidebar.always_show == SidebarConfig().always_show
    assert "always_show" in result.warnings[0]

    first, second = parse_config({}).config, parse_config({}).config
    first.sidebar.always_show.append(".x")
    assert ".x" not in second.sidebar.always_show


def test_gitignore_is_shown_by_default():
    from shellac.config import SidebarConfig

    assert ".gitignore" in SidebarConfig().always_show
