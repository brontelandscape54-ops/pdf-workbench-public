from __future__ import annotations

from types import MethodType

from PySide6.QtWidgets import QLabel, QPushButton


def install_page_locking(window) -> None:
    """Add per-page layout protection without changing OCR/export semantics.

    Locked pages are skipped by all bulk-apply operations. A locked page may
    still be used as the source layout for applying its settings elsewhere.
    """
    window.locked_pages = set()

    panel = window.centralWidget().widget(2)
    layout = panel.layout()

    insert_at = layout.count()
    for index in range(layout.count()):
        item = layout.itemAt(index)
        widget = item.widget()
        if isinstance(widget, QLabel) and widget.text() == "Export":
            insert_at = index
            break

    lock_label = QLabel("ページ固定")
    lock_button = QPushButton("現在ページを固定")
    layout.insertWidget(insert_at, lock_label)
    layout.insertWidget(insert_at + 1, lock_button)
    window.page_lock_button = lock_button

    original_open_pdf = window.open_pdf
    original_show_current_page = window._show_current_page
    original_refresh_thumbnail = window._refresh_thumbnail
    original_populate_thumbnails = window._populate_thumbnails
    original_apply_indexes = window._apply_current_to_indexes

    def update_thumbnail_label(page_index: int) -> None:
        if not (0 <= page_index < window.page_list.count()):
            return
        prefix = "🔒 " if page_index in window.locked_pages else ""
        window.page_list.item(page_index).setText(f"{prefix}{page_index + 1}")

    def update_lock_button() -> None:
        if not window.page_settings:
            lock_button.setEnabled(False)
            lock_button.setText("現在ページを固定")
            return
        lock_button.setEnabled(True)
        if window.current_page in window.locked_pages:
            lock_button.setText("現在ページの固定を解除")
        else:
            lock_button.setText("現在ページを固定")

    def toggle_current_lock() -> None:
        if not window.page_settings:
            return
        page_index = window.current_page
        if page_index in window.locked_pages:
            window.locked_pages.remove(page_index)
            window.statusBar().showMessage(f"{page_index + 1}頁の固定を解除しました")
        else:
            window.locked_pages.add(page_index)
            window.statusBar().showMessage(
                f"{page_index + 1}頁を固定しました（一括反映から保護されます）"
            )
        update_thumbnail_label(page_index)
        update_lock_button()

    def open_pdf(self) -> None:
        self.locked_pages.clear()
        original_open_pdf()
        for page_index in range(self.page_list.count()):
            update_thumbnail_label(page_index)
        update_lock_button()

    def show_current_page(self) -> None:
        original_show_current_page()
        update_lock_button()

    def refresh_thumbnail(self, page_index: int) -> None:
        original_refresh_thumbnail(page_index)
        update_thumbnail_label(page_index)

    def populate_thumbnails(self) -> None:
        original_populate_thumbnails()
        for page_index in range(self.page_list.count()):
            update_thumbnail_label(page_index)

    def apply_current_to_indexes(self, indexes: list[int], label: str) -> None:
        requested = sorted(set(indexes))
        unlocked = [index for index in requested if index not in self.locked_pages]
        skipped = len(requested) - len(unlocked)
        if not unlocked:
            if skipped:
                self.statusBar().showMessage(
                    f"対象の {skipped} ページはすべて固定されているため変更しませんでした"
                )
            return
        original_apply_indexes(unlocked, label)
        if skipped:
            self.statusBar().showMessage(
                f"{len(unlocked)} ページに反映しました（固定中の {skipped} ページを除外）"
            )

    window.open_pdf = MethodType(open_pdf, window)
    window._show_current_page = MethodType(show_current_page, window)
    window._refresh_thumbnail = MethodType(refresh_thumbnail, window)
    window._populate_thumbnails = MethodType(populate_thumbnails, window)
    window._apply_current_to_indexes = MethodType(apply_current_to_indexes, window)

    lock_button.clicked.connect(toggle_current_lock)
    update_lock_button()
