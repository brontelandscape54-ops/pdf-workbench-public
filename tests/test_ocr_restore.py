from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from pdf_workbench.core.models import PageSplitSettings, SplitMode
from pdf_workbench.core.ocr_bundle import export_ocr_bundle
from pdf_workbench.core.ocr_restore import inspect_ocr_pdf, restore_ocr_pdf


def _make_one_page_source(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((40, 80), "SOURCE")
    doc.save(path)
    doc.close()


def test_restore_preserves_searchable_text_with_scaled_ocr_pages(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    _make_one_page_source(source)
    bundle = export_ocr_bundle(
        source,
        tmp_path / "bundle",
        [PageSplitSettings(mode=SplitMode.HORIZONTAL_2, y_ratio=0.5)],
        dpi=144,
        grayscale=False,
    )

    split_doc = fitz.open(bundle.split_pdf)
    ocr_doc = fitz.open()
    try:
        for page_index, split_page in enumerate(split_doc):
            page = ocr_doc.new_page(
                width=split_page.rect.width * 2,
                height=split_page.rect.height * 2,
            )
            page.show_pdf_page(
                page.rect,
                split_doc,
                page_index,
                keep_proportion=False,
            )
            page.insert_text(
                (20, 40),
                "TOP_TEXT" if page_index == 0 else "BOTTOM_TEXT",
            )
        ocr_path = tmp_path / "ocr.pdf"
        ocr_doc.save(ocr_path)
    finally:
        ocr_doc.close()
        split_doc.close()

    inspection = inspect_ocr_pdf(bundle.bundle_dir, ocr_path)
    assert inspection.has_extractable_text is True

    output = tmp_path / "restored.pdf"
    source_pages, imported_pieces = restore_ocr_pdf(
        bundle.bundle_dir,
        ocr_path,
        output,
    )
    assert source_pages == 1
    assert imported_pieces == 2

    restored = fitz.open(output)
    try:
        assert len(restored) == 1
        assert restored[0].rect.width == pytest.approx(400)
        assert restored[0].rect.height == pytest.approx(600)
        text = restored[0].get_text("text")
        assert "TOP_TEXT" in text
        assert "BOTTOM_TEXT" in text
    finally:
        restored.close()


def test_restore_rejects_page_count_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    _make_one_page_source(source)
    bundle = export_ocr_bundle(
        source,
        tmp_path / "bundle",
        [PageSplitSettings(mode=SplitMode.HORIZONTAL_2)],
        dpi=144,
    )

    one_page_doc = fitz.open()
    one_page_doc.new_page(width=100, height=100)
    one_page_pdf = tmp_path / "one.pdf"
    one_page_doc.save(one_page_pdf)
    one_page_doc.close()

    with pytest.raises(ValueError, match="expected 2, actual 1"):
        inspect_ocr_pdf(bundle.bundle_dir, one_page_pdf)


def test_pdf_without_text_is_warning_state_not_geometry_error(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    _make_one_page_source(source)
    bundle = export_ocr_bundle(
        source,
        tmp_path / "bundle",
        [PageSplitSettings(mode=SplitMode.NONE)],
    )

    image_only = fitz.open()
    image_only.new_page(width=400, height=600)
    image_only_path = tmp_path / "image_only.pdf"
    image_only.save(image_only_path)
    image_only.close()

    inspection = inspect_ocr_pdf(bundle.bundle_dir, image_only_path)
    assert inspection.has_extractable_text is False
