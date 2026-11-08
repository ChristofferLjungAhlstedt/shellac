import json
from pathlib import Path

from shellac.pane_tree import MAX_RATIO, MIN_RATIO, Axis, Leaf, PaneTree, Split
from shellac.session import (
    MAX_PANES,
    MAX_TABS,
    PaneState,
    SessionState,
    SplitState,
    TabState,
    capture_tab,
    first_cwd,
    pane_count,
    replay,
    session_from_data,
    session_to_data,
)
from shellac.state import UiState, load_state, save_state


def cwd_of(payload: str) -> str | None:
    return payload or None


def sample_tree() -> PaneTree:
    """a | (b over c), with the divider of the first split moved."""
    tree = PaneTree("/a")
    b = tree.split(tree.focused, Axis.HORIZONTAL, "/b")
    tree.split(b, Axis.VERTICAL, "/c")
    assert isinstance(tree.root, Split)
    tree.root.ratio = 0.3
    return tree


def rebuild(tab: TabState) -> PaneTree:
    tree = PaneTree(first_cwd(tab.layout))

    def split(leaf: Leaf, axis: Axis, ratio: float, cwd: str | None) -> Leaf:
        new = tree.split(leaf, axis, cwd)
        assert new.parent is not None
        new.parent.ratio = ratio
        return new

    assert isinstance(tree.root, Leaf)
    replay(tab.layout, tree.root, split)
    return tree


# -- capture ----------------------------------------------------------------------------


def test_capture_records_shape_ratio_directories_and_focus():
    tree = sample_tree()
    tab = capture_tab(tree, cwd_of)
    assert tab == TabState(
        SplitState(
            Axis.HORIZONTAL,
            0.3,
            PaneState("/a"),
            SplitState(Axis.VERTICAL, 0.5, PaneState("/b"), PaneState("/c")),
        ),
        focused=2,
    )


def test_capture_notes_the_zoomed_pane_but_not_for_a_single_pane():
    tree = sample_tree()
    tree.set_focus(tree.leaves()[1])
    tree.toggle_zoom()
    tab = capture_tab(tree, cwd_of)
    assert tab is not None and (tab.focused, tab.zoomed) == (1, 1)
    assert capture_tab(PaneTree("/x"), cwd_of) == TabState(PaneState("/x"))


def test_unknown_directory_is_kept_as_unknown():
    assert capture_tab(PaneTree(""), cwd_of) == TabState(PaneState(None))


def test_panes_that_are_not_kept_are_dropped_and_their_split_collapses():
    tree = sample_tree()
    tab = capture_tab(tree, cwd_of, keep=lambda p: p != "/b")
    assert tab == TabState(
        SplitState(Axis.HORIZONTAL, 0.3, PaneState("/a"), PaneState("/c")), focused=1
    )
    assert capture_tab(PaneTree("/only"), cwd_of, keep=lambda _p: False) is None


def test_dropping_the_focused_pane_falls_back_to_the_first():
    tree = sample_tree()  # focus is on /c
    tab = capture_tab(tree, cwd_of, keep=lambda p: p != "/c")
    assert tab is not None and tab.focused == 0


# -- replay -----------------------------------------------------------------------------


def test_replay_rebuilds_the_same_layout():
    original = capture_tab(sample_tree(), cwd_of)
    assert original is not None
    rebuilt = rebuild(original)
    again = capture_tab(rebuilt, cwd_of)
    assert again is not None
    assert again.layout == original.layout
    assert [leaf.payload for leaf in rebuilt.leaves()] == ["/a", "/b", "/c"]


def test_replay_handles_a_left_heavy_layout():
    layout = SplitState(
        Axis.VERTICAL,
        0.7,
        SplitState(Axis.HORIZONTAL, 0.4, PaneState("/1"), PaneState("/2")),
        PaneState("/3"),
    )
    rebuilt = rebuild(TabState(layout))
    assert [leaf.payload for leaf in rebuilt.leaves()] == ["/1", "/2", "/3"]
    again = capture_tab(rebuilt, cwd_of)
    assert again is not None and again.layout == layout


def test_pane_count_and_first_cwd():
    layout = capture_tab(sample_tree(), cwd_of).layout
    assert pane_count(layout) == 3
    assert first_cwd(layout) == "/a"


# -- JSON -------------------------------------------------------------------------------


def test_session_round_trips_through_json():
    tab = capture_tab(sample_tree(), cwd_of)
    session = SessionState((tab, TabState(PaneState(None))), selected=1)
    data = json.loads(json.dumps(session_to_data(session)))
    assert session_from_data(data) == session


def test_state_file_round_trip_keeps_the_session(tmp_path: Path):
    path = tmp_path / "state.json"
    session = SessionState((capture_tab(sample_tree(), cwd_of),), selected=0)
    assert save_state(UiState(sidebar_width=300, session=session), path)
    loaded = load_state(path)
    assert loaded.session == session and loaded.sidebar_width == 300


def test_state_without_a_session_stays_without_one(tmp_path: Path):
    path = tmp_path / "state.json"
    save_state(UiState(), path)
    assert "session" not in json.loads(path.read_text())
    assert load_state(path).session is None


def test_garbage_never_raises_and_gives_none():
    for data in (None, 5, "x", [], {}, {"tabs": 3}, {"tabs": []}, {"tabs": [5, None, "x"]}):
        assert session_from_data(data) is None, data


def test_bad_tabs_are_dropped_good_ones_kept():
    good = {"layout": {"cwd": "/g"}}
    bad_axis = {"layout": {"axis": "diagonal", "first": {}, "second": {}}}
    missing_child = {"layout": {"axis": "horizontal", "first": {}}}
    session = session_from_data({"tabs": [bad_axis, good, missing_child]})
    assert session == SessionState((TabState(PaneState("/g")),))


def test_bad_field_values_are_repaired():
    data = {
        "selected": 99,
        "tabs": [
            {
                "focused": "x",
                "zoomed": 7,
                "layout": {
                    "axis": "vertical",
                    "ratio": 5,
                    "first": {"cwd": 12},
                    "second": {"cwd": ""},
                },
            }
        ],
    }
    session = session_from_data(data)
    assert session is not None and session.selected == 0
    tab = session.tabs[0]
    assert (tab.focused, tab.zoomed) == (0, None)
    assert isinstance(tab.layout, SplitState)
    assert tab.layout.ratio == MAX_RATIO
    assert tab.layout.first == tab.layout.second == PaneState(None)

    data["tabs"][0]["layout"]["ratio"] = True
    assert session_from_data(data).tabs[0].layout.ratio == 0.5
    data["tabs"][0]["layout"]["ratio"] = -1
    assert session_from_data(data).tabs[0].layout.ratio == MIN_RATIO


def test_a_single_pane_ignores_zoom():
    data = {"tabs": [{"layout": {"cwd": "/a"}, "zoomed": 0}]}
    assert session_from_data(data).tabs[0].zoomed is None


def test_sizes_are_capped():
    data = {"tabs": [{"layout": {"cwd": "/a"}}] * (MAX_TABS + 30)}
    assert len(session_from_data(data).tabs) == MAX_TABS

    layout: dict = {}
    for _ in range(MAX_PANES + 5):
        layout = {"axis": "horizontal", "first": {}, "second": layout}
    assert session_from_data({"tabs": [{"layout": layout}]}) is None


def test_extreme_nesting_does_not_overflow_the_stack():
    layout: dict = {}
    for _ in range(5000):
        layout = {"axis": "horizontal", "first": layout, "second": {}}
    assert session_from_data({"tabs": [{"layout": layout}]}) is None
