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


def st():
    return win()._settings


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
    xdo("key", "ctrl+comma")


def pos(path):
    _ok, b = st()._reset_buttons[path].compute_bounds(st())
    return (round(b.get_x()), round(b.get_y()), round(b.get_width()))


def s2():
    global P0
    P0 = pos(("appearance", "font_size"))
    check(
        "reset hidden when default",
        st()._reset_buttons[("appearance", "font_size")].get_opacity() == 0.0,
    )
    check("Ctrl+, opens settings", st() is not None and st().get_visible())
    shot("m19_appearance")
    check("save disabled when clean", not st()._save.get_sensitive())
    st()._set(("appearance", "font_size"), 15.0)
    st()._set(("appearance", "theme"), "one-light")
    st()._set(("tabs", "autohide"), False)
    st()._set(("appearance", "font_family"), "DejaVu Sans Mono")


def s3():
    P1 = pos(("appearance", "font_size"))
    check("reset button keeps its place when it appears", P0 == P1 and P1[2] > 10, f"{P0} {P1}")
    check("save enabled", st()._save.get_sensitive())
    check("theme previewed live", app.theme.id == "one-light", app.theme.id)
    check(
        "font previewed live",
        app.config.appearance.font_size == 15.0,
        str(app.config.appearance.font_size),
    )
    check(
        "font on a real pane",
        win()._current_container().focused_pane.terminal.get_font().get_size() > 0,
    )
    check("saved config still old", win()._saved_config.appearance.font_size == 12.0)
    check("config untouched", "font_size" not in cfg(), cfg())
    check("count label", "4 unsaved" in st()._count.get_label(), st()._count.get_label())
    shot("m19_dirty")
    st().close()


def s4():
    check("close asks first", st().get_visible() and st()._dirty())
    shot("m19_dialog")
    xdo("key", "Escape")


def s5():
    check("Esc keeps editing", st()._dirty())
    st()._save.emit("clicked")


def s6():
    c = cfg()
    check(
        "config written",
        "font_size = 15.0" in c
        and "DejaVu Sans Mono" in c
        and 'theme = "one-light"' in c
        and "autohide = false" in c,
        c,
    )
    check(
        "applied",
        app.config.appearance.font_size == 15.0
        and app.theme.id == "one-light"
        and not app.config.tabs.autohide,
        f"{app.config.appearance.font_size} {app.theme.id}",
    )
    check("clean after save", not st()._dirty())
    check("theme persists as config", app._theme_override is None)
    st().open("terminal")


def s7():
    shot("m19_terminal")
    st().open("sidebar")


def s8():
    shot("m19_sidebar")
    st().open("keybindings")


def s9():
    shot("m19_keys")
    st()._set(("appearance", "follow_system_scheme"), True)
    st().open("appearance")


def s10():
    check(
        "dark_theme row enabled when following",
        st()._rows[("appearance", "dark_theme")].get_sensitive(),
    )
    check(
        "per-row reset visible",
        st()._reset_buttons[("appearance", "font_size")].get_opacity() == 1.0,
    )
    st()._reset_everything()


def s11():
    check("Reset puts defaults in draft", st()._draft[("appearance", "font_size")] == 12.0)
    check(
        "Reset previewed, file untouched",
        app.config.appearance.font_size == 12.0 and "font_size = 15.0" in cfg(),
    )
    shot("m19_reset")
    st()._save.emit("clicked")


def s12():
    check(
        "config cleaned of defaults",
        "font_size" not in cfg()
        and "font_family" not in cfg()
        and "autohide" not in cfg()
        and "theme =" not in cfg(),
        cfg(),
    )
    check(
        "defaults applied",
        app.config.appearance.font_size == 12.0 and app.theme.id == "catppuccin-mocha",
        app.theme.id,
    )


def s12b():
    st()._set(("appearance", "opacity"), 0.5)
    st()._set(("appearance", "padding"), 30)


def s12c():
    check(
        "opacity+padding previewed",
        app.config.appearance.opacity == 0.5 and app.config.appearance.padding == 30,
    )
    check("config file untouched", "opacity" not in cfg(), cfg())
    st()._cancel.emit("clicked")


def s12d():
    check(
        "cancel reverts preview",
        app.config.appearance.opacity == 0.95 and app.config.appearance.padding == 8,
        str(app.config.appearance.opacity),
    )
    xdo("key", "ctrl+comma")


def s12e():
    app.cycle_theme()


def s12f():
    check(
        "settings theme row follows cycled theme",
        st()._draft[("appearance", "theme")] == app.theme.id
        and st()._saved[("appearance", "theme")] == app.theme.id,
        app.theme.id,
    )
    check("not dirty after cycle", not st()._dirty(), str(st()._changes()))
    xdo("key", "ctrl+shift+p")


def s12g():
    check("follows again", st()._draft[("appearance", "theme")] == app.theme.id, app.theme.id)


def s12h():
    global BEFORE
    BEFORE = app.theme.id
    st()._set(("appearance", "theme"), "nord")


def s13():
    check("preview nord", app.theme.id == "nord")
    st()._cancel.emit("clicked")


def s14():
    check(
        "cancel restores theme",
        app.theme.id == BEFORE and not st().get_visible(),
        app.theme.id + " " + BEFORE,
    )
    xdo("key", "ctrl+comma")


def s15():
    check("reopens", st().get_visible() and not st()._dirty())
    st()._on_open_shortcuts()


def s16():
    p = win()._palette
    check("shortcut editor opens in edit mode", p is not None and p._editing)
    shot("m19_to_palette")
    p._cancel.emit("clicked")
    win().close()
    app.quit()


steps = [
    (s1, 1200),
    (s2, 800),
    (s3, 500),
    (s4, 600),
    (s5, 500),
    (s6, 1500),
    (s7, 600),
    (s8, 600),
    (s9, 600),
    (s10, 600),
    (s11, 600),
    (s12, 1500),
    (s12b, 300),
    (s12c, 500),
    (s12d, 600),
    (s12e, 600),
    (s12f, 500),
    (s12g, 600),
    (s12h, 500),
    (s13, 700),
    (s14, 600),
    (s15, 600),
    (s16, 300),
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
