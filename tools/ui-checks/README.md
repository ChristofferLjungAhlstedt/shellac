# GUI checks

Scripted checks that drive the real windows under a virtual display (Xvfb): they press keys with
`xdotool`, call widget methods, assert on the application state and take screenshots. They are
not part of `pytest` because they need a display stack.

    tools/ui-checks/run.sh tools/ui-checks/settings_window.py

Each script prints `CHECK PASS` / `CHECK FAIL` lines and ends with `RESULT ALL PASSED` or a list
of failures. `settings_window.py` covers the settings window (draft, Save, Cancel, Reset, live
preview, theme following); `palette_draft.py` covers the command palette's shortcut editor.
Both run steps on a timer, so a step that needs time to settle (a file reload takes about
250 ms) is given a longer delay. New checks are easiest to write by copying one of these.
