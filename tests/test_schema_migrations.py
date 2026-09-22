from __future__ import annotations

from copy import deepcopy
import json

import pytest

from pdf_workbench.core.schema_migrations import (
    SchemaSpec,
    UnsupportedSchemaVersion,
    migrate_document,
)
from pdf_workbench.core.ocr_manifest import (
    FORMAT_NAME,
    FORMAT_VERSION,
    load_manifest,
)
from pdf_workbench.core.workspace import (
    WORKSPACE_FORMAT,
    WORKSPACE_VERSION,
    load_workspace,
)


def test_consecutive_migrations_preserve_original_document() -> None:
    spec = SchemaSpec("example", 3)
    original = {"format": "example", "version": 1, "nested": {"value": "old"}}
    snapshot = deepcopy(original)

    def one_to_two(data):
        data["nested"]["value"] = "new"
        data["version"] = 2
        return data

    def two_to_three(data):
        data["additional"] = True
        data["version"] = 3
        return data

    result = migrate_document(original, spec, {1: one_to_two, 2: two_to_three})
    assert result == {
        "format": "example",
        "version": 3,
        "nested": {"value": "new"},
        "additional": True,
    }
    assert original == snapshot
    assert result is not original


def test_no_missing_migration_step_is_silently_skipped() -> None:
    spec = SchemaSpec("example", 3)
    with pytest.raises(UnsupportedSchemaVersion, match="no migration"):
        migrate_document(
            {"format": "example", "version": 1}, spec,
            {1: lambda data: {**data, "version": 2}},
        )


@pytest.mark.parametrize("version", [0, -1, 4, True, "1", None])
def test_invalid_or_future_schema_versions_are_rejected(version) -> None:
    with pytest.raises(UnsupportedSchemaVersion):
        migrate_document(
            {"format": "example", "version": version},
            SchemaSpec("example", 3),
            {},
        )


def test_migration_must_advance_exactly_one_version() -> None:
    with pytest.raises(ValueError, match="must set version 2"):
        migrate_document(
            {"format": "example", "version": 1},
            SchemaSpec("example", 2),
            {1: lambda data: {**data, "version": 3}},
        )


def test_manifest_and_workspace_keep_independent_v1_baselines() -> None:
    assert FORMAT_VERSION == 1
    assert WORKSPACE_VERSION == 1
    assert FORMAT_NAME != WORKSPACE_FORMAT


def test_workspace_loader_does_not_rewrite_the_source_file(tmp_path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    path = bundle / "workspace.json"
    data = {
        "format": WORKSPACE_FORMAT,
        "version": WORKSPACE_VERSION,
        "source_pdf_path": "/some/old/path.pdf",
        "current_page": 0,
    }
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)
    loaded = load_workspace(bundle)
    assert loaded == data
    assert path.read_bytes() == raw


def test_future_workspace_version_is_not_accepted(tmp_path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "workspace.json").write_text(
        json.dumps({"format": WORKSPACE_FORMAT, "version": WORKSPACE_VERSION + 1}),
        encoding="utf-8",
    )
    with pytest.raises(UnsupportedSchemaVersion):
        load_workspace(bundle)
