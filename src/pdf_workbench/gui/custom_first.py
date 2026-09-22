from __future__ import annotations

from types import MethodType

from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from pdf_workbench.core.custom_presets import (
    as_custom_settings,
    four_region_settings,
    one_region_settings,
)
from pdf_workbench.core.models import SplitMode
from .context_help import _wrap_button_with_help


def install_custom_first(window) -> None:
    """Present Custom split as the only editable layout, with two quick presets."""
    manual = window.manual_controls_scroll.widget()
    layout = manual.layout()

    # The fixed modes remain readable in old manifests, but are no longer
    # choices in the current editor. The existing overlap field remains usable.
    for field in (window.mode_combo, window.x_ratio, window.y_ratio, window.order_combo):
        field.hide()
    # Hide labels in the nested form as well.
    for index in range(layout.count()):
        child = layout.itemAt(index).layout()
        if child is None or not hasattr(child, "labelForField"):
            continue
        for field in (window.mode_combo, window.x_ratio, window.y_ratio, window.order_combo):
            label = child.labelForField(field)
            if label is not None:
                label.hide()

    def normalize_all(self) -> None:
        if not self.page_settings:
            return
        self.page_settings = [as_custom_settings(s) for s in self.page_settings]

    original_populate = window._populate_thumbnails
    def populate_thumbnails(self) -> None:
        normalize_all(self)
        original_populate()
    window._populate_thumbnails = MethodType(populate_thumbnails, window)

    original_show = window._show_current_page
    def show_current_page(self) -> None:
        if self.page_settings:
            index = self.current_page
            current = self.page_settings[index]
            if current.mode != SplitMode.CUSTOM:
                self.page_settings[index] = as_custom_settings(current)
        original_show()
    window._show_current_page = MethodType(show_current_page, window)

    def apply_preset(self, make_settings, status: str) -> None:
        if not self.page_settings:
            return
        index = self.current_page
        before = (index, self._clone_all_settings())
        selection = self._capture_custom_selection()
        updated = make_settings(as_custom_settings(self.page_settings[index]))
        self.page_settings[index] = updated
        self._history_selection_override = selection
        sync = getattr(self, "_sync_selected_page_layout", None)
        if callable(sync):
            sync()
        self._record_undo_snapshot(before)
        self._show_current_page()
        self.page_view.select_custom_path((0, 0) if not updated.custom_root.is_leaf else ())
        self._refresh_custom_selection_label()
        self._refresh_thumbnail(index)
        self.statusBar().showMessage(status)

    four_button = QPushButton("頁全体を4分割")
    four_button.clicked.connect(
        lambda: apply_preset(window, four_region_settings, "現在頁を4領域にしました")
    )
    reset_button = window.custom_reset_button
    try:
        reset_button.clicked.disconnect()
    except (RuntimeError, TypeError):
        pass
    reset_button.setText("分割なし（1領域）")
    reset_button.clicked.connect(
        lambda: apply_preset(window, one_region_settings, "現在頁を1領域に戻しました")
    )

    existing_wrapper = getattr(reset_button, "_context_help_wrapper", reset_button)
    insertion = layout.indexOf(existing_wrapper)
    if insertion < 0:
        insertion = layout.indexOf(window.custom_selected_label) + 1
    layout.insertWidget(insertion, four_button)
    window.four_region_button = four_button
    _wrap_button_with_help(
        manual, four_button,
        "現在頁を等分の4領域（右上→右下→左上→左下）にします。"
        "作成後もCustom splitの赤線をドラッグして位置を調整できます。"
        "複数ページ選択中は、その全ページへ同じ4分割を反映します。"
        "固定ページは除外し、⌘Zでまとめて元へ戻せます。",
    )

    reset_wrapper = getattr(reset_button, "_context_help_wrapper", None)
    if isinstance(reset_wrapper, QWidget):
        for label in reset_wrapper.findChildren(QLabel):
            if "Custom split" in label.text() or "1領域" in label.text():
                label.setText(
                    "現在頁の分割をすべて消して1領域に戻します。"
                    "複数ページ選択中は選択中の全ページを1領域にします。"
                    "固定ページは除外し、⌘Zでまとめて元へ戻せます。"
                )
    four_button.setEnabled(bool(window.page_settings))

    # The obsolete one-line auto-split button was superseded by the dedicated
    # automatic-split tab. Keep it hidden when Custom controls refresh.
    old_custom_visibility = window._set_custom_controls_visible
    def set_custom_controls_visible(self, visible: bool) -> None:
        old_custom_visibility(visible)
        if hasattr(self, "custom_auto_split_button"):
            self.custom_auto_split_button.hide()
    window._set_custom_controls_visible = MethodType(
        set_custom_controls_visible, window
    )

    original_enabled = window._set_controls_enabled
    def set_controls_enabled(self, enabled: bool) -> None:
        original_enabled(enabled)
        four_button.setEnabled(enabled)
    window._set_controls_enabled = MethodType(set_controls_enabled, window)
