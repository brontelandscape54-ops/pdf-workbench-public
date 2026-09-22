from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QPushButton

from pdf_workbench.core.auto_split import find_best_whitespace_split
from pdf_workbench.core.models import (
    CustomPath,
    CustomSplitDirection,
    CustomSplitNode,
    SplitMode,
    custom_leaf_rects,
    custom_order_after_split,
    normalized_custom_order,
    reorder_custom_subset,
    split_custom_leaf,
)
from pdf_workbench.core.pdf_engine import render_page_to_image

from .main_window import MainWindow


SelectionState = tuple[set[CustomPath], CustomPath, CustomPath | None]


class WorkbenchMainWindow(MainWindow):
    """Main window with advanced Custom-split interaction layered on v0.1 UI."""

    def __init__(self) -> None:
        self._pending_reorder_snapshot = None
        self._pending_custom_selection_snapshot: SelectionState | None = None
        self._history_selection_override: SelectionState | None = None
        self._undo_selection_stack: list[SelectionState] = []
        self._redo_selection_stack: list[SelectionState] = []
        super().__init__()

        self.page_view.on_custom_reorder_progress = self._custom_reorder_progress
        self.page_view.on_custom_reorder_finished = self._custom_reorder_finished
        self.page_view.on_custom_reorder_cancelled = self._custom_reorder_cancelled

        self.custom_reorder_button = QPushButton("選択領域の順番を振り直す")
        self.custom_reorder_button.clicked.connect(self.start_custom_reorder)
        self.custom_auto_split_button = QPushButton("選択領域を自動分割…")
        self.custom_auto_split_button.clicked.connect(self.auto_split_selected_custom)

        panel = self.custom_reset_button.parentWidget()
        layout = panel.layout() if panel is not None else None
        if layout is not None:
            delete_index = layout.indexOf(self.custom_delete_button)
            layout.insertWidget(delete_index, self.custom_auto_split_button)
            reset_index = layout.indexOf(self.custom_reset_button)
            layout.insertWidget(reset_index + 1, self.custom_reorder_button)

        self.custom_help.setText(
            self.custom_help.text()
            + "\n『選択領域を自動分割…』は紙面の白い谷から候補線を提案します。"
            + "\n連続番号の領域を複数選択 →『順番を振り直す』→ 希望順にクリック。Escでキャンセル。"
        )
        is_custom = bool(self.page_settings) and self.page_settings[self.current_page].mode == SplitMode.CUSTOM
        self.custom_reorder_button.setVisible(is_custom)
        self.custom_reorder_button.setEnabled(is_custom)
        self.custom_auto_split_button.setVisible(is_custom)
        self.custom_auto_split_button.setEnabled(is_custom)

    def _set_custom_controls_visible(self, visible: bool) -> None:
        super()._set_custom_controls_visible(visible)
        if hasattr(self, "custom_reorder_button"):
            self.custom_reorder_button.setVisible(visible)
        if hasattr(self, "custom_auto_split_button"):
            self.custom_auto_split_button.setVisible(visible)

    def _set_controls_enabled(self, enabled: bool) -> None:
        super()._set_controls_enabled(enabled)
        if hasattr(self, "custom_reorder_button"):
            self.custom_reorder_button.setEnabled(enabled)
        if hasattr(self, "custom_auto_split_button"):
            self.custom_auto_split_button.setEnabled(enabled)

    def _capture_custom_selection(self) -> SelectionState:
        return (
            self.page_view.selected_custom_paths,
            self.page_view.selected_custom_path,
            self.page_view.selected_custom_line_path,
        )

    def _resolve_selection_path(self, path: CustomPath) -> CustomPath | None:
        if not self.page_settings:
            return None
        settings = self.page_settings[self.current_page]
        if settings.mode != SplitMode.CUSTOM:
            return None
        order = normalized_custom_order(settings.custom_root, settings.custom_order)
        valid = set(order)
        if path in valid:
            return path

        candidate = path
        while candidate:
            candidate = candidate[:-1]
            if candidate in valid:
                return candidate

        descendants = [
            leaf for leaf in order if len(leaf) >= len(path) and leaf[: len(path)] == path
        ]
        return descendants[0] if descendants else (order[0] if order else None)

    def _restore_custom_selection_state(self, state: SelectionState) -> None:
        if not self.page_settings:
            return
        settings = self.page_settings[self.current_page]
        if settings.mode != SplitMode.CUSTOM:
            return
        old_paths, old_active, old_line = state
        resolved = {
            result
            for path in old_paths
            if (result := self._resolve_selection_path(path)) is not None
        }
        active = self._resolve_selection_path(old_active)
        if not resolved and active is not None:
            resolved = {active}
        if active is None and resolved:
            active = next(iter(resolved))
        if active is None:
            return
        self.page_view.restore_custom_selection(resolved, active, old_line)
        self._refresh_custom_selection_label()

    def _record_undo_snapshot(self, snapshot) -> None:
        _page_index, settings = snapshot
        if settings == self.page_settings:
            self._history_selection_override = None
            return
        selection = self._history_selection_override or self._capture_custom_selection()
        super()._record_undo_snapshot(snapshot)
        self._undo_selection_stack.append(selection)
        if len(self._undo_selection_stack) > self.HISTORY_LIMIT:
            self._undo_selection_stack.pop(0)
        self._redo_selection_stack.clear()
        self._history_selection_override = None

    def _custom_edit_started(self) -> None:
        if self._pending_custom_selection_snapshot is None:
            self._pending_custom_selection_snapshot = self._capture_custom_selection()
        super()._custom_edit_started()

    def _custom_edit_finished(self) -> None:
        if self._pending_custom_selection_snapshot is not None:
            self._history_selection_override = self._pending_custom_selection_snapshot
        if (
            self._pending_custom_snapshot is not None
            and self._pending_custom_snapshot[1][self.current_page]
            != self.page_settings[self.current_page]
        ):
            sync = getattr(self, "_sync_selected_page_layout", None)
            if callable(sync):
                sync()
        super()._custom_edit_finished()
        self._pending_custom_selection_snapshot = None

    def undo(self) -> None:
        if not self._undo_stack:
            return
        redo_selection = self._capture_custom_selection()
        undo_selection = (
            self._undo_selection_stack.pop()
            if self._undo_selection_stack
            else redo_selection
        )
        super().undo()
        self._redo_selection_stack.append(redo_selection)
        self._restore_custom_selection_state(undo_selection)

    def redo(self) -> None:
        if not self._redo_stack:
            return
        undo_selection = self._capture_custom_selection()
        redo_selection = (
            self._redo_selection_stack.pop()
            if self._redo_selection_stack
            else undo_selection
        )
        super().redo()
        self._undo_selection_stack.append(undo_selection)
        self._restore_custom_selection_state(redo_selection)

    def _refresh_custom_selection_label(self) -> None:
        if not self.page_settings:
            return
        settings = self.page_settings[self.current_page]
        if settings.mode != SplitMode.CUSTOM:
            return
        order = normalized_custom_order(settings.custom_root, settings.custom_order)
        selected = self.page_view.selected_custom_paths
        if self.page_view.is_reordering_custom:
            return
        if len(selected) > 1:
            numbers = sorted(order.index(path) + 1 for path in selected if path in order)
            if numbers:
                self.custom_selected_label.setText(
                    f"選択領域: {', '.join(map(str, numbers))} / 全 {len(order)} 個"
                )
            return
        path = self.page_view.selected_custom_path
        number = order.index(path) + 1 if path in order else 1
        self.custom_selected_label.setText(
            f"選択領域: {number} / {len(order)}  （色付き領域が選択中）"
        )

    def _split_custom_at_ratio(
        self,
        direction: CustomSplitDirection,
        ratio: float,
    ) -> None:
        if not self.page_settings:
            return
        settings = self.page_settings[self.current_page]
        if settings.mode != SplitMode.CUSTOM:
            return
        selected_path = self.page_view.selected_custom_path
        root_before = settings.custom_root.clone()
        old_order = normalized_custom_order(root_before, settings.custom_order)
        snapshot = (self.current_page, self._clone_all_settings())
        selection_before = self._capture_custom_selection()
        try:
            new_order = custom_order_after_split(
                root_before,
                old_order,
                selected_path,
            )
            split_custom_leaf(
                settings.custom_root,
                selected_path,
                direction,
                ratio=ratio,
            )
            settings.custom_order = new_order
        except ValueError as exc:
            QMessageBox.warning(self, "Custom split", str(exc))
            return
        self._history_selection_override = selection_before
        sync = getattr(self, "_sync_selected_page_layout", None)
        if callable(sync):
            sync()
        self._record_undo_snapshot(snapshot)
        self.page_view.set_settings(settings)
        self.page_view.select_custom_path(selected_path + (0,))
        self._refresh_custom_selection_label()
        self._refresh_thumbnail(self.current_page)

    def split_selected_custom(self, direction: CustomSplitDirection) -> None:
        self._split_custom_at_ratio(direction, 0.5)

    def auto_split_selected_custom(self) -> None:
        if not self.page_settings or self.doc is None:
            return
        settings = self.page_settings[self.current_page]
        if settings.mode != SplitMode.CUSTOM:
            return
        if len(self.page_view.selected_custom_paths) != 1:
            QMessageBox.information(
                self,
                "自動分割",
                "自動分割する領域を1つだけ選択してください。",
            )
            return

        selected_path = self.page_view.selected_custom_path
        rects = custom_leaf_rects(settings.custom_root)
        normalized_rect = rects.get(selected_path)
        if normalized_rect is None:
            return

        try:
            image = render_page_to_image(self.doc[self.current_page], 110)
            x0, y0, x1, y1 = normalized_rect
            crop_box = (
                max(0, min(image.width - 1, round(x0 * image.width))),
                max(0, min(image.height - 1, round(y0 * image.height))),
                max(1, min(image.width, round(x1 * image.width))),
                max(1, min(image.height, round(y1 * image.height))),
            )
            if crop_box[2] - crop_box[0] < 24 or crop_box[3] - crop_box[1] < 24:
                raise ValueError("選択領域が小さすぎるため解析できません")
            candidate = find_best_whitespace_split(image.crop(crop_box))
        except Exception as exc:
            QMessageBox.warning(self, "自動分割", f"画像解析に失敗しました。\n\n{exc}")
            return

        if candidate is None:
            QMessageBox.information(
                self,
                "自動分割",
                "この領域では、十分に明瞭な白い分割候補を見つけられませんでした。\n"
                "手動で分割するか、より大きな領域を選択して試してください。",
            )
            return

        if candidate.direction is CustomSplitDirection.VERTICAL:
            description = "左右に分割（縦線）"
            axis_name = "左端から"
        else:
            description = "上下に分割（横線）"
            axis_name = "上端から"

        answer = QMessageBox.question(
            self,
            "自動分割候補",
            f"白い余白から次の候補を検出しました。\n\n"
            f"分割方向: {description}\n"
            f"候補位置: {axis_name} {candidate.ratio * 100:.1f}%\n"
            f"候補の余白幅: 領域の {candidate.gap_width_ratio * 100:.1f}%\n"
            f"信頼度（暫定）: {candidate.score:.2f}\n\n"
            "この位置で分割しますか？\n"
            "分割後も赤線をドラッグして調整でき、⌘Zで戻せます。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._split_custom_at_ratio(candidate.direction, candidate.ratio)
        self.statusBar().showMessage(
            f"自動候補で{description}しました（{candidate.ratio * 100:.1f}%）"
        )

    def reset_custom_layout(self) -> None:
        if not self.page_settings:
            return
        snapshot = (self.current_page, self._clone_all_settings())
        selection_before = self._capture_custom_selection()
        settings = self.page_settings[self.current_page]
        settings.custom_root = CustomSplitNode()
        settings.custom_order = []
        self._history_selection_override = selection_before
        sync = getattr(self, "_sync_selected_page_layout", None)
        if callable(sync):
            sync()
        self._record_undo_snapshot(snapshot)
        self.page_view.set_settings(settings)
        self.page_view.select_custom_path(())
        self._refresh_custom_selection_label()
        self._refresh_thumbnail(self.current_page)

    def start_custom_reorder(self) -> None:
        if not self.page_settings:
            return
        settings = self.page_settings[self.current_page]
        if settings.mode != SplitMode.CUSTOM:
            return
        selected = self.page_view.selected_custom_paths
        order = normalized_custom_order(settings.custom_root, settings.custom_order)
        positions = sorted(order.index(path) for path in selected if path in order)
        if len(positions) < 2:
            QMessageBox.information(
                self,
                "順番を振り直す",
                "番号が連続している2つ以上の領域を先に選択してください。",
            )
            return
        if positions != list(range(positions[0], positions[-1] + 1)):
            QMessageBox.warning(
                self,
                "順番を振り直す",
                "番号が連続している領域だけを選択してください。",
            )
            return
        self._pending_reorder_snapshot = (
            self.current_page,
            self._clone_all_settings(),
            self._capture_custom_selection(),
        )
        if self.page_view.begin_custom_reorder(selected):
            first_number = positions[0] + 1
            last_number = positions[-1] + 1
            self.custom_selected_label.setText(
                f"順番振り直し: {first_number}〜{last_number} を希望順にクリック（Escで中止）"
            )

    def _custom_reorder_progress(self, done: int, total: int) -> None:
        self.custom_selected_label.setText(
            f"順番振り直し中: {done}/{total} 選択済み — 次の領域をクリック（Escで中止）"
        )

    def _custom_reorder_finished(
        self,
        selected: set[CustomPath],
        clicked: list[CustomPath],
    ) -> None:
        if not self.page_settings or self._pending_reorder_snapshot is None:
            return
        settings = self.page_settings[self.current_page]
        page_index, before_settings, selection_before = self._pending_reorder_snapshot
        try:
            settings.custom_order = reorder_custom_subset(
                settings.custom_root,
                settings.custom_order,
                selected,
                clicked,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "順番を振り直す", str(exc))
            self._pending_reorder_snapshot = None
            return
        self._history_selection_override = selection_before
        sync = getattr(self, "_sync_selected_page_layout", None)
        if callable(sync):
            sync()
        self._record_undo_snapshot((page_index, before_settings))
        self._pending_reorder_snapshot = None
        self.page_view.set_settings(settings)
        self.page_view.restore_custom_selection(set(clicked), clicked[-1])
        self._refresh_thumbnail(self.current_page)
        self._refresh_custom_selection_label()
        self.statusBar().showMessage("選択領域のOCR順を振り直しました")

    def _custom_reorder_cancelled(self) -> None:
        if self._pending_reorder_snapshot is not None:
            _page_index, _settings, selection = self._pending_reorder_snapshot
            self._pending_reorder_snapshot = None
            self._restore_custom_selection_state(selection)
        self._refresh_custom_selection_label()
        self.statusBar().showMessage("順番の振り直しをキャンセルしました")
