import pytest

from pdf_workbench.core.models import (
    CustomSplitDirection,
    CustomSplitNode,
    FourSplitOrder,
    PageSplitSettings,
    SplitMode,
    coerce_four_split_order,
    coerce_split_mode,
    collapse_custom_split,
    custom_leaf_paths,
    custom_node_at_path,
    merge_custom_leaves,
    split_custom_leaf,
)


def test_split_mode_string_is_coerced_to_enum() -> None:
    assert coerce_split_mode("four") is SplitMode.FOUR
    assert coerce_split_mode("horizontal_2") is SplitMode.HORIZONTAL_2
    assert coerce_split_mode("custom") is SplitMode.CUSTOM


def test_four_split_order_string_is_coerced_to_enum() -> None:
    assert coerce_four_split_order("rtl_tb") is FourSplitOrder.RTL_TB


def test_normalized_settings_coerce_qt_style_string_values() -> None:
    settings = PageSplitSettings()
    settings.mode = "four"  # type: ignore[assignment]
    settings.order = "rtl_tb"  # type: ignore[assignment]

    normalized = settings.normalized()

    assert normalized.mode is SplitMode.FOUR
    assert normalized.order is FourSplitOrder.RTL_TB


def test_custom_split_leaf_can_be_split_recursively() -> None:
    root = CustomSplitNode()
    split_custom_leaf(root, (), CustomSplitDirection.VERTICAL, ratio=0.6)
    split_custom_leaf(root, (0,), CustomSplitDirection.HORIZONTAL, ratio=0.25)

    assert custom_leaf_paths(root) == [(0, 0), (0, 1), (1,)]
    right = custom_node_at_path(root, (0,))
    assert right.direction is CustomSplitDirection.HORIZONTAL
    assert right.ratio == 0.25


def test_custom_split_clone_is_independent() -> None:
    settings = PageSplitSettings(mode=SplitMode.CUSTOM)
    split_custom_leaf(settings.custom_root, (), CustomSplitDirection.VERTICAL)

    cloned = settings.clone()
    split_custom_leaf(cloned.custom_root, (0,), CustomSplitDirection.HORIZONTAL)

    assert custom_leaf_paths(settings.custom_root) == [(0,), (1,)]
    assert custom_leaf_paths(cloned.custom_root) == [(0, 0), (0, 1), (1,)]


def test_custom_split_can_collapse_selected_subtree() -> None:
    root = CustomSplitNode()
    split_custom_leaf(root, (), CustomSplitDirection.VERTICAL)
    split_custom_leaf(root, (0,), CustomSplitDirection.HORIZONTAL)
    split_custom_leaf(root, (0, 0), CustomSplitDirection.VERTICAL)

    collapse_custom_split(root, (0,))

    assert custom_leaf_paths(root) == [(0,), (1,)]
    collapsed = custom_node_at_path(root, (0,))
    assert collapsed.is_leaf
    assert collapsed.first is None
    assert collapsed.second is None


def test_custom_split_can_merge_rectangular_leaf_selection() -> None:
    root = CustomSplitNode()
    split_custom_leaf(root, (), CustomSplitDirection.HORIZONTAL)
    split_custom_leaf(root, (0,), CustomSplitDirection.VERTICAL)
    split_custom_leaf(root, (1,), CustomSplitDirection.VERTICAL)

    # Merge the two top-row cells into one full-width top region.
    merge_custom_leaves(root, {(0, 0), (0, 1)})

    assert len(custom_leaf_paths(root)) == 3


def test_custom_split_rejects_l_shaped_merge() -> None:
    root = CustomSplitNode()
    split_custom_leaf(root, (), CustomSplitDirection.HORIZONTAL)
    split_custom_leaf(root, (0,), CustomSplitDirection.VERTICAL)
    split_custom_leaf(root, (1,), CustomSplitDirection.VERTICAL)

    with pytest.raises(ValueError, match="長方形"):
        merge_custom_leaves(root, {(0, 0), (0, 1), (1, 0)})
