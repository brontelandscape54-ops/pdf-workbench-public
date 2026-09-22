from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SplitMode(str, Enum):
    NONE = "none"
    HORIZONTAL_2 = "horizontal_2"
    FOUR = "four"
    CUSTOM = "custom"


class FourSplitOrder(str, Enum):
    RTL_TB = "rtl_tb"
    LTR_TB = "ltr_tb"
    Z = "z"


class CustomSplitDirection(str, Enum):
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"


CustomPath = tuple[int, ...]
NormalizedRect = tuple[float, float, float, float]


def coerce_split_mode(value: SplitMode | str) -> SplitMode:
    return value if isinstance(value, SplitMode) else SplitMode(value)


def coerce_four_split_order(value: FourSplitOrder | str) -> FourSplitOrder:
    return value if isinstance(value, FourSplitOrder) else FourSplitOrder(value)


def coerce_custom_split_direction(
    value: CustomSplitDirection | str,
) -> CustomSplitDirection:
    return value if isinstance(value, CustomSplitDirection) else CustomSplitDirection(value)


@dataclass(slots=True)
class CustomSplitNode:
    """One node in a recursive rectangular split tree."""

    direction: CustomSplitDirection | None = None
    ratio: float = 0.5
    first: CustomSplitNode | None = None
    second: CustomSplitNode | None = None

    @property
    def is_leaf(self) -> bool:
        return self.direction is None

    def normalized(self) -> "CustomSplitNode":
        if self.direction is None:
            return CustomSplitNode()
        direction = coerce_custom_split_direction(self.direction)
        if self.first is None or self.second is None:
            raise ValueError("custom split node must have two children")
        return CustomSplitNode(
            direction=direction,
            ratio=min(0.999, max(0.001, float(self.ratio))),
            first=self.first.normalized(),
            second=self.second.normalized(),
        )

    def clone(self) -> "CustomSplitNode":
        return CustomSplitNode(
            direction=self.direction,
            ratio=self.ratio,
            first=self.first.clone() if self.first is not None else None,
            second=self.second.clone() if self.second is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        if self.direction is None:
            return {"type": "leaf"}
        assert self.first is not None and self.second is not None
        direction = coerce_custom_split_direction(self.direction)
        return {
            "type": "split",
            "direction": direction.value,
            "ratio": float(self.ratio),
            "first": self.first.to_dict(),
            "second": self.second.to_dict(),
        }


def custom_node_at_path(root: CustomSplitNode, path: CustomPath) -> CustomSplitNode:
    node = root
    for step in path:
        if step not in (0, 1) or node.is_leaf:
            raise ValueError(f"invalid custom split path: {path}")
        child = node.first if step == 0 else node.second
        if child is None:
            raise ValueError(f"invalid custom split path: {path}")
        node = child
    return node


def split_custom_leaf(
    root: CustomSplitNode,
    path: CustomPath,
    direction: CustomSplitDirection | str,
    *,
    ratio: float = 0.5,
) -> None:
    node = custom_node_at_path(root, path)
    if not node.is_leaf:
        raise ValueError("selected custom node is already split")
    node.direction = coerce_custom_split_direction(direction)
    node.ratio = min(0.999, max(0.001, float(ratio)))
    node.first = CustomSplitNode()
    node.second = CustomSplitNode()


def collapse_custom_split(root: CustomSplitNode, path: CustomPath) -> None:
    node = custom_node_at_path(root, path)
    if node.is_leaf:
        raise ValueError("selected custom node is not a split line")
    node.direction = None
    node.ratio = 0.5
    node.first = None
    node.second = None


def custom_leaf_paths(root: CustomSplitNode) -> list[CustomPath]:
    paths: list[CustomPath] = []

    def walk(node: CustomSplitNode, path: CustomPath) -> None:
        if node.is_leaf:
            paths.append(path)
            return
        if node.first is None or node.second is None:
            raise ValueError("custom split node must have two children")
        walk(node.first, path + (0,))
        walk(node.second, path + (1,))

    walk(root, ())
    return paths


def normalized_custom_order(
    root: CustomSplitNode,
    order: list[CustomPath] | tuple[CustomPath, ...],
) -> list[CustomPath]:
    """Return a complete valid reading order for the current custom leaves."""
    traversal = custom_leaf_paths(root)
    valid = set(traversal)
    result: list[CustomPath] = []
    seen: set[CustomPath] = set()
    for path in order:
        normalized_path = tuple(path)
        if normalized_path in valid and normalized_path not in seen:
            result.append(normalized_path)
            seen.add(normalized_path)
    for path in traversal:
        if path not in seen:
            result.append(path)
            seen.add(path)
    return result


def custom_order_after_split(
    root_before: CustomSplitNode,
    order: list[CustomPath] | tuple[CustomPath, ...],
    path: CustomPath,
) -> list[CustomPath]:
    """Replace one leaf in reading order with its two new children."""
    current = normalized_custom_order(root_before, order)
    if path not in current:
        return []
    index = current.index(path)
    return current[:index] + [path + (0,), path + (1,)] + current[index + 1 :]


def reorder_custom_subset(
    root: CustomSplitNode,
    order: list[CustomPath] | tuple[CustomPath, ...],
    selected: set[CustomPath] | list[CustomPath] | tuple[CustomPath, ...],
    clicked_order: list[CustomPath] | tuple[CustomPath, ...],
) -> list[CustomPath]:
    """Reorder a consecutive block of custom OCR regions.

    The selected regions must occupy consecutive positions in the current reading
    order.  Only that block is replaced; all regions outside it retain their
    positions.
    """
    current = normalized_custom_order(root, order)
    selected_set = set(selected)
    clicked = list(clicked_order)
    if len(selected_set) < 2:
        raise ValueError("順番を振り直すには2つ以上の領域を選択してください")
    if len(clicked) != len(selected_set) or set(clicked) != selected_set:
        raise ValueError("選択した領域をそれぞれ1回ずつ順番にクリックしてください")

    positions = sorted(current.index(path) for path in selected_set if path in current)
    if len(positions) != len(selected_set):
        raise ValueError("選択領域に現在の分割に存在しない領域が含まれています")
    if positions != list(range(positions[0], positions[-1] + 1)):
        raise ValueError("番号が連続している領域だけを選択してください")

    result = list(current)
    for position, path in zip(positions, clicked):
        result[position] = path
    return result


def custom_leaf_rects(root: CustomSplitNode) -> dict[CustomPath, NormalizedRect]:
    """Return normalized page rectangles for every custom leaf."""
    result: dict[CustomPath, NormalizedRect] = {}

    def walk(
        node: CustomSplitNode,
        path: CustomPath,
        rect: NormalizedRect,
    ) -> None:
        if node.is_leaf:
            result[path] = rect
            return
        if node.direction is None or node.first is None or node.second is None:
            raise ValueError("custom split node must have two children")
        x0, y0, x1, y1 = rect
        ratio = min(0.999, max(0.001, float(node.ratio)))
        if node.direction is CustomSplitDirection.VERTICAL:
            split_x = x0 + (x1 - x0) * ratio
            first_rect = (split_x, y0, x1, y1)
            second_rect = (x0, y0, split_x, y1)
        else:
            split_y = y0 + (y1 - y0) * ratio
            first_rect = (x0, y0, x1, split_y)
            second_rect = (x0, split_y, x1, y1)
        walk(node.first, path + (0,), first_rect)
        walk(node.second, path + (1,), second_rect)

    walk(root, (), (0.0, 0.0, 1.0, 1.0))
    return result


def _rect_area(rect: NormalizedRect) -> float:
    x0, y0, x1, y1 = rect
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _build_custom_tree_from_rects(
    rects: list[NormalizedRect],
    bounds: NormalizedRect,
    *,
    eps: float = 1e-9,
) -> CustomSplitNode:
    if len(rects) == 1:
        return CustomSplitNode()

    bx0, by0, bx1, by1 = bounds
    x_candidates = sorted(
        {
            value
            for rect in rects
            for value in (rect[0], rect[2])
            if bx0 + eps < value < bx1 - eps
        }
    )
    for cut in x_candidates:
        left = [rect for rect in rects if rect[2] <= cut + eps]
        right = [rect for rect in rects if rect[0] >= cut - eps]
        if left and right and len(left) + len(right) == len(rects):
            try:
                right_node = _build_custom_tree_from_rects(
                    right, (cut, by0, bx1, by1), eps=eps
                )
                left_node = _build_custom_tree_from_rects(
                    left, (bx0, by0, cut, by1), eps=eps
                )
            except ValueError:
                continue
            return CustomSplitNode(
                direction=CustomSplitDirection.VERTICAL,
                ratio=(cut - bx0) / (bx1 - bx0),
                first=right_node,
                second=left_node,
            )

    y_candidates = sorted(
        {
            value
            for rect in rects
            for value in (rect[1], rect[3])
            if by0 + eps < value < by1 - eps
        }
    )
    for cut in y_candidates:
        top = [rect for rect in rects if rect[3] <= cut + eps]
        bottom = [rect for rect in rects if rect[1] >= cut - eps]
        if top and bottom and len(top) + len(bottom) == len(rects):
            try:
                top_node = _build_custom_tree_from_rects(
                    top, (bx0, by0, bx1, cut), eps=eps
                )
                bottom_node = _build_custom_tree_from_rects(
                    bottom, (bx0, cut, bx1, by1), eps=eps
                )
            except ValueError:
                continue
            return CustomSplitNode(
                direction=CustomSplitDirection.HORIZONTAL,
                ratio=(cut - by0) / (by1 - by0),
                first=top_node,
                second=bottom_node,
            )

    raise ValueError("merged layout cannot be represented as rectangular splits")


def merge_custom_leaves(
    root: CustomSplitNode,
    paths: set[CustomPath] | list[CustomPath],
) -> None:
    """Merge selected leaf regions when their union is one rectangle."""
    selected = set(paths)
    if len(selected) < 2:
        raise ValueError("select at least two areas to merge")

    leaf_rects = custom_leaf_rects(root)
    if not selected.issubset(leaf_rects):
        raise ValueError("selection contains an invalid custom area")

    chosen = [leaf_rects[path] for path in selected]
    merged: NormalizedRect = (
        min(rect[0] for rect in chosen),
        min(rect[1] for rect in chosen),
        max(rect[2] for rect in chosen),
        max(rect[3] for rect in chosen),
    )
    selected_area = sum(_rect_area(rect) for rect in chosen)
    if abs(selected_area - _rect_area(merged)) > 1e-8:
        raise ValueError("選択した領域は1つの長方形にならないため統合できません")

    remaining = [
        rect for path, rect in leaf_rects.items() if path not in selected
    ]
    new_rects = remaining + [merged]
    rebuilt = _build_custom_tree_from_rects(new_rects, (0.0, 0.0, 1.0, 1.0))
    root.direction = rebuilt.direction
    root.ratio = rebuilt.ratio
    root.first = rebuilt.first
    root.second = rebuilt.second


@dataclass(slots=True)
class PageSplitSettings:
    """Per-page split settings, stored independently of display/export DPI."""

    mode: SplitMode = SplitMode.CUSTOM
    x_ratio: float = 0.5
    y_ratio: float = 0.5
    overlap_px: int = 0
    order: FourSplitOrder = FourSplitOrder.RTL_TB
    custom_root: CustomSplitNode = field(default_factory=CustomSplitNode)
    custom_order: list[CustomPath] = field(default_factory=list)

    def normalized(self) -> "PageSplitSettings":
        root = self.custom_root.normalized()
        return PageSplitSettings(
            mode=coerce_split_mode(self.mode),
            x_ratio=min(0.999, max(0.001, float(self.x_ratio))),
            y_ratio=min(0.999, max(0.001, float(self.y_ratio))),
            overlap_px=max(0, int(self.overlap_px)),
            order=coerce_four_split_order(self.order),
            custom_root=root,
            custom_order=normalized_custom_order(root, self.custom_order),
        )

    def clone(self) -> "PageSplitSettings":
        return PageSplitSettings(
            mode=self.mode,
            x_ratio=self.x_ratio,
            y_ratio=self.y_ratio,
            overlap_px=self.overlap_px,
            order=self.order,
            custom_root=self.custom_root.clone(),
            custom_order=[tuple(path) for path in self.custom_order],
        )
