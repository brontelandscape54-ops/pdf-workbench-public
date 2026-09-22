from pdf_workbench.core.geometry import crop_regions, split_regions
from pdf_workbench.core.models import (
    CustomSplitDirection,
    FourSplitOrder,
    PageSplitSettings,
    SplitMode,
    reorder_custom_subset,
    split_custom_leaf,
)


def test_horizontal_two_split_center() -> None:
    s = PageSplitSettings(mode=SplitMode.HORIZONTAL_2, y_ratio=0.5)
    assert crop_regions(1000, 800, s) == [
        ("top", (0, 0, 1000, 400)),
        ("bottom", (0, 400, 1000, 800)),
    ]


def test_horizontal_two_split_with_overlap() -> None:
    s = PageSplitSettings(mode=SplitMode.HORIZONTAL_2, y_ratio=0.25, overlap_px=10)
    assert crop_regions(1000, 800, s) == [
        ("top", (0, 0, 1000, 210)),
        ("bottom", (0, 190, 1000, 800)),
    ]


def test_horizontal_two_split_ownership_ignores_overlap() -> None:
    s = PageSplitSettings(mode=SplitMode.HORIZONTAL_2, y_ratio=0.25, overlap_px=10)
    regions = split_regions(1000, 800, s)
    assert [(r.name, r.crop_box, r.ownership_box) for r in regions] == [
        ("top", (0, 0, 1000, 210), (0, 0, 1000, 200)),
        ("bottom", (0, 190, 1000, 800), (0, 200, 1000, 800)),
    ]


def test_four_split_rtl_tb() -> None:
    s = PageSplitSettings(
        mode=SplitMode.FOUR,
        x_ratio=0.6,
        y_ratio=0.25,
        order=FourSplitOrder.RTL_TB,
    )
    assert crop_regions(1000, 800, s) == [
        ("right_top", (600, 0, 1000, 200)),
        ("right_bottom", (600, 200, 1000, 800)),
        ("left_top", (0, 0, 600, 200)),
        ("left_bottom", (0, 200, 600, 800)),
    ]


def test_four_split_ownership_partitions_page() -> None:
    s = PageSplitSettings(
        mode=SplitMode.FOUR,
        x_ratio=0.6,
        y_ratio=0.25,
        overlap_px=10,
        order=FourSplitOrder.RTL_TB,
    )
    regions = split_regions(1000, 800, s)
    by_name = {region.name: region for region in regions}
    assert by_name["right_top"].ownership_box == (600, 0, 1000, 200)
    assert by_name["right_bottom"].ownership_box == (600, 200, 1000, 800)
    assert by_name["left_top"].ownership_box == (0, 0, 600, 200)
    assert by_name["left_bottom"].ownership_box == (0, 200, 600, 800)


def test_custom_split_can_subdivide_only_one_region() -> None:
    s = PageSplitSettings(mode=SplitMode.CUSTOM)
    split_custom_leaf(s.custom_root, (), CustomSplitDirection.VERTICAL, ratio=0.6)
    split_custom_leaf(s.custom_root, (0,), CustomSplitDirection.HORIZONTAL, ratio=0.25)

    regions = split_regions(1000, 800, s)
    assert [(r.name, r.ownership_box) for r in regions] == [
        ("custom_001", (600, 0, 1000, 200)),
        ("custom_002", (600, 200, 1000, 800)),
        ("custom_003", (0, 0, 600, 800)),
    ]


def test_custom_split_overlap_expands_crop_not_ownership() -> None:
    s = PageSplitSettings(mode=SplitMode.CUSTOM, overlap_px=10)
    split_custom_leaf(s.custom_root, (), CustomSplitDirection.VERTICAL, ratio=0.6)
    split_custom_leaf(s.custom_root, (0,), CustomSplitDirection.HORIZONTAL, ratio=0.25)

    regions = split_regions(1000, 800, s)
    assert [(r.crop_box, r.ownership_box) for r in regions] == [
        ((590, 0, 1000, 210), (600, 0, 1000, 200)),
        ((590, 190, 1000, 800), (600, 200, 1000, 800)),
        ((0, 0, 610, 800), (0, 0, 600, 800)),
    ]


def test_custom_split_ownership_exactly_partitions_page() -> None:
    s = PageSplitSettings(mode=SplitMode.CUSTOM)
    split_custom_leaf(s.custom_root, (), CustomSplitDirection.HORIZONTAL, ratio=0.4)
    split_custom_leaf(s.custom_root, (1,), CustomSplitDirection.VERTICAL, ratio=0.3)

    regions = split_regions(1000, 800, s)
    total = sum(
        (r.ownership_box[2] - r.ownership_box[0])
        * (r.ownership_box[3] - r.ownership_box[1])
        for r in regions
    )
    assert total == 1000 * 800


def test_custom_order_changes_actual_export_order() -> None:
    s = PageSplitSettings(mode=SplitMode.CUSTOM)
    split_custom_leaf(s.custom_root, (), CustomSplitDirection.VERTICAL, ratio=0.6)
    split_custom_leaf(s.custom_root, (0,), CustomSplitDirection.HORIZONTAL, ratio=0.25)
    s.custom_order = [(1,), (0, 1), (0, 0)]

    regions = split_regions(1000, 800, s)
    assert [r.ownership_box for r in regions] == [
        (0, 0, 600, 800),
        (600, 200, 1000, 800),
        (600, 0, 1000, 200),
    ]


def test_reorder_custom_subset_only_changes_selected_consecutive_block() -> None:
    s = PageSplitSettings(mode=SplitMode.CUSTOM)
    split_custom_leaf(s.custom_root, (), CustomSplitDirection.VERTICAL)
    split_custom_leaf(s.custom_root, (0,), CustomSplitDirection.HORIZONTAL)
    split_custom_leaf(s.custom_root, (1,), CustomSplitDirection.HORIZONTAL)
    s.custom_order = [(0, 0), (0, 1), (1, 0), (1, 1)]

    reordered = reorder_custom_subset(
        s.custom_root,
        s.custom_order,
        {(0, 1), (1, 0)},
        [(1, 0), (0, 1)],
    )
    assert reordered == [(0, 0), (1, 0), (0, 1), (1, 1)]


def test_reorder_custom_subset_rejects_nonconsecutive_numbers() -> None:
    s = PageSplitSettings(mode=SplitMode.CUSTOM)
    split_custom_leaf(s.custom_root, (), CustomSplitDirection.VERTICAL)
    split_custom_leaf(s.custom_root, (0,), CustomSplitDirection.HORIZONTAL)
    split_custom_leaf(s.custom_root, (1,), CustomSplitDirection.HORIZONTAL)
    s.custom_order = [(0, 0), (0, 1), (1, 0), (1, 1)]

    import pytest

    with pytest.raises(ValueError):
        reorder_custom_subset(
            s.custom_root,
            s.custom_order,
            {(0, 0), (1, 0)},
            [(1, 0), (0, 0)],
        )


def test_no_split() -> None:
    s = PageSplitSettings(mode=SplitMode.NONE)
    assert crop_regions(1000, 800, s) == [("full", (0, 0, 1000, 800))]


def test_crop_regions_remains_compatible() -> None:
    s = PageSplitSettings(mode=SplitMode.HORIZONTAL_2, y_ratio=0.5, overlap_px=7)
    assert crop_regions(100, 80, s) == [
        (region.name, region.crop_box)
        for region in split_regions(100, 80, s)
    ]


def test_ratios_are_clamped() -> None:
    s = PageSplitSettings(mode=SplitMode.FOUR, x_ratio=-5, y_ratio=8)
    result = crop_regions(100, 100, s)
    for _name, (x0, y0, x1, y1) in result:
        assert 0 <= x0 < x1 <= 100
        assert 0 <= y0 < y1 <= 100
