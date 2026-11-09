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
    check("menu always offers saving", "Save Tab as Workspace…" in menu_labels(side._build_menu(there)))
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


def b1():
    # Saving: the current tab (3 panes) into a folder without a workspace file.
    check("no file there yet", not os.path.exists(f"{OTHER}/{WORKSPACE_FILE}"))
    win().save_workspace(OTHER)


def b2():
    path = f"{OTHER}/{WORKSPACE_FILE}"
    check("save writes the file at once when none exists", os.path.exists(path) and dialog() is None)
    text = read(path) if os.path.exists(path) else ""
    result = parse_workspace(text, OTHER)
    check("and it reads back as the same shape", result.workspace is not None and
          isinstance(result.workspace.tabs[0].layout, SplitState)
          and abs(result.workspace.tabs[0].layout.ratio - 0.3) < 0.02, str(result.error))
    check("directories outside the folder stay absolute", f'dir = "{real(BASE)}/api"' in text or f'{BASE}/api' in text, text)
    state["saved"] = text
    win().save_workspace(OTHER)  # again: the file exists now


def b3():
    d = dialog()
    check("saving over a file asks first", d is not None)
    if d is not None:
        check("and warns that commands are lost", "Commands" in d.get_body(), d.get_body())
        press("Cancel")


def b4():
    check("Cancel leaves the file alone", read(f"{OTHER}/{WORKSPACE_FILE}") == state["saved"])
    win().save_workspace(OTHER)


def b5():
    press("Replace")


def b6():
    check("Replace saves again", dialog() is None and os.path.exists(f"{OTHER}/{WORKSPACE_FILE}"))
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


state: dict = {}
STEPS = [
    (a1, 800), (a2, 500), (a3, 600), (a4, 500), (a5, 3500), (a6, 500),
    (b1, 800), (b2, 800), (b3, 500), (b4, 800), (b5, 800), (b6, 800),
    (c1, 800), (c2, 800), (c3, 300),
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
