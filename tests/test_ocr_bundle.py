from __future__ import annotations

import json
from pathlib import Path

import fitz

from pdf_workbench.core.models import PageSplitSettings, SplitMode
from pdf_workbench.core.ocr_bundle import export_ocr_bundle
from pdf_workbench.core.ocr_manifest import sha256_file


def _make_source_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((40, 80), "PAGE1")
    page = doc.new_page(width=500, height=700)
    page.insert_text((40, 80), "PAGE2")
    doc.save(path)
    doc.close()


def test_mixed_mode_bundle_export(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    _make_source_pdf(source)

    result = export_ocr_bundle(
        source,
        tmp_path / "sample_ocr_bundle",
        [
            PageSplitSettings(
                mode=SplitMode.HORIZONTAL_2,
                y_ratio=0.4,
                overlap_px=8,
            ),
            PageSplitSettings(
                mode=SplitMode.FOUR,
                x_ratio=0.6,
                y_ratio=0.5,
            ),
        ],
        dpi=144,
        quality=90,
        grayscale=False,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    split_doc = fitz.open(result.split_pdf)
    try:
        assert result.output_page_count == 6
        assert len(split_doc) == 6
    finally:
        split_doc.close()

    assert manifest["source"]["sha256"] == sha256_file(source)
    assert manifest["source"]["embedded_source"] is None
    assert [piece["output_page"] for piece in manifest["pieces"]] == list(range(1, 7))
    assert all("path" not in key.lower() for key in manifest["source"].keys())


def test_bundle_can_optionally_embed_original(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    _make_source_pdf(source)

    result = export_ocr_bundle(
        source,
        tmp_path / "bundle",
        [PageSplitSettings(mode=SplitMode.NONE), PageSplitSettings(mode=SplitMode.NONE)],
        include_original=True,
    )

    embedded = result.bundle_dir / "source" / "original.pdf"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert embedded.is_file()
    assert sha256_file(embedded) == sha256_file(source)
    assert manifest["source"]["embedded_source"] == "source/original.pdf"


def test_existing_bundle_can_be_replaced_while_preserving_user_files(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    _make_source_pdf(source)
    bundle = tmp_path / "bundle"

    first = export_ocr_bundle(
        source,
        bundle,
        [PageSplitSettings(mode=SplitMode.NONE), PageSplitSettings(mode=SplitMode.NONE)],
    )
    user_file = first.bundle_dir / "ocr_result_searchable.pdf"
    user_file.write_bytes(b"user-added-ocr-result")
    (first.bundle_dir / "workspace.json").write_text("old workspace", encoding="utf-8")

    second = export_ocr_bundle(
        source,
        bundle,
        [
            PageSplitSettings(mode=SplitMode.HORIZONTAL_2),
            PageSplitSettings(mode=SplitMode.NONE),
        ],
        replace_existing=True,
    )

    assert second.bundle_dir == bundle
    assert second.output_page_count == 3
    assert user_file.read_bytes() == b"user-added-ocr-result"
    assert not (bundle / "workspace.json").exists()
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_pages"][0]["split_mode"] == SplitMode.HORIZONTAL_2.value
