"""Shell integration snippets (FR-10).

VTE learns a pane's working directory from OSC 7. Not every zsh setup emits it,
so ``paneterm --print-shell-integration`` prints this for ``~/.zshrc``.
"""

# Percent-encodes everything outside the URI-safe set, byte by byte (LC_ALL=C),
# so directories with spaces or non-ASCII names produce a valid file:// URI.
ZSH_SNIPPET = r"""autoload -Uz add-zsh-hook
_paneterm_osc7() { local LC_ALL=C c out= i; for ((i=1; i<=${#PWD}; i++)); do c=${PWD[i]}; [[ $c == [a-zA-Z0-9/._~-] ]] && out+=$c || out+=$(printf '%%%02X' "'$c"); done; printf '\e]7;file://%s%s\e\\' "${HOST}" "$out"; }
add-zsh-hook precmd _paneterm_osc7
"""
