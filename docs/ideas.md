# Ideas and roadmap

A brainstorm of possible additions to Shellac, grouped by area. Items marked **planned** are
being built; the rest are candidates, in no fixed order.

## Planned

- **Command palette with a keybinding editor** (done). A compact, always-available window listing
  every command with its shortcuts. A pen button enlarges it and makes the shortcuts
  editable, including adding a second shortcut for the same command. Settings are written
  back to `config.toml` without touching the rest of the file.
- **GUI settings.** A settings window for the common options, so a newcomer does not have to
  edit TOML.

## High value

- **Session restore.** Reopen with the same tabs, split layout and working directories. The
  pane tree is plain data, so this is mostly serializing it into the state file.
- **Saved layouts / workspaces.** A small TOML file per project describing the splits and the
  command each pane starts with, opened from the sidebar's context menu on a folder.
- **Finished-command notifications.** A desktop notification or a tab marker when a long
  command ends in a background pane or tab, using the shell integration to detect the end of a
  command.

## Splits and tabs

- Broadcast input to several panes at once.
- Drag a pane to rearrange the layout; rename and color tabs.
- Swap two panes with a key; move a pane to its own tab.
- Confirm before closing a pane that is running a command (`confirm_close_running` is parsed
  already but not wired up).

## Sidebar

- Git extras: branch name and ahead/behind counts in the header, a "changed files only"
  filter, stage and unstage from the context menu.
- Search inside files (ripgrep-backed) with results that open at the matching line.
- Multi-select for move, copy and trash; drag and drop a file into a terminal to paste its path.
- File preview for images and markdown in a popover.

## Terminal features

- Prompt marks: jump between previous prompts and select a command's whole output.
- Quick actions on selection: open `path:line` from compiler output in the editor.
- Inline images (kitty or sixel protocols). VTE support is limited, so low priority.
- A drop-down ("quake") mode on a global shortcut. On KDE Wayland this needs a portal or a
  KWin script, so it would start as experimental.

## Polish and distribution

- Window transparency and blur; per-project profiles (font, shell and theme per project).
- Flatpak and `.deb` packages, which is the biggest step towards a finished product.
- A CI workflow running pytest and ruff, tagged releases and a changelog.
