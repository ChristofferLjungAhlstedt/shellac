import tomllib

from shellac.config_edit import apply_setting_changes, format_value, save_setting_changes


def test_format_value():
    assert format_value(True) == "true"
    assert format_value(12.0) == "12.0"
    assert format_value(0.95) == "0.95"
    assert format_value('a"b') == '"a\\"b"'
    assert format_value(["x", "y"]) == '["x", "y"]'


def test_edits_in_place_adds_and_removes_and_keeps_comments():
    text = '# mine\n[appearance]\nfont_size = 11  # big\ntheme = "nord"\n\n[sidebar]\nwidth = 300\n'
    out = apply_setting_changes(
        text,
        {
            ("appearance", "font_size"): 14.0,
            ("appearance", "theme"): None,
            ("appearance", "padding"): 4,
            ("general", "shell"): "/bin/zsh",
        },
    )
    assert out is not None and out.startswith("# mine\n")
    data = tomllib.loads(out)
    assert data["appearance"] == {"font_size": 14.0, "padding": 4}
    assert data["sidebar"] == {"width": 300}
    assert data["general"] == {"shell": "/bin/zsh"}
    assert out.index("padding") < out.index("[sidebar]")


def test_multiline_arrays_are_replaced_whole():
    text = '[sidebar]\nalways_show = [\n  ".a",\n  ".b",\n]\nindent = 8\n'
    out = apply_setting_changes(text, {("sidebar", "always_show"): [".c"]})
    assert tomllib.loads(out)["sidebar"] == {"always_show": [".c"], "indent": 8}


def test_inline_table_is_refused():
    assert (
        apply_setting_changes("appearance = { theme = 'x' }\n", {("appearance", "padding"): 1})
        is None
    )


def test_save_creates_file(tmp_path):
    path = tmp_path / "d" / "config.toml"
    assert save_setting_changes(path, {("tabs", "autohide"): False}) is None
    assert tomllib.loads(path.read_text()) == {"tabs": {"autohide": False}}


def test_a_table_left_empty_is_removed():
    text = '# top\n[appearance]\ntheme = "nord"\n\n[sidebar]\nwidth = 300\n'
    out = apply_setting_changes(text, {("appearance", "theme"): None})
    assert out == "# top\n\n[sidebar]\nwidth = 300\n"
    assert apply_setting_changes("[tabs]\nautohide = false\n", {("tabs", "autohide"): None}) == ""
