from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from PIL import Image

from .models import (
    CustomPath,
    CustomSplitDirection,
    CustomSplitNode,
    custom_leaf_paths,
    custom_node_at_path,
    normalized_custom_order,
)


@dataclass(frozen=True, slots=True)
class AutoSplitCandidate:
    """One image-derived split suggestion inside the currently selected region."""

    direction: CustomSplitDirection
    ratio: float
    score: float
    gap_width_ratio: float
    gap_ink_density: float
    kind: str = "whitespace"


@dataclass(frozen=True, slots=True)
class AutoSplitPlan:
    """A recursive rectangular layout inferred from the source image."""

    root: CustomSplitNode
    split_count: int
    leaf_count: int
    scores: tuple[float, ...]
    kinds: tuple[str, ...] = ()

    @property
    def average_score(self) -> float:
        if not self.scores:
            return 0.0
        return sum(self.scores) / len(self.scores)

    @property
    def minimum_score(self) -> float:
        return min(self.scores, default=0.0)

    @property
    def balance_split_count(self) -> int:
        return sum(kind == "balance" for kind in self.kinds)

    @property
    def whitespace_split_count(self) -> int:
        return self.split_count - self.balance_split_count


@dataclass(frozen=True, slots=True)
class AutoSplitPreset:
    key: str
    label: str
    description: str
    min_score: float
    min_gap_width_ratio: float
    min_child_fraction: float
    min_child_pixels: int
    max_depth: int
    edge_fraction: float
    candidate_floor: float
    min_region_area_fraction: float
    balance_area_fraction: float | None


AUTO_SPLIT_PRESETS: tuple[AutoSplitPreset, ...] = (
    AutoSplitPreset(
        key="safe",
        label="安全（現在相当）",
        description="明瞭な段間だけを採用し、誤分割をできるだけ避けます。",
        min_score=0.30,
        min_gap_width_ratio=0.020,
        min_child_fraction=0.16,
        min_child_pixels=48,
        max_depth=6,
        edge_fraction=0.10,
        candidate_floor=0.22,
        min_region_area_fraction=0.070,
        balance_area_fraction=None,
    ),
    AutoSplitPreset(
        key="standard",
        label="標準（推奨）",
        description="少し細い余白や弱い谷も拾います。通常はこちらを推奨します。",
        min_score=0.26,
        min_gap_width_ratio=0.012,
        min_child_fraction=0.13,
        min_child_pixels=40,
        max_depth=7,
        edge_fraction=0.08,
        candidate_floor=0.18,
        min_region_area_fraction=0.040,
        balance_area_fraction=0.28,
    ),
    AutoSplitPreset(
        key="aggressive",
        label="積極的",
        description="記事間・段間らしい弱めの谷も拾います。後で手動調整する前提です。",
        min_score=0.22,
        min_gap_width_ratio=0.006,
        min_child_fraction=0.10,
        min_child_pixels=32,
        max_depth=8,
        edge_fraction=0.06,
        candidate_floor=0.14,
        min_region_area_fraction=0.020,
        balance_area_fraction=0.18,
    ),
    AutoSplitPreset(
        key="exploratory",
        label="探索的",
        description="かなり弱い候補も拾い、紙面構造のたたき台を多めに作ります。",
        min_score=0.17,
        min_gap_width_ratio=0.003,
        min_child_fraction=0.07,
        min_child_pixels=24,
        max_depth=9,
        edge_fraction=0.04,
        candidate_floor=0.10,
        min_region_area_fraction=0.010,
        balance_area_fraction=0.10,
    ),
)


def get_auto_split_preset(key: str) -> AutoSplitPreset:
    for preset in AUTO_SPLIT_PRESETS:
        if preset.key == key:
            return preset
    raise ValueError(f"unknown auto split preset: {key}")


def _otsu_threshold(gray: Image.Image) -> int:
    histogram = gray.histogram()
    total = sum(histogram)
    if total <= 0:
        return 128

    weighted_sum = sum(index * count for index, count in enumerate(histogram))
    background_weight = 0
    background_sum = 0.0
    best_variance = -1.0
    best_threshold = 128

    for threshold, count in enumerate(histogram):
        background_weight += count
        if background_weight == 0:
            continue
        foreground_weight = total - background_weight
        if foreground_weight == 0:
            break
        background_sum += threshold * count
        background_mean = background_sum / background_weight
        foreground_mean = (weighted_sum - background_sum) / foreground_weight
        variance = (
            background_weight
            * foreground_weight
            * (background_mean - foreground_mean) ** 2
        )
        if variance > best_variance:
            best_variance = variance
            best_threshold = threshold
    return best_threshold


def _prepare_gray(image: Image.Image, max_side: int = 900) -> Image.Image:
    gray = image.convert("L")
    longest = max(gray.size)
    if longest > max_side:
        scale = max_side / longest
        gray = gray.resize(
            (max(1, round(gray.width * scale)), max(1, round(gray.height * scale))),
            Image.Resampling.BILINEAR,
        )
    return gray


def _ink_profiles(gray: Image.Image) -> tuple[list[float], list[float]]:
    threshold = min(245, _otsu_threshold(gray) + 18)
    width, height = gray.size
    pixels = gray.load()
    columns = [0] * width
    rows = [0] * height

    for y in range(height):
        row_count = 0
        for x in range(width):
            if pixels[x, y] < threshold:
                columns[x] += 1
                row_count += 1
        rows[y] = row_count

    return (
        [count / height for count in columns],
        [count / width for count in rows],
    )


def _quantile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _axis_candidate(
    profile: list[float],
    direction: CustomSplitDirection,
    *,
    edge_fraction: float = 0.10,
    candidate_floor: float = 0.22,
) -> AutoSplitCandidate | None:
    size = len(profile)
    if size < 24:
        return None

    first = max(1, round(size * edge_fraction))
    last = min(size - 1, round(size * (1.0 - edge_fraction)))
    central = profile[first:last]
    if len(central) < 8:
        return None

    median = _quantile(central, 0.50)
    lower_quartile = _quantile(central, 0.25)
    upper_quartile = _quantile(central, 0.75)
    spread = upper_quartile - lower_quartile

    if median < 0.003 and upper_quartile < 0.006:
        return None

    low_cut = min(0.065, lower_quartile + max(0.004, spread * 0.20))
    min_run = max(2, round(size * 0.004))

    runs: list[tuple[int, int]] = []
    run_start: int | None = None
    for index in range(first, last):
        if profile[index] <= low_cut:
            if run_start is None:
                run_start = index
        elif run_start is not None:
            if index - run_start >= min_run:
                runs.append((run_start, index))
            run_start = None
    if run_start is not None and last - run_start >= min_run:
        runs.append((run_start, last))

    best: AutoSplitCandidate | None = None
    for start, end in runs:
        width = end - start
        center = (start + end) / 2.0
        ratio = center / size
        if not (edge_fraction < ratio < 1.0 - edge_fraction):
            continue

        gap_density = sum(profile[start:end]) / width
        contrast = max(0.0, (median - gap_density) / max(0.012, median))
        width_ratio = width / size
        width_bonus = min(1.0, sqrt(width_ratio / 0.035))
        balance = 1.0 - 0.22 * abs(ratio - 0.5) / 0.5
        score = contrast * (0.62 + 0.38 * width_bonus) * balance

        candidate = AutoSplitCandidate(
            direction=direction,
            ratio=ratio,
            score=score,
            gap_width_ratio=width_ratio,
            gap_ink_density=gap_density,
        )
        if best is None or candidate.score > best.score:
            best = candidate

    if best is None or best.score < candidate_floor:
        return None
    return best


def find_best_whitespace_split(
    image: Image.Image,
    *,
    edge_fraction: float = 0.10,
    candidate_floor: float = 0.22,
) -> AutoSplitCandidate | None:
    if image.width < 24 or image.height < 24:
        return None

    gray = _prepare_gray(image)
    columns, rows = _ink_profiles(gray)
    vertical = _axis_candidate(
        columns,
        CustomSplitDirection.VERTICAL,
        edge_fraction=edge_fraction,
        candidate_floor=candidate_floor,
    )
    horizontal = _axis_candidate(
        rows,
        CustomSplitDirection.HORIZONTAL,
        edge_fraction=edge_fraction,
        candidate_floor=candidate_floor,
    )

    candidates = [item for item in (vertical, horizontal) if item is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.score)


def _window_minimum(
    profile: list[float],
    *,
    first: int,
    last: int,
    window: int,
) -> tuple[int, float] | None:
    if last - first < window or window <= 0:
        return None
    prefix = [0.0]
    for value in profile:
        prefix.append(prefix[-1] + value)

    best_center = -1
    best_mean = float("inf")
    half = window // 2
    for center in range(first + half, last - (window - half) + 1):
        start = center - half
        end = start + window
        mean = (prefix[end] - prefix[start]) / window
        if mean < best_mean:
            best_mean = mean
            best_center = center
    if best_center < 0:
        return None
    return best_center, best_mean


def find_balance_split(image: Image.Image) -> AutoSplitCandidate | None:
    """Find a low-ink near-central cut for an otherwise oversized region.

    This is deliberately weaker evidence than a real whitespace gutter. It is
    used only as an optional balancing fallback, so large page regions can be
    brought to comparable sizes even when their layout contains no full-height
    or full-width white corridor.
    """
    if image.width < 48 or image.height < 48:
        return None
    gray = _prepare_gray(image)
    columns, rows = _ink_profiles(gray)
    if max(_quantile(columns, 0.75), _quantile(rows, 0.75)) < 0.006:
        return None

    candidates: list[tuple[float, AutoSplitCandidate]] = []
    for profile, direction, axis_size, other_size in (
        (columns, CustomSplitDirection.VERTICAL, gray.width, gray.height),
        (rows, CustomSplitDirection.HORIZONTAL, gray.height, gray.width),
    ):
        first = round(axis_size * 0.28)
        last = round(axis_size * 0.72)
        window = max(3, round(axis_size * 0.015))
        found = _window_minimum(profile, first=first, last=last, window=window)
        if found is None:
            continue
        center, density = found
        median = _quantile(profile[first:last], 0.50)
        contrast = max(0.0, (median - density) / max(0.012, median))
        ratio = center / axis_size
        aspect_preference = axis_size / max(1.0, axis_size + other_size)
        quality = 0.62 * contrast + 0.38 * aspect_preference
        score = 0.08 + 0.14 * min(1.0, contrast)
        candidates.append(
            (
                quality,
                AutoSplitCandidate(
                    direction=direction,
                    ratio=ratio,
                    score=score,
                    gap_width_ratio=window / axis_size,
                    gap_ink_density=density,
                    kind="balance",
                ),
            )
        )

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


@dataclass(slots=True)
class _PendingLeaf:
    node: CustomSplitNode
    image: Image.Image
    depth: int
    area_fraction: float
    candidate: AutoSplitCandidate
    priority: float


def build_whitespace_split_plan(
    image: Image.Image,
    *,
    max_regions: int = 12,
    preset: AutoSplitPreset | None = None,
    min_score: float = 0.30,
    min_gap_width_ratio: float = 0.020,
    min_child_fraction: float = 0.16,
    min_child_pixels: int = 48,
    max_depth: int = 6,
    edge_fraction: float = 0.10,
    candidate_floor: float = 0.22,
    min_region_area_fraction: float = 0.070,
    balance_area_fraction: float | None = None,
    enable_balance_fallback: bool = True,
) -> AutoSplitPlan:
    """Infer rectangular split lines with global best-first selection.

    Clear whitespace gutters always receive normal priority. When enabled, an
    oversized leaf that has no acceptable whitespace gutter may enter the same
    global queue with a lower-priority balance cut near its low-ink centre.
    This prevents one side or one page from remaining huge merely because its
    scan/layout lacks a perfectly continuous white corridor.
    """
    if preset is not None:
        min_score = preset.min_score
        min_gap_width_ratio = preset.min_gap_width_ratio
        min_child_fraction = preset.min_child_fraction
        min_child_pixels = preset.min_child_pixels
        max_depth = preset.max_depth
        edge_fraction = preset.edge_fraction
        candidate_floor = preset.candidate_floor
        min_region_area_fraction = preset.min_region_area_fraction
        balance_area_fraction = preset.balance_area_fraction

    if max_regions < 1:
        raise ValueError("max_regions must be >= 1")
    if not 0.0 <= min_score <= 1.5:
        raise ValueError("min_score is outside the supported range")
    if not 0.0 <= min_gap_width_ratio < 1.0:
        raise ValueError("min_gap_width_ratio must be between 0 and 1")
    if not 0.0 < min_child_fraction < 0.5:
        raise ValueError("min_child_fraction must be between 0 and 0.5")
    if min_child_pixels < 12:
        raise ValueError("min_child_pixels must be >= 12")
    if not 0.0 <= edge_fraction < 0.5:
        raise ValueError("edge_fraction must be between 0 and 0.5")
    if not 0.0 < min_region_area_fraction < 0.5:
        raise ValueError("min_region_area_fraction must be between 0 and 0.5")
    if balance_area_fraction is not None and not 0.0 < balance_area_fraction <= 1.0:
        raise ValueError("balance_area_fraction must be between 0 and 1")

    root = CustomSplitNode()
    scores: list[float] = []
    kinds: list[str] = []
    leaves: list[_PendingLeaf] = []

    def evaluate(
        node: CustomSplitNode,
        region: Image.Image,
        depth: int,
        area_fraction: float,
    ) -> None:
        if depth >= max_depth:
            return
        if region.width < min_child_pixels * 2 or region.height < min_child_pixels * 2:
            return
        if area_fraction < min_region_area_fraction * 2:
            return

        candidate = find_best_whitespace_split(
            region,
            edge_fraction=edge_fraction,
            candidate_floor=candidate_floor,
        )
        accepted = bool(
            candidate is not None
            and candidate.score >= min_score
            and candidate.gap_width_ratio >= min_gap_width_ratio
            and min(candidate.ratio, 1.0 - candidate.ratio) >= min_child_fraction
        )

        if not accepted:
            candidate = None
            if (
                enable_balance_fallback
                and balance_area_fraction is not None
                and area_fraction >= balance_area_fraction
            ):
                candidate = find_balance_split(region)

        if candidate is None:
            return

        first_area = area_fraction * candidate.ratio
        second_area = area_fraction * (1.0 - candidate.ratio)
        if min(first_area, second_area) < min_region_area_fraction:
            return

        if candidate.direction is CustomSplitDirection.VERTICAL:
            split_px = max(1, min(region.width - 1, round(region.width * candidate.ratio)))
            if min(split_px, region.width - split_px) < min_child_pixels:
                return
        else:
            split_px = max(1, min(region.height - 1, round(region.height * candidate.ratio)))
            if min(split_px, region.height - split_px) < min_child_pixels:
                return

        if candidate.kind == "balance":
            priority = 0.06 + 0.15 * area_fraction + 0.03 * candidate.score
        else:
            priority = candidate.score * sqrt(area_fraction)
        leaves.append(
            _PendingLeaf(
                node=node,
                image=region,
                depth=depth,
                area_fraction=area_fraction,
                candidate=candidate,
                priority=priority,
            )
        )

    evaluate(root, image, 0, 1.0)
    split_budget = max_regions - 1

    while leaves and len(scores) < split_budget:
        best_index = max(
            range(len(leaves)),
            key=lambda index: (
                leaves[index].priority,
                leaves[index].candidate.kind == "whitespace",
                leaves[index].candidate.score,
                leaves[index].area_fraction,
            ),
        )
        leaf = leaves.pop(best_index)
        candidate = leaf.candidate
        node = leaf.node
        region = leaf.image

        node.direction = candidate.direction
        node.ratio = candidate.ratio
        node.first = CustomSplitNode()
        node.second = CustomSplitNode()
        scores.append(candidate.score)
        kinds.append(candidate.kind)

        if candidate.direction is CustomSplitDirection.VERTICAL:
            split_px = max(1, min(region.width - 1, round(region.width * candidate.ratio)))
            left = region.crop((0, 0, split_px, region.height))
            right = region.crop((split_px, 0, region.width, region.height))
            right_fraction = leaf.area_fraction * (1.0 - candidate.ratio)
            left_fraction = leaf.area_fraction * candidate.ratio
            evaluate(node.first, right, leaf.depth + 1, right_fraction)
            evaluate(node.second, left, leaf.depth + 1, left_fraction)
        else:
            split_px = max(1, min(region.height - 1, round(region.height * candidate.ratio)))
            top = region.crop((0, 0, region.width, split_px))
            bottom = region.crop((0, split_px, region.width, region.height))
            top_fraction = leaf.area_fraction * candidate.ratio
            bottom_fraction = leaf.area_fraction * (1.0 - candidate.ratio)
            evaluate(node.first, top, leaf.depth + 1, top_fraction)
            evaluate(node.second, bottom, leaf.depth + 1, bottom_fraction)

    return AutoSplitPlan(
        root=root,
        split_count=len(scores),
        leaf_count=len(scores) + 1,
        scores=tuple(scores),
        kinds=tuple(kinds),
    )


def graft_auto_split_plan(
    root: CustomSplitNode,
    order: list[CustomPath] | tuple[CustomPath, ...],
    path: CustomPath,
    plan_root: CustomSplitNode,
) -> list[CustomPath]:
    """Replace one custom leaf with an inferred subtree and preserve OCR order."""
    target = custom_node_at_path(root, path)
    if not target.is_leaf:
        raise ValueError("自動分割の対象は最終領域である必要があります")

    current_order = normalized_custom_order(root, order)
    if path not in current_order:
        raise ValueError("自動分割対象が現在のOCR順に存在しません")

    replacement = plan_root.clone()
    local_paths = custom_leaf_paths(replacement)
    expanded_paths = [path + local_path for local_path in local_paths]
    index = current_order.index(path)

    target.direction = replacement.direction
    target.ratio = replacement.ratio
    target.first = replacement.first
    target.second = replacement.second

    return current_order[:index] + expanded_paths + current_order[index + 1 :]
