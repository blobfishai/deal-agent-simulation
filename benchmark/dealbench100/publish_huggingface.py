#!/usr/bin/env python3
"""Publish and byte-verify the exact DealBench-100 Hugging Face payload."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .huggingface_receipts import (
    PLATFORM_METADATA_PATHS,
    payload_manifest,
    verify_hugging_face_publication,
)

from .model_run import load_published_model_run
from .release import (
    DEFAULT_OUTPUT,
    HF_COMMIT,
    HF_DATASET,
    HF_TASK_RELEASE_PARENT,
)
from .spec import BENCHMARK_VERSION


COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
HF_PAYLOAD = DEFAULT_OUTPUT / "huggingface"
PACKAGE_ROOT = Path(__file__).resolve().parent
TASK_PUBLICATION_RECEIPT = (
    PACKAGE_ROOT / "publication_receipts" / f"huggingface-v{BENCHMARK_VERSION}-tasks.json"
)
RESULT_PUBLICATION_RECEIPT = (
    PACKAGE_ROOT / "publication_receipts" / f"huggingface-v{BENCHMARK_VERSION}-results.json"
)


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _payload_paths(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and ".cache" not in path.relative_to(root).parts
    }


def publish_exact_payload(
    *,
    expected_parent: str,
    hf_api: Any,
    payload_root: Path = HF_PAYLOAD,
    release_kind: str = "results",
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Upload one generated payload and prove every immutable remote object."""

    payload_root = payload_root.resolve()
    if payload_root != HF_PAYLOAD.resolve() or not payload_root.is_dir():
        raise ValueError("Hugging Face payload must be the generated DealBench release")
    if release_kind not in {"task", "results"}:
        raise ValueError("release_kind must be task or results")
    model_run = load_published_model_run()
    if release_kind == "results" and model_run is None:
        raise ValueError("refusing to publish without a complete checked-in model run")
    checked_parent = HF_COMMIT if release_kind == "results" else HF_TASK_RELEASE_PARENT
    if (
        COMMIT_PATTERN.fullmatch(expected_parent) is None
        or expected_parent != checked_parent
    ):
        raise ValueError("expected parent must equal the checked-in DealBench publication pin")
    local_paths = _payload_paths(payload_root)
    if release_kind == "task" and any(
        path == "model-runs" or path.startswith("model-runs/")
        for path in local_paths
    ):
        raise ValueError("task release must not contain model-run artifacts")

    before = hf_api.dataset_info(
        HF_DATASET,
        revision="main",
        files_metadata=True,
    )
    observed_parent = _field(before, "sha")
    if observed_parent != expected_parent:
        raise ValueError(
            f"Hugging Face parent changed: {observed_parent!r} != {expected_parent!r}"
        )
    unexpected_remote = sorted(
        str(_field(row, "rfilename"))
        for row in (_field(before, "siblings", []) or [])
        if _field(row, "rfilename") not in local_paths
        and _field(row, "rfilename") not in PLATFORM_METADATA_PATHS
    )
    if unexpected_remote:
        raise ValueError(
            f"remote contains paths absent from the generated payload: {unexpected_remote}"
        )

    manifest_sha, files, size = payload_manifest(payload_root)
    commit_info = hf_api.upload_folder(
        repo_id=HF_DATASET,
        repo_type="dataset",
        folder_path=str(payload_root),
        revision="main",
        commit_message=(
            f"Publish qualified DealBench-100 {BENCHMARK_VERSION} task release"
            if release_kind == "task"
            else "Publish complete GPT-5.6 Luna DealBench-100 run "
            f"{model_run['job']['id']}"
        ),
    )
    commit = _field(commit_info, "oid") or _field(commit_info, "commit_id")
    if not isinstance(commit, str) or COMMIT_PATTERN.fullmatch(commit) is None:
        raise ValueError("Hugging Face upload did not return an immutable commit")
    published = hf_api.dataset_info(
        HF_DATASET,
        revision=commit,
        files_metadata=True,
    )
    if _field(published, "sha") != commit:
        raise ValueError("Hugging Face immutable revision did not round-trip")
    receipt = verify_hugging_face_publication(
        payload_root,
        _field(published, "siblings", []) or [],
        commit=commit,
    )
    if (
        receipt["payloadManifestSha256"] != manifest_sha
        or receipt["payloadFiles"] != files
        or receipt["payloadBytes"] != size
    ):
        raise ValueError("Hugging Face receipt does not match the pre-upload payload")
    publication = {
        "schema_version": "dealbench.hugging-face-publication.v1",
        "dataset": HF_DATASET,
        "release_kind": release_kind,
        "parent_commit": expected_parent,
        "model_job_id": model_run["job"]["id"] if model_run is not None else None,
        **receipt,
    }
    if receipt_path is not None:
        _write_json_atomic(receipt_path, publication)
    return publication


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-parent", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--publish-exact-payload",
        action="store_true",
        help="Publish a complete results payload after a qualified model run.",
    )
    mode.add_argument(
        "--publish-task-release",
        action="store_true",
        help="Publish a qualified task-only payload before model evaluation.",
    )
    args = parser.parse_args()
    from huggingface_hub import HfApi

    receipt = publish_exact_payload(
        expected_parent=args.expected_parent,
        hf_api=HfApi(),
        release_kind="task" if args.publish_task_release else "results",
        receipt_path=(
            TASK_PUBLICATION_RECEIPT
            if args.publish_task_release
            else RESULT_PUBLICATION_RECEIPT
        ),
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
