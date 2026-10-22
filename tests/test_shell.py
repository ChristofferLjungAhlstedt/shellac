from pathlib import Path

from paneterm.shell import (
    COLORTERM_VALUE,
    LAST_RESORT_SHELL,
    TERM_VALUE,
    build_environment,
    resolve_shell,
    resolve_working_directory,
)


def _fake_shell(directory: Path, name: str, executable: bool = True) -> str:
    path = directory / name
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755 if executable else 0o644)
    return str(path)


def test_configured_shell_wins(tmp_path: Path):
    configured = _fake_shell(tmp_path, "myshell")
    env_shell = _fake_shell(tmp_path, "envshell")
    assert resolve_shell(configured, {"SHELL": env_shell}) == configured


def test_env_shell_used_when_nothing_configured(tmp_path: Path):
    env_shell = _fake_shell(tmp_path, "envshell")
    assert resolve_shell("", {"SHELL": env_shell}) == env_shell


def test_non_executable_or_missing_candidates_are_skipped(tmp_path: Path):
    not_exec = _fake_shell(tmp_path, "noexec", executable=False)
    result = resolve_shell(not_exec, {"SHELL": str(tmp_path / "missing")})
    assert result != not_exec
    assert result in ("/bin/zsh", "/bin/bash", LAST_RESORT_SHELL)


def test_environment_forces_term_and_colorterm():
    env = dict(item.split("=", 1) for item in build_environment({"TERM": "xterm-kitty", "A": "b"}))
    assert env["TERM"] == TERM_VALUE
    assert env["COLORTERM"] == COLORTERM_VALUE
    assert env["A"] == "b"


def test_environment_does_not_mutate_the_base():
    base = {"TERM": "dumb"}
    build_environment(base)
    assert base == {"TERM": "dumb"}


def test_working_directory_kept_when_it_exists(tmp_path: Path):
    assert resolve_working_directory(str(tmp_path), home="/home/x") == str(tmp_path)


def test_deleted_working_directory_falls_back_to_home(tmp_path: Path):
    gone = tmp_path / "gone"
    assert resolve_working_directory(str(gone), home="/home/x") == "/home/x"


def test_no_working_directory_falls_back_to_home():
    assert resolve_working_directory(None, home="/home/x") == "/home/x"
