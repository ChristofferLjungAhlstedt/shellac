from paneterm.keybindings import DEFAULT_KEYBINDINGS, find_conflicts, normalize_accelerator


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
        mods, _key = normalize_accelerator(accel)
        assert mods != frozenset({"control"}), action
