import sys, os, subprocess
from gi.repository import GLib
from shellac.application import Application

app = Application()
app.hold()
fails = []
SHOT = os.environ["SHOTDIR"]
CFG = os.environ["XDG_CONFIG_HOME"] + "/shellac/config.toml"


def win():
    return app.props.active_window


def pal():
    return win()._palette


def check(l, c, d=""):
    print(("CHECK PASS " if c else "CHECK FAIL ") + l + (f" [{d}]" if d else ""), flush=True)
    if not c:
        fails.append(l)


def shot(n):
    subprocess.run(["import", "-window", "root", f"{SHOT}/{n}.png"], check=False)


def xdo(*a):
    subprocess.run(["xdotool", *a], check=False)


def cfg():
    return open(CFG).read() if os.path.exists(CFG) else ""


def s1():
    win().activate_action("win.command_palette", None)


def s2():
    pal()._edit_button.set_active(True)


def s3():
    pal()._start_capture("split_right", None)
    pal().grab_focus()


def s4():
    xdo("key", "ctrl+alt+r")


def s5():
    check(
        "draft has second shortcut",
        pal()._draft["split_right"] == ["<Ctrl><Shift>e", "<Ctrl><Alt>r"],
        str(pal()._draft["split_right"]),
    )
    check("NOT applied before save", app.keybindings()["split_right"] == ["<Ctrl><Shift>e"])
    check("config untouched before save", "keybindings" not in cfg(), cfg())
    check("save enabled when dirty", pal()._save.get_sensitive())
    shot("m10_dirty")
    pal()._edit_button.set_active(False)  # try to leave


def s6():
    check("leaving asks first (still editing)", pal()._editing and pal()._edit_button.get_active())
    shot("m10_dialog")
    xdo("key", "Escape")


def s7():
    check("Esc on dialog keeps editing", pal()._editing and pal()._dirty())
    pal()._start_capture("goto_tab_1", 0)
    pal().grab_focus()


def s8():
    xdo("key", "ctrl+alt+3")


def s9():
    d = pal()._draft
    check(
        "goto modifiers staged for all nine",
        [d[f"goto_tab_{n}"] for n in (1, 9)] == [["<Ctrl><Alt>1"], ["<Ctrl><Alt>9"]],
        str([d["goto_tab_1"], d["goto_tab_9"]]),
    )
    pal()._scroller.get_vadjustment().set_value(900)


def s10():
    shot("m10_goto")
    pal()._save.emit("clicked")


def s11():
    b = app.keybindings()
    check(
        "saved: split_right applied",
        b["split_right"] == ["<Ctrl><Shift>e", "<Ctrl><Alt>r"],
        str(b["split_right"]),
    )
    check("saved: goto_tab_5", b["goto_tab_5"] == ["<Ctrl><Alt>5"], str(b["goto_tab_5"]))
    check("config file written", "split_right" in cfg() and "goto_tab_5" in cfg())
    check("left edit mode after save", not pal()._editing)
    pal()._edit_button.set_active(True)


def s12():
    pal()._reset_all.emit("clicked")
    check(
        "Reset puts defaults into the draft",
        pal()._draft["goto_tab_1"] == ["<Alt>1"]
        and pal()._draft["split_right"] == ["<Ctrl><Shift>e"],
    )
    check("Reset not applied until save", app.keybindings()["goto_tab_1"] == ["<Ctrl><Alt>1"])
    pal()._cancel.emit("clicked")


def s13():
    check(
        "Cancel discards and leaves edit",
        not pal()._editing and app.keybindings()["goto_tab_1"] == ["<Ctrl><Alt>1"],
    )
    pal()._edit_button.set_active(True)


def s14():
    pal()._reset_everything()
    pal()._save.emit("clicked")


def s15():
    check(
        "saved reset restores defaults",
        app.keybindings()["goto_tab_1"] == ["<Alt>1"]
        and app.keybindings()["split_right"] == ["<Ctrl><Shift>e"],
        str(app.keybindings()["split_right"]),
    )
    check("config cleaned", "goto_tab" not in cfg() and "split_right" not in cfg(), cfg())
    pal()._edit_button.set_active(True)


def s16():
    pal()._start_capture("copy", 0)
    pal().grab_focus()


def s17():
    xdo("key", "ctrl+alt+9")


def s18():
    check("dirty before closing", pal()._dirty())
    pal().close()


def s19():
    shot("m10_close_dialog")
    check("closing asks first (palette still visible)", pal().get_visible())
    xdo("key", "Escape")


def s20():
    win().close()
    app.quit()


steps = [
    (s1, 1200),
    (s2, 600),
    (s3, 300),
    (s4, 600),
    (s5, 700),
    (s6, 700),
    (s7, 400),
    (s8, 600),
    (s9, 500),
    (s10, 300),
    (s11, 1500),
    (s12, 600),
    (s13, 400),
    (s14, 900),
    (s15, 1600),
    (s16, 400),
    (s17, 600),
    (s18, 800),
    (s19, 500),
    (s20, 0),
]
idx = [0]


def run():
    if idx[0] >= len(steps):
        return False
    fn, dl = steps[idx[0]]
    idx[0] += 1
    try:
        fn()
    except Exception:
        import traceback

        traceback.print_exc()
        fails.append(fn.__name__)
    GLib.timeout_add(dl, run)
    return False


GLib.timeout_add(2000, run)
app.run([sys.argv[0]])
print("RESULT", "ALL PASSED" if not fails else fails, flush=True)
