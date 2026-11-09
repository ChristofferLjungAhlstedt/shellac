import os
import pty
import subprocess
import time

from shellac.close_confirm import close_dialog_text
from shellac.config import Config, GeneralConfig
from shellac.terminal_actions import is_command_running


def test_one_named_program():
    heading, body = close_dialog_text("pane", ["vim"])
    assert heading == "Close this pane?"
    assert body == "“vim” is still running in this pane. Closing it ends the program."


def test_one_unnamed_program():
    _heading, body = close_dialog_text("tab", [None])
    assert body.startswith("A program is still running in this tab.")


def test_window_heading_reads_naturally():
    assert close_dialog_text("window", ["make"])[0] == "Close the window?"
    assert close_dialog_text("tab", ["make"])[0] == "Close this tab?"


def test_several_programs_are_listed_once_each():
    _h, body = close_dialog_text("window", ["vim", "ssh", "vim"])
    assert body == (
        "3 programs are still running in this window: “vim” and “ssh”. Closing ends them."
    )


def test_many_programs_are_cut_off_with_a_count():
    _h, body = close_dialog_text("window", ["a", "b", "c", "d", "e"])
    assert "“a”, “b”, “c” and 2 more" in body
    assert body.startswith("5 programs")


def test_mixed_known_and_unknown():
    _h, body = close_dialog_text("tab", ["vim", None, None])
    assert "“vim” and 2 others" in body
    assert "3 programs" in body


def test_only_unknown_programs_have_no_list():
    _h, body = close_dialog_text("tab", [None, None])
    assert body == "2 programs are still running in this tab. Closing ends them."


def test_the_setting_defaults_on():
    assert Config().general.confirm_close_running is True
    assert GeneralConfig().confirm_close_running is True
    assert GeneralConfig().allow_trusted_workspaces is True


def test_command_running_with_no_shell_or_closed_descriptor_is_false():
    assert is_command_running(0, None) is False
    r, w = os.pipe()
    os.close(r)
    os.close(w)
    assert is_command_running(r, 1234) is False


def _shell_with_terminal(script: str):
    master, slave = pty.openpty()

    def make_session_leader():
        import fcntl
        import termios

        os.setsid()
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

    shell = subprocess.Popen(
        ["sh", "-c", script],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        preexec_fn=make_session_leader,
        close_fds=True,
    )
    return master, slave, shell


def test_command_running_follows_the_foreground_group():
    # set -m gives each command its own process group, like an interactive shell.
    master, slave, shell = _shell_with_terminal("set -m; sleep 0.5; sleep 0.8")
    try:
        time.sleep(0.2)
        assert is_command_running(master, shell.pid) is True  # a command has the terminal
        shell.wait()
        # With the shell gone nothing is in the foreground that we can name.
    finally:
        shell.kill()
        shell.wait()
        os.close(master)
        os.close(slave)


def test_command_not_running_when_the_shell_holds_the_terminal():
    # Without job control the command shares the shell's group: the shell is the foreground.
    master, slave, shell = _shell_with_terminal("sleep 0.6")
    try:
        time.sleep(0.2)
        assert is_command_running(master, shell.pid) is False
    finally:
        shell.kill()
        shell.wait()
        os.close(master)
        os.close(slave)
