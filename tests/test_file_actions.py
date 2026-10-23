import stat
from pathlib import Path

import pytest

from paneterm.config import SidebarConfig, parse_config
from paneterm.file_actions import (
    HOLD_SCRIPT,
    Plan,
    Problem,
    build_argv,
    hold_open,
    open_with_command,
    plan_file_action,
)


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "bin"
    folder.mkdir()
    for name in ("nano", "vim", "glow", "bat"):
        tool = folder / name
        tool.write_text("#!/bin/sh\n")
        tool.chmod(0o755)
    return folder


@pytest.fixture
def env(bin_dir: Path) -> dict[str, str]:
    return {"PATH": str(bin_dir)}


def config(**options) -> SidebarConfig:
    return SidebarConfig(**options)


def test_default_opens_the_editor_in_a_split(env, bin_dir):
    plan = plan_file_action("/p/a.txt", config(), env)
    assert plan == Plan("split", [str(bin_dir / "nano"), "/p/a.txt"])


def test_editor_tab_and_configured_editor(env, bin_dir):
    plan = plan_file_action("/p/a.txt", config(on_file_activate="editor_tab", editor="vim -R"), env)
    assert plan == Plan("tab", ["vim", "-R", "/p/a.txt"])


def test_no_editor_is_a_problem():
    result = plan_file_action("/p/a.txt", config(), {"PATH": "/nonexistent"})
    assert isinstance(result, Problem) and "editor" in result.message.lower()


def test_open_with_wins_over_the_editor_by_extension_or_name(env):
    table = {"md": "glow -p {path}", "Makefile": "bat"}
    assert open_with_command("README.MD", table) == "glow -p {path}"
    assert open_with_command("Makefile", table) == "bat"
    assert open_with_command("a.txt", table) is None
    plan = plan_file_action("/p/README.md", config(open_with={"md": "glow -p {path}"}), env)
    assert plan.argv[1:] == ["-p", "/p/README.md"] and plan.argv[0].endswith("glow")


def test_open_with_accepts_a_leading_dot(env):
    assert open_with_command("a.py", {".py": "x"}) == "x"


def test_command_mode_holds_the_pane_open(env):
    plan = plan_file_action(
        "/p/a.txt", config(on_file_activate="command_split", file_command="bat"), env
    )
    assert plan.placement == "split"
    assert plan.argv[:3] == ["/bin/sh", "-c", HOLD_SCRIPT]
    assert plan.argv[-1] == "/p/a.txt"
    plain = plan_file_action(
        "/p/a.txt",
        config(on_file_activate="command_tab", file_command="bat", keep_pane_open=False),
        env,
    )
    assert plain.placement == "tab" and plain.argv[0].endswith("bat")


def test_command_mode_without_a_command_explains_what_to_set(env):
    result = plan_file_action("/p/a.txt", config(on_file_activate="command_split"), env)
    assert isinstance(result, Problem) and "file_command" in result.message


def test_run_needs_an_executable_file(tmp_path, env):
    script = tmp_path / "go.sh"
    script.write_text("#!/bin/sh\necho hi\n")
    plan = plan_file_action(str(script), config(on_file_activate="run"), env)
    assert isinstance(plan, Problem) and "executable" in plan.message
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    plan = plan_file_action(str(script), config(on_file_activate="run"), env)
    assert plan.placement == "split" and plan.argv[-1] == str(script)
    assert plan.argv[0] == "/bin/sh"  # held open so the output can be read


def test_paste_and_desktop_need_no_command():
    assert plan_file_action("/p/a", config(on_file_activate="paste_path")) == Plan("paste")
    assert plan_file_action("/p/a", config(on_file_activate="desktop_open")) == Plan("desktop")


def test_template_placeholders_and_quoting(env):
    argv = build_argv('bat --title "{name} in {dir}" {path}', "/my dir/a b.txt", env)
    assert argv[1:] == ["--title", "a b.txt in /my dir", "/my dir/a b.txt"]
    assert build_argv("bat", "/p/x", env)[-1] == "/p/x"  # path appended when not mentioned


def test_bad_templates_are_problems(env):
    assert isinstance(build_argv('bat "unterminated', "/p/x", env), Problem)
    assert isinstance(build_argv("   ", "/p/x", env), Problem)
    missing = build_argv("no-such-tool {path}", "/p/x", env)
    assert isinstance(missing, Problem) and "no-such-tool" in missing.message


def test_hostile_file_names_stay_single_arguments(env):
    nasty = "/p/$(touch pwned); `id` 'x' \"y\".txt"
    argv = build_argv("bat {path}", nasty, env)
    assert argv[-1] == nasty and len(argv) == 2


def test_held_command_really_runs_and_waits(tmp_path):
    import subprocess

    argv = hold_open(["/bin/echo", "it works"])
    done = subprocess.run(argv, input="\n", capture_output=True, text=True, timeout=10)
    assert "it works" in done.stdout and "exited with status 0" in done.stdout
    argv = hold_open(["/bin/sh", "-c", "exit 3"])
    done = subprocess.run(argv, input="\n", capture_output=True, text=True, timeout=10)
    assert "exited with status 3" in done.stdout


def test_config_accepts_the_new_options_and_rejects_bad_modes():
    ok = parse_config(
        {
            "sidebar": {
                "on_file_activate": "command_tab",
                "file_command": "bat {path}",
                "open_with": {"py": "python {path}"},
                "keep_pane_open": False,
            }
        }
    )
    assert ok.warnings == []
    assert ok.config.sidebar.open_with == {"py": "python {path}"}
    bad = parse_config({"sidebar": {"on_file_activate": "teleport", "open_with": {"py": 3}}})
    assert len(bad.warnings) == 2
    assert bad.config.sidebar.on_file_activate == "editor_split"
