"""Independent, fail-closed Harbor task and lock receipt verification.

The public benchmark reports must prove that each trial ran the exact task bytes
that were released and published.  Harbor records two task identities:

* ``lock.json.task.digest`` is the durable publisher content digest.
* ``result.json.task_checksum`` is Harbor's legacy full-directory ``dirhash``.

This module recomputes both without trusting either receipt.  The publisher hash
implementation mirrors Harbor 0.21's ``Packager`` protocol; the legacy checksum
mirrors dirhash's default ``name`` + ``data`` protocol for ordinary task trees.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any

SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
HARBOR_DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
PUBLISH_DIRECT_FILES = ("task.toml", "instruction.md", "README.md")
PUBLISH_DIRECTORIES = ("environment", "tests", "solution", "steps")
DEFAULT_IGNORED_SUFFIXES = (".pyc", ".pyo", ".swp", ".swo", "~")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_release_task_path(configured: str, tasks_path: Path) -> Path:
    """Resolve an absolute or relocatable Harbor task path into one release."""

    tasks_path = tasks_path.resolve()
    configured_path = Path(configured).expanduser()
    if configured_path.is_absolute():
        resolved = configured_path.resolve()
    elif (
        ".." not in configured_path.parts
        and len(configured_path.parts) >= 3
        and configured_path.parts[-3:-1] == ("harbor", "tasks")
    ):
        resolved = (tasks_path / configured_path.name).resolve()
    else:
        raise ValueError(f"unbound relative task path: {configured}")
    if resolved.parent != tasks_path or not resolved.is_dir():
        raise ValueError(f"task path is outside the supplied release: {configured}")
    return resolved


def _default_publish_ignored(relative: Path) -> bool:
    return (
        "__pycache__" in relative.parts
        or relative.name == ".DS_Store"
        or relative.name.endswith(DEFAULT_IGNORED_SUFFIXES)
    )


def harbor_publishable_files(task_dir: Path) -> list[Path]:
    """Collect files with Harbor 0.21's publisher selection semantics."""

    task_dir = task_dir.resolve()
    files: set[Path] = set()
    for name in PUBLISH_DIRECT_FILES:
        path = task_dir / name
        if path.is_file():
            files.add(path)
    for name in PUBLISH_DIRECTORIES:
        directory = task_dir / name
        if directory.is_dir():
            files.update(path for path in directory.rglob("*") if path.is_file())

    gitignore = task_dir / ".gitignore"
    if gitignore.is_file():
        try:
            import pathspec  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError(
                f"{task_dir}: pathspec is required to verify Harbor .gitignore semantics"
            ) from error
        spec = pathspec.PathSpec.from_lines(
            "gitignore", gitignore.read_text(encoding="utf-8").splitlines()
        )
        files = {
            path
            for path in files
            if not spec.match_file(path.relative_to(task_dir).as_posix())
        }
    else:
        files = {
            path
            for path in files
            if not _default_publish_ignored(path.relative_to(task_dir))
        }
    return sorted(files, key=lambda path: path.relative_to(task_dir).as_posix())


def harbor_task_digest(task_dir: Path) -> tuple[str, int, int]:
    """Return Harbor's durable ``sha256:`` digest, file count, and byte count."""

    task_dir = task_dir.resolve()
    files = harbor_publishable_files(task_dir)
    outer = hashlib.sha256()
    total_bytes = 0
    for path in files:
        relative = path.relative_to(task_dir).as_posix()
        file_digest = sha256_file(path)
        total_bytes += path.stat().st_size
        outer.update(f"{relative}\0{file_digest}\n".encode())
    return f"sha256:{outer.hexdigest()}", len(files), total_bytes


def _legacy_directory_checksum(directory: Path) -> str | None:
    descriptors: list[str] = []
    for path in directory.iterdir():
        if path.is_symlink():
            raise ValueError(
                f"{path}: symlinks require Harbor's dirhash implementation and are rejected"
            )
        if path.is_dir():
            child_checksum = _legacy_directory_checksum(path)
            if child_checksum is None:
                continue
            properties = (f"dirhash:{child_checksum}", f"name:{path.name}")
        elif path.is_file():
            properties = (f"data:{sha256_file(path)}", f"name:{path.name}")
        else:
            continue
        descriptors.append("\0".join(sorted(properties)))
    if not descriptors:
        return None
    descriptor = "\0\0".join(sorted(descriptors))
    return hashlib.sha256(descriptor.encode("utf-8")).hexdigest()


def legacy_task_checksum(task_dir: Path) -> str:
    """Recompute Harbor's legacy ``dirhash(path, 'sha256')`` checksum."""

    checksum = _legacy_directory_checksum(task_dir.resolve())
    if checksum is None:
        raise ValueError(f"{task_dir}: cannot checksum an empty task directory")
    return checksum


def bind_trial_task(
    *,
    slug: str,
    version: str,
    trial_dir: Path,
    result: dict[str, Any],
    tasks_path: Path,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Validate one trial against its exact release task and return its receipt."""

    label = f"{slug}: {trial_dir.name}"
    task_name = result.get("task_name")
    task_checksum = result.get("task_checksum")
    configured_path = (result.get("config") or {}).get("task", {}).get("path")
    if not isinstance(task_name, str) or not isinstance(configured_path, str):
        raise ValueError(f"{label} lacks task provenance")
    if not isinstance(task_checksum, str) or not SHA256_PATTERN.fullmatch(task_checksum):
        raise ValueError(f"{label} has an invalid legacy task checksum")
    if result.get("trial_name") not in (None, trial_dir.name):
        raise ValueError(f"{label} result trial name does not match its directory")

    resolved_task = resolve_release_task_path(configured_path, tasks_path)
    task_id = result.get("task_id")
    if isinstance(task_id, dict) and isinstance(task_id.get("path"), str):
        result_task_id_path = resolve_release_task_path(task_id["path"], tasks_path)
        if result_task_id_path != resolved_task:
            raise ValueError(f"{label} result task_id path disagrees with its config")

    task_toml_path = resolved_task / "task.toml"
    if not task_toml_path.is_file():
        raise ValueError(f"{label} release task lacks task.toml")
    task_toml = tomllib.loads(task_toml_path.read_text(encoding="utf-8"))
    task_metadata = task_toml.get("task") or {}
    if task_metadata.get("name") != task_name or task_metadata.get("version") != version:
        raise ValueError(f"{label} task.toml identity does not match the run")
    metadata_id = (task_toml.get("metadata") or {}).get("task_id")
    if metadata_id is not None and metadata_id != resolved_task.name:
        raise ValueError(f"{label} task.toml metadata task_id disagrees with its directory")

    lock_path = trial_dir / "lock.json"
    if not lock_path.is_file():
        raise ValueError(f"{label} lacks lock.json")
    lock = read_json(lock_path)
    if lock.get("schema_version") != 2:
        raise ValueError(f"{label} has an unsupported trial lock schema")
    lock_task = lock.get("task") or {}
    lock_task_path = lock_task.get("path")
    if not isinstance(lock_task_path, str):
        raise ValueError(f"{label} lock lacks its task path")
    resolved_lock_path = resolve_release_task_path(lock_task_path, tasks_path)
    if resolved_lock_path != resolved_task:
        raise ValueError(f"{label} lock and result resolve to different release tasks")
    if (
        lock_task.get("name") != resolved_task.name
        or lock_task.get("version") != version
        or lock_task.get("type") != "local"
    ):
        raise ValueError(f"{label} lock task identity is not the expected local release")
    lock_digest = lock_task.get("digest")
    if not isinstance(lock_digest, str) or not HARBOR_DIGEST_PATTERN.fullmatch(lock_digest):
        raise ValueError(f"{label} lock has an invalid Harbor task digest")

    computed_digest, published_files, published_bytes = harbor_task_digest(resolved_task)
    if lock_digest != computed_digest:
        raise ValueError(f"{label} lock digest does not match the supplied release bytes")
    computed_legacy_checksum = legacy_task_checksum(resolved_task)
    if task_checksum != computed_legacy_checksum:
        raise ValueError(f"{label} result checksum does not match the supplied release tree")

    receipt = {
        "taskId": resolved_task.name,
        "taskName": task_name,
        "harborTaskDigest": lock_digest,
        "trialTaskChecksum": task_checksum,
        "lockSha256": sha256_file(lock_path),
        "publishedFileCount": published_files,
        "publishedBytes": published_bytes,
    }
    return resolved_task, receipt, lock


def validate_job_lock(
    *,
    slug: str,
    job_dir: Path,
    trial_locks: list[dict[str, Any]],
    expected_harbor_version: str | None = None,
    expected_trials: int = 100,
) -> dict[str, Any]:
    """Bind trial locks byte-for-meaning to Harbor's immutable job lock."""

    lock_path = job_dir / "lock.json"
    if not lock_path.is_file():
        raise ValueError(f"{slug}: job lacks lock.json")
    lock = read_json(lock_path)
    if lock.get("schema_version") != 3:
        raise ValueError(f"{slug}: unsupported Harbor job lock schema")
    harbor_version = (lock.get("harbor") or {}).get("version")
    if not isinstance(harbor_version, str) or not harbor_version:
        raise ValueError(f"{slug}: job lock lacks a Harbor version")
    if expected_harbor_version is not None and harbor_version != expected_harbor_version:
        raise ValueError(
            f"{slug}: job lock Harbor {harbor_version} does not match {expected_harbor_version}"
        )
    retry = lock.get("retry") or {}
    if retry.get("max_retries") != 0:
        raise ValueError(f"{slug}: job lock permitted retries")
    locked_trials = lock.get("trials") or []
    if expected_trials <= 0:
        raise ValueError(f"{slug}: expected trial count must be positive")
    if len(locked_trials) != expected_trials or len(trial_locks) != expected_trials:
        raise ValueError(
            f"{slug}: job lock must bind exactly {expected_trials} trials"
        )

    def by_task(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        mapped: dict[str, dict[str, Any]] = {}
        for row in rows:
            name = (row.get("task") or {}).get("name")
            if not isinstance(name, str) or name in mapped:
                raise ValueError(f"{slug}: job or trial locks contain duplicate task identities")
            mapped[name] = row
        return mapped

    if by_task(locked_trials) != by_task(trial_locks):
        raise ValueError(f"{slug}: per-trial locks do not exactly match the job lock")
    return {
        "jobLockSha256": sha256_file(lock_path),
        "harborVersion": harbor_version,
        "jobLockSchema": int(lock["schema_version"]),
        "trialLockSchema": 2,
        "nConcurrentTrials": lock.get("n_concurrent_trials"),
    }
