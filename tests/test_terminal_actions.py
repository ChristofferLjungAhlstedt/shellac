import os
import pty
import shlex
import subprocess
import time
from pathlib import Path

from paneterm.terminal_actions import (
    cd_command,
    editor_argv,
    foreground_name,
    is_shell_idle,
    path_text,
)


def test_cd_command_round_trips_through_a_real_shell(tmp_path: Path):
    for name in [
        "plain",
        "with space",
        "it's",
        '"quoted"',
        "$(touch pwned)",
        "a;b&c|d",
        "-dash",
        "näme ü",
    ]:
        target = tmp_path / name
        target.mkdir()
        result = subprocess.run(
            ["sh", "-c", cd_command(str(target)) + "pwd"],
            capture_output=True,
            text=True,
            cwd="/",
        )
        assert result.stdout.strip() == str(target), name
    assert not (tmp_path / "pwned").exists()
    assert not Path("/pwned").exists()


def test_cd_command_keeps_newlines_in_names_inside_the_quotes():
    line = cd_command("/tmp/new\nline")
    assert line.endswith("\n")
    # The newline inside the name is quoted, so the shell still sees a single cd argument.
    assert shlex.split(line) == ["cd", "--", "/tmp/new\nline"]


def test_path_text_quotes_and_leaves_a_space():
    assert path_text("/a b") == "'/a b' "
    assert shlex.split(path_text("/tmp/it's")) == ["/tmp/it's"]


def test_editor_precedence_config_then_visual_then_editor(tmp_path: Path):
    for name in ("cfgedit", "visedit", "edited"):
        script = tmp_path / name
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
    env = {"PATH": str(tmp_path), "VISUAL": "visedit", "EDITOR": "edited"}
    assert editor_argv("/f", "cfgedit", env) == ["cfgedit", "/f"]
    assert editor_argv("/f", "", env) == ["visedit", "/f"]
    assert editor_argv("/f", "", {"PATH": str(tmp_path), "EDITOR": "edited"}) == ["edited", "/f"]


def test_editor_setting_may_carry_arguments(tmp_path: Path):
    script = tmp_path / "myedit"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    env = {"PATH": str(tmp_path)}
    assert editor_argv("/f", "myedit --wait -n", env) == ["myedit", "--wait", "-n", "/f"]


def test_unusable_editor_falls_through_to_the_next_source(tmp_path: Path):
    good = tmp_path / "good"
    good.write_text("#!/bin/sh\n")
    good.chmod(0o755)
    env = {"PATH": str(tmp_path), "VISUAL": "does-not-exist", "EDITOR": "good"}
    assert editor_argv("/f", "'unbalanced", env) == ["good", "/f"]


def test_no_editor_installed_gives_none(tmp_path: Path):
    assert editor_argv("/f", "", {"PATH": str(tmp_path)}) is None


def test_idle_detection_on_a_real_pty():
    """A shell at its prompt is idle; while it runs a command it is not."""
    master, slave = pty.openpty()

    def make_session_leader():
        os.setsid()
        import fcntl
        import termios

        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

    shell = subprocess.Popen(
        ["sh", "-c", "set -m; sleep 0.4; sleep 5"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        preexec_fn=make_session_leader,
        close_fds=True,
    )
    try:
        time.sleep(0.15)
        # While the shell's first command runs in its own job group, the shell is not
        # in the foreground.
        assert is_shell_idle(master, shell.pid) is False
        assert foreground_name(master) in ("sleep", None)
        assert is_shell_idle(master, None) is False
    finally:
        shell.kill()
        shell.wait()
        os.close(master)
        os.close(slave)


def test_idle_detection_with_a_closed_descriptor_is_false():
    r, w = os.pipe()
    os.close(r)
    os.close(w)
    assert is_shell_idle(r, 1234) is False
    assert foreground_name(r) is None
