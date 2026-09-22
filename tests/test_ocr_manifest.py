from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pdf_workbench.core.ocr_manifest import (
    FORMAT_NAME,
    FORMAT_VERSION,
    load_manifest,
    sha256_file,
    validate_manifest,
    write_manifest,
)


def minimal_manifest() -> dict[str, object]:
    return {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "source": {
            "filename": "sample.pdf",
            "sha256": "0" * 64,
            "size_bytes": 1,
            "page_count": 1,
            "embedded_source": None,
        },
        "export": {"dpi": 180, "grayscale": True, "jpeg_quality": 70},
        "source_pages": [
            {
                "source_page": 1,
                "source_page_size_pt": [100.0, 200.0],
                "source_render_size_px": [1000, 2000],
                "split_mode": "none",
                "x_ratio": 0.5,
                "y_ratio": 0.5,
                "overlap_px": 0,
                "four_split_order": "rtl_tb",
            }
        ],
        "pieces": [
            {
                "piece_id": "piece_000001",
                "output_page": 1,
                "source_page": 1,
                "piece_name": "full",
                "crop_box_px": [0, 0, 1000, 2000],
                "ownership_box_px": [0, 0, 1000, 2000],
            }
        ],
    }


def test_manifest_round_trip_from_bundle_directory(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    data = minimal_manifest()
    write_manifest(bundle / "manifest.json", data)
    path, loaded = load_manifest(bundle)
    assert path == bundle / "manifest.json"
    assert loaded == data


def test_manifest_rejects_non_contiguous_output_pages() -> None:
    data = minimal_manifest()
    pieces = data["pieces"]
    assert isinstance(pieces, list)
    pieces[0]["output_page"] = 2
    with pytest.raises(ValueError, match="output_page"):
        validate_manifest(data)


def test_manifest_rejects_ownership_outside_crop() -> None:
    data = minimal_manifest()
    pieces = data["pieces"]
    assert isinstance(pieces, list)
    pieces[0]["ownership_box_px"] = [-1, 0, 1000, 2000]
    with pytest.raises(ValueError, match="ownership"):
        validate_manifest(data)


def test_sha256_file(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(b"abc")
    assert sha256_file(path) == hashlib.sha256(b"abc").hexdigest()
