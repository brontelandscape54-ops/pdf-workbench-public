from __future__ import annotations

import pytest

from pdf_workbench.core.custom_presets import (
    as_custom_settings,
    four_region_settings,
    one_region_settings,
)
from pdf_workbench.core.geometry import split_regions
from pdf_workbench.core.models import (
    FourSplitOrder,
    PageSplitSettings,
    SplitMode,
    custom_leaf_paths,
)


def test_new_page_starts_as_editable_one_region() -> None:
    settings = PageSplitSettings()
    assert settings.mode is SplitMode.CUSTOM
    assert custom_leaf_paths(settings.custom_root) == [()]
    assert len(split_regions(800, 1200, settings)) == 1


def test_four_region_preset_is_editable_and_in_japanese_reading_order() -> None:
    settings = four_region_settings(PageSplitSettings())
    assert settings.mode is SplitMode.CUSTOM
    assert custom_leaf_paths(settings.custom_root) == [
        (0, 0), (0, 1), (1, 0), (1, 1)
    ]
    boxes = [region.ownership_box for region in split_regions(800, 1200, settings)]
    assert boxes == [
        (400, 0, 800, 600),
        (400, 600, 800, 1200),
        (0, 0, 400, 600),
        (0, 600, 400, 1200),
    ]


def test_one_region_preset_resets_only_layout_not_other_export_settings() -> None:
    old = four_region_settings(PageSplitSettings(overlap_px=14))
    result = one_region_settings(old)
    assert result.mode is SplitMode.CUSTOM
    assert result.overlap_px == 14
    assert result.custom_order == [()]
    assert len(split_regions(800, 1200, result)) == 1
    assert len(split_regions(800, 1200, old)) == 4


@pytest.mark.parametrize("mode", [
    SplitMode.NONE, SplitMode.HORIZONTAL_2, SplitMode.FOUR
])
@pytest.mark.parametrize("order", list(FourSplitOrder))
def test_legacy_fixed_modes_keep_export_geometry_and_order(mode, order) -> None:
    old = PageSplitSettings(
        mode=mode,
        x_ratio=0.43,
        y_ratio=0.61,
        overlap_px=10,
        order=order,
    )
    migrated = as_custom_settings(old)
    assert migrated.mode is SplitMode.CUSTOM
    before = split_regions(1000, 1400, old)
    after = split_regions(1000, 1400, migrated)
    assert [r.crop_box for r in before] == [r.crop_box for r in after]
    assert [r.ownership_box for r in before] == [r.ownership_box for r in after]
    assert old.mode is mode


def test_existing_custom_layout_is_not_reset_during_migration() -> None:
    settings = four_region_settings(PageSplitSettings())
    settings.custom_order = list(reversed(settings.custom_order))
    migrated = as_custom_settings(settings)
    assert migrated.custom_order == settings.custom_order
    assert migrated.custom_root.to_dict() == settings.custom_root.to_dict()
    assert migrated.custom_root is not settings.custom_root
