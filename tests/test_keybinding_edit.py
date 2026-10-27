import tomllib

from shellac.keybinding_edit import apply_binding_changes, save_binding_changes


def parsed(text: str) -> dict:
    return tomllib.loads(text)


def test_creates_the_table_at_the_end_and_keeps_existing_content():
    text = "# my settings\n[appearance]\ntheme = 'nord'  # nice\n"
    out = apply_binding_changes(text, {"copy": ["<Ctrl>c"]})
    assert out is not None
    assert out.startswith("# my settings\n[appearance]\ntheme = 'nord'  # nice\n")
    assert parsed(out)["keybindings"] == {"copy": "<Ctrl>c"}


def test_replaces_a_line_in_place_and_keeps_neighbours_and_comments():
    text = (
        '[keybindings]\n# splits\nsplit_right = "<Ctrl><Shift>e"  # old\ncopy = "<Ctrl><Shift>c"\n'
        "\n[sidebar]\nwidth = 300\n"
    )
    out = apply_binding_changes(text, {"split_right": ["<Ctrl><Alt>r"]})
    assert out is not None
    assert "# splits" in out
    data = parsed(out)
    assert data["keybindings"] == {"split_right": "<Ctrl><Alt>r", "copy": "<Ctrl><Shift>c"}
    assert data["sidebar"]["width"] == 300


def test_several_shortcuts_become_an_array():
    out = apply_binding_changes("", {"copy": ["<Ctrl>a", "<Alt>b"]})
    assert parsed(out)["keybindings"]["copy"] == ["<Ctrl>a", "<Alt>b"]


def test_new_entry_goes_inside_an_existing_table_not_after_the_next_one():
    text = '[keybindings]\ncopy = "<Ctrl>x"\n\n[sidebar]\nwidth = 1\n'
    out = apply_binding_changes(text, {"paste": ["<Ctrl>y"]})
    data = parsed(out)
    assert data["keybindings"] == {"copy": "<Ctrl>x", "paste": "<Ctrl>y"}
    assert data["sidebar"] == {"width": 1}


def test_none_removes_the_entry_even_when_it_spans_lines():
    text = '[keybindings]\ncopy = [\n  "<Ctrl>a",\n  "<Alt>b",\n]\npaste = "<Ctrl>v"\n'
    out = apply_binding_changes(text, {"copy": None})
    assert parsed(out)["keybindings"] == {"paste": "<Ctrl>v"}


def test_unsupported_layouts_are_refused():
    assert (
        apply_binding_changes('keybindings = { copy = "<Ctrl>c" }\n', {"copy": ["<Ctrl>x"]}) is None
    )
    assert apply_binding_changes("[keybindings.extra]\na = 1\n", {"copy": ["<Ctrl>x"]}) is None


def test_invalid_toml_is_never_made_worse():
    assert apply_binding_changes("[keybindings\nbroken", {"copy": ["<Ctrl>x"]}) is None


def test_save_writes_atomically_and_creates_the_file(tmp_path):
    path = tmp_path / "sub" / "config.toml"
    assert save_binding_changes(path, {"copy": ["<Ctrl>x"]}) is None
    assert parsed(path.read_text())["keybindings"]["copy"] == "<Ctrl>x"
    assert not list(path.parent.glob("*.tmp"))
    assert save_binding_changes(path, {"copy": None}) is None
    assert (
        "keybindings" not in parsed(path.read_text()) or not parsed(path.read_text())["keybindings"]
    )


def test_empty_list_is_written_as_an_explicit_unbind_and_none_removes():
    out = apply_binding_changes('[keybindings]\ncopy = "<Ctrl>c"\n', {"copy": []})
    assert parsed(out)["keybindings"]["copy"] == []
    out = apply_binding_changes(out, {"copy": None})
    assert parsed(out).get("keybindings", {}) == {}
