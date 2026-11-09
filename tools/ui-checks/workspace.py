"""Workspaces (.shellac.toml): open with a confirmation, save, and the sidebar menu.

Run with: tools/ui-checks/run.sh tools/ui-checks/workspace.py
Real shells run the commands: `echo RESULT$((6*7))` prints RESULT42, which only appears in
the terminal if the command ran (the typed line itself shows `$((6*7))`).
"""

import os
import subprocess
import sys
import types

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Vte", "3.91")
from gi.repository import GLib, Gtk, Vte  # noqa: E402

from shellac.application import Application  # noqa: E402
from shellac.pane_tree import Axis  # noqa: E402
from shellac.session import SplitState  # noqa: E402
from shellac.state import load_state  # noqa: E402
from shellac.workspace import WORKSPACE_FILE, parse_workspace  # noqa: E402

SHOT = os.environ["SHOTDIR"]
BASE = os.environ["HOME"] + "/proj"
OTHER = os.environ["HOME"] + "/plain"
fails: list[str] = []
app = Application()
app.hold()

WORKSPACE = """
[[tab]]
split = "right"
ratio = 0.3
[[tab.pane]]
dir = "api"
run = "echo API$((6*7))"
[[tab.pane]]
split = "down"
[[tab.pane.pane]]
dir = "web"
run = "echo WEB$((6*7))"
[[tab.pane.pane]]
dir = "logs"
focus = true

[[tab]]
dir = "web"
"""


def check(label, ok, detail=""):
    print(("CHECK PASS " if ok else "CHECK FAIL ") + label + (f" [{detail}]" if detail else ""),
          flush=True)
    if not ok:
        fails.append(label)


def shot(name):
    subprocess.run(["import", "-window", "root", f"{SHOT}/{name}.png"], check=False)


def win():
    return app.props.active_window


def containers():
    view = win()._tab_view
    return [win()._containers[view.get_nth_page(i)] for i in range(view.get_n_pages())]


def dialog():
    return win().get_visible_dialog()


def buttons(widget):
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Button):
            yield child
        yield from buttons(child)
        child = child.get_next_sibling()


def press(label):
    for button in buttons(dialog()):
        if button.get_label() == label:
            button.emit("clicked")
            return True
    return False


def screen_text(pane):
    return pane.terminal.get_text_format(Vte.Format.TEXT) or ""


def menu_labels(menu):
    labels = []
    for i in range(menu.get_n_items()):
        section = menu.get_item_link(i, "section")
        if section is not None:
            labels += menu_labels(section)
        label = menu.get_item_attribute_value(i, "label", None)
        if label is not None:
            labels.append(label.get_string())
    return labels


def real(path):
    return os.path.realpath(path)


def read(path):
    with open(path) as handle:
        return handle.read()


# -- steps -----------------------------------------------------------------------------------


def a1():
    for name in ("api", "web", "logs"):
        os.makedirs(f"{BASE}/{name}", exist_ok=True)
    os.makedirs(OTHER, exist_ok=True)
    with open(f"{BASE}/{WORKSPACE_FILE}", "w") as handle:
        handle.write(WORKSPACE)
    # The sidebar menu offers "Open Workspace" only where there is a file.
    here = types.SimpleNamespace(path=BASE, is_dir=True)
    there = types.SimpleNamespace(path=OTHER, is_dir=True)
    inside = types.SimpleNamespace(path=f"{BASE}/api", is_dir=True)
    file_in_project = types.SimpleNamespace(path=f"{BASE}/{WORKSPACE_FILE}", is_dir=False)
    side = win()._sidebar
    check("menu offers Open Workspace for a folder with a file",
          "Open Workspace" in menu_labels(side._build_menu(here)))
    check("...also on the file itself", "Open Workspace" in menu_labels(side._build_menu(file_in_project)))
    check("menu does not offer it elsewhere",
          "Open Workspace" not in menu_labels(side._build_menu(there))
          and "Open Workspace" not in menu_labels(side._build_menu(inside)))
    check("no file: offers to start one", "Start a Workspace in This Folder…" in menu_labels(side._build_menu(there)))
    check("file: offers to update it", "Update Workspace with Current Layout…" in menu_labels(side._build_menu(here))
          and "Start a Workspace in This Folder…" not in menu_labels(side._build_menu(here)))
    check("old wording is gone", "Save Tab as Workspace…" not in menu_labels(side._build_menu(there)))
    win().open_workspace(BASE)


def a2():
    d = dialog()
    check("commands are listed and confirmed first", d is not None)
    if d is None:
        return
    check("heading", d.get_heading() == "Run these commands?", d.get_heading())
    check("body lists both commands", "echo API$((6*7))" in d.get_body() and "echo WEB$((6*7))" in d.get_body())
    shot("workspace_confirm")
    press("Cancel")


def a3():
    check("Cancel opens nothing", len(containers()) == 1, str(len(containers())))
    win().open_workspace(BASE)


def a4():
    check("asks again", dialog() is not None)
    press("Run")


def a5():
    pass  # let the shells start and the commands run


def a6():
    tabs = containers()
    check("two tabs added", len(tabs) == 3, str(len(tabs)))
    if len(tabs) != 3:
        return
    check("the first new tab is selected", win()._current_container() is tabs[1])
    layout = tabs[1].capture().layout
    check("tab 1 is split side by side", isinstance(layout, SplitState) and layout.axis == Axis.HORIZONTAL)
    check("with the divider at 30 %", abs(layout.ratio - 0.3) < 0.02, f"{layout.ratio:.2f}")
    check("the right side is stacked", isinstance(layout.second, SplitState) and layout.second.axis == Axis.VERTICAL)
    panes = tabs[1].panes()
    dirs = [real(p.current_directory() or "") for p in panes]
    check("directories", dirs == [real(f"{BASE}/api"), real(f"{BASE}/web"), real(f"{BASE}/logs")], str(dirs))
    check("first command ran", "API42" in screen_text(panes[0]), screen_text(panes[0])[-80:])
    check("second command ran", "WEB42" in screen_text(panes[1]), screen_text(panes[1])[-80:])
    check("a pane without a command just has its prompt", "42" not in screen_text(panes[2]))
    check("focus = true focuses that pane", tabs[1].focused_pane is panes[2])
    check("the second tab is one pane in web",
          len(tabs[2].panes()) == 1 and real(tabs[2].panes()[0].current_directory() or "") == real(f"{BASE}/web"))
    shot("workspace_opened")


def rows():
    d = dialog()
    return d.folder_rows, d.command_rows


def b1():
    # Starting a workspace from the current tab (3 panes) in a folder without a file.
    check("no file there yet", not os.path.exists(f"{OTHER}/{WORKSPACE_FILE}"))
    win().edit_workspace(OTHER)


def b2():
    d = dialog()
    check("the start dialog opens", d is not None and d.get_title() == "Start a workspace")
    if d is None:
        return
    folders, commands = rows()
    check("one folder and one command per pane", len(folders) == 3 and len(commands) == 3)
    check("folders prefilled from the panes", folders[0].get_text().endswith("api"), folders[0].get_text())
    check("no commands yet", all(c.get_text() == "" for c in commands))
    check("a clear button label", any(b.get_label() == "Create" for b in buttons(d)))
    shot("workspace_dialog_start")
    commands[0].set_text("echo HI")
    folders[2].set_text("")
    press("Create")


def b3():
    path = f"{OTHER}/{WORKSPACE_FILE}"
    check("Create writes the file and closes", os.path.exists(path) and dialog() is None)
    text = read(path) if os.path.exists(path) else ""
    check("it starts with explaining comments", text.startswith("#") and "Open Workspace" in text)
    result = parse_workspace(text, OTHER)
    check("and reads back", result.workspace is not None, str(result.error))
    check("the command is written", 'run = "echo HI"' in text, text)
    check("panes without a command get a hint", "# run =" in text)
    win().edit_workspace(OTHER)


def b4():
    d = dialog()
    check("the update dialog opens", d is not None and d.get_title() == "Update workspace")
    if d is None:
        return
    folders, commands = rows()
    check("update keeps each pane's command", commands[0].get_text() == "echo HI", commands[0].get_text())
    check("and warns that comments are not kept", "comments" in d._draft.note)
    shot("workspace_dialog_update")
    folders[1].set_text("no-such-folder")
    press("Update")


def b5():
    d = dialog()
    check("a missing folder keeps the dialog open", d is not None)
    if d is None:
        return
    folders, _ = rows()
    check("and marks that row", folders[1].has_css_class("error"), folders[1].get_title())
    check("other rows are not marked", not folders[0].has_css_class("error"))
    shot("workspace_dialog_error")
    folders[1].set_text("")
    check("editing clears the mark", not folders[1].has_css_class("error"))
    state["tabs"] = len(containers())
    win()._activate_file = lambda path: state.__setitem__("activated", path)  # editor is user config
    press("Save and Edit as Text")


def b6():
    check("Save and Edit as Text closes the dialog", dialog() is None)
    text = read(f"{OTHER}/{WORKSPACE_FILE}")
    check("the file was saved", 'run = "echo HI"' in text and "no-such-folder" not in text)
    check("and handed to the editor setting", state.get("activated") == f"{OTHER}/{WORKSPACE_FILE}",
          str(state.get("activated")))
    # A file that cannot be read as a workspace opens nothing and asks nothing.
    with open(f"{OTHER}/{WORKSPACE_FILE}", "w") as handle:
        handle.write('[[tab]]\nrun = "unterminated\n')
    state["tabs"] = len(containers())
    win().open_workspace(OTHER)


def c1():
    check("a broken file opens nothing and asks nothing", len(containers()) == state["tabs"] and dialog() is None)
    # A workspace with no commands opens without asking.
    with open(f"{OTHER}/{WORKSPACE_FILE}", "w") as handle:
        handle.write("[[tab]]\n[[tab.pane]]\n[[tab.pane]]\nsplit = 'down'\n")
    win().open_workspace(OTHER)


def c2():
    check("no commands, no question", dialog() is None)
    check("it just opens", len(containers()) == state["tabs"] + 1)
    # A folder with no file at all.
    os.unlink(f"{OTHER}/{WORKSPACE_FILE}")
    win().open_workspace(OTHER)


def c3():
    check("a missing file opens nothing", len(containers()) == state["tabs"] + 1 and dialog() is None)


def write_workspace(command):
    with open(f"{OTHER}/{WORKSPACE_FILE}", "w") as handle:
        handle.write(f'[[tab]]\n[[tab.pane]]\nrun = "{command}"\n')


def labels():
    return [b.get_label() for b in buttons(dialog())] if dialog() else []


def d1():
    # "Always Run": offered on the question, and remembered.
    write_workspace("echo TRUST$((6*7))")
    state["tabs"] = len(containers())
    win().open_workspace(OTHER)


def d2():
    check("the question offers Always Run", "Always Run" in labels(), str(labels()))
    shot("workspace_always_run")
    press("Always Run")


def d3():
    check("Always Run opens the workspace", len(containers()) == state["tabs"] + 1)
    trusted = load_state().trusted_workspaces
    check("and remembers the folder", real(OTHER) in trusted, str(list(trusted)))
    state["tabs"] = len(containers())
    win().open_workspace(OTHER)


def d4():
    check("a trusted workspace opens without asking", dialog() is None)
    check("it opened", len(containers()) == state["tabs"] + 1, str(len(containers())))
    # A command that changed is asked about again, and says so.
    write_workspace("echo CHANGED")
    state["tabs"] = len(containers())
    win().open_workspace(OTHER)


def d5():
    d = dialog()
    check("a changed command asks again", d is not None)
    if d is not None:
        check("and says it changed", "changed" in d.get_body(), d.get_body()[:80])
        shot("workspace_changed")
        press("Cancel")


def d6():
    check("Cancel opens nothing", len(containers()) == state["tabs"])
    # The setting off: the stored trust is ignored and Always Run is not offered.
    write_workspace("echo TRUST$((6*7))")
    win()._config.general.allow_trusted_workspaces = False
    win().open_workspace(OTHER)


def d7():
    check("setting off: asks even for a trusted workspace", dialog() is not None)
    check("and offers no Always Run", "Always Run" not in labels(), str(labels()))
    press("Cancel")
    win()._config.general.allow_trusted_workspaces = True


state: dict = {}
STEPS = [
    (a1, 800), (a2, 500), (a3, 600), (a4, 500), (a5, 3500), (a6, 500),
    (b1, 800), (b2, 800), (b3, 800), (b4, 800), (b5, 800), (b6, 1000),
    (c1, 800), (c2, 800), (c3, 300),
    (d1, 700), (d2, 400), (d3, 2500), (d4, 800), (d5, 500), (d6, 600), (d7, 500),
]
idx = [0]


def run():
    if idx[0] >= len(STEPS):
        app.release()
        GLib.idle_add(app.quit)
        return False
    fn, delay = STEPS[idx[0]]
    idx[0] += 1
    try:
        fn()
    except Exception:
        import traceback

        traceback.print_exc()
        fails.append(fn.__name__)
    GLib.timeout_add(delay, run)
    return False


GLib.timeout_add(2000, run)
app.run([sys.argv[0]])
print("RESULT", "ALL PASSED" if not fails else fails, flush=True)
