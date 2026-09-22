from __future__ import annotations

from types import MethodType

from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def _find_layout_containing(layout, widget: QWidget):
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item.widget() is widget:
            return layout, index
        child_layout = item.layout()
        if child_layout is not None:
            found = _find_layout_containing(child_layout, widget)
            if found is not None:
                return found
    return None


def _wrap_button_with_help(root: QWidget, button: QPushButton, text: str) -> None:
    if getattr(button, "_context_help_installed", False):
        return
    root_layout = root.layout()
    if root_layout is None:
        return
    found = _find_layout_containing(root_layout, button)
    if found is None:
        return
    layout, index = found
    if not isinstance(layout, QBoxLayout):
        return

    # isVisible() is false while an ancestor/window has not yet been shown, so
    # using it here can accidentally hide ordinary buttons forever. Preserve
    # only the button's *explicit* hidden state instead.
    was_explicitly_hidden = button.isHidden()

    layout.takeAt(index)
    wrapper = QWidget(root)
    wrapper.setMinimumHeight(0)
    outer = QVBoxLayout(wrapper)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(3)

    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(5)
    row.addWidget(button, 1)

    help_button = QPushButton("?")
    help_button.setCheckable(True)
    help_button.setFixedSize(24, 24)
    help_button.setToolTip("この操作の説明を表示 / 非表示")
    row.addWidget(help_button, 0)
    outer.addLayout(row)

    help_label = QLabel(text)
    help_label.setWordWrap(True)
    help_label.setFrameShape(QFrame.Shape.StyledPanel)
    help_label.setContentsMargins(7, 6, 7, 6)
    help_label.setStyleSheet(
        "QLabel { background: palette(alternate-base); border-radius: 4px; }"
    )
    help_label.setVisible(False)
    outer.addWidget(help_label)

    help_button.toggled.connect(help_label.setVisible)
    layout.insertWidget(index, wrapper)

    button._context_help_installed = True  # type: ignore[attr-defined]
    button._context_help_wrapper = wrapper  # type: ignore[attr-defined]
    button._context_help_button = help_button  # type: ignore[attr-defined]
    wrapper.setVisible(not was_explicitly_hidden)


def _button_by_text(root: QWidget, text: str) -> QPushButton | None:
    for button in root.findChildren(QPushButton):
        if button.text() == text:
            return button
    return None


def _set_help_wrapper_visible(button: QPushButton | None, visible: bool) -> None:
    if not isinstance(button, QPushButton):
        return
    wrapper = getattr(button, "_context_help_wrapper", None)
    if isinstance(wrapper, QWidget):
        wrapper.setVisible(visible)


def install_context_help(window) -> None:
    """Reduce visual clutter and add expandable help beside major actions."""

    # The explicit page-range syntax and page locking now cover the intended
    # bulk-apply workflow, so this older left-list apply action is redundant.
    if hasattr(window, "apply_selected_button"):
        window.apply_selected_button.setVisible(False)
        window.apply_selected_button.setEnabled(False)

    # The long always-visible Custom explanation is replaced by local help.
    if hasattr(window, "custom_help"):
        window.custom_help.setVisible(False)

    manual_panel = None
    if hasattr(window, "manual_controls_scroll"):
        manual_panel = window.manual_controls_scroll.widget()
    if manual_panel is not None:
        manual_help: list[tuple[QPushButton | None, str]] = [
            (
                _button_by_text(manual_panel, "Open PDF…"),
                "新しいPDFを開いて作業を始めます。既存のOCR Bundleから続きを行う場合は、下の「Open OCR Bundle…」を使います。",
            ),
            (
                getattr(window, "open_bundle_button", None),
                "Export for OCR…で作成したBundleを開き、manifest.jsonの分割設定とworkspace.jsonの作業状態を復元して作業を再開します。元PDFが移動している場合は選び直せます。",
            ),
            (
                getattr(window, "page_lock_button", None),
                "現在ページを一括変更から保護します。固定ページは「指定ページ」「全ページ」への設定反映や一括自動分割から除外されます。特殊なページを先に仕上げて固定しておく用途に向きます。",
            ),
            (
                getattr(window, "custom_vertical_button", None),
                "選択中のCustom領域を左右2領域に分けます。縦の赤線が入り、分割後は右側領域が選択されます。Shift+Enterでも実行できます。",
            ),
            (
                getattr(window, "custom_horizontal_button", None),
                "選択中のCustom領域を上下2領域に分けます。横の赤線が入り、分割後は上側領域が選択されます。Enterでも実行できます。",
            ),
            (
                getattr(window, "custom_delete_button", None),
                "複数領域を選択している場合は、選択部分が1つの長方形になるときだけ統合します。分割線を選択している場合は、その分割を削除します。",
            ),
            (
                getattr(window, "custom_reset_button", None),
                "現在ページのCustom splitを解除し、ページ全体を1領域へ戻します。必要なら⌘Zで元に戻せます。",
            ),
            (
                getattr(window, "custom_reorder_button", None),
                "番号が連続する複数領域を選択してから押し、新しいOCR読み順に領域をクリックします。画面上の番号だけでなく、OCR用PDFの出力順も変更されます。Escで中止できます。",
            ),
            (
                getattr(window, "apply_range_button", None),
                "現在ページの分割設定を、指定したページだけへコピーします。例: 4,11-20。周期指定は 4-60/7 のように書くと4頁から7頁おきに反映します。固定ページは変更しません。",
            ),
            (
                getattr(window, "apply_all_button", None),
                "現在ページの分割設定を全ページへコピーします。固定したページは変更されないため、例外ページを固定してから標準レイアウトを全体へ配る用途に使えます。",
            ),
            (
                getattr(window, "export_button", None),
                "現在の分割設定に従って通常の分割済みPDFを書き出します。出力は画像ベースで、既定はカラーです。",
            ),
            (
                getattr(window, "export_ocr_button", None),
                "外部OCRへ渡す分割PDFとmanifest.jsonをBundleとして書き出します。同時にworkspace.jsonも保存するため、このBundleは作業保存・再開にも使えます。既定はカラーです。",
            ),
            (
                getattr(window, "restore_ocr_button", None),
                "OCR Bundleの分割情報と、外部OCRで処理した検索可能PDFを使って、元のページ構成へ再配置します。元PDFそのものは復元時には不要です。",
            ),
        ]
        for button, text in manual_help:
            if isinstance(button, QPushButton):
                _wrap_button_with_help(manual_panel, button, text)

    auto_panel = getattr(window, "auto_split_tab", None)
    if isinstance(auto_panel, QWidget):
        auto_help: list[tuple[QPushButton | None, str]] = [
            (
                getattr(window, "auto_split_current_region_button", None),
                "Custom splitで選択している1領域だけを画像解析し、その内部に複数の分割線を自動生成します。周囲の既存レイアウトは維持します。",
            ),
            (
                getattr(window, "auto_split_current_page_button", None),
                "現在ページ全体を画像解析し、自動生成したCustom splitへ置き換えます。検出感度・安全上限・均衡補正の設定が使われます。",
            ),
            (
                getattr(window, "auto_split_range_button", None),
                "手動タブのページ指定欄を使って複数ページを一括解析します。4-60/7のような周期指定も利用できます。固定ページは除外されます。",
            ),
            (
                getattr(window, "auto_split_selected_pages_button", None),
                "左のサムネイル一覧で⌘クリックまたはShiftクリックした複数ページだけを一括自動分割します。処理全体は1回の⌘Zで戻せます。",
            ),
        ]
        for button, text in auto_help:
            if isinstance(button, QPushButton):
                _wrap_button_with_help(auto_panel, button, text)

    # Custom-split controls genuinely appear/disappear as the split mode
    # changes. Synchronize their wrappers explicitly instead of relying on Qt's
    # effective visibility during startup.
    original_custom_visibility = window._set_custom_controls_visible
    custom_buttons = [
        getattr(window, "custom_vertical_button", None),
        getattr(window, "custom_horizontal_button", None),
        getattr(window, "custom_delete_button", None),
        getattr(window, "custom_reset_button", None),
        getattr(window, "custom_reorder_button", None),
    ]

    def set_custom_controls_visible(self, visible: bool) -> None:
        original_custom_visibility(visible)
        self.custom_help.setVisible(False)
        for button in custom_buttons:
            _set_help_wrapper_visible(button, visible)

    window._set_custom_controls_visible = MethodType(
        set_custom_controls_visible,
        window,
    )

    is_custom = bool(window.page_settings) and window.page_settings[window.current_page].mode.value == "custom"
    for button in custom_buttons:
        _set_help_wrapper_visible(button, is_custom)
