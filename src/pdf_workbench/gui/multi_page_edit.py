"""Thumbnail multi-selection drives direct, preview-based bulk editing.

Only explicit manual editing operations call _sync_selected_page_layout().
Simply selecting pages or navigating never changes any saved page settings.
The caller records a single pre-edit Undo snapshot after synchronization.
"""
from __future__ import annotations

from types import MethodType

from PySide6.QtWidgets import QLabel

from pdf_workbench.core.multi_page_edit import copy_preview_layout


def install_multi_page_edit(window) -> None:
    manual = window.manual_controls_scroll.widget()
    layout = manual.layout()
    notice = QLabel()
    notice.setWordWrap(True)
    notice.setStyleSheet(
        "QLabel { background: palette(alternate-base); border-radius: 4px;"
        " padding: 6px; }"
    )
    notice.hide()
    layout.insertWidget(2, notice)
    window.multi_page_edit_notice = notice

    def selected_indexes() -> list[int]:
        return sorted({
            index.row() for index in window.page_list.selectedIndexes()
            if 0 <= index.row() < len(window.page_settings)
        })

    def refresh_notice() -> None:
        selected = selected_indexes()
        if len(selected) < 2:
            notice.hide()
            return
        active = window.current_page
        if active not in selected:
            notice.setText(
                f"{len(selected)}頁を選択中。中央の {active + 1} 頁は選択対象外のため、"
                "一括編集は行いません。"
            )
        else:
            locked = set(getattr(window, "locked_pages", set()))
            targets = [index for index in selected if index == active or index not in locked]
            numbers = ", ".join(str(index + 1) for index in selected)
            excluded = len(selected) - len(targets)
            note = f"（固定中 {excluded} 頁を除外）" if excluded else ""
            notice.setText(
                f"{len(selected)}頁選択中：{numbers}\n"
                f"中央 {active + 1} 頁の編集を {len(targets)} 頁に反映します{note}。"
            )
        notice.show()

    def synchronize(self) -> list[int]:
        indexes = selected_indexes()
        changed = copy_preview_layout(
            self.page_settings,
            self.current_page,
            indexes,
            getattr(self, "locked_pages", set()),
        )
        for index in changed:
            self._refresh_thumbnail(index)
        refresh_notice()
        return changed

    window._sync_selected_page_layout = MethodType(synchronize, window)
    window.page_list.itemSelectionChanged.connect(refresh_notice)
    window.page_list.currentRowChanged.connect(lambda _row: refresh_notice())

    # These two wrappers are already installed by page locking/custom-first.
    # Repaint the selection banner when opening a different source or resuming
    # a saved Bundle, both of which repopulate the left-side thumbnail list.
    original_populate = window._populate_thumbnails

    def populate_thumbnails(self) -> None:
        original_populate()
        refresh_notice()

    window._populate_thumbnails = MethodType(populate_thumbnails, window)

    original_show = window._show_current_page

    def show_current_page(self) -> None:
        original_show()
        refresh_notice()

    window._show_current_page = MethodType(show_current_page, window)
    refresh_notice()
