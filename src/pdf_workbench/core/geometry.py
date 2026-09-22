from __future__ import annotations

from dataclasses import dataclass

from .models import (
    CustomPath,
    CustomSplitDirection,
    CustomSplitNode,
    FourSplitOrder,
    PageSplitSettings,
    SplitMode,
    normalized_custom_order,
)

Box = tuple[int, int, int, int]
NamedBox = tuple[str, Box]


@dataclass(frozen=True, slots=True)
class SplitRegion:
    name: str
    crop_box: Box
    ownership_box: Box


def _clamp_split(value: int, minimum: int, maximum: int) -> int:
    return max(minimum + 1, min(maximum - 1, value))


def _expand_box(box: Box, overlap: int, width: int, height: int) -> Box:
    x0, y0, x1, y1 = box
    return (
        max(0, x0 - overlap),
        max(0, y0 - overlap),
        min(width, x1 + overlap),
        min(height, y1 + overlap),
    )


def _custom_ownership_boxes(
    width: int,
    height: int,
    root: CustomSplitNode,
) -> dict[CustomPath, Box]:
    boxes: dict[CustomPath, Box] = {}

    def walk(node: CustomSplitNode, path: CustomPath, box: Box) -> None:
        if node.is_leaf:
            boxes[path] = box
            return
        if node.first is None or node.second is None or node.direction is None:
            raise ValueError("custom split node must have two children")

        x0, y0, x1, y1 = box
        ratio = min(0.999, max(0.001, float(node.ratio)))
        if node.direction is CustomSplitDirection.VERTICAL:
            split_x = _clamp_split(round(x0 + (x1 - x0) * ratio), x0, x1)
            # first = right, second = left (Japanese vertical-reading default)
            walk(node.first, path + (0,), (split_x, y0, x1, y1))
            walk(node.second, path + (1,), (x0, y0, split_x, y1))
        elif node.direction is CustomSplitDirection.HORIZONTAL:
            split_y = _clamp_split(round(y0 + (y1 - y0) * ratio), y0, y1)
            # first = top, second = bottom
            walk(node.first, path + (0,), (x0, y0, x1, split_y))
            walk(node.second, path + (1,), (x0, split_y, x1, y1))
        else:
            raise ValueError(f"unsupported custom split direction: {node.direction}")

    normalized_root = root.normalized()
    walk(normalized_root, (), (0, 0, width, height))
    return boxes


def split_regions(width: int, height: int, settings: PageSplitSettings) -> list[SplitRegion]:
    """Return OCR crop boxes and non-overlapping restore ownership boxes."""
    if width < 2 or height < 2:
        raise ValueError("width and height must both be >= 2")

    s = settings.normalized()
    overlap = s.overlap_px

    if s.mode is SplitMode.NONE:
        box = (0, 0, width, height)
        return [SplitRegion("full", box, box)]

    if s.mode is SplitMode.CUSTOM:
        ownership_by_path = _custom_ownership_boxes(width, height, s.custom_root)
        order = normalized_custom_order(s.custom_root, s.custom_order)
        return [
            SplitRegion(
                name=f"custom_{index:03d}",
                crop_box=_expand_box(ownership_by_path[path], overlap, width, height),
                ownership_box=ownership_by_path[path],
            )
            for index, path in enumerate(order, start=1)
        ]

    split_y = _clamp_split(round(height * s.y_ratio), 0, height)
    ownership: dict[str, Box] = {
        "top": (0, 0, width, split_y),
        "bottom": (0, split_y, width, height),
    }
    crops: dict[str, Box] = {
        "top": (0, 0, width, min(height, split_y + overlap)),
        "bottom": (0, max(0, split_y - overlap), width, height),
    }

    if s.mode is SplitMode.HORIZONTAL_2:
        return [
            SplitRegion(name, crops[name], ownership[name])
            for name in ("top", "bottom")
        ]

    if s.mode is not SplitMode.FOUR:
        raise ValueError(f"unsupported split mode: {s.mode}")

    split_x = _clamp_split(round(width * s.x_ratio), 0, width)
    ownership = {
        "right_top": (split_x, 0, width, split_y),
        "right_bottom": (split_x, split_y, width, height),
        "left_top": (0, 0, split_x, split_y),
        "left_bottom": (0, split_y, split_x, height),
    }
    crops = {
        "right_top": (
            max(0, split_x - overlap),
            0,
            width,
            min(height, split_y + overlap),
        ),
        "right_bottom": (
            max(0, split_x - overlap),
            max(0, split_y - overlap),
            width,
            height,
        ),
        "left_top": (
            0,
            0,
            min(width, split_x + overlap),
            min(height, split_y + overlap),
        ),
        "left_bottom": (
            0,
            max(0, split_y - overlap),
            min(width, split_x + overlap),
            height,
        ),
    }

    orders = {
        FourSplitOrder.RTL_TB: ["right_top", "right_bottom", "left_top", "left_bottom"],
        FourSplitOrder.LTR_TB: ["left_top", "left_bottom", "right_top", "right_bottom"],
        FourSplitOrder.Z: ["left_top", "right_top", "left_bottom", "right_bottom"],
    }
    return [
        SplitRegion(name, crops[name], ownership[name])
        for name in orders[s.order]
    ]


def crop_regions(width: int, height: int, settings: PageSplitSettings) -> list[NamedBox]:
    """Return named crop boxes in export order for one rendered page."""
    return [
        (region.name, region.crop_box)
        for region in split_regions(width, height, settings)
    ]
