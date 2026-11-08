"""Session restore, end to end: build tabs and splits, quit, start a second process, compare.

Run with: tools/ui-checks/run.sh tools/ui-checks/session_restore.py
Phase 1 builds the layout and quits; it then starts itself again as phase 2 (same HOME and
state directory) to see what came back. Both phases print CHECK lines.
"""

import json
import os
import subprocess
import sys

from gi.repository import GLib

from shellac.application import Application
from shellac.pane_tree import Axis

PHASE = sys.argv[1] if len(sys.argv) > 1 else "build"
SHOT = os.environ["SHOTDIR"]
STATE = os.environ["XDG_STATE_HOME"] + "/shellac/state.json"
CFG_DIR = os.environ["XDG_CONFIG_HOME"] + "/shellac"
BASE = os.environ["HOME"] + "/work"
DIRS = {name: f"{BASE}/{name}" for name in ("a", "b", "c", "d", "e")}

fails: list[str] = []


def check(label, ok, detail=""):
    print(f"[{PHASE}] " + ("CHECK PASS " if ok else "CHECK FAIL ") + label
          + (f" [{detail}]" if detail else ""), flush=True)
    if not ok:
        fails.append(label)


def shot(name):
    subprocess.run(["import", "-window", "root", f"{SHOT}/{PHASE}_{name}.png"], check=False)


def real(path):
    return os.path.realpath(path)


app = Application()
app.hold()


def win():
    return app.props.active_window


def containers():
    w = win()
    view = w._tab_view
    return [w._containers[view.get_nth_page(i)] for i in range(view.get_n_pages())]


def cwds(container):
    return [real(p.current_directory() or "") for p in container.panes()]


def ratios(container):
    return [round(split.ratio, 2) for split in container._paneds]


# -- phase 1: build -------------------------------------------------------------------------


def b1():
    for d in DIRS.values():
        os.makedirs(d, exist_ok=True)
    w = win()
    first = w._current_container()
    # Tab 1 starts in $HOME; give it a layout: a | (home over a)
    first.split(Axis.HORIZONTAL, cwd=DIRS["a"])
    # Tab 2: b | c, plus an editor-style pane that must not be restored
    t2 = w.new_tab(cwd=DIRS["b"])
    t2.split(Axis.HORIZONTAL, cwd=DIRS["c"])
    t2.split(Axis.VERTICAL, argv=["sleep", "600"], cwd=DIRS["c"])
    # Tab 3: d over e, zoomed on e
    t3 = w.new_tab(cwd=DIRS["d"])
    t3.split(Axis.VERTICAL, cwd=DIRS["e"])
    t3.toggle_zoom()
    # Select the middle tab
    w._select_tab(1)


def b2():
    # Let the layout settle, then move the first divider of tab 2 off 50/50.
    t2 = containers()[1]
    split = next(iter(t2._paneds))
    paned = t2._paneds[split]
    extent = paned.get_width()
    check("tab 2 has a real size", extent > 100, str(extent))
    paned.set_position(int(extent * 0.3))


def b3():
    t2 = containers()[1]
    check("divider moved in the model", 0.25 < t2.tree.root.ratio < 0.35, str(t2.tree.root.ratio))
    shot("built")
    win()._save_state()
    data = json.load(open(STATE))
    check("session written to state.json", "session" in data and len(data["session"]["tabs"]) == 3)
    check("selected tab saved", data["session"]["selected"] == 1, str(data["session"]["selected"]))
    t2_data = data["session"]["tabs"][1]
    panes = json.dumps(t2_data["layout"]).count("cwd")
    check("editor pane left out of tab 2", panes == 2, json.dumps(t2_data["layout"]))
    check("zoom saved for tab 3", data["session"]["tabs"][2].get("zoomed") == 1)


def b4():
    app.release()
    win().close()  # the normal close path: do_close_request saves again and ends the shells
    GLib.idle_add(app.quit)


# -- phase 2: restore (phase 3, "fresh", then starts after every shell exited) -----------------------------------------------------------------------


def r1():
    w = win()
    tabs = containers()
    check("three tabs restored", len(tabs) == 3, str(len(tabs)))
    if len(tabs) != 3:
        return
    check("selected tab restored", w._current_container() is tabs[1])
    t1, t2, t3 = tabs
    check("tab 1: two panes, home and a", cwds(t1) == [real(os.environ["HOME"]), real(DIRS["a"])],
          str(cwds(t1)))
    check("tab 2: two panes b and c (editor dropped)", cwds(t2) == [real(DIRS["b"]), real(DIRS["c"])],
          str(cwds(t2)))
    check("tab 3: d and e", cwds(t3) == [real(DIRS["d"]), real(DIRS["e"])], str(cwds(t3)))
    check("tab 3 zoomed on e", t3.tree.zoomed is t3.tree.leaves()[1])
    check("tab 3 focus is the zoomed pane", t3.tree.focused is t3.tree.leaves()[1])
    check("tab 1 splits side by side", t1.tree.root.axis == Axis.HORIZONTAL)
    check("tab 3 splits stacked", t3.tree.root.axis == Axis.VERTICAL)


def r2():
    t2 = containers()[1]
    paned = next(iter(t2._paneds.values()))
    extent = paned.get_width()
    share = paned.get_position() / extent if extent else -1
    check("divider position restored on screen", 0.25 < share < 0.35, f"{share:.2f}")
    check("divider position in the model", 0.25 < t2.tree.root.ratio < 0.35,
          str(t2.tree.root.ratio))
    shot("restored")
    # Focus: the selected tab's focused pane has keyboard focus.
    pane = containers()[1].focused_pane
    print(f"[restore] INFO window active={win().is_active()} "
          f"pane has focus={pane.terminal.has_focus()}", flush=True)
    check("focused pane holds keyboard focus", pane.terminal.has_focus())


def r3():
    # Restore must not have lost the session: closing again re-saves the same thing.
    win()._save_state()
    data = json.load(open(STATE))
    check("session survives a second save", len(data["session"]["tabs"]) == 3)
    # Exit every shell: the session is cleared.
    for pane in [p for c in containers() for p in c.panes()]:
        pane.send_text("exit\n")


def r4():
    data = json.load(open(STATE))
    check("clearing: no session after the last shell exits", "session" not in data, str(data.keys()))
    app.release()
    GLib.idle_add(app.quit)


STEPS = {
    "build": [(b1, 1500), (b2, 1500), (b3, 800), (b4, 500)],
    "restore": [(r1, 2000), (r2, 1500), (r3, 1500), (r4, 500)],
    "fresh": [],
}[PHASE]
idx = [0]


def run():
    if idx[0] >= len(STEPS):
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


if PHASE == "fresh":
    def f1():
        tabs = containers()
        check("no session means one fresh tab", len(tabs) == 1 and len(tabs[0].panes()) == 1)
        pane = tabs[0].focused_pane
        print(f"[fresh] INFO window active={win().is_active()} pane has focus="
              f"{pane.terminal.has_focus()}", flush=True)
        app.release()
        GLib.idle_add(app.quit)

    STEPS.append((f1, 100))

GLib.timeout_add(2000, run)
app.run([sys.argv[0]])

if PHASE == "build":
    # Same environment, new process: this is the real "restart".
    for phase in ("restore", "fresh"):
        result = subprocess.run([sys.executable, sys.argv[0], phase])
        if result.returncode != 0:
            fails.append(f"{phase} phase exited with {result.returncode}")
    print("RESULT", "ALL PASSED" if not fails else fails, flush=True)
else:
    print(f"[{PHASE}] RESULT", "ALL PASSED" if not fails else fails, flush=True)
    sys.exit(1 if fails else 0)
