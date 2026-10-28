# Configuration reference

shellac reads `$XDG_CONFIG_HOME/shellac/config.toml` (default `~/.config/shellac/config.toml`).
Every setting has a default, and a missing or partial file is fine. An invalid value logs a
warning, shows one toast, and falls back to its default; it never crashes. shellac never
rewrites your config file.

User themes go in `~/.config/shellac/themes/*.toml` (see [Themes](#themes)).
`shellac --help` lists the command-line flags.

## All settings with their defaults

```toml
[general]
shell = ""               # empty = $SHELL, then /bin/zsh, then /bin/bash
login_shell = true       # start the shell with -l
scrollback_lines = 10000
clickable_urls = true    # clicking a URL in the output opens it
link_activation = "click"  # click | ctrl_click: what opens a link
context_menu = true      # right-click menu (copy, paste, select all, splits, link actions)
search_case_sensitive = false
search_wrap_around = true

[window]
width = 1000
height = 640

[panes]
resize_step = 40         # pixels moved by one keyboard resize

[tabs]
autohide = true          # hide the tab bar while only one tab is open

[appearance]
theme = "catppuccin-mocha"
follow_system_scheme = false             # true: pick dark_theme or light_theme by the system
dark_theme = "catppuccin-mocha"
light_theme = "one-light"
font_family = "JetBrainsMono Nerd Font"   # falls back to FiraCode/Iosevka NF, then Monospace
font_size = 12
opacity = 0.95           # terminal background only, never the text
padding = 8
cursor_shape = "block"   # block | ibeam | underline
cursor_blink = false
zoom_scope = "pane"      # pane | window: what Ctrl+plus / Ctrl+minus resize
zoom_step = 0.1

[sidebar]
visible = true           # first-launch default; afterwards the remembered state wins
width = 260              # same
follow_cwd = true        # the root follows the focused pane's directory
show_hidden = false      # H toggles it while the tree is focused
hide_gitignored = false  # true hides ignored entries; false dims them (I toggles)
git_status = true        # color and mark changed files (needs git)
on_file_activate = "editor_split"   # editor_split | editor_tab | command_split | command_tab
                                    # | run | paste_path | desktop_open
file_command = ""        # for command_*: argv template, e.g. "bat --paging=always {path}"
keep_pane_open = true    # command_* and run: wait for Enter after the command exits
always_show = [".gitignore"]        # dotfiles shown even while show_hidden = false
file_type_icons = true   # language/file-type logos in the tree (false = plain icons)
on_dir_activate = "cd"              # cd | reroot
editor = ""              # empty = $VISUAL, then $EDITOR, then nano/vim/vi (may include arguments)
editor_split_direction = "right"    # right | down
reveal_in_root = true    # a cd inside the shown tree expands to it instead of re-rooting
indent = 16              # pixels per tree level

[sidebar.open_with]      # per-extension override of the activation command
# py = "vim {path}"
# sh = "bash {path}"

[keybindings]
copy = "<Ctrl><Shift>c"
paste = "<Ctrl><Shift>v"
```


## Keybindings

Keybindings use GTK accelerator syntax (`<Ctrl><Shift>c`). If two actions share an
accelerator, a warning is logged and shown as a toast.

A value is one accelerator, or a list of them to give an action several shortcuts (the first
is the primary one). An empty list leaves the action without a shortcut:

```toml
[keybindings]
split_right = ["<Ctrl><Shift>e", "<Ctrl><Alt>r"]
paste = []                         # no shortcut
```

You do not have to edit this by hand: the command palette (`Ctrl+Shift+Space`, then the pen
button; changes apply when you press Save) edits exactly these lines. It only changes the lines of the actions you edit, so your
comments and the rest of the file stay as they are. If the file uses a layout it will not guess
at (for example `keybindings = { ... }` as an inline table) it asks you to edit by hand.

| Action name | Default | Does |
| --- | --- | --- |
| `split_down` | `<Ctrl><Shift>o` | new pane below |
| `split_right` | `<Ctrl><Shift>e` | new pane to the right |
| `close_pane` | `<Ctrl><Shift>w` | close the pane |
| `zoom_pane` | `<Ctrl><Shift>z` | zoom or unzoom the pane |
| `focus_left/right/up/down` | `<Ctrl><Alt>Arrow` | move focus |
| `resize_left/right/up/down` | `<Ctrl><Shift><Alt>Arrow` | move the divider (the sidebar's when it has focus) |
| `new_tab`, `next_tab`, `prev_tab` | `<Ctrl><Shift>t`, `<Ctrl>Page_Down`, `<Ctrl>Page_Up` | tabs |
| `goto_tab_1` ... `goto_tab_9` | `<Alt>1` ... `<Alt>9` | jump to a tab |
| `copy`, `paste` | `<Ctrl><Shift>c`, `<Ctrl><Shift>v` | clipboard |
| `search` | `<Ctrl><Shift>f` | search the scrollback |
| `zoom_in`, `zoom_out`, `zoom_reset` | `<Ctrl>plus`, `<Ctrl>minus`, `<Ctrl>0` | font size |
| `cycle_theme`, `reload_config` | `<Ctrl><Shift>p`, `<Ctrl><Shift>r` | themes and config |
| `command_palette` | `<Ctrl><Shift>space` | open the command palette |
| `toggle_sidebar`, `focus_sidebar` | `<Ctrl><Shift>b`, `<Ctrl><Alt>b` | sidebar |

## Sidebar file activation

`on_file_activate` decides what clicking (double-clicking) a file does:

| Mode | Effect |
| --- | --- |
| `editor_split` (default) | open the editor in a new split (`editor`, else `$VISUAL`, `$EDITOR`, then nano/vim/vi) |
| `editor_tab` | the same, in a new tab |
| `command_split`, `command_tab` | run `file_command` in a split or tab |
| `run` | execute the file itself (must be executable; otherwise a toast explains) |
| `paste_path` | paste the shell-quoted path at the prompt |
| `desktop_open` | hand the file to the desktop's default application |

`file_command` is an argument template with the placeholders `{path}`, `{dir}` and `{name}`.
It is run as an argument list, never through a shell, so file names with spaces or quotes
are safe. `[sidebar.open_with]` maps a file extension to its own command and wins over the
mode, for example `py = "vim {path}"`. With `keep_pane_open = true` a pane running a command
stays open until you press Enter, so the output can be read.

## Themes

Bundled: `catppuccin-mocha` (default), `tokyo-night`, `gruvbox-dark`, `nord` and `one-light`.
**Ctrl+Shift+P** cycles through them, recoloring every pane, tab and the window chrome at
once. Set one permanently with `theme = "nord"`.

To add your own, drop a `.toml` file into `~/.config/shellac/themes/` (created on first
start). Copy one of the bundled files from the installed package as a template: `terminal`
colors, a 16-entry `palette`, and `ui` colors for the chrome. A user theme with the same
file name as a bundled one replaces it. With `follow_system_scheme = true`, `dark_theme` or
`light_theme` is chosen by the desktop's dark/light preference and changes when it does.

## Live reload

The config file and the themes folder are watched. Saving either applies the change to
all open windows and panes within a moment, including fonts, colors, opacity, padding,
the tab bar and keybindings. Ctrl+Shift+R reloads on demand.

- A mistake never breaks a running window: an invalid value, an unknown theme or broken
  TOML logs a warning, shows one toast, and uses the default for that value.
- A theme picked with Ctrl+Shift+P is remembered between sessions (in
  `~/.local/state/shellac/state.json`, never in your config). It survives saving unrelated
  settings, including shortcuts edited in the command palette. It is dropped by Ctrl+Shift+R,
  or when you change `theme`, `dark_theme`, `light_theme` or `follow_system_scheme` in the
  config. While
  following the system scheme, cycling pauses the following until the next reload.
- Settings that only matter at creation (`shell`, `login_shell`, window size) apply to
  new panes and tabs, not to shells that are already running.

