from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .schema_migrations import SchemaSpec, migrate_document

FORMAT_NAME = "pdf-workbench-ocr-bundle"
FORMAT_VERSION = 1
MANIFEST_SCHEMA = SchemaSpec(FORMAT_NAME, FORMAT_VERSION)
# On-disk v1 already contains the geometry and source-page mapping needed for
# OCR restore. Do not bump this independently of a real disk schema change.
MANIFEST_MIGRATIONS = {}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(path: str | Path, data: dict[str, object]) -> None:
    validate_manifest(data)
    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_manifest(path_or_bundle: str | Path) -> tuple[Path, dict[str, object]]:
    manifest_path = Path(path_or_bundle)
    if manifest_path.is_dir():
        manifest_path = manifest_path / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest root must be an object")
    current = migrate_document(data, MANIFEST_SCHEMA, MANIFEST_MIGRATIONS)
    validate_manifest(current)
    return manifest_path, current


def _box(value: Any, label: str) -> tuple[int, int, int, int]:
    if not (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(item, int) and not isinstance(item, bool) for item in value)
    ):
        raise ValueError(f"{label} must be four integers")
    x0, y0, x1, y1 = value
    if not (x0 < x1 and y0 < y1):
        raise ValueError(f"invalid {label}")
    return x0, y0, x1, y1


def validate_manifest(data: Mapping[str, Any]) -> None:
    migrate_document(data, MANIFEST_SCHEMA, MANIFEST_MIGRATIONS)

    source = data.get("source")
    if not isinstance(source, Mapping):
        raise ValueError("source must be an object")
    page_count = source.get("page_count")
    if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count <= 0:
        raise ValueError("source.page_count must be positive")
    filename = source.get("filename")
    if not isinstance(filename, str) or not filename:
        raise ValueError("source.filename must be non-empty")
    embedded = source.get("embedded_source")
    if embedded is not None:
        if (
            not isinstance(embedded, str)
            or Path(embedded).is_absolute()
            or embedded != "source/original.pdf"
        ):
            raise ValueError(
                "source.embedded_source must be relative source/original.pdf or null"
            )

    source_pages = data.get("source_pages")
    if not isinstance(source_pages, list) or len(source_pages) != page_count:
        raise ValueError("source_pages must contain exactly source.page_count entries")

    pages_by_number: dict[int, Mapping[str, Any]] = {}
    for entry in source_pages:
        if not isinstance(entry, Mapping):
            raise ValueError("source_pages entries must be objects")
        source_page = entry.get("source_page")
        if (
            not isinstance(source_page, int)
            or source_page < 1
            or source_page > page_count
            or source_page in pages_by_number
        ):
            raise ValueError("invalid or duplicate source_page")
        page_size = entry.get("source_page_size_pt")
        render_size = entry.get("source_render_size_px")
        if not (
            isinstance(page_size, list)
            and len(page_size) == 2
            and all(
                isinstance(item, (int, float))
                and not isinstance(item, bool)
                and item > 0
                for item in page_size
            )
        ):
            raise ValueError("invalid source_page_size_pt")
        if not (
            isinstance(render_size, list)
            and len(render_size) == 2
            and all(
                isinstance(item, int) and not isinstance(item, bool) and item > 0
                for item in render_size
            )
        ):
            raise ValueError("invalid source_render_size_px")
        pages_by_number[source_page] = entry

    if sorted(pages_by_number) != list(range(1, page_count + 1)):
        raise ValueError("source_pages numbering must be contiguous")

    pieces = data.get("pieces")
    if not isinstance(pieces, list) or not pieces:
        raise ValueError("pieces must be a non-empty list")

    seen_ids: set[str] = set()
    seen_outputs: set[int] = set()
    ownership_by_page: dict[int, list[tuple[int, int, int, int]]] = {
        number: [] for number in pages_by_number
    }

    for piece in pieces:
        if not isinstance(piece, Mapping):
            raise ValueError("pieces entries must be objects")
        piece_id = piece.get("piece_id")
        output_page = piece.get("output_page")
        source_page = piece.get("source_page")
        if not isinstance(piece_id, str) or not piece_id or piece_id in seen_ids:
            raise ValueError("piece_id must be unique")
        seen_ids.add(piece_id)
        if (
            not isinstance(output_page, int)
            or output_page < 1
            or output_page in seen_outputs
        ):
            raise ValueError("output_page must be unique positive integers")
        seen_outputs.add(output_page)
        if not isinstance(source_page, int) or source_page not in pages_by_number:
            raise ValueError("piece source_page is invalid")

        crop = _box(piece.get("crop_box_px"), "crop_box_px")
        ownership = _box(piece.get("ownership_box_px"), "ownership_box_px")
        render_width, render_height = pages_by_number[source_page][
            "source_render_size_px"
        ]
        if not (
            0 <= crop[0] < crop[2] <= render_width
            and 0 <= crop[1] < crop[3] <= render_height
        ):
            raise ValueError("crop_box_px lies outside source render")
        if not (
            crop[0] <= ownership[0] < ownership[2] <= crop[2]
            and crop[1] <= ownership[1] < ownership[3] <= crop[3]
        ):
            raise ValueError("ownership_box_px must lie inside crop_box_px")
        ownership_by_page[source_page].append(ownership)

    if sorted(seen_outputs) != list(range(1, len(pieces) + 1)):
        raise ValueError("output_page values must be contiguous starting at 1")

    for source_page, boxes in ownership_by_page.items():
        render_width, render_height = pages_by_number[source_page][
            "source_render_size_px"
        ]
        total_area = sum(
            (x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in boxes
        )
        if total_area != render_width * render_height:
            raise ValueError(
                f"ownership boxes do not partition source page {source_page}"
            )
        for index, first in enumerate(boxes):
            for second in boxes[index + 1 :]:
                overlap_width = max(
                    0, min(first[2], second[2]) - max(first[0], second[0])
                )
                overlap_height = max(
                    0, min(first[3], second[3]) - max(first[1], second[1])
                )
                if overlap_width * overlap_height:
                    raise ValueError(
                        f"ownership boxes overlap on source page {source_page}"
                    )
