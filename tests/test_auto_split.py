from PIL import Image, ImageDraw

from pdf_workbench.core.auto_split import (
    AUTO_SPLIT_PRESETS,
    build_whitespace_split_plan,
    find_best_whitespace_split,
    get_auto_split_preset,
    graft_auto_split_plan,
)
from pdf_workbench.core.models import (
    CustomSplitDirection,
    CustomSplitNode,
    custom_leaf_paths,
    normalized_custom_order,
)


def test_detects_vertical_gutter_between_text_blocks() -> None:
    image = Image.new("L", (600, 800), 255)
    draw = ImageDraw.Draw(image)
    for y in range(80, 720, 20):
        draw.rectangle((40, y, 265, y + 8), fill=20)
        draw.rectangle((335, y, 560, y + 8), fill=20)

    candidate = find_best_whitespace_split(image)

    assert candidate is not None
    assert candidate.direction is CustomSplitDirection.VERTICAL
    assert 0.47 <= candidate.ratio <= 0.53


def test_detects_horizontal_gutter_between_text_blocks() -> None:
    image = Image.new("L", (800, 600), 255)
    draw = ImageDraw.Draw(image)
    for x in range(50, 750, 25):
        draw.rectangle((x, 40, x + 9, 255), fill=20)
        draw.rectangle((x, 345, x + 9, 560), fill=20)

    candidate = find_best_whitespace_split(image)

    assert candidate is not None
    assert candidate.direction is CustomSplitDirection.HORIZONTAL
    assert 0.47 <= candidate.ratio <= 0.53


def test_blank_image_has_no_meaningful_split() -> None:
    image = Image.new("L", (600, 800), 255)

    assert find_best_whitespace_split(image) is None


def test_recursive_plan_finds_three_clear_columns() -> None:
    image = Image.new("L", (900, 700), 255)
    draw = ImageDraw.Draw(image)
    columns = ((40, 260), (340, 560), (640, 860))
    for y in range(50, 650, 18):
        for x0, x1 in columns:
            draw.rectangle((x0, y, x1, y + 8), fill=25)

    plan = build_whitespace_split_plan(image, max_regions=8)

    assert plan.split_count == 2
    assert plan.leaf_count == 3
    assert len(custom_leaf_paths(plan.root)) == 3


def test_recursive_plan_does_not_split_only_on_normal_line_spacing() -> None:
    image = Image.new("L", (500, 700), 255)
    draw = ImageDraw.Draw(image)
    for y in range(40, 660, 18):
        draw.rectangle((35, y, 465, y + 8), fill=25)

    plan = build_whitespace_split_plan(image, max_regions=12)

    assert plan.split_count == 0
    assert plan.leaf_count == 1


def test_best_first_plan_distributes_budget_across_equally_complex_sides() -> None:
    image = Image.new("L", (1000, 700), 255)
    draw = ImageDraw.Draw(image)
    columns = ((35, 205), (285, 455), (545, 715), (795, 965))
    for y in range(50, 650, 18):
        for x0, x1 in columns:
            draw.rectangle((x0, y, x1, y + 8), fill=25)

    plan = build_whitespace_split_plan(
        image,
        max_regions=4,
        preset=get_auto_split_preset("standard"),
    )

    assert plan.leaf_count == 4
    assert plan.root.direction is CustomSplitDirection.VERTICAL
    assert plan.root.first is not None and not plan.root.first.is_leaf
    assert plan.root.second is not None and not plan.root.second.is_leaf


def test_balance_fallback_splits_large_region_without_clear_whitespace_gutter() -> None:
    image = Image.new("L", (800, 600), 25)

    without_balance = build_whitespace_split_plan(
        image,
        max_regions=4,
        preset=get_auto_split_preset("standard"),
        enable_balance_fallback=False,
    )
    with_balance = build_whitespace_split_plan(
        image,
        max_regions=4,
        preset=get_auto_split_preset("standard"),
        enable_balance_fallback=True,
    )

    assert without_balance.split_count == 0
    assert with_balance.split_count > 0
    assert with_balance.balance_split_count == with_balance.split_count


def test_safe_preset_never_forces_balance_split() -> None:
    image = Image.new("L", (800, 600), 25)

    plan = build_whitespace_split_plan(
        image,
        max_regions=8,
        preset=get_auto_split_preset("safe"),
        enable_balance_fallback=True,
    )

    assert plan.split_count == 0
    assert plan.balance_split_count == 0


def test_graft_plan_replaces_one_leaf_and_preserves_surrounding_order() -> None:
    root = CustomSplitNode()
    root.direction = CustomSplitDirection.VERTICAL
    root.ratio = 0.5
    root.first = CustomSplitNode()
    root.second = CustomSplitNode()
    order = normalized_custom_order(root, [])

    replacement = CustomSplitNode(
        direction=CustomSplitDirection.HORIZONTAL,
        ratio=0.4,
        first=CustomSplitNode(),
        second=CustomSplitNode(),
    )
    new_order = graft_auto_split_plan(root, order, (0,), replacement)

    assert custom_leaf_paths(root) == [(0, 0), (0, 1), (1,)]
    assert new_order == [(0, 0), (0, 1), (1,)]


def test_auto_split_presets_are_ordered_from_safe_to_exploratory() -> None:
    assert [preset.key for preset in AUTO_SPLIT_PRESETS] == [
        "safe",
        "standard",
        "aggressive",
        "exploratory",
    ]

    safe = get_auto_split_preset("safe")
    standard = get_auto_split_preset("standard")
    aggressive = get_auto_split_preset("aggressive")
    exploratory = get_auto_split_preset("exploratory")

    assert safe.min_score > standard.min_score > aggressive.min_score > exploratory.min_score
    assert (
        safe.min_gap_width_ratio
        > standard.min_gap_width_ratio
        > aggressive.min_gap_width_ratio
        > exploratory.min_gap_width_ratio
    )
    assert (
        safe.min_child_fraction
        > standard.min_child_fraction
        > aggressive.min_child_fraction
        > exploratory.min_child_fraction
    )
    assert safe.min_child_pixels > standard.min_child_pixels > aggressive.min_child_pixels > exploratory.min_child_pixels
    assert safe.edge_fraction > standard.edge_fraction > aggressive.edge_fraction > exploratory.edge_fraction
    assert safe.max_depth < standard.max_depth < aggressive.max_depth < exploratory.max_depth
    assert (
        safe.min_region_area_fraction
        > standard.min_region_area_fraction
        > aggressive.min_region_area_fraction
        > exploratory.min_region_area_fraction
    )
    assert safe.balance_area_fraction is None
    assert (
        standard.balance_area_fraction
        > aggressive.balance_area_fraction
        > exploratory.balance_area_fraction
    )


def test_plan_accepts_named_sensitivity_preset() -> None:
    image = Image.new("L", (900, 700), 255)
    draw = ImageDraw.Draw(image)
    columns = ((40, 260), (340, 560), (640, 860))
    for y in range(50, 650, 18):
        for x0, x1 in columns:
            draw.rectangle((x0, y, x1, y + 8), fill=25)

    plan = build_whitespace_split_plan(
        image,
        max_regions=8,
        preset=get_auto_split_preset("standard"),
    )

    assert plan.leaf_count >= 3
