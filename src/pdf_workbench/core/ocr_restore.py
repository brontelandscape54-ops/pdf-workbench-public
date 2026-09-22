from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import fitz

from .ocr_manifest import load_manifest

ProgressCallback = Callable[[int, int], bool | None]


@dataclass(frozen=True, slots=True)
class OcrPdfInspection:
    expected_pages: int
    actual_pages: int
    has_extractable_text: bool


def inspect_ocr_pdf(
    manifest_path_or_bundle: str | Path,
    ocr_pdf: str | Path,
) -> OcrPdfInspection:
    _manifest_path, manifest = load_manifest(manifest_path_or_bundle)
    expected_pages = len(manifest["pieces"])

    document = fitz.open(str(ocr_pdf))
    try:
        actual_pages = len(document)
        if actual_pages != expected_pages:
            raise ValueError(
                "OCR PDF page count mismatch: "
                f"expected {expected_pages}, actual {actual_pages}. "
                "OCR must not add, delete, or reorder pages."
            )

        for page_number, page in enumerate(document, start=1):
            if page.rect.width <= 0 or page.rect.height <= 0:
                raise ValueError(f"OCR PDF page {page_number} has zero size")

        has_text = any(page.get_text("text").strip() for page in document)
        return OcrPdfInspection(
            expected_pages=expected_pages,
            actual_pages=actual_pages,
            has_extractable_text=has_text,
        )
    finally:
        document.close()


def restore_ocr_pdf(
    manifest_path_or_bundle: str | Path,
    ocr_pdf: str | Path,
    output_pdf: str | Path,
    *,
    progress: ProgressCallback | None = None,
) -> tuple[int, int]:
    _manifest_path, manifest = load_manifest(manifest_path_or_bundle)
    inspect_ocr_pdf(manifest_path_or_bundle, ocr_pdf)

    output_path = Path(output_pdf).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f".{output_path.name}.tmp")
    if temp_path.exists():
        temp_path.unlink()

    ocr_doc = fitz.open(str(ocr_pdf))
    output_doc = fitz.open()
    imported_piece_count = 0

    try:
        source_pages = {
            entry["source_page"]: entry
            for entry in manifest["source_pages"]
        }
        pieces_by_source: dict[int, list[dict[str, object]]] = {
            source_page: [] for source_page in source_pages
        }
        for piece in manifest["pieces"]:
            pieces_by_source[piece["source_page"]].append(piece)

        total_pages = len(source_pages)
        for done, source_page_number in enumerate(sorted(source_pages), start=1):
            page_meta = source_pages[source_page_number]
            page_width_pt, page_height_pt = page_meta["source_page_size_pt"]
            render_width_px, render_height_px = page_meta["source_render_size_px"]
            output_page = output_doc.new_page(
                width=page_width_pt,
                height=page_height_pt,
            )

            for piece in pieces_by_source[source_page_number]:
                crop_x0, crop_y0, crop_x1, crop_y1 = piece["crop_box_px"]
                own_x0, own_y0, own_x1, own_y1 = piece["ownership_box_px"]

                fraction_x0 = (own_x0 - crop_x0) / (crop_x1 - crop_x0)
                fraction_y0 = (own_y0 - crop_y0) / (crop_y1 - crop_y0)
                fraction_x1 = (own_x1 - crop_x0) / (crop_x1 - crop_x0)
                fraction_y1 = (own_y1 - crop_y0) / (crop_y1 - crop_y0)

                ocr_page_number = piece["output_page"] - 1
                source_page = ocr_doc[ocr_page_number]
                source_rect = source_page.rect
                clip = fitz.Rect(
                    source_rect.x0 + fraction_x0 * source_rect.width,
                    source_rect.y0 + fraction_y0 * source_rect.height,
                    source_rect.x0 + fraction_x1 * source_rect.width,
                    source_rect.y0 + fraction_y1 * source_rect.height,
                )

                target = fitz.Rect(
                    own_x0 / render_width_px * page_width_pt,
                    own_y0 / render_height_px * page_height_pt,
                    own_x1 / render_width_px * page_width_pt,
                    own_y1 / render_height_px * page_height_pt,
                )

                output_page.show_pdf_page(
                    target,
                    ocr_doc,
                    ocr_page_number,
                    clip=clip,
                    keep_proportion=False,
                    overlay=True,
                )
                imported_piece_count += 1

            if progress is not None and progress(done, total_pages) is False:
                raise InterruptedError("restore cancelled")

        output_doc.save(str(temp_path), garbage=4, deflate=True, clean=True)
        output_doc.close()
        output_doc = fitz.open()
        temp_path.replace(output_path)
        return len(source_pages), imported_piece_count
    finally:
        try:
            output_doc.close()
        except Exception:
            pass
        ocr_doc.close()
        if temp_path.exists():
            temp_path.unlink()
