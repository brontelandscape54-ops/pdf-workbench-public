from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import (
    CustomSplitDirection,
    CustomSplitNode,
    FourSplitOrder,
    PageSplitSettings,
    SplitMode,
)
from .ocr_manifest import load_manifest, sha256_file
from .schema_migrations import SchemaSpec, migrate_document
from .custom_presets import as_custom_settings


WORKSPACE_FORMAT = "pdf-workbench-workspace"
WORKSPACE_VERSION = 1
WORKSPACE_FILENAME = "workspace.json"
WORKSPACE_SCHEMA = SchemaSpec(WORKSPACE_FORMAT, WORKSPACE_VERSION)
WORKSPACE_MIGRATIONS = {}


def custom_node_from_dict(data: dict[str, Any]) -> CustomSplitNode:
    node_type = data.get("type")
    if node_type == "leaf":
        return CustomSplitNode()
    if node_type != "split":
        raise ValueError("invalid custom split node type")

    direction = CustomSplitDirection(str(data["direction"]))
    ratio = float(data["ratio"])
    first = data.get("first")
    second = data.get("second")
    if not isinstance(first, dict) or not isinstance(second, dict):
        raise ValueError("custom split node must have two children")
    return CustomSplitNode(
        direction=direction,
        ratio=ratio,
        first=custom_node_from_dict(first),
        second=custom_node_from_dict(second),
    ).normalized()


def settings_from_manifest(manifest: dict[str, Any]) -> list[PageSplitSettings]:
    source_pages = manifest.get("source_pages")
    if not isinstance(source_pages, list):
        raise ValueError("manifest source_pages is missing")

    settings_list: list[PageSplitSettings] = []
    for expected_index, entry in enumerate(source_pages, start=1):
        if not isinstance(entry, dict):
            raise ValueError("invalid source page entry")
        if int(entry.get("source_page", -1)) != expected_index:
            raise ValueError("manifest source pages are not contiguous")

        mode = SplitMode(str(entry.get("split_mode", SplitMode.NONE.value)))
        settings = PageSplitSettings(
            mode=mode,
            x_ratio=float(entry.get("x_ratio", 0.5)),
            y_ratio=float(entry.get("y_ratio", 0.5)),
            overlap_px=int(entry.get("overlap_px", 0)),
            order=FourSplitOrder(
                str(entry.get("four_split_order", FourSplitOrder.RTL_TB.value))
            ),
        )
        if mode is SplitMode.CUSTOM:
            layout = entry.get("custom_layout")
            if not isinstance(layout, dict):
                raise ValueError("custom page is missing custom_layout")
            settings.custom_root = custom_node_from_dict(layout)
            raw_order = entry.get("custom_order", [])
            if not isinstance(raw_order, list):
                raise ValueError("invalid custom_order")
            settings.custom_order = [
                tuple(int(step) for step in path)
                for path in raw_order
                if isinstance(path, list)
            ]
        settings_list.append(as_custom_settings(settings.normalized()).normalized())
    return settings_list


def load_workspace(bundle_dir: str | Path) -> dict[str, Any] | None:
    path = Path(bundle_dir).expanduser().resolve() / WORKSPACE_FILENAME
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("workspace.json must contain a JSON object")
    return migrate_document(data, WORKSPACE_SCHEMA, WORKSPACE_MIGRATIONS)


def load_bundle_workspace(
    bundle_dir: str | Path,
) -> tuple[dict[str, Any], dict[str, Any] | None, list[PageSplitSettings]]:
    _manifest_path, manifest = load_manifest(bundle_dir)
    workspace = load_workspace(bundle_dir)
    settings = settings_from_manifest(manifest)
    return manifest, workspace, settings


def source_candidates(
    bundle_dir: str | Path,
    manifest: dict[str, Any],
    workspace: dict[str, Any] | None,
) -> list[Path]:
    bundle = Path(bundle_dir).expanduser().resolve()
    candidates: list[Path] = []

    if workspace is not None:
        raw_path = workspace.get("source_pdf_path")
        if isinstance(raw_path, str) and raw_path:
            candidates.append(Path(raw_path).expanduser())

    source = manifest.get("source")
    if isinstance(source, dict):
        embedded = source.get("embedded_source")
        if isinstance(embedded, str) and embedded:
            candidates.append(bundle / embedded)
        filename = source.get("filename")
        if isinstance(filename, str) and filename:
            candidates.append(bundle.parent / filename)

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = candidate.resolve() if candidate.exists() else candidate.absolute()
        key = str(resolved)
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def source_matches_manifest(path: str | Path, manifest: dict[str, Any]) -> bool:
    source = manifest.get("source")
    if not isinstance(source, dict):
        return False
    expected_hash = source.get("sha256")
    if not isinstance(expected_hash, str) or not expected_hash:
        return False
    candidate = Path(path).expanduser().resolve()
    return candidate.is_file() and sha256_file(candidate) == expected_hash
