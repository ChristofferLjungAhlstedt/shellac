"""confirm_close_running: closing a pane, tab or window while a command runs asks first.

Run with: tools/ui-checks/run.sh tools/ui-checks/confirm_close.py
Real shells are used: a pane "is running" while `sleep` holds the terminal's foreground.
"""

import dataclasses
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from shellac.application import Application
from shellac.pane_tree import Axis

SHOT = os.environ["SHOTDIR"]
fails: list[str] = []
app = Application()
app.hold()
state: dict = {}


def check(label, ok, detail=""):
    print(("CHECK PASS " if ok else "CHECK FAIL ") + label + (f" [{detail}]" if detail else ""),
          flush=True)
    if not ok:
        fails.append(label)


def shot(name):
    subprocess.run(["import", "-window", "root", f"{SHOT}/{name}.png"], check=False)


def win():
    return app.props.active_window


def tabs():
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
    d = dialog()
    for button in buttons(d):
        if button.get_label() == label:
            button.emit("clicked")
            return True
    return False


def sleeping(pid):
    return os.path.exists(f"/proc/{pid}") and "Z" not in open(f"/proc/{pid}/stat").read().split(")")[-1][:3]


def run_in(pane):
    pane.send_text("sleep 300\n")


# 1. one tab with two panes (idle shells), second tab with a pane running sleep ------------


def s1():
    first = tabs()[0]
    first.split(Axis.HORIZONTAL)
    win().new_tab()
    win()._select_tab(0)


def s1b():
    run_in(tabs()[1].focused_pane)  # the new shell has had time to start


def s2():
    first, second = tabs()
    check("idle pane is not running a command", not first.focused_pane.is_running_command())
    check("pane with sleep is running a command", second.focused_pane.is_running_command(),
          str(second.focused_pane.busy_with()))
    check("busy_with names it", second.focused_pane.busy_with() == "sleep")
    # Closing an idle pane just closes it.
    win().activate_action("win.close_pane", None)


def s3():
    first, _second = tabs()
    check("idle pane closes without asking", dialog() is None and len(first.panes()) == 1,
          f"{len(first.panes())} panes, dialog={dialog()}")
    # Now the busy tab: close its pane. It is the tab's only pane and there are two tabs.
    win()._select_tab(1)


def s4():
    win().activate_action("win.close_pane", None)


def s5():
    d = dialog()
    check("busy pane asks before closing", d is not None)
    if d is None:
        return
    check("heading says tab", d.get_heading() == "Close this tab?", d.get_heading())
    check("body names sleep", "“sleep”" in d.get_body(), d.get_body())
    shot("confirm_pane")
    state["pid"] = int(subprocess.check_output(["pgrep", "-n", "sleep"]).split()[0])
    press("Keep open")


def s6():
    check("Keep open leaves the tab", len(tabs()) == 2 and dialog() is None)
    check("and the program running", sleeping(state["pid"]))
    win().activate_action("win.close_pane", None)


def s7():
    check("asks again", dialog() is not None)
    press("Close")


def s8():
    check("Close ends the tab", len(tabs()) == 1, str(len(tabs())))


# 2. the tab's close button (close-page) --------------------------------------------------


def t1():
    win().new_tab()


def t1b():
    run_in(tabs()[1].focused_pane)


def t2():
    view = win()._tab_view
    state["page"] = view.get_page(tabs()[1].widget)
    view.close_page(state["page"])


def t3():
    d = dialog()
    check("closing a busy tab asks", d is not None)
    if d is not None:
        check("tab heading", d.get_heading() == "Close this tab?", d.get_heading())
        press("Keep open")


def t4():
    check("Keep open keeps the tab", len(tabs()) == 2)
    win()._tab_view.close_page(state["page"])  # not stuck: asks again


def t5():
    check("tab can be closed again after keeping it", dialog() is not None)
    press("Close")


def t6():
    check("tab closed after Close", len(tabs()) == 1)


# 3. an editor-style pane (one command, not a shell) counts --------------------------------


def e1():
    pane = tabs()[0].split(Axis.HORIZONTAL, argv=["sleep", "300"])
    state["editor"] = pane


def e2():
    check("a pane running one command counts as running", state["editor"].is_running_command())
    win().activate_action("win.close_pane", None)  # the new pane has focus


def e3():
    d = dialog()
    check("closing it asks", d is not None)
    if d is not None:
        check("heading says pane", d.get_heading() == "Close this pane?", d.get_heading())
        press("Close")


def e4():
    check("editor pane closed", len(tabs()[0].panes()) == 1)


# 4. window close ---------------------------------------------------------------------------


def w1():
    run_in(tabs()[0].focused_pane)


def w2():
    win().close()


def w3():
    d = dialog()
    check("closing the window asks", d is not None)
    if d is not None:
        check("window heading", d.get_heading() == "Close the window?", d.get_heading())
        shot("confirm_window")
        press("Keep open")


def w4():
    check("window stays open on Keep open", win().get_visible() and dialog() is None)


# 5. setting off, then nothing asks ---------------------------------------------------------


def o1():
    w = state["window"] = win()
    general = dataclasses.replace(w._config.general, confirm_close_running=False)
    w._config = dataclasses.replace(w._config, general=general)
    w.close()


def o2():
    w = state["window"]
    check("window closed without asking when the setting is off",
          not w.get_visible() and w.get_visible_dialog() is None)


# 6. a program that exits by itself never asks (new window state from scratch) -------------


STEPS = [
    (s1, 1500), (s1b, 1000), (s2, 800), (s3, 600), (s4, 600), (s5, 500), (s6, 600), (s7, 500), (s8, 500),
    (t1, 1500), (t1b, 1000), (t2, 800), (t3, 500), (t4, 600), (t5, 500), (t6, 500),
    (e1, 800), (e2, 600), (e3, 500), (e4, 500),
    (w1, 1000), (w2, 700), (w3, 500), (w4, 500),
    (o1, 800), (o2, 500),
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
subprocess.run(["pkill", "-f", "sleep 300"], check=False)
print("RESULT", "ALL PASSED" if not fails else fails, flush=True)
