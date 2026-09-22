from __future__ import annotations

from pathlib import Path

import fitz
from PySide6.QtCore import QItemSelectionModel, QRect, QSize, QSignalBlocker, Qt
from PySide6.QtGui import (
    QAction,
    QFont,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from pdf_workbench.core.geometry import split_regions
from pdf_workbench.core.models import (
    CustomSplitDirection,
    CustomSplitNode,
    FourSplitOrder,
    PageSplitSettings,
    SplitMode,
    coerce_four_split_order,
    coerce_split_mode,
    custom_leaf_paths,
    split_custom_leaf,
)
from pdf_workbench.core.ocr_bundle import export_ocr_bundle
from pdf_workbench.core.ocr_manifest import load_manifest
from pdf_workbench.core.ocr_restore import inspect_ocr_pdf, restore_ocr_pdf
from pdf_workbench.core.page_ranges import parse_page_spec
from pdf_workbench.core.pdf_engine import export_split_pdf
from .page_view import PageView


class MainWindow(QMainWindow):
    PREVIEW_DPI = 110
    THUMBNAIL_DPI = 24
    HISTORY_LIMIT = 100

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDF Workbench v0.1")
        self.resize(1440, 900)

        self.pdf_path: Path | None = None
        self.doc: fitz.Document | None = None
        self.page_settings: list[PageSplitSettings] = []
        self.current_page = 0
        self._undo_stack: list[tuple[int, list[PageSplitSettings]]] = []
        self._redo_stack: list[tuple[int, list[PageSplitSettings]]] = []
        self._pending_custom_snapshot: tuple[int, list[PageSplitSettings]] | None = None

        self.page_view = PageView()
        self.page_view.on_x_ratio_changed = self._view_x_changed
        self.page_view.on_y_ratio_changed = self._view_y_changed
        self.page_view.on_custom_selected = self._custom_selected
        self.page_view.on_custom_edit_started = self._custom_edit_started
        self.page_view.on_custom_edit_finished = self._custom_edit_finished
        self.page_view.on_custom_error = self._custom_error
        self.page_view.on_custom_split_requested = self.split_selected_custom

        self.page_list = QListWidget()
        self.page_list.setIconSize(QSize(120, 160))
        self.page_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.page_list.setMinimumWidth(155)
        self.page_list.setMaximumWidth(210)
        self.page_list.currentRowChanged.connect(self._thumbnail_page_changed)

        controls = self._build_controls()
        splitter = QSplitter()
        splitter.addWidget(self.page_list)
        splitter.addWidget(self.page_view)
        splitter.addWidget(controls)
        splitter.setSizes([175, 965, 300])
        self.setCentralWidget(splitter)

        file_menu = self.menuBar().addMenu("File")
        open_action = QAction("Open PDF…", self)
        open_action.triggered.connect(self.open_pdf)
        file_menu.addAction(open_action)

        restore_action = QAction("Restore OCR Results…", self)
        restore_action.triggered.connect(self.restore_ocr_results)
        file_menu.addAction(restore_action)

        edit_menu = self.menuBar().addMenu("Edit")
        self.undo_action = QAction("元に戻す", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.undo)
        edit_menu.addAction(self.undo_action)
        self.redo_action = QAction("やり直す", self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.triggered.connect(self.redo)
        edit_menu.addAction(self.redo_action)

        self.statusBar().showMessage("Open a PDF to begin")
        self._set_controls_enabled(False)
        self._update_history_actions()

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        open_button = QPushButton("Open PDF…")
        open_button.clicked.connect(self.open_pdf)
        layout.addWidget(open_button)

        nav = QHBoxLayout()
        self.prev_button = QPushButton("◀")
        self.next_button = QPushButton("▶")
        self.page_spin = QSpinBox()
        self.page_count_label = QLabel("/ 0")
        self.prev_button.clicked.connect(lambda: self.go_to_page(self.current_page - 1))
        self.next_button.clicked.connect(lambda: self.go_to_page(self.current_page + 1))
        self.page_spin.valueChanged.connect(lambda value: self.go_to_page(value - 1))
        nav.addWidget(self.prev_button)
        nav.addWidget(self.page_spin)
        nav.addWidget(self.page_count_label)
        nav.addWidget(self.next_button)
        layout.addLayout(nav)

        history_buttons = QHBoxLayout()
        self.undo_button = QPushButton("↶ 一つ戻る")
        self.redo_button = QPushButton("↷ やり直す")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        history_buttons.addWidget(self.undo_button)
        history_buttons.addWidget(self.redo_button)
        layout.addLayout(history_buttons)

        form = QFormLayout()

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("4 split", SplitMode.FOUR)
        self.mode_combo.addItem("Horizontal 2 split", SplitMode.HORIZONTAL_2)
        self.mode_combo.addItem("Custom split", SplitMode.CUSTOM)
        self.mode_combo.addItem("No split", SplitMode.NONE)
        self.mode_combo.currentIndexChanged.connect(self._controls_changed)
        form.addRow("Split mode", self.mode_combo)

        self.x_ratio = QDoubleSpinBox()
        self.x_ratio.setRange(0.1, 99.9)
        self.x_ratio.setDecimals(1)
        self.x_ratio.setSuffix(" %")
        self.x_ratio.valueChanged.connect(self._controls_changed)
        form.addRow("Vertical line", self.x_ratio)

        self.y_ratio = QDoubleSpinBox()
        self.y_ratio.setRange(0.1, 99.9)
        self.y_ratio.setDecimals(1)
        self.y_ratio.setSuffix(" %")
        self.y_ratio.valueChanged.connect(self._controls_changed)
        form.addRow("Horizontal line", self.y_ratio)

        self.overlap = QSpinBox()
        self.overlap.setRange(0, 1000)
        self.overlap.setSuffix(" px")
        self.overlap.valueChanged.connect(self._controls_changed)
        form.addRow("Overlap", self.overlap)

        self.order_combo = QComboBox()
        self.order_combo.addItem(
            "Right top → right bottom → left top → left bottom",
            FourSplitOrder.RTL_TB,
        )
        self.order_combo.addItem(
            "Left top → left bottom → right top → right bottom",
            FourSplitOrder.LTR_TB,
        )
        self.order_combo.addItem("Z order", FourSplitOrder.Z)
        self.order_combo.currentIndexChanged.connect(self._controls_changed)
        form.addRow("4-split order", self.order_combo)

        layout.addLayout(form)

        self.custom_help = QLabel(
            "Custom split: 色の付いた領域が選択中です。\n"
            "Enter: 上下に分割 ／ Shift+Enter: 左右に分割\n"
            "分割後は新しくできた上側／右側の領域を続けて選択します。\n"
            "Shift + 方向キーで隣接領域を追加選択できます。\\n"
            "中央プレビューで⌘A（Windows/LinuxはCtrl+A）: 全領域選択 ／ Esc: 複数選択解除\\n"
            "複数領域を選んでDeleteすると、長方形なら1領域に統合します。\n"
            "赤い分割線はドラッグ調整、クリック選択後Deleteで削除できます。\n"
            "トラックパッドのピンチ操作で中央プレビューを拡大縮小できます。\n"
            "各領域の数字はOCRへ出す順番です。"
        )
        self.custom_selected_label = QLabel("選択領域: 1")
        custom_buttons = QHBoxLayout()
        self.custom_vertical_button = QPushButton("左右に分割（縦線）")
        self.custom_horizontal_button = QPushButton("上下に分割（横線）")
        self.custom_vertical_button.clicked.connect(
            lambda: self.split_selected_custom(CustomSplitDirection.VERTICAL)
        )
        self.custom_horizontal_button.clicked.connect(
            lambda: self.split_selected_custom(CustomSplitDirection.HORIZONTAL)
        )
        custom_buttons.addWidget(self.custom_vertical_button)
        custom_buttons.addWidget(self.custom_horizontal_button)
        self.custom_delete_button = QPushButton("選択領域 / 分割線を削除・統合")
        self.custom_delete_button.clicked.connect(self.delete_custom_selection)
        self.custom_reset_button = QPushButton("Custom splitをリセット")
        self.custom_reset_button.clicked.connect(self.reset_custom_layout)

        layout.addWidget(self.custom_help)
        layout.addWidget(self.custom_selected_label)
        layout.addLayout(custom_buttons)
        layout.addWidget(self.custom_delete_button)
        layout.addWidget(self.custom_reset_button)

        layout.addWidget(QLabel("分割設定を他のページへ反映"))
        self.page_range_input = QLineEdit()
        self.page_range_input.setPlaceholderText("例: 4,11-60,120-150")
        layout.addWidget(self.page_range_input)
        self.apply_range_button = QPushButton("指定ページに現在の設定を反映")
        self.apply_range_button.clicked.connect(self.apply_current_to_range)
        layout.addWidget(self.apply_range_button)
        self.apply_selected_button = QPushButton("左で選択したページに現在の設定を反映")
        self.apply_selected_button.clicked.connect(self.apply_current_to_selected_pages)
        layout.addWidget(self.apply_selected_button)
        self.apply_all_button = QPushButton("全ページに現在の設定を反映")
        self.apply_all_button.clicked.connect(self.apply_current_to_all)
        layout.addWidget(self.apply_all_button)

        layout.addWidget(QLabel("Export"))
        export_form = QFormLayout()
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 600)
        self.dpi_spin.setValue(180)
        export_form.addRow("DPI", self.dpi_spin)
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 95)
        self.quality_spin.setValue(70)
        export_form.addRow("JPEG quality", self.quality_spin)
        self.grayscale = QCheckBox("Grayscale")
        self.grayscale.setChecked(True)
        export_form.addRow("Color", self.grayscale)
        self.include_original = QCheckBox("Include original PDF in OCR bundle")
        self.include_original.setChecked(False)
        export_form.addRow("OCR bundle", self.include_original)
        layout.addLayout(export_form)

        self.export_button = QPushButton("Export PDF…")
        self.export_button.clicked.connect(self.export_pdf)
        layout.addWidget(self.export_button)

        self.export_ocr_button = QPushButton("Export for OCR…")
        self.export_ocr_button.clicked.connect(self.export_for_ocr)
        layout.addWidget(self.export_ocr_button)

        self.restore_ocr_button = QPushButton("Restore OCR Results…")
        self.restore_ocr_button.clicked.connect(self.restore_ocr_results)
        layout.addWidget(self.restore_ocr_button)

        layout.addStretch(1)
        self._set_custom_controls_visible(False)
        return panel

    def _clone_all_settings(self) -> list[PageSplitSettings]:
        return [settings.clone() for settings in self.page_settings]

    @staticmethod
    def _changed_page_indexes(
        before: list[PageSplitSettings],
        after: list[PageSplitSettings],
    ) -> list[int]:
        limit = min(len(before), len(after))
        changed = [index for index in range(limit) if before[index] != after[index]]
        if len(before) != len(after):
            changed.extend(range(limit, max(len(before), len(after))))
        return changed

    def _record_undo_snapshot(
        self,
        snapshot: tuple[int, list[PageSplitSettings]],
    ) -> None:
        current_page, settings = snapshot
        if settings == self.page_settings:
            return
        self._undo_stack.append((current_page, settings))
        if len(self._undo_stack) > self.HISTORY_LIMIT:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_history_actions()

    def _update_history_actions(self) -> None:
        can_undo = bool(self._undo_stack)
        can_redo = bool(self._redo_stack)
        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(can_undo)
            self.redo_action.setEnabled(can_redo)
        if hasattr(self, "undo_button"):
            self.undo_button.setEnabled(can_undo)
            self.redo_button.setEnabled(can_redo)

    def undo(self) -> None:
        if not self._undo_stack or not self.page_settings:
            return
        before = self._clone_all_settings()
        current_snapshot = (self.current_page, before)
        page_index, settings = self._undo_stack.pop()
        changed = self._changed_page_indexes(before, settings)
        self._redo_stack.append(current_snapshot)
        self.page_settings = [item.clone() for item in settings]
        self.current_page = max(0, min(len(self.page_settings) - 1, page_index))
        self._show_current_page()
        for index in changed:
            if index != self.current_page:
                self._refresh_thumbnail(index)
        self._refresh_thumbnail(self.current_page)
        self._update_history_actions()
        self.statusBar().showMessage("一つ前の分割操作に戻しました")

    def redo(self) -> None:
        if not self._redo_stack or not self.page_settings:
            return
        before = self._clone_all_settings()
        current_snapshot = (self.current_page, before)
        page_index, settings = self._redo_stack.pop()
        changed = self._changed_page_indexes(before, settings)
        self._undo_stack.append(current_snapshot)
        self.page_settings = [item.clone() for item in settings]
        self.current_page = max(0, min(len(self.page_settings) - 1, page_index))
        self._show_current_page()
        for index in changed:
            if index != self.current_page:
                self._refresh_thumbnail(index)
        self._refresh_thumbnail(self.current_page)
        self._update_history_actions()
        self.statusBar().showMessage("取り消した分割操作をやり直しました")

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.prev_button,
            self.next_button,
            self.page_spin,
            self.mode_combo,
            self.x_ratio,
            self.y_ratio,
            self.overlap,
            self.order_combo,
            self.apply_all_button,
            self.apply_range_button,
            self.apply_selected_button,
            self.page_range_input,
            self.export_button,
            self.export_ocr_button,
            self.include_original,
            self.custom_vertical_button,
            self.custom_horizontal_button,
            self.custom_delete_button,
            self.custom_reset_button,
        ):
            widget.setEnabled(enabled)
        if not enabled:
            self._set_custom_controls_visible(False)

    def _set_custom_controls_visible(self, visible: bool) -> None:
        for widget in (
            self.custom_help,
            self.custom_selected_label,
            self.custom_vertical_button,
            self.custom_horizontal_button,
            self.custom_delete_button,
            self.custom_reset_button,
        ):
            widget.setVisible(visible)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.doc is not None:
            self.doc.close()
        super().closeEvent(event)

    def open_pdf(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open PDF",
            "",
            "PDF files (*.pdf)",
        )
        if not filename:
            return
        try:
            if self.doc is not None:
                self.doc.close()
            self.pdf_path = Path(filename)
            self.doc = fitz.open(filename)
            if len(self.doc) == 0:
                raise ValueError("PDF has no pages")
            self.page_settings = [PageSplitSettings() for _ in range(len(self.doc))]
            self.current_page = 0
            self._undo_stack.clear()
            self._redo_stack.clear()
            self._pending_custom_snapshot = None
            with QSignalBlocker(self.page_spin):
                self.page_spin.setRange(1, len(self.doc))
                self.page_spin.setValue(1)
            self.page_count_label.setText(f"/ {len(self.doc)}")
            self._set_controls_enabled(True)
            self._populate_thumbnails()
            self._show_current_page()
            self._update_history_actions()
            self.statusBar().showMessage(str(self.pdf_path))
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))

    def _thumbnail_page_changed(self, row: int) -> None:
        if row >= 0 and self.doc is not None:
            self.go_to_page(row)

    def go_to_page(self, page_index: int) -> None:
        if self.doc is None:
            return
        page_index = max(0, min(len(self.doc) - 1, page_index))
        if page_index == self.current_page and self.page_view.scene() is not None:
            return
        self.current_page = page_index
        with QSignalBlocker(self.page_spin):
            self.page_spin.setValue(page_index + 1)
        self._set_current_thumbnail_without_losing_selection(page_index)
        self._show_current_page()

    def _set_current_thumbnail_without_losing_selection(self, page_index: int) -> None:
        # A click in the thumbnail list already set its current index. Do not
        # change the selection again while Qt is processing Cmd/Shift-click.
        if self.page_list.currentRow() == page_index:
            return
        # Moving the keyboard/preview focus must not collapse a Cmd/Shift
        # thumbnail multi-selection. A single selection still follows normal
        # page navigation.
        with QSignalBlocker(self.page_list):
            if len(self.page_list.selectedIndexes()) > 1:
                index = self.page_list.model().index(page_index, 0)
                self.page_list.selectionModel().setCurrentIndex(
                    index, QItemSelectionModel.SelectionFlag.NoUpdate
                )
            else:
                self.page_list.setCurrentRow(page_index)

    def _render_preview(self, page_index: int) -> QPixmap:
        assert self.doc is not None
        page = self.doc[page_index]
        zoom = self.PREVIEW_DPI / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        qimg = QImage(
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        ).copy()
        return QPixmap.fromImage(qimg)

    def _render_thumbnail(self, page_index: int) -> QPixmap:
        assert self.doc is not None
        page = self.doc[page_index]
        zoom = self.THUMBNAIL_DPI / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        qimg = QImage(
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        ).copy()
        image = QPixmap.fromImage(qimg)
        painter = QPainter(image)
        split_pen = QPen(Qt.GlobalColor.red, 3)
        painter.setPen(split_pen)
        regions = split_regions(pix.width, pix.height, self.page_settings[page_index])
        for number, region in enumerate(regions, start=1):
            x0, y0, x1, y1 = region.ownership_box
            width = max(1, x1 - x0 - 1)
            height = max(1, y1 - y0 - 1)
            painter.drawRect(x0, y0, width, height)

            font = QFont()
            font.setPointSize(18)
            font.setBold(True)
            painter.setFont(font)
            number_pen = QPen(Qt.GlobalColor.blue, 2)
            painter.setPen(number_pen)
            painter.drawText(
                QRect(x0, y0, width, height),
                Qt.AlignmentFlag.AlignCenter,
                str(number),
            )
            painter.setPen(split_pen)
        painter.end()
        return image

    def _populate_thumbnails(self) -> None:
        if self.doc is None:
            return
        with QSignalBlocker(self.page_list):
            self.page_list.clear()
            for page_index in range(len(self.doc)):
                item = QListWidgetItem(QIcon(self._render_thumbnail(page_index)), str(page_index + 1))
                item.setSizeHint(QSize(140, 180))
                self.page_list.addItem(item)
            self.page_list.setCurrentRow(self.current_page)

    def _refresh_thumbnail(self, page_index: int) -> None:
        if self.doc is None or not (0 <= page_index < self.page_list.count()):
            return
        item = self.page_list.item(page_index)
        item.setIcon(QIcon(self._render_thumbnail(page_index)))

    def _refresh_all_thumbnails(self) -> None:
        if self.doc is None:
            return
        for page_index in range(len(self.doc)):
            self._refresh_thumbnail(page_index)

    def _show_current_page(self) -> None:
        if self.doc is None:
            return
        settings = self.page_settings[self.current_page]
        self._load_settings_into_controls(settings)
        self.page_view.set_page(self._render_preview(self.current_page), settings)
        self._refresh_custom_selection_label()
        self._set_current_thumbnail_without_losing_selection(self.current_page)
        self.prev_button.setEnabled(self.current_page > 0)
        self.next_button.setEnabled(self.current_page < len(self.doc) - 1)
        self.statusBar().showMessage(
            f"{self.pdf_path.name if self.pdf_path else ''} — "
            f"page {self.current_page + 1}/{len(self.doc)}"
        )

    def _load_settings_into_controls(self, s: PageSplitSettings) -> None:
        widgets = [
            self.mode_combo,
            self.x_ratio,
            self.y_ratio,
            self.overlap,
            self.order_combo,
        ]
        blockers = [QSignalBlocker(widget) for widget in widgets]
        try:
            self.mode_combo.setCurrentIndex(self.mode_combo.findData(s.mode))
            self.x_ratio.setValue(s.x_ratio * 100)
            self.y_ratio.setValue(s.y_ratio * 100)
            self.overlap.setValue(s.overlap_px)
            self.order_combo.setCurrentIndex(self.order_combo.findData(s.order))
            self._update_control_visibility(s.mode)
        finally:
            del blockers

    def _controls_changed(self) -> None:
        if not self.page_settings:
            return
        snapshot = (self.current_page, self._clone_all_settings())
        settings = self.page_settings[self.current_page]
        settings.mode = coerce_split_mode(self.mode_combo.currentData())
        settings.x_ratio = self.x_ratio.value() / 100.0
        settings.y_ratio = self.y_ratio.value() / 100.0
        settings.overlap_px = self.overlap.value()
        settings.order = coerce_four_split_order(self.order_combo.currentData())
        if snapshot[1][self.current_page] != settings:
            sync = getattr(self, "_sync_selected_page_layout", None)
            if callable(sync):
                sync()
            self._record_undo_snapshot(snapshot)
        self._update_control_visibility(settings.mode)
        self.page_view.set_settings(settings)
        self._refresh_custom_selection_label()
        self._refresh_thumbnail(self.current_page)

    def _update_control_visibility(self, mode: SplitMode) -> None:
        self.x_ratio.setEnabled(mode == SplitMode.FOUR)
        self.y_ratio.setEnabled(mode in {SplitMode.FOUR, SplitMode.HORIZONTAL_2})
        self.order_combo.setEnabled(mode == SplitMode.FOUR)
        is_custom = mode == SplitMode.CUSTOM
        self._set_custom_controls_visible(is_custom)
        self.custom_vertical_button.setEnabled(is_custom)
        self.custom_horizontal_button.setEnabled(is_custom)
        self.custom_delete_button.setEnabled(is_custom)
        self.custom_reset_button.setEnabled(is_custom)

    def _view_x_changed(self, ratio: float) -> None:
        with QSignalBlocker(self.x_ratio):
            self.x_ratio.setValue(ratio * 100)
        self._refresh_thumbnail(self.current_page)

    def _view_y_changed(self, ratio: float) -> None:
        with QSignalBlocker(self.y_ratio):
            self.y_ratio.setValue(ratio * 100)
        self._refresh_thumbnail(self.current_page)

    def _custom_selected(self, _path: tuple[int, ...]) -> None:
        self._refresh_custom_selection_label()

    def _custom_error(self, message: str) -> None:
        self._pending_custom_snapshot = None
        QMessageBox.warning(self, "Custom split", message)

    def _custom_edit_started(self) -> None:
        if self._pending_custom_snapshot is None:
            self._pending_custom_snapshot = (self.current_page, self._clone_all_settings())

    def _custom_edit_finished(self) -> None:
        if self._pending_custom_snapshot is not None:
            self._record_undo_snapshot(self._pending_custom_snapshot)
            self._pending_custom_snapshot = None
        self._refresh_custom_selection_label()
        self._refresh_thumbnail(self.current_page)

    def _refresh_custom_selection_label(self) -> None:
        if not self.page_settings:
            return
        settings = self.page_settings[self.current_page]
        if settings.mode != SplitMode.CUSTOM:
            return
        paths = custom_leaf_paths(settings.custom_root)
        selected = self.page_view.selected_custom_paths
        if len(selected) > 1:
            self.custom_selected_label.setText(
                f"選択領域: {len(selected)} 個 / 全 {len(paths)} 個  （Deleteで統合）"
            )
            return
        path = self.page_view.selected_custom_path
        try:
            number = paths.index(path) + 1
        except ValueError:
            number = 1
        self.custom_selected_label.setText(
            f"選択領域: {number} / {len(paths)}  （色付き領域が選択中）"
        )

    def delete_custom_selection(self) -> None:
        if not self.page_view.delete_selection():
            if self.page_view.selected_custom_line_path is None and len(self.page_view.selected_custom_paths) < 2:
                QMessageBox.information(
                    self,
                    "Custom split",
                    "統合するには2つ以上の領域を選択するか、削除する分割線をクリックして選択してください。",
                )

    def split_selected_custom(self, direction: CustomSplitDirection) -> None:
        if not self.page_settings:
            return
        settings = self.page_settings[self.current_page]
        if settings.mode != SplitMode.CUSTOM:
            return
        selected_path = self.page_view.selected_custom_path
        snapshot = (self.current_page, self._clone_all_settings())
        try:
            split_custom_leaf(
                settings.custom_root,
                selected_path,
                direction,
                ratio=0.5,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Custom split", str(exc))
            return
        self._record_undo_snapshot(snapshot)
        self.page_view.set_settings(settings)
        self.page_view.select_custom_path(selected_path + (0,))
        self._refresh_custom_selection_label()
        self._refresh_thumbnail(self.current_page)

    def reset_custom_layout(self) -> None:
        if not self.page_settings:
            return
        snapshot = (self.current_page, self._clone_all_settings())
        settings = self.page_settings[self.current_page]
        settings.custom_root = CustomSplitNode()
        self._record_undo_snapshot(snapshot)
        self.page_view.set_settings(settings)
        self._refresh_custom_selection_label()
        self._refresh_thumbnail(self.current_page)

    def _apply_current_to_indexes(self, indexes: list[int], label: str) -> None:
        if not self.page_settings or not indexes:
            return
        snapshot = (self.current_page, self._clone_all_settings())
        source = self.page_settings[self.current_page].clone()
        for index in indexes:
            self.page_settings[index] = source.clone()
        self._record_undo_snapshot(snapshot)
        for index in indexes:
            self._refresh_thumbnail(index)
        self._show_current_page()
        self.statusBar().showMessage(label)

    def apply_current_to_range(self) -> None:
        if not self.page_settings:
            return
        try:
            indexes = parse_page_spec(self.page_range_input.text(), len(self.page_settings))
        except ValueError as exc:
            QMessageBox.warning(self, "ページ指定", str(exc))
            return
        self._apply_current_to_indexes(
            indexes,
            f"現在の分割設定を {len(indexes)} ページに反映しました",
        )

    def apply_current_to_selected_pages(self) -> None:
        indexes = sorted({index.row() for index in self.page_list.selectedIndexes()})
        if not indexes:
            QMessageBox.information(
                self,
                "ページ選択",
                "左のサムネイル一覧で、反映先ページを⌘クリックまたはShiftクリックで選択してください。",
            )
            return
        self._apply_current_to_indexes(
            indexes,
            f"左で選択した {len(indexes)} ページに分割設定を反映しました",
        )

    def apply_current_to_all(self) -> None:
        if not self.page_settings:
            return
        self._apply_current_to_indexes(
            list(range(len(self.page_settings))),
            "Current split settings applied to all pages",
        )

    def export_pdf(self) -> None:
        if self.pdf_path is None or self.doc is None:
            return
        suggested = self.pdf_path.with_name(f"{self.pdf_path.stem}_workbench.pdf")
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export PDF",
            str(suggested),
            "PDF files (*.pdf)",
        )
        if not filename:
            return

        progress = QProgressDialog("Exporting…", "Cancel", 0, len(self.doc), self)
        progress.setWindowTitle("PDF Workbench")
        progress.setMinimumDuration(0)

        def on_progress(done: int, total: int) -> bool:
            progress.setMaximum(total)
            progress.setValue(done)
            QApplication.processEvents()
            return not progress.wasCanceled()

        try:
            source_count, output_count = export_split_pdf(
                self.pdf_path,
                filename,
                self.page_settings,
                dpi=self.dpi_spin.value(),
                quality=self.quality_spin.value(),
                grayscale=self.grayscale.isChecked(),
                progress=on_progress,
            )
            progress.close()
            if progress.wasCanceled():
                self.statusBar().showMessage("Export cancelled")
                return
            QMessageBox.information(
                self,
                "Export complete",
                f"Source pages: {source_count}\nOutput pages: {output_count}\n\n{filename}",
            )
        except Exception as exc:
            progress.close()
            QMessageBox.critical(self, "Export failed", str(exc))

    def export_for_ocr(self) -> None:
        if self.pdf_path is None or self.doc is None:
            return

        parent = QFileDialog.getExistingDirectory(
            self,
            "Choose folder for OCR bundle",
            str(self.pdf_path.parent),
        )
        if not parent:
            return

        bundle_dir = Path(parent) / f"{self.pdf_path.stem}_ocr_bundle"
        progress = QProgressDialog(
            "Creating OCR bundle…",
            "Cancel",
            0,
            len(self.doc),
            self,
        )
        progress.setWindowTitle("PDF Workbench")
        progress.setMinimumDuration(0)

        def on_progress(done: int, total: int) -> bool:
            progress.setMaximum(total)
            progress.setValue(done)
            QApplication.processEvents()
            return not progress.wasCanceled()

        try:
            result = export_ocr_bundle(
                self.pdf_path,
                bundle_dir,
                self.page_settings,
                dpi=self.dpi_spin.value(),
                quality=self.quality_spin.value(),
                grayscale=self.grayscale.isChecked(),
                include_original=self.include_original.isChecked(),
                progress=on_progress,
            )
            progress.close()
            QMessageBox.information(
                self,
                "OCR bundle complete",
                f"Source pages: {result.source_page_count}\n"
                f"Split pages: {result.output_page_count}\n\n"
                f"{result.bundle_dir}",
            )
        except InterruptedError:
            progress.close()
            self.statusBar().showMessage("OCR bundle export cancelled")
        except Exception as exc:
            progress.close()
            QMessageBox.critical(self, "OCR bundle export failed", str(exc))

    def restore_ocr_results(self) -> None:
        QMessageBox.information(
            self,
            "OCR結果から元のページ構成を復元",
            "この処理には、次の2つが必要です。\n\n"
            "① OCR Bundle（分割情報）\n"
            "   「Export for OCR…」で作成した *_ocr_bundle フォルダを選びます。\n"
            "   フォルダ内の manifest.json には、元のページサイズや分割位置など、\n"
            "   『分割したページをどこへ戻すか』という情報が記録されています。\n\n"
            "② OCR済みPDF\n"
            "   Bundle内の *_split_for_ocr.pdf を、NDLOCRなど任意のOCRソフトで\n"
            "   処理して作成した検索可能PDFを選びます。\n\n"
            "PDF Workbenchは、①の『元に戻すための配置情報』と、\n"
            "②の『OCR済みページ』を組み合わせて、分割前のページ構成を復元します。\n\n"
            "元のPDFそのものを選択する必要はありません。",
        )

        bundle_dir = QFileDialog.getExistingDirectory(
            self,
            "1/2 — OCR Bundleを選択：Export for OCR…で作成した *_ocr_bundle フォルダ",
            str(self.pdf_path.parent) if self.pdf_path else "",
        )
        if not bundle_dir:
            return

        ocr_pdf, _ = QFileDialog.getOpenFileName(
            self,
            "2/2 — OCR済みPDFを選択：分割PDFをOCRソフトで処理して作成した検索可能PDF",
            bundle_dir,
            "PDF files (*.pdf)",
        )
        if not ocr_pdf:
            return

        try:
            _manifest_path, manifest = load_manifest(bundle_dir)
            source = manifest["source"]
            source_filename = source["filename"]
            source_stem = Path(source_filename).stem
            suggested = Path(bundle_dir).parent / f"{source_stem}_ocr_restored.pdf"

            output_pdf, _ = QFileDialog.getSaveFileName(
                self,
                "復元したOCR PDFを保存",
                str(suggested),
                "PDF files (*.pdf)",
            )
            if not output_pdf:
                return

            inspection = inspect_ocr_pdf(bundle_dir, ocr_pdf)
            if not inspection.has_extractable_text:
                answer = QMessageBox.warning(
                    self,
                    "OCR文字が見つかりません",
                    "選択したPDFから検索・コピー可能な文字を検出できませんでした。\n\n"
                    "復元処理自体は続行できますが、完成したPDFは検索可能にならない可能性があります。\n"
                    "このまま続行しますか？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return

            page_count = source["page_count"]
            progress = QProgressDialog(
                "OCRページを元の配置へ復元しています…",
                "Cancel",
                0,
                page_count,
                self,
            )
            progress.setWindowTitle("PDF Workbench")
            progress.setMinimumDuration(0)

            def on_progress(done: int, total: int) -> bool:
                progress.setMaximum(total)
                progress.setValue(done)
                QApplication.processEvents()
                return not progress.wasCanceled()

            try:
                restored_pages, imported_pieces = restore_ocr_pdf(
                    bundle_dir,
                    ocr_pdf,
                    output_pdf,
                    progress=on_progress,
                )
                progress.close()
                QMessageBox.information(
                    self,
                    "復元完了",
                    f"復元した元ページ数: {restored_pages}\n"
                    f"取り込んだ分割ページ数: {imported_pieces}\n\n"
                    f"{output_pdf}",
                )
            except InterruptedError:
                progress.close()
                self.statusBar().showMessage("OCR restore cancelled")
            except Exception:
                progress.close()
                raise
        except Exception as exc:
            QMessageBox.critical(self, "OCR restore failed", str(exc))
