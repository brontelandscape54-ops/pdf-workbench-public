"""Versioned, non-destructive loaders for persisted Bundle JSON documents.

The on-disk manifest and workspace have independent versions. Every schema
change adds exactly one explicit N -> N+1 migration per affected document.
Migrating returns a deep copy: opening a Bundle never rewrites its files.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Mapping


class UnsupportedSchemaVersion(ValueError):
    """The saved document cannot be interpreted by this version of the app."""


@dataclass(frozen=True)
class SchemaSpec:
    format_name: str
    current_version: int
    oldest_version: int = 1


Migration = Callable[[dict[str, Any]], dict[str, Any]]


def migrate_document(
    document: Mapping[str, Any],
    spec: SchemaSpec,
    steps: Mapping[int, Migration],
) -> dict[str, Any]:
    """Return a current-version copy by applying registered, consecutive steps.

    Keys in ``steps`` are *source* versions: steps[1] transforms 1 -> 2.
    No implicit upgrades, downgrades, or mutation of the input are permitted.
    The schema-specific validator should be called on the returned document.
    """
    if not isinstance(document, Mapping):
        raise ValueError("saved document must be an object")
    if document.get("format") != spec.format_name:
        raise ValueError(
            f"unsupported format: {document.get('format')!r}; "
            f"expected {spec.format_name!r}"
        )
    version = document.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise UnsupportedSchemaVersion(
            f"{spec.format_name}: version must be an integer"
        )
    if version < spec.oldest_version or version > spec.current_version:
        raise UnsupportedSchemaVersion(
            f"{spec.format_name}: version {version} is not supported "
            f"(supported: {spec.oldest_version}–{spec.current_version})"
        )
    migrated: dict[str, Any] = deepcopy(dict(document))
    while version < spec.current_version:
        step = steps.get(version)
        if step is None:
            raise UnsupportedSchemaVersion(
                f"{spec.format_name}: no migration from v{version} to v{version + 1}"
            )
        result = step(migrated)
        if not isinstance(result, dict):
            raise ValueError(f"{spec.format_name}: v{version} migration must return an object")
        next_version = result.get("version")
        if isinstance(next_version, bool) or next_version != version + 1:
            raise ValueError(
                f"{spec.format_name}: v{version} migration must set version {version + 1}"
            )
        if result.get("format") != spec.format_name:
            raise ValueError(f"{spec.format_name}: migration changed the document format")
        migrated = result
        version += 1
    return migrated
