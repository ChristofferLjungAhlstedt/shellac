# Design notes

Decisions made where the original specification was ambiguous, plus project history.

## Decisions

Where the spec was ambiguous, the simplest behavior was chosen:

- **Login shell.** The shell is started with `-l` (FR-1 asks for a login shell). Set
  `login_shell = false` to turn that off.
- **TERM and COLORTERM.** Always set to `xterm-256color` and `truecolor` for the child.
  FR-2's "unless the user overrides them" has no config key yet, because inheriting TERM
  from whichever terminal launched Shellac would advertise the wrong capabilities.
- **Window size.** `[window] width/height` was added so there are no magic constants in
  widget code.

- **Light theme.** `one-light` rather than Catppuccin Latte: Latte's yellow and magenta fall
  below 2.5:1 contrast on its background. A unit test keeps every bundled theme readable
  (body text at least 7:1, colored ANSI entries at least 2.5:1).
- **Config folders.** Shellac creates `~/.config/shellac/` and its `themes/` folder on
  startup (not the config file itself). Directories are watched instead of the file, so
  editors that save by renaming a temp file over it are handled.
- **Split naming.** `split_down` puts the new pane below, `split_right` puts it beside,
  matching Terminator. Inside the code these are `Axis.VERTICAL` / `Axis.HORIZONTAL`
  (GTK's orientation of the children), which is the reverse of the everyday wording.
- **Focus indicator.** `focus_indicator = "border"` draws a 1 px accent outline over the
  pane, so it never changes the pane's size. It only shows while several panes are visible.
- **Remote shells.** Inside `ssh`, the remote shell's OSC 7 reports its own path. A URI
  naming another host is ignored, so a new split opens in a local directory instead.
- **Close behavior.** Closing a pane sends its shell SIGHUP. With `confirm_close_running` (on by
  default) closing a pane, a tab or the window first asks if a command is in the foreground of a
  pane (see `close_confirm.py`, `TerminalPane.is_running_command`). It asks about the program the
  terminal reports, so it is a heuristic: background jobs and nested shells are not seen. A pane
  that exits by itself never asks.
- **Known cosmetic warning.** Closing a pane programmatically in an unfocused window can log
  a GTK `gtk_paned_set_focus_child` warning. It did not appear with real keypresses in a
  focused window, and has no visible effect.

- **Double click on a directory.** The first click already expanded it, so a double click
  expands and then `cd`s (or re-roots). It does not toggle twice.
- **Typed text at the prompt.** `cd` is typed after whatever is already on the command line,
  as the spec's idle check cannot see a half-typed line.
- **Unreachable root.** If the root directory disappears the tree moves to the nearest
  directory that still exists. A directory still open in a shell sends no delete event, so
  this is also checked once a second.
- **Filter** only applies to directories that are already loaded; it never scans the disk.

- **Window size.** The size and maximized state are remembered in the state file and win over
  `[window] width/height`, which only set the first-launch size.
- **Search** uses VTE's own search: the match is highlighted and selected in the terminal.
  Enter / Shift+Enter go to the next / previous match, Escape closes the bar. The text is
  matched literally, not as a regular expression.
- **URL clicking** only opens `http`, `https`, `ftp(s)`, `file` and `mailto`, also for OSC 8
  hyperlinks, so a program cannot make Ctrl+click launch an arbitrary protocol handler.
  A trailing `.` `,` `)` is not treated as part of the link, so a URL that itself ends in
  `)` loses it.
- **Font zoom** is per pane by default; `zoom_scope = "window"` zooms every pane and new ones.

- **Session restore** stores the layout as plain data (`session.py`) in `state.json`, not the
  config. It is on by default (`general.restore_session`). Only directories are restored, never
  running programs or scrollback. Editor panes opened from the sidebar are skipped and their
  split collapses. The session is captured on close and on every state save (sidebar resize,
  toggle), so a crash loses little; the cwd of a pane is whatever it was at the last save. When
  the last tab closes because its shell exited, the session is cleared, so exiting every shell
  means a fresh start. Reading is defensive and capped (64 tabs, 64 panes per tab).
- **Finished-command notifications** (`command_watch.py`, polled from `window.py`). The window
  samples every pane once a second to see whether a command holds the terminal's foreground (the
  same check as the close confirmation) and reports one that ran at least
  `finished_after_seconds`. Polling was chosen over shell integration because the only
  integration Shellac ships is a zsh snippet (OSC 7), and this works in every shell without
  setup. The price is that the exit status is unknown and the program name is whatever was last
  in the foreground. Who is told depends on where you are: a marker on a background tab, a
  desktop notification only while the window is not active (`attention()`), nothing when you
  are watching. The tab marker is libadwaita's own "needs attention" indicator and is cleared
  when the tab is selected. If prompt marks (OSC 133) ever land in VTE, the exit status and exact
  start and end could replace the polling.
- **Workspaces** (`workspace.py`, `.shellac.toml`). A workspace is parsed into the same
  `TabState`/`SplitState` types session restore uses, so one `replay` rebuilds both; the only
  addition is `PaneState.command`. The file format is nested `[[tab.pane]]` tables, which read
  like the layout and cover any split tree; more than two siblings are folded into equal binary
  splits. It is opened only from the sidebar menu, not the palette, because every palette
  command must have a default shortcut (and a workspace is tied to a folder anyway). Because
  the file can arrive with a cloned repository, opening one that would run commands always
  shows them and asks; there is deliberately no "always trust" yet. Commands are typed into the
  new shell with `TerminalPane.type_when_ready`: a line sent at once to a starting shell can be
  lost, so it waits for the prompt to be drawn and the output to go quiet (300 ms), or sends
  after 4 s to a shell that prints nothing. Saving writes only what Shellac knows: layout,
  ratios and directories (relative to the folder when inside it); it asks before replacing a
  file, since the old commands would be lost.

## Milestones

| Milestone | Scope |
| --- | --- |
| M1 | Single terminal window: themed window, VTE running your shell, copy/paste, config loading |
| M2 | Nested splits, close/collapse, directional focus, resize, pane zoom, tabs, working-directory inheritance |
| M3 | Five bundled themes, runtime switching, live config reload, system light/dark following, rebindable keys |
| M4 | File tree sidebar: lazy tree, follow mode and pin, live updates, icons, activation, context menu, filter |
| M5 | Git status colors, `.gitignore` dimming/hiding, scrollback search, clickable URLs, font zoom, remembered window size |
| M6 | Launcher entry and icon (`--install-desktop`), install steps per distro, screenshots |

## Testing

Automated checks ran with GTK 4.14, libadwaita 1.5, VTE 0.76 and Python 3.12 under Xvfb;
daily use is on Kubuntu 26.04 with Python 3.14. Not yet tested on Wayland.

## Renamed from "paneterm"

Shellac was developed under the working title paneterm. If you used an early build, move
your files once:

```sh
mv ~/.config/paneterm ~/.config/shellac
mv ~/.local/state/paneterm ~/.local/state/shellac
```

and remove the old install with `paneterm --uninstall-desktop` and `pipx uninstall paneterm`.

## Settings window

- `settings_schema.py` lists the pages and fields and is GTK-free; a test checks every field
  against the config dataclasses, `ENUMS` and `RANGES`, so the window cannot offer a value the
  loader would reject.
- `config_edit.py` edits single `key = value` lines (keybindings use it too). A value equal to
  the default removes its line; the result is re-parsed with `tomllib` before it is written.
- Appearance options are previewed live through an overlay on the loaded config
  (`Application.preview_appearance`; `config` is what is in effect, `_disk_config` what the file
  says). The theme uses a temporary runtime override (`preview_theme`), so Cancel returns to the
  previous look and Save hands the decision back to the config. The theme row’s baseline is the
  theme in effect, which is why cycling themes with the keybinding moves the row.
- Not offered: window size, sidebar visibility and width (remembered state), `always_show`,
  and `[sidebar.open_with]`.
