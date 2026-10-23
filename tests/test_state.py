import json
from pathlib import Path

from paneterm.state import UiState, load_state, save_state, state_path


def test_missing_file_means_no_state(tmp_path: Path):
    assert load_state(tmp_path / "nope.json") == UiState()


def test_round_trip(tmp_path: Path):
    path = tmp_path / "sub" / "state.json"
    assert save_state(UiState(sidebar_visible=False, sidebar_width=333), path)
    assert load_state(path) == UiState(sidebar_visible=False, sidebar_width=333)


def test_partial_state_keeps_the_unset_value_unset(tmp_path: Path):
    path = tmp_path / "state.json"
    save_state(UiState(sidebar_visible=True), path)
    assert load_state(path) == UiState(sidebar_visible=True, sidebar_width=None)


def test_damaged_or_wrong_typed_files_never_raise(tmp_path: Path):
    path = tmp_path / "state.json"
    for text in [
        "",
        "{",
        "[]",
        "null",
        '{"sidebar": 5}',
        '{"sidebar": {"visible": "yes", "width": "wide"}}',
    ]:
        path.write_text(text)
        assert load_state(path) == UiState(), text


def test_out_of_range_and_boolean_widths_are_ignored(tmp_path: Path):
    path = tmp_path / "state.json"
    for width in (5, 99999, True, 12.5):
        path.write_text(json.dumps({"sidebar": {"width": width}}))
        assert load_state(path).sidebar_width is None, width


def test_save_failure_is_reported_not_raised(tmp_path: Path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    assert save_state(UiState(sidebar_visible=True), blocker / "state.json") is False


def test_state_path_honours_xdg_state_home(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert state_path() == tmp_path / "paneterm" / "state.json"


def test_save_leaves_no_temporary_file_behind(tmp_path: Path):
    path = tmp_path / "state.json"
    save_state(UiState(sidebar_width=250), path)
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]
