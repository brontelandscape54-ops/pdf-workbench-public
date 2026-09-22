"""Copy the visible page's completed editable layout to selected thumbnails."""
from __future__ import annotations

from collections.abc import Collection, Sequence

from .models import PageSplitSettings


def copy_preview_layout(
    page_settings: list[PageSplitSettings],
    current_page: int,
    selected_pages: Collection[int],
    locked_pages: Collection[int] = (),
) -> list[int]:
    """Return changed target indices; never alias one page's mutable tree.

    Selection by itself does nothing. Call only after a manual edit, while the
    caller still holds the pre-edit snapshot for a single Undo operation.
    The central preview page must be part of the multi-selection.
    """
    selected = set(selected_pages)
    if (
        len(selected) < 2
        or current_page not in selected
        or not 0 <= current_page < len(page_settings)
    ):
        return []
    source = page_settings[current_page]
    locked = set(locked_pages)
    changed: list[int] = []
    for index in sorted(selected):
        if index == current_page or index in locked or not 0 <= index < len(page_settings):
            continue
        if page_settings[index] != source:
            page_settings[index] = source.clone()
            changed.append(index)
    return changed


def editable_selection(
    selected_pages: Collection[int],
    current_page: int,
    locked_pages: Collection[int] = (),
) -> tuple[list[int], list[int]]:
    selected = sorted(set(selected_pages))
    locked = set(locked_pages)
    editable = [index for index in selected if index not in locked]
    if current_page in selected and current_page in locked:
        # A locked preview may be edited directly, while other locked pages
        # remain protected from copying.
        editable.append(current_page)
        editable.sort()
    return editable, [index for index in selected if index in locked and index != current_page]
