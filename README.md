# paneterm

A good-looking Linux terminal emulator with fast pane splitting and a file tree sidebar.
Built on GTK4, libadwaita and VTE; Python 3.11+.

> **paneterm is a working title.** The name is defined in `paneterm/__init__.py` and
> `pyproject.toml` only, so renaming it later is a two-file change.

## Status

Built milestone by milestone from the development specification.

| Milestone | State |
| --- | --- |
| M1 Single terminal window | Done: themed window, VTE running your shell, copy/paste, config loading |
| M2 Splits and tabs | Done: nested splits, close/collapse, directional focus, resize, pane zoom, tabs, working-directory inheritance |
| M3 Config and themes (runtime switching, live reload, more themes) | Loader and validation done; runtime switching and bundled themes other than Catppuccin Mocha are not |
| M4 File tree sidebar | Not started |
| M5 Git integration and polish | Not started |
| M6 Packaging (`.desktop` file, icon) | Not started |

## Keybindings

All bindings use Ctrl+Shift or Ctrl+Alt, so they never collide with shell shortcuts.
They are remappable in `[keybindings]`.

| Action | Default |
| --- | --- |
| Split, new pane below (`split_down`) | Ctrl+Shift+O |
| Split, new pane to the right (`split_right`) | Ctrl+Shift+E |
| Close pane (`close_pane`) | Ctrl+Shift+W |
| Zoom / unzoom pane (`zoom_pane`) | Ctrl+Shift+Z |
| Move focus (`focus_left/right/up/down`) | Ctrl+Alt+Arrows |
| Resize pane (`resize_left/right/up/down`) | Ctrl+Shift+Alt+Arrows |
| New tab / next / previous | Ctrl+Shift+T / Ctrl+PageDown / Ctrl+PageUp |
| Jump to tab 1..9 (`goto_tab_1`..) | Alt+1..9 |
| Copy / paste | Ctrl+Shift+C / Ctrl+Shift+V |

Not yet wired up (later milestones): `toggle_sidebar`, `search`, `cycle_theme`, and
Ctrl+Shift+R (reload config).

## Install (Kubuntu / Ubuntu / Debian)

PyGObject, GTK4, libadwaita and VTE come from the distro, not from PyPI.

```sh
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-vte-3.91 pipx
pipx install --system-site-packages .
paneterm
```

`--system-site-packages` is required so the isolated environment can see the
distro's `python3-gi`.

To run straight from a checkout instead:

```sh
python3 -m paneterm
```

Fedora: `sudo dnf install python3-gobject gtk4 libadwaita vte291-gtk4`.

Package names for the VTE GTK4 typelib (`gir1.2-vte-3.91`) have been stable across
Ubuntu releases, but they have **not** been confirmed on Kubuntu 26.04 itself. If `apt`
cannot find a package, search with `apt search vte | grep -i gtk4`.

Tested so far with GTK 4.14, libadwaita 1.5, VTE 0.76 and Python 3.12 (under Xvfb).
Not yet tested on Kubuntu 26.04, on Wayland, or with zsh.

## Working directory tracking (OSC 7)

Split panes and the sidebar need to know each shell's current directory. VTE learns it
from the OSC 7 escape sequence, which not every zsh setup emits. Add this to `~/.zshrc`:

```sh
paneterm --print-shell-integration >> ~/.zshrc
```

The snippet percent-encodes the path, so directories with spaces or non-ASCII names work.
It is three lines rather than the one line the spec asks for; a plain one-liner produces
invalid URIs for such paths. Without it, paneterm falls back to reading
`/proc/<pid>/cwd`, which also works but cannot see through nested shells.

## Configuration

`$XDG_CONFIG_HOME/paneterm/config.toml` (default `~/.config/paneterm/config.toml`).
Every setting has a default, and a missing or partial file is fine. An invalid value
logs a warning, shows one toast, and falls back to its default; it never crashes.
User themes go in `~/.config/paneterm/themes/*.toml` and override bundled ones with the
same file name. `paneterm --help` lists the command-line flags.

```toml
[general]
shell = ""               # empty = $SHELL, then /bin/zsh, then /bin/bash
login_shell = true       # start the shell with -l
scrollback_lines = 10000

[window]
width = 1000
height = 640

[panes]
resize_step = 40         # pixels moved by one keyboard resize

[tabs]
autohide = true          # hide the tab bar while only one tab is open

[appearance]
theme = "catppuccin-mocha"
font_family = "JetBrainsMono Nerd Font"   # falls back to FiraCode/Iosevka NF, then Monospace
font_size = 12
opacity = 0.95           # terminal background only, never the text
padding = 8
cursor_shape = "block"   # block | ibeam | underline
cursor_blink = false

[keybindings]
copy = "<Ctrl><Shift>c"
paste = "<Ctrl><Shift>v"
```

Keybindings for actions that are not implemented yet (splits, tabs, sidebar, ...) are
accepted and validated but not bound until their milestone lands.

## Design decisions

Where the spec was ambiguous, the simplest behavior was chosen:

- **Login shell.** The shell is started with `-l` (FR-1 asks for a login shell). Set
  `login_shell = false` to turn that off.
- **TERM and COLORTERM.** Always set to `xterm-256color` and `truecolor` for the child.
  FR-2's "unless the user overrides them" has no config key yet, because inheriting TERM
  from whichever terminal launched paneterm would advertise the wrong capabilities.
- **Window size.** `[window] width/height` was added so there are no magic constants in
  widget code. Persisting the size between launches belongs to M5.

- **Split naming.** `split_down` puts the new pane below, `split_right` puts it beside,
  matching Terminator. Inside the code these are `Axis.VERTICAL` / `Axis.HORIZONTAL`
  (GTK's orientation of the children), which is the reverse of the everyday wording.
- **Focus indicator.** `focus_indicator = "border"` draws a 1 px accent outline over the
  pane, so it never changes the pane's size. It only shows while several panes are visible.
- **Remote shells.** Inside `ssh`, the remote shell's OSC 7 reports its own path. A URI
  naming another host is ignored, so a new split opens in a local directory instead.
- **Close behavior.** Closing a pane sends its shell SIGHUP. There is no "confirm close
  while a command is running" prompt yet (`confirm_close_running` is parsed but unused).
- **Known cosmetic warning.** Closing a pane programmatically in an unfocused window can log
  a GTK `gtk_paned_set_focus_child` warning. It did not appear with real keypresses in a
  focused window, and has no visible effect.

## Development

```sh
python3 -m pytest        # needs python3-pytest, or: pip install -e '.[dev]'
ruff check . && ruff format --check .
```

The config, theme, keybinding and shell-resolution modules do not import GTK, so their
tests run without a display. The pane tree (M2) will follow the same rule.
