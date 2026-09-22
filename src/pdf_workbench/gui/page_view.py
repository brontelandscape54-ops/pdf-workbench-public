from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeyEvent,
    QNativeGestureEvent,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from pdf_workbench.core.models import (
    CustomSplitDirection,
    CustomSplitNode,
    PageSplitSettings,
    SplitMode,
    collapse_custom_split,
    custom_leaf_paths,
    custom_leaf_rects,
    merge_custom_leaves,
    normalized_custom_order,
)


CustomPath = tuple[int, ...]
SPLIT_LINE_HIT_WIDTH = 20.0


def _cosmetic_pen(color, width: int, style: Qt.PenStyle | None = None) -> QPen:
    pen = QPen(color, width)
    pen.setCosmetic(True)
    if style is not None:
        pen.setStyle(style)
    return pen


def _wide_line_shape(line, width: float = SPLIT_LINE_HIT_WIDTH) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(line.p1())
    path.lineTo(line.p2())
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    return stroker.createStroke(path)


class _SplitLine(QGraphicsLineItem):
    def __init__(
        self,
        orientation: Qt.Orientation,
        extent: float,
        on_changed: Callable[[float], None],
    ) -> None:
        super().__init__()
        self.orientation = orientation
        self.extent = extent
        self.on_changed = on_changed
        self.setPen(_cosmetic_pen(Qt.GlobalColor.red, 4))
        self.setZValue(10)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        if orientation == Qt.Orientation.Vertical:
            self.setLine(0, 0, 0, extent)
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setLine(0, 0, extent, 0)
            self.setCursor(Qt.CursorShape.SizeVerCursor)

    def shape(self) -> QPainterPath:  # type: ignore[override]
        return _wide_line_shape(self.line())

    def boundingRect(self) -> QRectF:  # type: ignore[override]
        return self.shape().boundingRect()

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value):  # type: ignore[override]
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and isinstance(value, QPointF):
            scene = self.scene()
            if scene is None:
                return value
            rect = scene.sceneRect()
            if self.orientation == Qt.Orientation.Vertical:
                x = min(rect.right(), max(rect.left(), value.x()))
                return QPointF(x, 0)
            y = min(rect.bottom(), max(rect.top(), value.y()))
            return QPointF(0, y)

        result = super().itemChange(change, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            scene = self.scene()
            if scene is not None:
                rect = scene.sceneRect()
                if self.orientation == Qt.Orientation.Vertical and rect.width() > 0:
                    self.on_changed(self.pos().x() / rect.width())
                elif self.orientation == Qt.Orientation.Horizontal and rect.height() > 0:
                    self.on_changed(self.pos().y() / rect.height())
        return result


class _CustomRegionItem(QGraphicsRectItem):
    def __init__(
        self,
        rect: QRectF,
        path: CustomPath,
        selected: bool,
        reorder_clicked: bool,
        on_selected: Callable[[CustomPath, bool], None],
    ) -> None:
        super().__init__(rect)
        self.path = path
        self.on_selected = on_selected
        self.setZValue(5)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if reorder_clicked:
            self.setPen(_cosmetic_pen(QColor(0, 150, 80), 5))
            self.setBrush(QBrush(QColor(0, 180, 90, 85)))
        elif selected:
            self.setPen(_cosmetic_pen(QColor(0, 110, 255), 4))
            self.setBrush(QBrush(QColor(0, 120, 255, 70)))
        else:
            self.setPen(
                _cosmetic_pen(QColor(0, 120, 255, 150), 2, Qt.PenStyle.DashLine)
            )
            self.setBrush(QBrush(Qt.BrushStyle.NoBrush))

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        additive = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self.on_selected(self.path, additive)
        event.accept()


class _CustomSplitLine(QGraphicsLineItem):
    def __init__(
        self,
        direction: CustomSplitDirection,
        bounds: QRectF,
        ratio: float,
        path: CustomPath,
        selected: bool,
        on_selected: Callable[[CustomPath], None],
        on_started: Callable[[CustomPath], None],
        on_finished: Callable[[CustomPath], None],
    ) -> None:
        super().__init__()
        self.direction = direction
        self.bounds = bounds
        self.path = path
        self.on_selected = on_selected
        self.on_started = on_started
        self.on_finished = on_finished
        self.set_selected_visual(selected)
        self.setZValue(12)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

        if direction is CustomSplitDirection.VERTICAL:
            self.setLine(0, bounds.top(), 0, bounds.bottom())
            self.setPos(bounds.left() + bounds.width() * ratio, 0)
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setLine(bounds.left(), 0, bounds.right(), 0)
            self.setPos(0, bounds.top() + bounds.height() * ratio)
            self.setCursor(Qt.CursorShape.SizeVerCursor)

    def shape(self) -> QPainterPath:  # type: ignore[override]
        return _wide_line_shape(self.line())

    def boundingRect(self) -> QRectF:  # type: ignore[override]
        return self.shape().boundingRect()

    def set_selected_visual(self, selected: bool) -> None:
        self.setPen(
            _cosmetic_pen(
                QColor(210, 0, 160) if selected else Qt.GlobalColor.red,
                7 if selected else 4,
            )
        )

    def absolute_position(self) -> float:
        if self.direction is CustomSplitDirection.VERTICAL:
            return self.pos().x()
        return self.pos().y()

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value):  # type: ignore[override]
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and isinstance(value, QPointF):
            if self.direction is CustomSplitDirection.VERTICAL:
                x = min(self.bounds.right() - 1, max(self.bounds.left() + 1, value.x()))
                return QPointF(x, 0)
            y = min(self.bounds.bottom() - 1, max(self.bounds.top() + 1, value.y()))
            return QPointF(0, y)
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.on_selected(self.path)
        self.on_started(self.path)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        super().mouseReleaseEvent(event)
        QTimer.singleShot(0, lambda: self.on_finished(self.path))


class PageView(QGraphicsView):
    MIN_ZOOM = 0.15
    MAX_ZOOM = 8.0

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHints(self.renderHints())
        self._pixmap_item = None
        self._vertical_line: _SplitLine | None = None
        self._horizontal_line: _SplitLine | None = None
        self._custom_items: list[QGraphicsItem] = []
        self._custom_line_items: dict[CustomPath, _CustomSplitLine] = {}
        self._settings: PageSplitSettings | None = None
        self._selected_custom_paths: set[CustomPath] = {()}
        self._active_custom_path: CustomPath = ()
        self._selected_custom_line_path: CustomPath | None = None
        self._reorder_targets: set[CustomPath] | None = None
        self._reorder_clicked: list[CustomPath] = []
        self.on_x_ratio_changed: Callable[[float], None] | None = None
        self.on_y_ratio_changed: Callable[[float], None] | None = None
        self.on_custom_selected: Callable[[CustomPath], None] | None = None
        self.on_custom_edit_started: Callable[[], None] | None = None
        self.on_custom_edit_finished: Callable[[], None] | None = None
        self.on_custom_error: Callable[[str], None] | None = None
        self.on_custom_split_requested: Callable[[CustomSplitDirection], None] | None = None
        self.on_custom_reorder_progress: Callable[[int, int], None] | None = None
        self.on_custom_reorder_finished: Callable[[set[CustomPath], list[CustomPath]], None] | None = None
        self.on_custom_reorder_cancelled: Callable[[], None] | None = None

    @property
    def selected_custom_path(self) -> CustomPath:
        return self._active_custom_path

    @property
    def selected_custom_paths(self) -> set[CustomPath]:
        return set(self._selected_custom_paths)

    @property
    def selected_custom_line_path(self) -> CustomPath | None:
        return self._selected_custom_line_path

    @property
    def is_reordering_custom(self) -> bool:
        return self._reorder_targets is not None

    def _reading_order(self) -> list[CustomPath]:
        if self._settings is None:
            return []
        return normalized_custom_order(
            self._settings.custom_root,
            self._settings.custom_order,
        )

    def set_page(self, pixmap: QPixmap, settings: PageSplitSettings) -> None:
        self._scene.clear()
        self._pixmap_item = None
        self._vertical_line = None
        self._horizontal_line = None
        self._custom_items = []
        self._custom_line_items = {}
        self._settings = settings
        self._selected_custom_paths = {()}
        self._active_custom_path = ()
        self._selected_custom_line_path = None
        self._reorder_targets = None
        self._reorder_clicked = []
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(self._pixmap_item.boundingRect())
        self._rebuild_lines()
        self.fit_page()

    def set_settings(self, settings: PageSplitSettings) -> None:
        self._settings = settings
        self._rebuild_lines()

    @staticmethod
    def _closest_existing_path(path: CustomPath, valid: set[CustomPath]) -> CustomPath | None:
        candidate = path
        while True:
            if candidate in valid:
                return candidate
            if not candidate:
                return None
            candidate = candidate[:-1]

    def restore_custom_selection(
        self,
        paths: set[CustomPath] | tuple[CustomPath, ...] | list[CustomPath],
        active_path: CustomPath,
        line_path: CustomPath | None = None,
    ) -> None:
        if self._settings is None or self._settings.mode != SplitMode.CUSTOM:
            return
        valid = set(custom_leaf_paths(self._settings.custom_root))
        restored: set[CustomPath] = set()
        for path in paths:
            closest = self._closest_existing_path(tuple(path), valid)
            if closest is not None:
                restored.add(closest)
        if not restored:
            order = self._reading_order()
            if order:
                restored = {order[0]}
        active = self._closest_existing_path(active_path, valid)
        if active is None or active not in restored:
            active = next(iter(restored), ())
        self._selected_custom_paths = restored or {()}
        self._active_custom_path = active
        self._selected_custom_line_path = line_path
        self._rebuild_lines()
        if self.on_custom_selected:
            self.on_custom_selected(self._active_custom_path)

    def select_custom_path(self, path: CustomPath) -> bool:
        if self._settings is None or self._settings.mode != SplitMode.CUSTOM:
            return False
        if path not in set(custom_leaf_paths(self._settings.custom_root)):
            return False
        self._selected_custom_paths = {path}
        self._active_custom_path = path
        self._selected_custom_line_path = None
        if self.on_custom_selected:
            self.on_custom_selected(path)
        self.setFocus()
        self._rebuild_lines()
        return True

    def begin_custom_reorder(self, paths: set[CustomPath]) -> bool:
        if self._settings is None or self._settings.mode != SplitMode.CUSTOM:
            return False
        order = self._reading_order()
        selected = set(paths)
        if len(selected) < 2:
            if self.on_custom_error:
                self.on_custom_error("順番を振り直すには2つ以上の領域を選択してください")
            return False
        if not selected.issubset(set(order)):
            if self.on_custom_error:
                self.on_custom_error("選択領域が現在の分割と一致しません")
            return False
        positions = sorted(order.index(path) for path in selected)
        if positions != list(range(positions[0], positions[-1] + 1)):
            if self.on_custom_error:
                self.on_custom_error("番号が連続している領域だけを選択してください")
            return False
        self._reorder_targets = selected
        self._reorder_clicked = []
        self._selected_custom_paths = set(selected)
        self._selected_custom_line_path = None
        self.setFocus()
        self._rebuild_lines()
        if self.on_custom_reorder_progress:
            self.on_custom_reorder_progress(0, len(selected))
        return True

    def cancel_custom_reorder(self) -> None:
        if self._reorder_targets is None:
            return
        self._reorder_targets = None
        self._reorder_clicked = []
        self._rebuild_lines()
        if self.on_custom_reorder_cancelled:
            self.on_custom_reorder_cancelled()

    def _remove_guides(self) -> None:
        if self._vertical_line is not None:
            self._scene.removeItem(self._vertical_line)
        if self._horizontal_line is not None:
            self._scene.removeItem(self._horizontal_line)
        self._vertical_line = None
        self._horizontal_line = None
        for item in self._custom_items:
            if item.scene() is self._scene:
                self._scene.removeItem(item)
        self._custom_items = []
        self._custom_line_items = {}

    def _rebuild_lines(self) -> None:
        if self._settings is None or self._pixmap_item is None:
            return
        self._remove_guides()

        rect = self._scene.sceneRect()
        s = self._settings.normalized()

        if s.mode == SplitMode.CUSTOM:
            order = normalized_custom_order(s.custom_root, s.custom_order)
            valid = set(order)
            self._selected_custom_paths &= valid
            if self._reorder_targets is not None:
                self._reorder_targets &= valid
                self._reorder_clicked = [
                    path for path in self._reorder_clicked if path in self._reorder_targets
                ]
            if not self._selected_custom_paths:
                first = order[0] if order else ()
                self._selected_custom_paths = {first}
            if self._active_custom_path not in valid:
                self._active_custom_path = next(iter(self._selected_custom_paths))
            self._build_custom_items(s.custom_root, rect, ())
            if self._selected_custom_line_path not in self._custom_line_items:
                self._selected_custom_line_path = None
            return

        self._selected_custom_line_path = None
        if s.mode == SplitMode.FOUR:
            self._vertical_line = _SplitLine(
                Qt.Orientation.Vertical,
                rect.height(),
                self._x_moved,
            )
            self._vertical_line.setPos(rect.width() * s.x_ratio, 0)
            self._scene.addItem(self._vertical_line)

        if s.mode in {SplitMode.FOUR, SplitMode.HORIZONTAL_2}:
            self._horizontal_line = _SplitLine(
                Qt.Orientation.Horizontal,
                rect.width(),
                self._y_moved,
            )
            self._horizontal_line.setPos(0, rect.height() * s.y_ratio)
            self._scene.addItem(self._horizontal_line)

    def _build_custom_items(
        self,
        node: CustomSplitNode,
        bounds: QRectF,
        path: CustomPath,
    ) -> None:
        if node.is_leaf:
            region = _CustomRegionItem(
                bounds,
                path,
                path in self._selected_custom_paths,
                path in self._reorder_clicked,
                self._select_custom_path,
            )
            self._scene.addItem(region)
            self._custom_items.append(region)

            order = self._reading_order()
            number = order.index(path) + 1 if path in order else 1
            label = QGraphicsSimpleTextItem(str(number))
            font = QFont()
            font.setPointSize(28)
            font.setBold(True)
            label.setFont(font)
            label.setBrush(QBrush(QColor(0, 45, 190)))
            label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            label.setZValue(15)
            label_rect = label.boundingRect()
            label.setPos(
                bounds.center().x() - label_rect.width() / 2,
                bounds.center().y() - label_rect.height() / 2,
            )
            self._scene.addItem(label)
            self._custom_items.append(label)
            return

        if node.direction is None or node.first is None or node.second is None:
            return

        ratio = min(0.999, max(0.001, float(node.ratio)))
        line = _CustomSplitLine(
            node.direction,
            bounds,
            ratio,
            path,
            path == self._selected_custom_line_path,
            self._select_custom_line,
            self._custom_drag_started,
            self._custom_drag_finished,
        )
        self._scene.addItem(line)
        self._custom_items.append(line)
        self._custom_line_items[path] = line

        first_bounds, second_bounds = self._child_bounds(node.direction, bounds, ratio)
        self._build_custom_items(node.first, first_bounds, path + (0,))
        self._build_custom_items(node.second, second_bounds, path + (1,))

    @staticmethod
    def _child_bounds(
        direction: CustomSplitDirection,
        bounds: QRectF,
        ratio: float,
    ) -> tuple[QRectF, QRectF]:
        if direction is CustomSplitDirection.VERTICAL:
            split_x = bounds.left() + bounds.width() * ratio
            return (
                QRectF(split_x, bounds.top(), bounds.right() - split_x, bounds.height()),
                QRectF(bounds.left(), bounds.top(), split_x - bounds.left(), bounds.height()),
            )
        split_y = bounds.top() + bounds.height() * ratio
        return (
            QRectF(bounds.left(), bounds.top(), bounds.width(), split_y - bounds.top()),
            QRectF(bounds.left(), split_y, bounds.width(), bounds.bottom() - split_y),
        )

    def _select_custom_path(self, path: CustomPath, additive: bool = False) -> None:
        if self._reorder_targets is not None:
            if path not in self._reorder_targets or path in self._reorder_clicked:
                return
            self._reorder_clicked.append(path)
            self._active_custom_path = path
            self._rebuild_lines()
            if self.on_custom_reorder_progress:
                self.on_custom_reorder_progress(
                    len(self._reorder_clicked),
                    len(self._reorder_targets),
                )
            if len(self._reorder_clicked) == len(self._reorder_targets):
                targets = set(self._reorder_targets)
                clicked = list(self._reorder_clicked)
                self._reorder_targets = None
                self._reorder_clicked = []
                if self.on_custom_reorder_finished:
                    QTimer.singleShot(
                        0,
                        lambda: self.on_custom_reorder_finished(targets, clicked),
                    )
            return

        if additive:
            self._selected_custom_paths.add(path)
        else:
            self._selected_custom_paths = {path}
        self._active_custom_path = path
        self._selected_custom_line_path = None
        if self.on_custom_selected:
            self.on_custom_selected(path)
        self.setFocus()
        QTimer.singleShot(0, self._rebuild_lines)

    def _select_custom_line(self, path: CustomPath) -> None:
        if self._reorder_targets is not None:
            return
        self._selected_custom_line_path = path
        for item_path, line in self._custom_line_items.items():
            line.set_selected_visual(item_path == path)
        self.setFocus()

    def _custom_drag_started(self, _path: CustomPath) -> None:
        if self._reorder_targets is not None:
            return
        if self.on_custom_edit_started:
            self.on_custom_edit_started()

    def _custom_drag_finished(self, _path: CustomPath) -> None:
        if self._reorder_targets is not None:
            return
        if self._settings is None or self._settings.mode != SplitMode.CUSTOM:
            return
        positions = {
            path: line.absolute_position()
            for path, line in self._custom_line_items.items()
        }
        self._rebase_custom_tree(
            self._settings.custom_root,
            self._scene.sceneRect(),
            (),
            positions,
        )
        if self.on_custom_edit_finished:
            self.on_custom_edit_finished()
        QTimer.singleShot(0, self._rebuild_lines)

    def _rebase_custom_tree(
        self,
        node: CustomSplitNode,
        bounds: QRectF,
        path: CustomPath,
        positions: dict[CustomPath, float],
    ) -> None:
        if node.is_leaf:
            return
        if node.direction is None or node.first is None or node.second is None:
            return

        target = positions.get(path)
        if target is None:
            ratio = min(0.999, max(0.001, float(node.ratio)))
        elif node.direction is CustomSplitDirection.VERTICAL:
            if bounds.width() <= 2:
                ratio = 0.5
            else:
                target = min(bounds.right() - 1, max(bounds.left() + 1, target))
                ratio = (target - bounds.left()) / bounds.width()
        else:
            if bounds.height() <= 2:
                ratio = 0.5
            else:
                target = min(bounds.bottom() - 1, max(bounds.top() + 1, target))
                ratio = (target - bounds.top()) / bounds.height()

        node.ratio = min(0.999, max(0.001, ratio))
        first_bounds, second_bounds = self._child_bounds(node.direction, bounds, node.ratio)
        self._rebase_custom_tree(node.first, first_bounds, path + (0,), positions)
        self._rebase_custom_tree(node.second, second_bounds, path + (1,), positions)

    def delete_selection(self) -> bool:
        if self._reorder_targets is not None:
            return False
        if self._settings is None or self._settings.mode != SplitMode.CUSTOM:
            return False
        if len(self._selected_custom_paths) >= 2:
            if self.on_custom_edit_started:
                self.on_custom_edit_started()
            try:
                merge_custom_leaves(self._settings.custom_root, self._selected_custom_paths)
            except ValueError as exc:
                if self.on_custom_error:
                    self.on_custom_error(str(exc))
                return False
            self._selected_custom_paths = {()}
            self._active_custom_path = ()
            self._selected_custom_line_path = None
            if self.on_custom_edit_finished:
                self.on_custom_edit_finished()
            QTimer.singleShot(0, self._rebuild_lines)
            return True

        if self._selected_custom_line_path is not None:
            if self.on_custom_edit_started:
                self.on_custom_edit_started()
            collapse_custom_split(self._settings.custom_root, self._selected_custom_line_path)
            self._selected_custom_line_path = None
            self._selected_custom_paths = {()}
            self._active_custom_path = ()
            if self.on_custom_edit_finished:
                self.on_custom_edit_finished()
            QTimer.singleShot(0, self._rebuild_lines)
            return True
        return False

    def delete_selected_custom_line(self) -> bool:
        return self.delete_selection()

    def _neighbor_path(self, current: CustomPath, direction: Qt.Key) -> CustomPath | None:
        if self._settings is None:
            return None
        rects = custom_leaf_rects(self._settings.custom_root)
        current_rect = rects.get(current)
        if current_rect is None:
            return None
        x0, y0, x1, y1 = current_rect
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        candidates: list[tuple[float, float, CustomPath]] = []
        for path, rect in rects.items():
            if path == current:
                continue
            rx0, ry0, rx1, ry1 = rect
            rcx, rcy = (rx0 + rx1) / 2, (ry0 + ry1) / 2
            overlap_x = max(0.0, min(x1, rx1) - max(x0, rx0))
            overlap_y = max(0.0, min(y1, ry1) - max(y0, ry0))
            if direction == Qt.Key.Key_Left and rcx < cx and overlap_y > 0:
                candidates.append((cx - rcx, abs(cy - rcy), path))
            elif direction == Qt.Key.Key_Right and rcx > cx and overlap_y > 0:
                candidates.append((rcx - cx, abs(cy - rcy), path))
            elif direction == Qt.Key.Key_Up and rcy < cy and overlap_x > 0:
                candidates.append((cy - rcy, abs(cx - rcx), path))
            elif direction == Qt.Key.Key_Down and rcy > cy and overlap_x > 0:
                candidates.append((rcy - cy, abs(cx - rcx), path))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][2]

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if self._reorder_targets is not None:
            if event.key() == Qt.Key.Key_Escape:
                self.cancel_custom_reorder()
                event.accept()
                return
            super().keyPressEvent(event)
            return

        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter} and self._settings is not None and self._settings.mode == SplitMode.CUSTOM:
            direction = (
                CustomSplitDirection.VERTICAL
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                else CustomSplitDirection.HORIZONTAL
            )
            if self.on_custom_split_requested:
                self.on_custom_split_requested(direction)
                event.accept()
                return

        if event.key() in {Qt.Key.Key_Delete, Qt.Key.Key_Backspace}:
            if self.delete_selection():
                event.accept()
                return

        if event.key() in {Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down} and self._settings is not None and self._settings.mode == SplitMode.CUSTOM:
            neighbor = self._neighbor_path(self._active_custom_path, event.key())
            if neighbor is not None:
                additive = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                self._select_custom_path(neighbor, additive=additive)
                event.accept()
                return
        super().keyPressEvent(event)

    def _zoom_by(self, factor: float) -> None:
        current = self.transform().m11()
        if current <= 0:
            return
        target = current * factor
        if target < self.MIN_ZOOM:
            factor = self.MIN_ZOOM / current
        elif target > self.MAX_ZOOM:
            factor = self.MAX_ZOOM / current
        if factor > 0:
            self.scale(factor, factor)

    def wheelEvent(self, event: QWheelEvent) -> None:  # type: ignore[override]
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._zoom_by(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
            event.accept()
            return
        super().wheelEvent(event)

    def event(self, event) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.NativeGesture and isinstance(event, QNativeGestureEvent):
            if event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
                self._zoom_by(max(0.2, 1.0 + float(event.value())))
                event.accept()
                return True
        return super().event(event)

    def _x_moved(self, ratio: float) -> None:
        if self._settings is not None:
            self._settings.x_ratio = min(0.999, max(0.001, ratio))
        if self.on_x_ratio_changed:
            self.on_x_ratio_changed(ratio)

    def _y_moved(self, ratio: float) -> None:
        if self._settings is not None:
            self._settings.y_ratio = min(0.999, max(0.001, ratio))
        if self.on_y_ratio_changed:
            self.on_y_ratio_changed(ratio)

    def fit_page(self) -> None:
        if not self._scene.sceneRect().isEmpty():
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.fit_page()
