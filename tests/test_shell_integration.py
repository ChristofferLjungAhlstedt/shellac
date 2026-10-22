from paneterm.shell_integration import ZSH_SNIPPET


def test_snippet_starts_with_real_zsh_code():
    # Regression: a raw string once began with a literal backslash.
    assert ZSH_SNIPPET.startswith("autoload -Uz add-zsh-hook")


def test_snippet_hooks_precmd_and_emits_osc7():
    assert "add-zsh-hook precmd" in ZSH_SNIPPET
    assert r"\e]7;file://" in ZSH_SNIPPET
    assert ZSH_SNIPPET.endswith("\n")
