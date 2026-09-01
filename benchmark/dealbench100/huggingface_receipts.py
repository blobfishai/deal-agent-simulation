"""Fail-closed Hugging Face object receipts for benchmark publications."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

PLATFORM_METADATA_PATHS = frozenset({".gitattributes"})


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _payload_files(root: Path) -> dict[str, Path]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Hugging Face payload directory does not exist: {root}")
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file() and ".cache" not in path.relative_to(root).parts
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_id(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def payload_manifest(root: Path) -> tuple[str, int, int]:
    files = _payload_files(root)
    digest = hashlib.sha256()
    total_bytes = 0
    for relative, path in sorted(files.items()):
        size = path.stat().st_size
        total_bytes += size
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), len(files), total_bytes


def verify_hugging_face_publication(
    root: Path,
    siblings: Iterable[Any],
    *,
    commit: str,
) -> dict[str, Any]:
    """Match every local byte to one immutable Hub Git or LFS object."""

    if len(commit) != 40 or any(
        character not in "0123456789abcdef" for character in commit
    ):
        raise ValueError(f"invalid Hugging Face commit: {commit!r}")
    local = _payload_files(root)
    remote: dict[str, Any] = {}
    platform_metadata: list[str] = []
    for sibling in siblings:
        filename = _field(sibling, "rfilename")
        if not isinstance(filename, str) or not filename:
            raise ValueError("Hugging Face sibling lacks rfilename")
        if filename in PLATFORM_METADATA_PATHS and filename not in local:
            platform_metadata.append(filename)
            continue
        if filename in remote:
            raise ValueError(f"duplicate Hugging Face sibling: {filename}")
        remote[filename] = sibling

    if set(local) != set(remote):
        missing = sorted(set(local) - set(remote))
        unexpected = sorted(set(remote) - set(local))
        raise ValueError(
            "Hugging Face payload paths disagree with the release "
            f"(missing={missing}, unexpected={unexpected})"
        )

    git_blobs = 0
    lfs_objects = 0
    total_bytes = 0
    for relative, path in sorted(local.items()):
        sibling = remote[relative]
        size = path.stat().st_size
        remote_size = _field(sibling, "size")
        if remote_size != size:
            raise ValueError(
                f"Hugging Face size mismatch for {relative}: {remote_size} != {size}"
            )
        total_bytes += size
        lfs = _field(sibling, "lfs")
        if lfs is not None:
            expected = _field(lfs, "sha256")
            actual = sha256_file(path)
            lfs_objects += 1
        else:
            expected = _field(sibling, "blob_id")
            actual = git_blob_id(path)
            git_blobs += 1
        if not isinstance(expected, str) or actual != expected:
            raise ValueError(f"Hugging Face object mismatch for {relative}")

    manifest_sha256, manifest_files, manifest_bytes = payload_manifest(root)
    if manifest_files != len(local) or manifest_bytes != total_bytes:
        raise ValueError("Hugging Face local payload changed during verification")
    return {
        "commit": commit,
        "payloadFiles": len(local),
        "payloadBytes": total_bytes,
        "payloadManifestSha256": manifest_sha256,
        "gitBlobsVerified": git_blobs,
        "lfsObjectsVerified": lfs_objects,
        "platformMetadataExcluded": sorted(platform_metadata),
        "exactObjectIdentity": True,
    }
