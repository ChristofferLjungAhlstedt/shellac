from shellac.commands import COMMANDS, GOTO_TAB_PREFIX
from shellac.keybindings import DEFAULT_KEYBINDINGS


def test_every_command_has_a_default_shortcut_and_the_other_way_round():
    commands = {c.action for c in COMMANDS}
    bindable = {a for a in DEFAULT_KEYBINDINGS if not a.startswith(GOTO_TAB_PREFIX)}
    assert commands == bindable
