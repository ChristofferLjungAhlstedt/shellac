from shellac.keybindings import DEFAULT_KEYBINDINGS, find_conflicts, normalize_accelerator


def test_normalization_ignores_modifier_order_alias_and_case():
    a = normalize_accelerator("<Ctrl><Shift>o")
    b = normalize_accelerator("<Shift><Control>O")
    assert a is not None
    assert a == b


def test_arrow_keys_keep_their_names():
    assert normalize_accelerator("<Ctrl><Alt>Left") == (frozenset({"control", "alt"}), "left")


def test_malformed_accelerators_are_rejected():
    for bad in ["", "   ", "<Ctrl>", "<Bogus>x", "<Ctrl>a b", "<Ctrl><Shift"]:
        assert normalize_accelerator(bad) is None, bad


def test_defaults_have_no_conflicts():
    assert find_conflicts(DEFAULT_KEYBINDINGS) == []


def test_conflict_detected_across_spellings():
    bindings = {"split_down": "<Ctrl><Shift>o", "split_right": "<Shift><Control>O"}
    assert find_conflicts(bindings) == [("split_down", "split_right")]


def test_defaults_never_bind_a_bare_ctrl_letter():
    for action, accel in DEFAULT_KEYBINDINGS.items():
        mods, key = normalize_accelerator(accel)
        assert not (mods == frozenset({"control"}) and len(key) == 1 and key.isalpha()), action


def test_m2_actions_have_defaults():
    for action in (
        "resize_left",
        "resize_down",
        "next_tab",
        "prev_tab",
        "goto_tab_1",
        "goto_tab_9",
    ):
        assert action in DEFAULT_KEYBINDINGS
    assert "goto_tab_10" not in DEFAULT_KEYBINDINGS


def test_every_default_action_is_described_for_the_palette():
    from shellac.commands import COMMANDS, GOTO_TAB_PREFIX, GROUPS

    described = {c.action for c in COMMANDS}
    needed = {a for a in DEFAULT_KEYBINDINGS if not a.startswith(GOTO_TAB_PREFIX)}
    assert needed == described
    assert {c.group for c in COMMANDS} <= set(GROUPS)


def test_accelerator_tokens_for_keycaps():
    from shellac.keybindings import accelerator_tokens

    assert accelerator_tokens("<Ctrl><Shift>o") == ["Ctrl", "Shift", "O"]
    assert accelerator_tokens("<Ctrl><Shift><Alt>Left") == ["Ctrl", "Shift", "Alt", "←"]
    assert accelerator_tokens("<Ctrl>Page_Down") == ["Ctrl", "PgDn"]
    assert accelerator_tokens("<Ctrl><Shift>space") == ["Ctrl", "Shift", "Space"]
    assert accelerator_tokens("<Ctrl>plus") == ["Ctrl", "+"]
    assert accelerator_tokens("<Alt>F4") == ["Alt", "F4"]
    assert accelerator_tokens("<Bogus>x") == ["<Bogus>x"]


def test_safe_bindings_and_canonical_form():
    from shellac.keybindings import canonical_accelerator, is_safe_binding

    assert is_safe_binding("<Ctrl>a") and is_safe_binding("<Alt>1") and is_safe_binding("F5")
    assert not is_safe_binding("a") and not is_safe_binding("<Shift>a")
    assert canonical_accelerator("<Control><Shift>O") == "<Ctrl><Shift>o"
    assert canonical_accelerator("<Shift><Control>Page_Down") == "<Ctrl><Shift>Page_Down"
    assert canonical_accelerator("nonsense<") is None


def test_binding_conflicts_and_owner_lookup_cover_extra_shortcuts():
    from shellac.keybindings import find_binding_conflicts, owner_of

    bindings = {"a": ["<Ctrl>x", "<Alt>y"], "b": ["<Ctrl>z"], "c": ["<Alt><Shift>q", "<Control>X"]}
    assert find_binding_conflicts(bindings) == [("a", "c", "<Control>X")]
    assert owner_of("<Ctrl>z", bindings) == "b"
    assert owner_of("<Ctrl>z", bindings, ignore="b") is None


def test_with_key_keeps_the_modifiers():
    from shellac.keybindings import with_key

    assert with_key("<Ctrl><Alt>x", "3") == "<Ctrl><Alt>3"
    assert with_key("<Alt>7", "1") == "<Alt>1"
