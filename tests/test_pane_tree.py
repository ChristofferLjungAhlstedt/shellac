import pytest

from paneterm.pane_tree import (
    MAX_RATIO,
    MIN_RATIO,
    Axis,
    Direction,
    Leaf,
    PaneTree,
    Rect,
    Split,
)


def payloads(tree: PaneTree) -> list:
    return [leaf.payload for leaf in tree.leaves()]


def by_payload(tree: PaneTree, payload) -> Leaf:
    return next(leaf for leaf in tree.leaves() if leaf.payload == payload)


def assert_consistent(tree: PaneTree) -> None:
    """Parent links must agree with child links everywhere."""
    if tree.root is None:
        return
    assert tree.root.parent is None

    def walk(node):
        if isinstance(node, Split):
            assert node.first.parent is node
            assert node.second.parent is node
            walk(node.first)
            walk(node.second)

    walk(tree.root)
    assert tree.focused in tree.leaves()


# -- splitting --------------------------------------------------------------------------


def test_new_tree_has_one_focused_leaf():
    tree = PaneTree("a")
    assert payloads(tree) == ["a"]
    assert tree.focused is tree.root
    assert not tree.is_empty


def test_split_adds_second_pane_and_focuses_it():
    tree = PaneTree("a")
    new = tree.split(tree.focused, Axis.HORIZONTAL, "b")
    assert payloads(tree) == ["a", "b"]
    assert tree.focused is new
    assert isinstance(tree.root, Split)
    assert tree.root.ratio == 0.5
    assert tree.root.axis is Axis.HORIZONTAL
    assert_consistent(tree)


def test_split_of_nested_leaf_replaces_it_in_its_parent():
    tree = PaneTree("a")
    b = tree.split(tree.focused, Axis.HORIZONTAL, "b")
    tree.split(b, Axis.VERTICAL, "c")
    assert payloads(tree) == ["a", "b", "c"]
    assert_consistent(tree)
    assert isinstance(tree.root, Split)
    assert isinstance(tree.root.second, Split)
    assert tree.root.second.axis is Axis.VERTICAL


def test_splits_nest_to_arbitrary_depth():
    tree = PaneTree(0)
    for i in range(1, 40):
        axis = Axis.HORIZONTAL if i % 2 else Axis.VERTICAL
        tree.split(tree.focused, axis, i)
    assert payloads(tree) == list(range(40))
    assert_consistent(tree)


def test_split_of_a_foreign_leaf_is_rejected():
    tree = PaneTree("a")
    with pytest.raises(ValueError):
        tree.split(Leaf("stranger"), Axis.HORIZONTAL)


# -- closing ----------------------------------------------------------------------------


def test_closing_the_only_pane_empties_the_tree():
    tree = PaneTree("a")
    assert tree.close(tree.focused) is None
    assert tree.is_empty
    assert tree.focused is None
    assert tree.leaves() == []


def test_closing_a_pane_collapses_the_split_and_sibling_takes_over():
    tree = PaneTree("a")
    b = tree.split(tree.focused, Axis.HORIZONTAL, "b")
    assert tree.close(b) is tree.root
    assert isinstance(tree.root, Leaf)
    assert tree.root.payload == "a"
    assert tree.root.parent is None
    assert_consistent(tree)


def test_closing_the_first_pane_also_collapses():
    tree = PaneTree("a")
    tree.split(tree.focused, Axis.HORIZONTAL, "b")
    tree.close(by_payload(tree, "a"))
    assert payloads(tree) == ["b"]
    assert tree.focused is tree.root
    assert_consistent(tree)


def test_closing_a_middle_pane_collapses_only_its_own_split():
    tree = PaneTree("a")
    b = tree.split(tree.focused, Axis.HORIZONTAL, "b")
    tree.split(b, Axis.VERTICAL, "c")  # a | (b / c)
    tree.close(by_payload(tree, "b"))
    assert payloads(tree) == ["a", "c"]
    assert isinstance(tree.root, Split)
    assert isinstance(tree.root.second, Leaf)
    assert_consistent(tree)


def test_closing_any_pane_in_a_grid_leaves_a_consistent_tree():
    for victim in "abcd":
        tree = PaneTree("a")
        b = tree.split(by_payload(tree, "a"), Axis.HORIZONTAL, "b")
        tree.split(by_payload(tree, "a"), Axis.VERTICAL, "c")
        tree.split(b, Axis.VERTICAL, "d")
        assert sorted(payloads(tree)) == list("abcd")
        tree.close(by_payload(tree, victim))
        assert sorted(payloads(tree)) == sorted(set("abcd") - {victim})
        assert_consistent(tree)


def test_closing_the_focused_pane_focuses_the_nearest_leaf_in_the_sibling():
    tree = PaneTree("a")
    b = tree.split(tree.focused, Axis.HORIZONTAL, "b")
    c = tree.split(b, Axis.VERTICAL, "c")
    d = tree.split(c, Axis.HORIZONTAL, "d")  # a | (b / (c | d))
    tree.set_focus(by_payload(tree, "a"))
    tree.close(by_payload(tree, "a"))  # a was first, so nearest in the sibling is its first leaf
    assert tree.focused.payload == "b"
    tree.set_focus(d)
    tree.close(d)  # d was second, sibling is c
    assert tree.focused.payload == "c"


def test_closing_an_unfocused_pane_keeps_focus():
    tree = PaneTree("a")
    tree.split(tree.focused, Axis.HORIZONTAL, "b")
    assert tree.focused.payload == "b"
    tree.close(by_payload(tree, "a"))
    assert tree.focused.payload == "b"


def test_closing_a_leaf_twice_is_rejected():
    tree = PaneTree("a")
    b = tree.split(tree.focused, Axis.HORIZONTAL, "b")
    tree.close(b)
    with pytest.raises(ValueError):
        tree.close(b)


# -- zoom -------------------------------------------------------------------------------


def test_zoom_toggles_on_the_focused_pane():
    tree = PaneTree("a")
    b = tree.split(tree.focused, Axis.HORIZONTAL, "b")
    assert tree.toggle_zoom() is b
    assert tree.toggle_zoom() is None


def test_zoom_of_a_single_pane_is_a_no_op():
    tree = PaneTree("a")
    assert tree.toggle_zoom() is None
    assert tree.zoomed is None


def test_splitting_while_zoomed_unzooms():
    tree = PaneTree("a")
    tree.split(tree.focused, Axis.HORIZONTAL, "b")
    tree.toggle_zoom()
    tree.split(tree.focused, Axis.VERTICAL, "c")
    assert tree.zoomed is None


def test_closing_the_zoomed_pane_unzooms():
    tree = PaneTree("a")
    b = tree.split(tree.focused, Axis.HORIZONTAL, "b")
    tree.split(b, Axis.HORIZONTAL, "c")
    tree.toggle_zoom()
    tree.close(tree.zoomed)
    assert tree.zoomed is None


def test_closing_a_background_pane_keeps_zoom_unless_one_pane_remains():
    tree = PaneTree("a")
    b = tree.split(tree.focused, Axis.HORIZONTAL, "b")
    tree.split(b, Axis.HORIZONTAL, "c")
    zoomed = tree.toggle_zoom()
    tree.close(by_payload(tree, "a"))
    assert tree.zoomed is zoomed
    tree.close(by_payload(tree, "b"))
    assert tree.zoomed is None


def test_zoomed_rects_fill_the_area():
    tree = PaneTree("a")
    b = tree.split(tree.focused, Axis.HORIZONTAL, "b")
    tree.toggle_zoom()
    assert tree.compute_rects(100, 50) == {b: Rect(0, 0, 100, 50)}


# -- geometry and directional focus -----------------------------------------------------


def test_compute_rects_for_a_side_by_side_and_stacked_layout():
    tree = PaneTree("a")
    b = tree.split(tree.focused, Axis.HORIZONTAL, "b")
    c = tree.split(b, Axis.VERTICAL, "c")  # a | (b / c)
    rects = tree.compute_rects(200, 100)
    assert rects[by_payload(tree, "a")] == Rect(0, 0, 100, 100)
    assert rects[b] == Rect(100, 0, 100, 50)
    assert rects[c] == Rect(100, 50, 100, 50)


def grid(tree_payloads="abcd"):
    """a b
    c d   (built by splitting, so tree order is a, c, b, d)"""
    tree = PaneTree("a")
    b = tree.split(by_payload(tree, "a"), Axis.HORIZONTAL, "b")
    tree.split(by_payload(tree, "a"), Axis.VERTICAL, "c")
    tree.split(b, Axis.VERTICAL, "d")
    return tree


def test_directional_focus_follows_geometry_not_tree_order():
    tree = grid()
    rects = tree.compute_rects(200, 200)
    a, b, c, d = (by_payload(tree, p) for p in "abcd")
    assert tree.find_neighbor(Direction.RIGHT, rects, a) in (b, d)
    assert tree.find_neighbor(Direction.DOWN, rects, a) is c
    assert tree.find_neighbor(Direction.LEFT, rects, d) in (a, c)
    assert tree.find_neighbor(Direction.UP, rects, d) is b
    assert tree.find_neighbor(Direction.LEFT, rects, c) is None
    assert tree.find_neighbor(Direction.DOWN, rects, c) is None


def test_ties_go_to_the_most_recently_focused_pane():
    tree = grid()
    rects = tree.compute_rects(200, 200)
    a, b, d = (by_payload(tree, p) for p in "abd")
    # From a, moving right, b (top) and d (bottom) are both adjacent only if they
    # overlap vertically; a spans the full height of its own cell, so only b overlaps.
    assert tree.find_neighbor(Direction.RIGHT, rects, a) is b

    # A tall pane on the left next to two stacked panes on the right is a real tie.
    tall = PaneTree("l")
    top = tall.split(tall.focused, Axis.HORIZONTAL, "top")
    bottom = tall.split(top, Axis.VERTICAL, "bottom")
    rects = tall.compute_rects(200, 200)
    left = by_payload(tall, "l")
    tall.set_focus(bottom)
    tall.set_focus(top)
    tall.set_focus(left)
    assert tall.find_neighbor(Direction.RIGHT, rects) is top
    tall.set_focus(bottom)
    tall.set_focus(left)
    assert tall.find_neighbor(Direction.RIGHT, rects) is bottom


def test_directional_focus_ignores_panes_that_do_not_overlap_on_the_other_axis():
    tree = PaneTree("a")
    b = tree.split(tree.focused, Axis.HORIZONTAL, "b")
    a = by_payload(tree, "a")
    rects = {a: Rect(0, 0, 100, 100), b: Rect(100, 150, 100, 100)}
    assert tree.find_neighbor(Direction.RIGHT, rects, a) is None


def test_directional_focus_prefers_the_nearest_pane():
    tree = PaneTree("a")
    b = tree.split(tree.focused, Axis.HORIZONTAL, "b")
    c = tree.split(b, Axis.HORIZONTAL, "c")
    a = by_payload(tree, "a")
    rects = {a: Rect(0, 0, 100, 100), b: Rect(100, 0, 100, 100), c: Rect(200, 0, 100, 100)}
    assert tree.find_neighbor(Direction.RIGHT, rects, a) is b
    assert tree.find_neighbor(Direction.LEFT, rects, c) is b


def test_directional_focus_with_unknown_origin_returns_none():
    tree = PaneTree("a")
    assert tree.find_neighbor(Direction.RIGHT, {}, tree.focused) is None


# -- resizing ---------------------------------------------------------------------------


def test_resize_target_is_the_nearest_split_on_the_matching_axis():
    tree = PaneTree("a")
    b = tree.split(tree.focused, Axis.HORIZONTAL, "b")
    c = tree.split(b, Axis.VERTICAL, "c")  # a | (b / c)
    assert tree.resize_target(c, Direction.DOWN) is c.parent
    assert tree.resize_target(c, Direction.RIGHT) is tree.root
    assert tree.resize_target(by_payload(tree, "a"), Direction.DOWN) is None


def test_resize_moves_the_divider_and_clamps():
    tree = PaneTree("a")
    b = tree.split(tree.focused, Axis.HORIZONTAL, "b")
    split = tree.resize(b, Direction.RIGHT, 0.1)
    assert split is tree.root
    assert split.ratio == pytest.approx(0.6)
    tree.resize(b, Direction.LEFT, 0.3)
    assert split.ratio == pytest.approx(0.3)
    for _ in range(20):
        tree.resize(b, Direction.LEFT, 0.3)
    assert split.ratio == MIN_RATIO
    for _ in range(20):
        tree.resize(b, Direction.RIGHT, 0.3)
    assert split.ratio == MAX_RATIO


def test_resize_with_no_matching_split_does_nothing():
    tree = PaneTree("a")
    assert tree.resize(tree.focused, Direction.RIGHT, 0.1) is None
