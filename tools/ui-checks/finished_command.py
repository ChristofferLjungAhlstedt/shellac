"""Finished-command notifications: a tab marker and a desktop notification.

Run with: tools/ui-checks/run.sh tools/ui-checks/finished_command.py
Real shells run real `sleep` commands. The threshold is lowered to 2 s to keep it quick, and
the "window is away" case is made by overriding is_active (Xvfb has no window manager to
take focus away). Notifications are captured instead of sent.
"""

import dataclasses
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib  # noqa: E402

import shellac.window  # noqa: E402
from shellac.application import Application  # noqa: E402

SHOT = os.environ["SHOTDIR"]
fails: list[str] = []
sent: list[str] = []
app = Application()
app.hold()


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
    return [(view.get_nth_page(i), win()._containers[view.get_nth_page(i)])
            for i in range(view.get_n_pages())]


def run_in(index, command):
    tabs()[index][1].focused_pane.send_text(command + "\n")


def marked(index):
    return tabs()[index][0].get_needs_attention()


def configure(**changes):
    general = dataclasses.replace(win()._config.general, **changes)
    win()._config = dataclasses.replace(win()._config, general=general)


def capture_notifications():
    real_send = app.send_notification
    real_text = shellac.window.notification_text

    def record_text(tab_title, finished):
        title, body = real_text(tab_title, finished)
        texts.append((title, body))
        return title, body

    def record_send(ident, notification):
        sent.append(ident)
        real_send(ident, notification)

    shellac.window.notification_text = record_text
    app.send_notification = record_send


texts: list[tuple[str, str]] = []
state: dict = {}


def s1():
    capture_notifications()
    configure(finished_after_seconds=2)
    win().new_tab()
    win()._select_tab(0)


def s2():
    run_in(1, "sleep 4")  # a long command in the tab that is not showing


def s3():
    check("running: no marker yet", not marked(1))


def s4():
    pass  # wait for the sleep to end and for the 1 s poll to see it


def s5():
    check("background tab is marked when its command ends", marked(1))
    check("no popup while the window is in use", not sent, str(sent))
    shot("finished_marker")
    win()._select_tab(1)


def s6():
    check("selecting the tab clears the marker", not marked(1))
    run_in(1, "sleep 0.3")  # too short to report


def s7():
    win()._select_tab(0)


def s8():
    check("a short command is not reported", not marked(1))
    run_in(1, "sleep 4")


def s9():
    pass


def s10():
    pass


def s11():
    check("a second long command marks the tab again", marked(1))
    win()._select_tab(1)
    # Now the window "goes away" while a command runs in the tab that is showing.
    win().is_active = lambda: False
    run_in(1, "sleep 4")


def s12():
    pass


def s13():
    pass


def s14():
    check("a notification is sent when the window is away", len(sent) == 1, str(sent))
    check("notification names the command and the time",
          len(texts) == 1 and "\u201csleep\u201d finished after" in texts[0][1], str(texts))
    check("no marker on the tab that was showing", not marked(1))
    del win().is_active


def s15():
    # Coming back to the window withdraws the popup.
    check("popup is still tracked while away", len(win()._finished_ids) == 1)
    win().notify("is-active")


def s15b():
    check("coming back withdraws it", not win()._finished_ids)


def s16():
    configure(finished_tab_marker=False, finished_notification=False)
    win()._select_tab(0)
    sent.clear()
    run_in(1, "sleep 4")


def s17():
    pass


def s18():
    pass


def s19():
    check("nothing happens when both are off", not marked(1) and not sent, str(sent))


STEPS = [
    (s1, 1500), (s2, 1500), (s3, 1500), (s4, 2500), (s5, 700), (s6, 800), (s7, 800),
    (s8, 1500), (s9, 2500), (s10, 1500), (s11, 1000), (s12, 2500), (s13, 1500), (s14, 500),
    (s15, 500), (s15b, 300), (s16, 1500), (s17, 2500), (s18, 1500), (s19, 300),
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
subprocess.run(["pkill", "-f", "sleep 4"], check=False)
print("RESULT", "ALL PASSED" if not fails else fails, flush=True)
