from __future__ import annotations

from pdf_workbench.core.custom_presets import four_region_settings, one_region_settings
from pdf_workbench.core.models import PageSplitSettings, SplitMode
from pdf_workbench.core.multi_page_edit import copy_preview_layout, editable_selection


def _pages():
    return [
        four_region_settings(PageSplitSettings(overlap_px=7)),
        one_region_settings(PageSplitSettings(overlap_px=0)),
        one_region_settings(PageSplitSettings(overlap_px=3)),
        one_region_settings(PageSplitSettings(overlap_px=9)),
    ]


def test_selecting_multiple_pages_without_edit_does_not_change_data() -> None:
    pages = _pages()
    before = [page.clone() for page in pages]
    selection = {0, 1, 2}
    assert pages == before
    assert selection == {0, 1, 2}


def test_selected_pages_become_independent_clones_of_preview() -> None:
    pages = _pages()
    changed = copy_preview_layout(pages, 0, {0, 1, 2})
    assert changed == [1, 2]
    assert pages[1] == pages[0] == pages[2]
    assert pages[3] != pages[0]
    assert pages[1].custom_root is not pages[0].custom_root
    pages[1].custom_root.ratio = 0.2
    assert pages[1].custom_root.ratio != pages[0].custom_root.ratio


def test_fixed_selected_pages_are_not_overwritten() -> None:
    pages = _pages()
    original = pages[1].clone()
    changed = copy_preview_layout(pages, 0, {0, 1, 2}, {1})
    assert changed == [2]
    assert pages[1] == original


def test_preview_outside_selection_never_overwrites_targets() -> None:
    pages = _pages()
    before = [page.clone() for page in pages]
    assert copy_preview_layout(pages, 0, {1, 2}) == []
    assert pages == before


def test_one_selected_page_does_not_trigger_bulk_copy() -> None:
    pages = _pages()
    before = [page.clone() for page in pages]
    assert copy_preview_layout(pages, 0, {0}) == []
    assert pages == before


def test_copy_preserves_custom_reading_order_and_overlap() -> None:
    pages = _pages()
    pages[0].custom_order.reverse()
    copy_preview_layout(pages, 0, {0, 2})
    assert pages[2].custom_order == pages[0].custom_order
    assert pages[2].overlap_px == 7
    assert pages[2].mode is SplitMode.CUSTOM


def test_editable_selection_reports_excluded_fixed_thumbnails() -> None:
    editable, excluded = editable_selection({0, 1, 2, 3}, 0, {1, 3})
    assert editable == [0, 2]
    assert excluded == [1, 3]
