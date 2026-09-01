"""Self-contained Harbor dataset receipts for the public DealBench repository."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any

from benchmark.harbor_receipts import harbor_task_digest, sha256_file


def local_harbor_manifest(
    *,
    manifest_path: Path,
    tasks_path: Path,
    dataset_name: str,
    version: str,
) -> dict[str, Any]:
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    dataset = manifest.get("dataset") or {}
    if dataset.get("name") != dataset_name or dataset.get("version") != version:
        raise ValueError("DealBench dataset.toml identity does not match the release")
    declared = manifest.get("tasks") or []
    if len(declared) != 100:
        raise ValueError("DealBench dataset.toml must bind exactly 100 tasks")
    expected = {(str(row.get("name")), str(row.get("digest"))) for row in declared}
    actual: set[tuple[str, str]] = set()
    for task_dir in sorted(path for path in tasks_path.iterdir() if path.is_dir()):
        task = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
        digest, _, _ = harbor_task_digest(task_dir)
        actual.add((str((task.get("task") or {}).get("name")), digest))
    if len(actual) != 100 or expected != actual:
        raise ValueError("DealBench dataset.toml digests do not match the release tasks")
    canonical = json.dumps(
        sorted(expected), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    dataset_files: list[dict[str, Any]] = []
    declared_files = manifest.get("files") or []
    if not isinstance(declared_files, list):
        raise ValueError("DealBench dataset.toml files must be an array")
    seen_file_paths: set[str] = set()
    manifest_root = manifest_path.parent.resolve()
    for row in declared_files:
        if not isinstance(row, dict):
            raise ValueError("DealBench dataset.toml contains a malformed file binding")
        relative = row.get("path")
        digest = row.get("digest")
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).name != relative
            or relative in seen_file_paths
            or not isinstance(digest, str)
            or not digest.startswith("sha256:")
            or len(digest) != 71
            or any(character not in "0123456789abcdef" for character in digest[7:])
        ):
            raise ValueError("DealBench dataset.toml has an invalid file binding")
        local_file = (manifest_root / relative).resolve()
        if local_file.parent != manifest_root or not local_file.is_file():
            raise ValueError("DealBench declared Harbor dataset file is missing")
        actual_digest = f"sha256:{sha256_file(local_file)}"
        if actual_digest != digest:
            raise ValueError("DealBench declared Harbor dataset file digest changed")
        seen_file_paths.add(relative)
        dataset_files.append(
            {
                "path": relative,
                "digest": actual_digest,
                "bytes": local_file.stat().st_size,
            }
        )
    dataset_files.sort(key=lambda row: str(row["path"]))
    canonical_files = json.dumps(
        dataset_files, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "tasks": len(actual),
        "distinctTaskNames": len({name for name, _ in actual}),
        "distinctTaskDigests": len({digest for _, digest in actual}),
        "taskBindingsSha256": hashlib.sha256(canonical).hexdigest(),
        "datasetManifestSha256": sha256_file(manifest_path),
        "datasetFiles": dataset_files,
        "datasetFileBindingsSha256": hashlib.sha256(canonical_files).hexdigest(),
    }


def validate_registry_dataset_files(
    *,
    revision: int,
    registry_root: Path,
    expected_files: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recompute every dataset-level file exported from one Harbor revision."""

    observed_files: list[dict[str, Any]] = []
    resolved_root = registry_root.resolve()
    for expected_file in expected_files:
        registry_file = (resolved_root / str(expected_file["path"])).resolve()
        if registry_file.parent != resolved_root or not registry_file.is_file():
            raise ValueError(
                f"Harbor revision {revision} omitted declared dataset file "
                f"{expected_file['path']}"
            )
        observed_file = {
            "path": expected_file["path"],
            "digest": f"sha256:{sha256_file(registry_file)}",
            "bytes": registry_file.stat().st_size,
        }
        if observed_file != expected_file:
            raise ValueError(
                f"Harbor revision {revision} changed declared dataset file "
                f"{expected_file['path']}"
            )
        observed_files.append(observed_file)
    canonical_files = json.dumps(
        observed_files, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "datasetFiles": observed_files,
        "datasetFileBindingsSha256": hashlib.sha256(canonical_files).hexdigest(),
        "exactDatasetFiles": True,
    }
