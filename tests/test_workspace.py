from pathlib import Path

from shellac.pane_tree import Axis
from shellac.session import PaneState, SplitState, TabState, panes_of
from shellac.workspace import (
    HEADER,
    MAX_COMMANDS_SHOWN,
    WORKSPACE_FILE,
    PaneValues,
    build_tab,
    commands_in,
    confirm_text,
    folder_text,
    make_draft,
    pane_positions,
    parse_workspace,
    workspace_file,
    workspace_to_toml,
)


def project(tmp_path: Path) -> str:
    for name in ("api", "web", "logs"):
        (tmp_path / name).mkdir()
    return str(tmp_path)


def test_one_pane_per_tab_by_default(tmp_path: Path):
    folder = project(tmp_path)
    result = parse_workspace('[[tab]]\nrun = "make"\n', folder)
    assert result.error is None and result.warnings == ()
    assert result.workspace.tabs == (TabState(PaneState(folder, "make")),)


def test_two_panes_side_by_side_with_ratio_and_directories(tmp_path: Path):
    folder = project(tmp_path)
    text = """
[[tab]]
split = "right"
ratio = 0.3
[[tab.pane]]
dir = "api"
run = "nvim ."
[[tab.pane]]
dir = "web"
"""
    tab = parse_workspace(text, folder).workspace.tabs[0]
    assert tab.layout == SplitState(
        Axis.HORIZONTAL,
        0.3,
        PaneState(f"{folder}/api", "nvim ."),
        PaneState(f"{folder}/web", None),
    )


def test_nested_splits_and_down_means_stacked(tmp_path: Path):
    folder = project(tmp_path)
    text = """
[[tab]]
[[tab.pane]]
run = "a"
[[tab.pane]]
split = "down"
[[tab.pane.pane]]
run = "b"
[[tab.pane.pane]]
run = "c"
"""
    tab = parse_workspace(text, folder).workspace.tabs[0]
    assert tab.layout.axis == Axis.HORIZONTAL  # the default is side by side
    inner = tab.layout.second
    assert isinstance(inner, SplitState) and inner.axis == Axis.VERTICAL
    assert [p.command for p in panes_of(tab.layout)] == ["a", "b", "c"]


def test_more_than_two_panes_share_the_space_equally(tmp_path: Path):
    folder = project(tmp_path)
    text = "[[tab]]\n" + "[[tab.pane]]\n" * 4
    layout = parse_workspace(text, folder).workspace.tabs[0].layout
    ratios = []
    while isinstance(layout, SplitState):
        ratios.append(round(layout.ratio, 3))
        layout = layout.second
    assert ratios == [0.25, 0.333, 0.5]


def test_dir_on_a_split_is_the_default_for_its_panes(tmp_path: Path):
    folder = project(tmp_path)
    text = """
[[tab]]
dir = "api"
[[tab.pane]]
[[tab.pane]]
dir = "~"
"""
    first, second = panes_of(parse_workspace(text, folder).workspace.tabs[0].layout)
    assert first.cwd == f"{folder}/api"
    assert second.cwd == str(Path("~").expanduser())


def test_focus_picks_the_pane_to_focus(tmp_path: Path):
    text = "[[tab]]\n[[tab.pane]]\n[[tab.pane]]\nfocus = true\n"
    assert parse_workspace(text, project(tmp_path)).workspace.tabs[0].focused == 1


def test_several_tabs(tmp_path: Path):
    text = '[[tab]]\nrun = "one"\n[[tab]]\nrun = "two"\n'
    workspace = parse_workspace(text, project(tmp_path)).workspace
    assert len(workspace.tabs) == 2
    assert commands_in(workspace) == ["one", "two"]


def test_missing_folder_warns_and_falls_back(tmp_path: Path):
    folder = project(tmp_path)
    result = parse_workspace('[[tab]]\ndir = "nope"\n', folder)
    assert result.workspace.tabs[0].layout.cwd == folder
    assert "nope is not a folder" in result.warnings[0]


def test_odd_values_warn_and_use_defaults(tmp_path: Path):
    folder = project(tmp_path)
    text = """
[[tab]]
split = "diagonal"
ratio = "wide"
[[tab.pane]]
run = 5
[[tab.pane]]
"""
    result = parse_workspace(text, folder)
    layout = result.workspace.tabs[0].layout
    assert layout.axis == Axis.HORIZONTAL and layout.ratio == 0.5
    assert panes_of(layout)[0].command is None
    assert len(result.warnings) == 3


def test_ratio_with_three_panes_is_ignored_with_a_warning(tmp_path: Path):
    text = "[[tab]]\nratio = 0.9\n" + "[[tab.pane]]\n" * 3
    result = parse_workspace(text, project(tmp_path))
    assert any("two panes" in w for w in result.warnings)
    assert round(result.workspace.tabs[0].layout.ratio, 3) == 0.333


def test_a_ratio_out_of_range_is_clamped(tmp_path: Path):
    text = "[[tab]]\nratio = 7\n[[tab.pane]]\n[[tab.pane]]\n"
    ratio = parse_workspace(text, project(tmp_path)).workspace.tabs[0].layout.ratio
    assert 0.0 < ratio < 1.0


def test_a_single_child_is_just_that_pane(tmp_path: Path):
    text = '[[tab]]\n[[tab.pane]]\nrun = "x"\n'
    assert isinstance(parse_workspace(text, project(tmp_path)).workspace.tabs[0].layout, PaneState)


def test_bad_files_give_an_error_not_an_exception(tmp_path: Path):
    folder = project(tmp_path)
    for text in ("", "nothing here = 1", "[[tab]\n", "tab = 3"):
        result = parse_workspace(text, folder)
        assert result.workspace is None and result.error, text


def test_a_pane_entry_that_is_not_a_list_recovers_with_a_warning(tmp_path: Path):
    result = parse_workspace("[[tab]]\npane = 5\nrun = 'x'", project(tmp_path))
    assert result.workspace is not None and result.warnings
    assert commands_in(result.workspace) == ["x"]


def test_toml_syntax_error_names_the_line(tmp_path: Path):
    result = parse_workspace('[[tab]]\nrun = "unterminated\n', project(tmp_path))
    assert result.workspace is None and "line 2" in result.error


def test_too_many_panes_is_an_error(tmp_path: Path):
    text = "[[tab]]\n" + "[[tab.pane]]\n" * 70
    assert "more than" in parse_workspace(text, project(tmp_path)).error


def test_extreme_nesting_is_cut_off_not_crashed(tmp_path: Path):
    text = "[[tab]]\n" + "".join(f"[[tab{'.pane' * n}]]\n" for n in range(1, 40))
    result = parse_workspace(text, project(tmp_path))
    assert result.workspace is not None or result.error


def test_commands_and_confirmation_text(tmp_path: Path):
    text = '[[tab]]\n[[tab.pane]]\nrun = "nvim ."\n[[tab.pane]]\nrun = "npm test"\n'
    workspace = parse_workspace(text, project(tmp_path)).workspace
    assert commands_in(workspace) == ["nvim .", "npm test"]
    heading, body = confirm_text(commands_in(workspace))
    assert heading == "Run these commands?"
    assert "• nvim ." in body and "• npm test" in body and "trust" in body


def test_confirmation_text_cuts_a_long_list():
    commands = [f"cmd{i}" for i in range(MAX_COMMANDS_SHOWN + 3)]
    _heading, body = confirm_text(commands)
    assert "and 3 more" in body and f"cmd{MAX_COMMANDS_SHOWN}" not in body


def test_workspace_file_is_found_only_when_there(tmp_path: Path):
    assert workspace_file(str(tmp_path)) is None
    (tmp_path / WORKSPACE_FILE).write_text("[[tab]]\n")
    assert workspace_file(str(tmp_path)) == str(tmp_path / WORKSPACE_FILE)


def test_a_saved_tab_reads_back_the_same(tmp_path: Path):
    folder = project(tmp_path)
    layout = SplitState(
        Axis.HORIZONTAL,
        0.3,
        PaneState(f"{folder}/api"),
        SplitState(Axis.VERTICAL, 0.5, PaneState(folder), PaneState(f"{folder}/logs")),
    )
    text = workspace_to_toml(TabState(layout), folder)
    assert 'dir = "api"' in text and 'dir = "logs"' in text and "ratio = 0.3" in text
    result = parse_workspace(text, folder)
    assert result.warnings == () and result.workspace.tabs == (TabState(layout),)


def test_a_saved_single_pane_and_outside_directories(tmp_path: Path):
    folder = project(tmp_path)
    outside = tmp_path.parent
    text = workspace_to_toml(TabState(PaneState(str(outside))), folder)
    assert f'dir = "{outside}"' in text
    assert parse_workspace(text, folder).workspace.tabs[0].layout == PaneState(str(outside))
    assert parse_workspace(workspace_to_toml(TabState(PaneState(folder)), folder), folder)


def test_odd_characters_in_a_directory_survive_the_round_trip(tmp_path: Path):
    odd = tmp_path / 'my "proj" åäö #1'
    odd.mkdir()
    folder = str(tmp_path)
    tab = TabState(SplitState(Axis.VERTICAL, 0.5, PaneState(str(odd)), PaneState(folder)))
    assert parse_workspace(workspace_to_toml(tab, folder), folder).workspace.tabs == (tab,)


# -- the template and the editing dialog -----------------------------------------------------


def three_panes(folder: str) -> TabState:
    return TabState(
        SplitState(
            Axis.HORIZONTAL,
            0.3,
            PaneState(f"{folder}/api"),
            SplitState(Axis.VERTICAL, 0.5, PaneState(f"{folder}/web"), PaneState(folder)),
        )
    )


def test_a_new_file_explains_itself(tmp_path: Path):
    folder = project(tmp_path)
    text = workspace_to_toml(three_panes(folder), folder)
    assert text.startswith(HEADER)
    for hint in (
        'split = "right"',
        "ratio",
        'dir   = "api"',
        'run   = "npm run dev"',
        "focus = true",
    ):
        assert hint in text, hint
    assert "Open Workspace" in text and "another [[tab]]" in text
    assert text.count('# run = "command to type when this pane opens"') == 3


def test_the_hint_is_left_out_where_a_command_exists(tmp_path: Path):
    folder = project(tmp_path)
    tab = TabState(SplitState(Axis.HORIZONTAL, 0.5, PaneState(folder, "make"), PaneState(folder)))
    text = workspace_to_toml(tab, folder)
    assert text.count('# run = "command to type') == 1 and 'run = "make"' in text
    assert parse_workspace(text, folder).workspace.tabs == (tab,)


def test_the_template_is_valid_and_reads_back_with_focus(tmp_path: Path):
    folder = project(tmp_path)
    tab = TabState(three_panes(folder).layout, focused=2)
    text = workspace_to_toml(tab, folder)
    assert text.splitlines().count("focus = true") == 1  # the header only mentions it
    result = parse_workspace(text, folder)
    assert result.warnings == () and result.workspace.tabs == (tab,)
    first_focused = workspace_to_toml(three_panes(folder), folder)  # the first pane is the default
    assert "focus = true" not in first_focused.splitlines()


def test_folder_text(tmp_path: Path):
    folder = str(tmp_path)
    assert folder_text(folder, folder) == ""
    assert folder_text(f"{folder}/api/v1", folder) == "api/v1"
    assert folder_text("/elsewhere", folder) == "/elsewhere"
    assert folder_text(None, folder) == ""


def test_starting_uses_the_current_directories_and_no_commands(tmp_path: Path):
    folder = project(tmp_path)
    draft = make_draft(three_panes(folder), folder, None)
    assert draft.existing is False and draft.note is None
    assert draft.values == (PaneValues("api", ""), PaneValues("web", ""), PaneValues("", ""))


def test_updating_keeps_folders_and_commands_when_the_panes_match(tmp_path: Path):
    folder = project(tmp_path)
    old = """
[[tab]]
[[tab.pane]]
dir = "logs"
run = "tail -f app.log"
[[tab.pane]]
split = "down"
[[tab.pane.pane]]
run = "npm run dev"
[[tab.pane.pane]]
dir = "web"
"""
    draft = make_draft(three_panes(folder), folder, old)
    assert draft.existing is True
    assert draft.values == (
        PaneValues("logs", "tail -f app.log"),
        PaneValues("", "npm run dev"),
        PaneValues("web", ""),
    )
    assert draft.shape.layout.ratio == 0.3  # the layout is the current tab's
    assert "comments you added are not kept" in draft.note


def test_updating_to_a_different_number_of_panes_starts_over_and_says_so(tmp_path: Path):
    folder = project(tmp_path)
    draft = make_draft(three_panes(folder), folder, '[[tab]]\nrun = "make"\n')
    assert draft.values == (PaneValues("api", ""), PaneValues("web", ""), PaneValues("", ""))
    assert "3 panes and the saved workspace has 1" in draft.note


def test_a_file_with_several_tabs_is_flagged(tmp_path: Path):
    folder = project(tmp_path)
    draft = make_draft(TabState(PaneState(folder)), folder, "[[tab]]\n[[tab]]\n[[tab]]\n")
    assert "3 tabs; only this tab is kept" in draft.note


def test_an_unreadable_file_is_replaced_with_a_note(tmp_path: Path):
    folder = project(tmp_path)
    draft = make_draft(TabState(PaneState(folder)), folder, "[[tab]\n")
    assert draft.existing and "could not be read" in draft.note


def test_build_tab_applies_the_values_in_order(tmp_path: Path):
    folder = project(tmp_path)
    shape = three_panes(folder)
    values = [PaneValues("web", "a"), PaneValues("", " b "), PaneValues("logs", "")]
    tab, problems = build_tab(shape, folder, values)
    assert problems == {}
    assert [(p.cwd, p.command) for p in panes_of(tab.layout)] == [
        (f"{folder}/web", "a"),
        (folder, "b"),
        (f"{folder}/logs", None),
    ]
    assert tab.layout.ratio == 0.3 and tab.layout.axis == Axis.HORIZONTAL


def test_build_tab_reports_every_bad_folder_and_builds_nothing(tmp_path: Path):
    folder = project(tmp_path)
    values = [PaneValues("nope", ""), PaneValues("", ""), PaneValues("also/missing", "")]
    tab, problems = build_tab(three_panes(folder), folder, values)
    assert tab is None and sorted(problems) == [0, 2]
    assert "nope is not a folder" in problems[0]


def test_pane_positions_name_where_each_pane_is(tmp_path: Path):
    folder = str(tmp_path)
    assert pane_positions(PaneState(folder)) == ["Only pane"]
    assert pane_positions(three_panes(folder).layout) == ["Left", "Top right", "Bottom right"]
    grid = SplitState(
        Axis.VERTICAL,
        0.5,
        SplitState(Axis.HORIZONTAL, 0.5, PaneState("a"), PaneState("b")),
        SplitState(Axis.HORIZONTAL, 0.5, PaneState("c"), PaneState("d")),
    )
    assert pane_positions(grid) == ["Top left", "Top right", "Bottom left", "Bottom right"]
