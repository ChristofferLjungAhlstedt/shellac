# Design notes

Decisions made where the original specification was ambiguous, plus project history.

## Decisions

Where the spec was ambiguous, the simplest behavior was chosen:

- **Login shell.** The shell is started with `-l` (FR-1 asks for a login shell). Set
  `login_shell = false` to turn that off.
- **TERM and COLORTERM.** Always set to `xterm-256color` and `truecolor` for the child.
  FR-2's "unless the user overrides them" has no config key yet, because inheriting TERM
  from whichever terminal launched shellac would advertise the wrong capabilities.
- **Window size.** `[window] width/height` was added so there are no magic constants in
  widget code.

- **Light theme.** `one-light` rather than Catppuccin Latte: Latte's yellow and magenta fall
  below 2.5:1 contrast on its background. A unit test keeps every bundled theme readable
  (body text at least 7:1, colored ANSI entries at least 2.5:1).
- **Config folders.** shellac creates `~/.config/shellac/` and its `themes/` folder on
  startup (not the config file itself). Directories are watched instead of the file, so
  editors that save by renaming a temp file over it are handled.
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

shellac was developed under the working title paneterm. If you used an early build, move
your files once:

```sh
mv ~/.config/paneterm ~/.config/shellac
mv ~/.local/state/paneterm ~/.local/state/shellac
```

and remove the old install with `paneterm --uninstall-desktop` and `pipx uninstall paneterm`.
