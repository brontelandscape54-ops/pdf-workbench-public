from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Callable, Sequence

import fitz
from PIL import Image

from .geometry import crop_regions
from .models import PageSplitSettings

ProgressCallback = Callable[[int, int], bool | None]


def render_page_to_image(page: fitz.Page, dpi: int) -> Image.Image:
    if dpi <= 0:
        raise ValueError("dpi must be > 0")
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def prepare_image(img: Image.Image, grayscale: bool) -> Image.Image:
    return img.convert("L" if grayscale else "RGB")


def jpeg_bytes(img: Image.Image, quality: int) -> bytes:
    if not 1 <= quality <= 95:
        raise ValueError("quality must be between 1 and 95")
    bio = BytesIO()
    img.save(bio, format="JPEG", quality=quality, optimize=True, progressive=False)
    return bio.getvalue()


def add_image_page(out_doc: fitz.Document, img: Image.Image, dpi: int, quality: int) -> None:
    data = jpeg_bytes(img, quality)
    page = out_doc.new_page(
        width=img.width * 72.0 / dpi,
        height=img.height * 72.0 / dpi,
    )
    page.insert_image(page.rect, stream=data)


def export_split_pdf(
    input_pdf: str | Path,
    output_pdf: str | Path,
    page_settings: Sequence[PageSplitSettings],
    *,
    dpi: int = 180,
    quality: int = 70,
    grayscale: bool = False,
    progress: ProgressCallback | None = None,
) -> tuple[int, int]:
    """Export an image-based PDF according to per-page split settings.

    Returns (source_page_count, output_page_count).
    If progress returns False, export is cancelled and the partial file is removed.
    """
    input_path = Path(input_pdf).expanduser().resolve()
    output_path = Path(output_pdf).expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    if dpi <= 0:
        raise ValueError("dpi must be > 0")
    if not 1 <= quality <= 95:
        raise ValueError("quality must be between 1 and 95")

    src = fitz.open(str(input_path))
    if len(page_settings) != len(src):
        src.close()
        raise ValueError(
            f"page_settings length ({len(page_settings)}) must equal PDF page count ({len(src)})"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out = fitz.open()
    output_count = 0
    cancelled = False

    try:
        total = len(src)
        for page_index, page in enumerate(src):
            img = render_page_to_image(page, dpi)
            settings = page_settings[page_index]
            for _name, box in crop_regions(img.width, img.height, settings):
                cropped = prepare_image(img.crop(box), grayscale)
                add_image_page(out, cropped, dpi, quality)
                output_count += 1

            if progress is not None:
                keep_going = progress(page_index + 1, total)
                if keep_going is False:
                    cancelled = True
                    break

        if cancelled:
            return total, output_count

        out.save(str(output_path), garbage=4, deflate=True, clean=True)
        return total, output_count
    finally:
        out.close()
        src.close()
        if cancelled and output_path.exists():
            output_path.unlink()
