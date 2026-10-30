# Development guide

Working notes for anyone (or any assistant) continuing Shellac. `design-notes.md` explains why
things are the way they are; this file explains how to work on them.

## Ground rules (from the original specification)

- Python 3.11+, GTK4 + libadwaita + VTE. Type hints everywhere; `ruff` clean.
- The pane tree and all other logic that does not need a widget stays **GTK-free** and
  unit tested: `pane_tree`, `config`, `config_edit`, `settings_schema`, `theme`, `keybindings`,
  `keybinding_edit`, `commands`, `state`, `file_tree_model`, `file_actions`, `git_status`,
  `links`, `shell`, `terminal_actions`, `desktop`, `file_icons`, `file_type_icons`.
- Never block the GTK main loop (file system and git work run off the main thread).
- Every user-visible setting lives in the config, with a default and a validated range or set
  of values (`config.ENUMS`, `config.RANGES`).
- Ambiguous decisions are written down in `design-notes.md`.

## Everyday commands

    pytest -q                # unit tests, no display needed
    ruff format . && ruff check .
    tools/ui-checks/run.sh tools/ui-checks/settings_window.py   # GUI checks under Xvfb

Run the GUI checks after touching `window.py`, `application.py`, `settings_window.py`,
`command_palette.py`, `terminal_pane.py` or `theme.py`.

## Map of the code

| Area | Files |
| --- | --- |
| App and window | `application.py` (config/theme state, live preview, file watching), `window.py` |
| Panes and tabs | `pane_tree.py` (model), `pane_container.py`, `terminal_pane.py` |
| Sidebar | `file_tree_model.py`, `file_tree.py`, `sidebar.py`, `file_actions.py`, `git_status.py` |
| Config | `config.py` (load/validate), `config_edit.py` (line-level writes), `state.py` (UI state) |
| Settings | `settings_schema.py` (fields), `settings_window.py` (window) |
| Shortcuts | `keybindings.py`, `keybinding_edit.py`, `commands.py`, `command_palette.py` |
| Themes and CSS | `theme.py` and `resources/themes/*.toml` |

Adding a **command**: add it to `commands.COMMANDS`, `keybindings.DEFAULT_KEYBINDINGS` and
`application.IMPLEMENTED_ACTIONS`, add the `win.<name>` action in `window.py`, and list the
default in `docs/configuration.md`. A test checks that commands and default shortcuts agree; keep `IMPLEMENTED_ACTIONS` in step by hand.

Adding a **setting**: add the field to its dataclass in `config.py` (with `ENUMS`/`RANGES`
entries if needed), a row in `settings_schema.py` if it belongs in the window, and a line in
`docs/configuration.md`. `test_settings_schema.py` checks the schema against the config.

## How the config and the settings window interact

- The config file is the user's. It is never rewritten as a whole: `config_edit` changes only
  the lines that changed, keeps comments, drops a line whose value equals the default, and
  re-parses the result before writing. Layouts it will not guess at (inline tables) are
  refused with a message.
- `Application.config` is what is in effect (file plus any live preview);
  `Application._disk_config` is what the file says. The settings window compares against the
  second, and previews through `preview_appearance` / `preview_theme`.
- A save sets `_last_self_write`, so the reload the file watcher triggers is quiet and keeps a
  theme picked at runtime unless the theme settings themselves changed.

## Things that went wrong before (and how they were solved)

- **Fractional `em` font sizes** (for example `0.72em`) clipped the top of labels on some
  setups. Use round values such as `0.8em`; avoid `opacity`/padding tricks to compensate.
- **Symbolic icons** must be filled paths, not strokes; stroked icons rendered invisible.
  Some desktop icon themes ship **empty** versions of standard names (`value-increase-symbolic`
  and similar), so the settings window swaps the spin buttons' icons for Shellac's own
  (`settings_window._use_own_spin_icons`). Prefer `shellac-*` icon names for anything new.
- **PyGObject quirks:** `Gdk.Rectangle(x=..)` ignores keyword arguments (create it, then set the
  fields); the event argument of a `Gtk.EventControllerLegacy` handler arrives as `None`, so
  call `controller.get_current_event()`; `compute_bounds` returns `(ok, rect)`.
- **Font dialog filter:** at family level its items are `Pango.FontFamily`, not faces.
- **Layout stability:** controls that appear conditionally (per-option reset buttons) are kept
  in the layout and made invisible, so nothing shifts under the pointer.
- **Context menu:** a plain `Gtk.Popover` with flat buttons is used instead of `PopoverMenu`,
  which scrolled and capped its height.

## Known limitations and open items

- Not tested on Wayland; the GUI checks run on X11 only.
- A right-click menu click is also forwarded to programs that use mouse reporting (VTE has no
  getter for that mode).
- `general.confirm_close_running` exists in the config but does nothing yet.
- `APP_ID` (`io.github.shellac.Shellac`) is a placeholder until the repository's final home
  is decided; Fedora and Arch package names in the README are unverified.
- A theme cycled with the keybinding cannot be written to the config from the settings window
  (it is the baseline of the Theme row); pick another theme and back, or edit the file.
- Roadmap candidates are in `ideas.md` (session restore, finished-command notifications,
  packaging, CI).

## Testing the GUI from a sandbox

The checks in `tools/ui-checks/` use `xvfb-run`, `dbus-run-session`, `xdotool` and ImageMagick.
Screenshots are the quickest way to judge visual changes: crop and enlarge a region to inspect
small details. Remember that a sandbox has a complete icon theme and a few fonts, so problems
that depend on the user's desktop theme (missing icons, a font that is not installed) show up
only on their machine.
