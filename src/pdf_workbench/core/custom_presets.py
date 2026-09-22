from __future__ import annotations

from .models import (
    CustomSplitDirection as Direction,
    CustomSplitNode as Node,
    FourSplitOrder,
    PageSplitSettings,
    SplitMode,
    coerce_four_split_order,
    coerce_split_mode,
    normalized_custom_order,
)


def as_custom_settings(settings: PageSplitSettings) -> PageSplitSettings:
    """Convert historical fixed layouts without changing their OCR reading order."""
    result = settings.clone()
    mode = coerce_split_mode(result.mode)
    if mode is SplitMode.CUSTOM:
        result.mode = SplitMode.CUSTOM
        return result
    if mode is SplitMode.NONE:
        result.custom_root = Node()
        result.custom_order = [()]
    elif mode is SplitMode.HORIZONTAL_2:
        result.custom_root = Node(
            direction=Direction.HORIZONTAL,
            ratio=result.y_ratio,
            first=Node(),
            second=Node(),
        )
        result.custom_order = [(0,), (1,)]
    elif mode is SplitMode.FOUR:
        top_right = Node(direction=Direction.HORIZONTAL, ratio=result.y_ratio,
                         first=Node(), second=Node())
        top_left = Node(direction=Direction.HORIZONTAL, ratio=result.y_ratio,
                        first=Node(), second=Node())
        result.custom_root = Node(direction=Direction.VERTICAL, ratio=result.x_ratio,
                                  first=top_right, second=top_left)
        order = coerce_four_split_order(result.order)
        by_order = {
            FourSplitOrder.RTL_TB: [(0, 0), (0, 1), (1, 0), (1, 1)],
            FourSplitOrder.LTR_TB: [(1, 0), (1, 1), (0, 0), (0, 1)],
            FourSplitOrder.Z: [(1, 0), (0, 0), (1, 1), (0, 1)],
        }
        result.custom_order = by_order[order]
    else:
        raise ValueError(f"unsupported split mode: {mode}")
    result.mode = SplitMode.CUSTOM
    result.custom_order = normalized_custom_order(result.custom_root, result.custom_order)
    return result


def four_region_settings(settings: PageSplitSettings) -> PageSplitSettings:
    """Build an editable, equally sized four-region Japanese-reading layout."""
    result = settings.clone()
    result.mode = SplitMode.CUSTOM
    result.custom_root = Node(
        direction=Direction.VERTICAL,
        ratio=0.5,
        first=Node(direction=Direction.HORIZONTAL, ratio=0.5,
                   first=Node(), second=Node()),
        second=Node(direction=Direction.HORIZONTAL, ratio=0.5,
                    first=Node(), second=Node()),
    )
    result.custom_order = [(0, 0), (0, 1), (1, 0), (1, 1)]
    return result


def one_region_settings(settings: PageSplitSettings) -> PageSplitSettings:
    result = settings.clone()
    result.mode = SplitMode.CUSTOM
    result.custom_root = Node()
    result.custom_order = [()]
    return result
