from __future__ import annotations

import json
from pathlib import Path
from types import MethodType

import fitz
from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
    QProgressDialog,
    QPushButton,
)

from pdf_workbench.core.ocr_bundle import export_ocr_bundle
from pdf_workbench.core.workspace import (
    WORKSPACE_FILENAME,
    WORKSPACE_FORMAT,
    WORKSPACE_VERSION,
    load_bundle_workspace,
    source_candidates,
    source_matches_manifest,
)


def _workspace_payload(window) -> dict[str, object]:
    auto_sensitivity = None
    if hasattr(window, "auto_split_sensitivity"):
        auto_sensitivity = window.auto_split_sensitivity.currentData()

    auto_max_regions = None
    if hasattr(window, "auto_split_max_regions"):
        auto_max_regions = int(window.auto_split_max_regions.value())

    balance_fallback = None
    if hasattr(window, "auto_split_balance_fallback"):
        balance_fallback = bool(window.auto_split_balance_fallback.isChecked())

    return {
        "format": WORKSPACE_FORMAT,
        "version": WORKSPACE_VERSION,
        "source_pdf_path": str(window.pdf_path.resolve()) if window.pdf_path else None,
        "current_page": int(window.current_page),
        "locked_pages": sorted(int(index) for index in getattr(window, "locked_pages", set())),
        "export": {
            "dpi": int(window.dpi_spin.value()),
            "jpeg_quality": int(window.quality_spin.value()),
            "grayscale": bool(window.grayscale.isChecked()),
            "include_original": bool(window.include_original.isChecked()),
        },
        "auto_split": {
            "sensitivity": auto_sensitivity,
            "max_regions": auto_max_regions,
            "balance_fallback": balance_fallback,
        },
    }


def _write_workspace(window, bundle_dir: Path) -> None:
    payload = _workspace_payload(window)
    (bundle_dir / WORKSPACE_FILENAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def install_workspace_resume(window) -> None:
    """Make OCR bundles double as project-save / resume containers."""

    # New sessions default to color output. Users can still enable Grayscale.
    window.grayscale.setChecked(False)

    def export_for_ocr_with_workspace(self) -> None:
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
            _write_workspace(self, result.bundle_dir)
            QMessageBox.information(
                self,
                "OCR bundle complete",
                f"Source pages: {result.source_page_count}\n"
                f"Split pages: {result.output_page_count}\n\n"
                f"作業再開情報: {WORKSPACE_FILENAME}\n\n"
                f"{result.bundle_dir}",
            )
        except InterruptedError:
            progress.close()
            self.statusBar().showMessage("OCR bundle export cancelled")
        except Exception as exc:
            progress.close()
            QMessageBox.critical(self, "OCR bundle export failed", str(exc))

    try:
        window.export_ocr_button.clicked.disconnect()
    except (RuntimeError, TypeError):
        pass
    window.export_for_ocr = MethodType(export_for_ocr_with_workspace, window)
    window.export_ocr_button.clicked.connect(window.export_for_ocr)

    def choose_source_pdf(self, bundle_dir: Path, manifest, workspace) -> Path | None:
        for candidate in source_candidates(bundle_dir, manifest, workspace):
            try:
                if source_matches_manifest(candidate, manifest):
                    return candidate
            except Exception:
                continue

        expected_name = ""
        source = manifest.get("source")
        if isinstance(source, dict):
            expected_name = str(source.get("filename", ""))

        QMessageBox.information(
            self,
            "元PDFを選択",
            "Bundleに記録された元PDFの場所を見つけられませんでした。\n"
            "元PDFを移動・改名した場合は、現在の場所を選択してください。\n\n"
            f"記録上のファイル名: {expected_name}",
        )
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "元PDFを選択",
            str(bundle_dir.parent),
            "PDF files (*.pdf)",
        )
        if not filename:
            return None
        candidate = Path(filename).expanduser().resolve()
        try:
            if not source_matches_manifest(candidate, manifest):
                answer = QMessageBox.warning(
                    self,
                    "元PDFが一致しません",
                    "選択したPDFのSHA-256がBundle作成時の元PDFと一致しません。\n"
                    "別のPDFへ分割設定を適用すると位置がずれる可能性があります。\n\n"
                    "それでも開きますか？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return None
        except Exception as exc:
            QMessageBox.warning(self, "元PDF確認", str(exc))
            return None
        return candidate

    def restore_ui_settings(self, workspace) -> None:
        if not isinstance(workspace, dict):
            return
        export = workspace.get("export")
        if isinstance(export, dict):
            if export.get("dpi") is not None:
                self.dpi_spin.setValue(int(export["dpi"]))
            if export.get("jpeg_quality") is not None:
                self.quality_spin.setValue(int(export["jpeg_quality"]))
            if export.get("grayscale") is not None:
                self.grayscale.setChecked(bool(export["grayscale"]))
            if export.get("include_original") is not None:
                self.include_original.setChecked(bool(export["include_original"]))

        auto_split = workspace.get("auto_split")
        if isinstance(auto_split, dict):
            sensitivity = auto_split.get("sensitivity")
            if sensitivity is not None and hasattr(self, "auto_split_sensitivity"):
                index = self.auto_split_sensitivity.findData(sensitivity)
                if index >= 0:
                    self.auto_split_sensitivity.setCurrentIndex(index)
            max_regions = auto_split.get("max_regions")
            if max_regions is not None and hasattr(self, "auto_split_max_regions"):
                self.auto_split_max_regions.setValue(int(max_regions))
            balance = auto_split.get("balance_fallback")
            if balance is not None and hasattr(self, "auto_split_balance_fallback"):
                self.auto_split_balance_fallback.setChecked(bool(balance))

    def open_ocr_bundle(self) -> None:
        start = str(self.pdf_path.parent) if self.pdf_path else ""
        bundle_name = QFileDialog.getExistingDirectory(
            self,
            "作業を再開するOCR Bundleを選択",
            start,
        )
        if not bundle_name:
            return
        bundle_dir = Path(bundle_name).expanduser().resolve()

        try:
            manifest, workspace, settings = load_bundle_workspace(bundle_dir)
            source_path = choose_source_pdf(self, bundle_dir, manifest, workspace)
            if source_path is None:
                return

            doc = fitz.open(str(source_path))
            if len(doc) != len(settings):
                doc.close()
                raise ValueError(
                    f"元PDFは {len(doc)} 頁ですが、Bundleの設定は {len(settings)} 頁です"
                )

            if self.doc is not None:
                self.doc.close()
            self.pdf_path = source_path
            self.doc = doc
            self.page_settings = [item.clone() for item in settings]

            requested_page = 0
            if isinstance(workspace, dict):
                requested_page = int(workspace.get("current_page", 0))
            self.current_page = max(0, min(len(self.doc) - 1, requested_page))

            if hasattr(self, "locked_pages"):
                self.locked_pages.clear()
                if isinstance(workspace, dict):
                    raw_locked = workspace.get("locked_pages", [])
                    if isinstance(raw_locked, list):
                        self.locked_pages.update(
                            index
                            for raw in raw_locked
                            if isinstance(raw, int)
                            and 0 <= (index := int(raw)) < len(self.doc)
                        )

            self._undo_stack.clear()
            self._redo_stack.clear()
            if hasattr(self, "_undo_selection_stack"):
                self._undo_selection_stack.clear()
            if hasattr(self, "_redo_selection_stack"):
                self._redo_selection_stack.clear()
            self._pending_custom_snapshot = None

            with QSignalBlocker(self.page_spin):
                self.page_spin.setRange(1, len(self.doc))
                self.page_spin.setValue(self.current_page + 1)
            self.page_count_label.setText(f"/ {len(self.doc)}")
            self._set_controls_enabled(True)
            restore_ui_settings(self, workspace)
            self._populate_thumbnails()
            self._show_current_page()
            self._update_history_actions()
            self.statusBar().showMessage(f"OCR Bundleから作業を再開: {bundle_dir}")

            if workspace is None:
                QMessageBox.information(
                    self,
                    "作業を再開しました",
                    "このBundleはworkspace.json導入前に作成されたものです。\n"
                    "分割設定はmanifest.jsonから復元しました。\n"
                    "現在頁・固定頁・UI設定は保存されていないため初期値になっています。",
                )
        except Exception as exc:
            QMessageBox.critical(self, "OCR Bundleを開けませんでした", str(exc))

    window.open_ocr_bundle = MethodType(open_ocr_bundle, window)

    # Put the resume entry point directly below Open PDF in the manual panel.
    manual_panel = None
    if hasattr(window, "manual_controls_scroll"):
        manual_panel = window.manual_controls_scroll.widget()
    if manual_panel is not None and manual_panel.layout() is not None:
        layout = manual_panel.layout()
        open_bundle_button = QPushButton("Open OCR Bundle…")
        open_bundle_button.clicked.connect(window.open_ocr_bundle)
        insert_at = 1
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if isinstance(widget, QPushButton) and widget.text() == "Open PDF…":
                insert_at = index + 1
                break
        layout.insertWidget(insert_at, open_bundle_button)
        window.open_bundle_button = open_bundle_button

    file_menu = None
    for action in window.menuBar().actions():
        if action.text().replace("&", "") == "File":
            file_menu = action.menu()
            break
    if file_menu is not None:
        open_bundle_action = QAction("Open OCR Bundle…", window)
        open_bundle_action.triggered.connect(window.open_ocr_bundle)
        actions = file_menu.actions()
        insert_before = None
        for index, action in enumerate(actions):
            if action.text().replace("&", "") == "Open PDF…":
                insert_before = actions[index + 1] if index + 1 < len(actions) else None
                break
        if insert_before is not None:
            file_menu.insertAction(insert_before, open_bundle_action)
        else:
            file_menu.addAction(open_bundle_action)
        window.open_bundle_action = open_bundle_action
