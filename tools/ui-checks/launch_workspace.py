"""`shellac --workspace FOLDER`: opens that workspace instead of the last session, and a second
launch reaches the window that is already running.

Run with: tools/ui-checks/run.sh tools/ui-checks/launch_workspace.py
"""

import os
import subprocess
import sys

from gi.repository import GLib

from shellac.application import Application
from shellac.session import PaneState, SessionState, TabState
from shellac.state import UiState, save_state
from shellac.workspace import WORKSPACE_FILE

SHOT = os.environ["SHOTDIR"]
HOME = os.environ["HOME"]
ONE = f"{HOME}/one"
TWO = f"{HOME}/two"
fails: list[str] = []
state: dict = {}


def check(label, ok, detail=""):
    print(("CHECK PASS " if ok else "CHECK FAIL ") + label + (f" [{detail}]" if detail else ""),
          flush=True)
    if not ok:
        fails.append(label)


def tabs():
    view = app.props.active_window._tab_view
    return [app.props.active_window._containers[view.get_nth_page(i)] for i in range(view.get_n_pages())]


def write(folder, text):
    os.makedirs(f"{folder}/api", exist_ok=True)
    with open(f"{folder}/{WORKSPACE_FILE}", "w") as handle:
        handle.write(text)


# Before anything starts: a saved session of three tabs, which must NOT come back.
write(ONE, '[[tab]]\nsplit = "right"\n[[tab.pane]]\ndir = "api"\n[[tab.pane]]\n')
write(TWO, '[[tab]]\n[[tab.pane]]\n\n[[tab]]\ndir = "api"\n')
session = SessionState(tuple(TabState(PaneState(HOME)) for _ in range(3)))
save_state(UiState(session=session))

app = Application()
app.hold()


def a1():
    found = tabs()
    check("the saved session is not restored", len(found) == 1, str(len(found)))
    if found:
        check("and no empty tab is left behind", len(found[0].panes()) == 2, str(len(found[0].panes())))
        dirs = [os.path.realpath(p.current_directory() or "") for p in found[0].panes()]
        check("the workspace's directories", dirs[0] == os.path.realpath(f"{ONE}/api"), str(dirs))
    # A second launch, as a separate process, hands its folder to this window.
    state["proc"] = subprocess.Popen(
        [sys.executable, "-m", "shellac", "--workspace", TWO],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def a2():
    proc = state["proc"]
    try:
        code = proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        code = None
    check("the second launch exits at once", code == 0, str(code))
    check("and its workspace opened here", len(tabs()) == 3, str(len(tabs())))
    subprocess.run(["import", "-window", "root", f"{SHOT}/launch_workspace.png"], check=False)
    # Arguments that cannot work are refused before any window opens.
    for argument, wanted in ((f"{HOME}/nowhere", "not a folder"), (HOME, WORKSPACE_FILE)):
        done = subprocess.run([sys.executable, "-m", "shellac", "--workspace", argument],
                              capture_output=True, text=True, timeout=10)
        check(f"bad argument ({wanted})", done.returncode == 2 and wanted in done.stderr,
              f"{done.returncode} {done.stderr.strip()}")


STEPS = [(a1, 2500), (a2, 500)]
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


GLib.timeout_add(2500, run)
app.run([sys.argv[0], "--workspace", ONE])
print("RESULT", "ALL PASSED" if not fails else fails, flush=True)
