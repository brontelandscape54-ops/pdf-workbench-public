from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Sequence

import fitz

from .geometry import split_regions
from .models import PageSplitSettings, SplitMode
from .ocr_manifest import FORMAT_NAME, FORMAT_VERSION, sha256_file, write_manifest
from .pdf_engine import (
    ProgressCallback,
    add_image_page,
    prepare_image,
    render_page_to_image,
)


@dataclass(frozen=True, slots=True)
class BundleExportResult:
    bundle_dir: Path
    split_pdf: Path
    manifest_path: Path
    source_page_count: int
    output_page_count: int


README_TEXT = """PDF Workbench OCR bundle

OCR the *_split_for_ocr.pdf file with any OCR application.
Keep the page count and page order unchanged.
Save the OCR result as a searchable PDF.
Do not crop, rotate, reorder, insert, or delete pages before restoring.
"""


_GENERATED_ROOT_FILES = {"manifest.json", "README.txt", "workspace.json"}


def _is_workbench_generated_path(relative_path: Path) -> bool:
    if len(relative_path.parts) == 1:
        if relative_path.name in _GENERATED_ROOT_FILES:
            return True
        if relative_path.name.endswith("_split_for_ocr.pdf"):
            return True
    return relative_path.as_posix() == "source/original.pdf"


def _copy_preserved_bundle_files(existing_dir: Path, new_dir: Path) -> None:
    """Carry forward files the user added to an existing bundle.

    Workbench-generated files are recreated from the current state. Other
    files, for example an OCR application's searchable PDF saved inside the
    bundle, are preserved when the bundle is updated.
    """
    for source in existing_dir.rglob("*"):
        relative = source.relative_to(existing_dir)
        if _is_workbench_generated_path(relative):
            continue
        destination = new_dir / relative
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def export_ocr_bundle(
    input_pdf: str | Path,
    bundle_dir: str | Path,
    page_settings: Sequence[PageSplitSettings],
    *,
    dpi: int = 180,
    quality: int = 70,
    grayscale: bool = False,
    include_original: bool = False,
    replace_existing: bool = False,
    progress: ProgressCallback | None = None,
) -> BundleExportResult:
    source_path = Path(input_pdf).expanduser().resolve()
    target_dir = Path(bundle_dir).expanduser().resolve()

    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if dpi <= 0:
        raise ValueError("dpi must be > 0")
    if not 1 <= quality <= 95:
        raise ValueError("quality must be between 1 and 95")
    if target_dir.exists() and not target_dir.is_dir():
        raise NotADirectoryError(target_dir)

    target_nonempty = target_dir.exists() and any(target_dir.iterdir())
    if target_nonempty and not replace_existing:
        raise FileExistsError(f"bundle directory is not empty: {target_dir}")

    temp_dir = target_dir.parent / f".{target_dir.name}.tmp"
    backup_dir = target_dir.parent / f".{target_dir.name}.previous"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    source_doc = fitz.open(str(source_path))
    output_doc = fitz.open()
    output_count = 0

    try:
        if len(page_settings) != len(source_doc):
            raise ValueError(
                f"page_settings length ({len(page_settings)}) must equal PDF page count ({len(source_doc)})"
            )

        source_pages: list[dict[str, object]] = []
        pieces: list[dict[str, object]] = []
        total = len(source_doc)

        for page_index, page in enumerate(source_doc):
            image = render_page_to_image(page, dpi)
            settings = page_settings[page_index].normalized()
            regions = split_regions(image.width, image.height, settings)

            source_page_entry: dict[str, object] = {
                "source_page": page_index + 1,
                "source_page_size_pt": [
                    float(page.rect.width),
                    float(page.rect.height),
                ],
                "source_render_size_px": [image.width, image.height],
                "split_mode": settings.mode.value,
                "x_ratio": settings.x_ratio,
                "y_ratio": settings.y_ratio,
                "overlap_px": settings.overlap_px,
                "four_split_order": settings.order.value,
            }
            if settings.mode is SplitMode.CUSTOM:
                source_page_entry["custom_layout"] = settings.custom_root.to_dict()
                source_page_entry["custom_order"] = [
                    list(path) for path in settings.custom_order
                ]
            source_pages.append(source_page_entry)

            for region in regions:
                cropped = prepare_image(image.crop(region.crop_box), grayscale)
                add_image_page(output_doc, cropped, dpi, quality)
                output_count += 1
                pieces.append(
                    {
                        "piece_id": f"piece_{output_count:06d}",
                        "output_page": output_count,
                        "source_page": page_index + 1,
                        "piece_name": region.name,
                        "crop_box_px": list(region.crop_box),
                        "ownership_box_px": list(region.ownership_box),
                    }
                )

            if progress is not None and progress(page_index + 1, total) is False:
                raise InterruptedError("bundle export cancelled")

        split_name = f"{source_path.stem}_split_for_ocr.pdf"
        split_path = temp_dir / split_name
        output_doc.save(str(split_path), garbage=4, deflate=True, clean=True)

        embedded_source: str | None = None
        if include_original:
            source_dir = temp_dir / "source"
            source_dir.mkdir()
            shutil.copy2(source_path, source_dir / "original.pdf")
            embedded_source = "source/original.pdf"

        manifest: dict[str, object] = {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "source": {
                "filename": source_path.name,
                "sha256": sha256_file(source_path),
                "size_bytes": source_path.stat().st_size,
                "page_count": len(source_doc),
                "embedded_source": embedded_source,
            },
            "export": {
                "dpi": dpi,
                "grayscale": grayscale,
                "jpeg_quality": quality,
            },
            "source_pages": source_pages,
            "pieces": pieces,
        }
        write_manifest(temp_dir / "manifest.json", manifest)
        (temp_dir / "README.txt").write_text(README_TEXT, encoding="utf-8")

        if target_nonempty and replace_existing:
            _copy_preserved_bundle_files(target_dir, temp_dir)

        if target_nonempty and replace_existing:
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            target_dir.replace(backup_dir)
            try:
                temp_dir.replace(target_dir)
            except Exception:
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                backup_dir.replace(target_dir)
                raise
            shutil.rmtree(backup_dir, ignore_errors=True)
        else:
            if target_dir.exists():
                target_dir.rmdir()
            temp_dir.replace(target_dir)

        return BundleExportResult(
            bundle_dir=target_dir,
            split_pdf=target_dir / split_name,
            manifest_path=target_dir / "manifest.json",
            source_page_count=len(source_doc),
            output_page_count=output_count,
        )
    finally:
        output_doc.close()
        source_doc.close()
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
