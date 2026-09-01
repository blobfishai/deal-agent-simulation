#!/usr/bin/env python3
"""Publish and byte-verify the exact DealBench-100 Harbor results bundle."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Callable

from benchmark.build_first_party_harbor_report import validate_registry_round_trip

from .harbor_receipts import local_harbor_manifest, validate_registry_dataset_files
from .model_run import DATASET_REF, DATASET_REVISION, DATASET_TAG, load_published_model_run
from .release import DEFAULT_OUTPUT, HARBOR_DATASET_ID, HARBOR_RESULTS_TAG, HF_COMMIT
from .spec import BENCHMARK_VERSION

HARBOR_PAYLOAD = DEFAULT_OUTPUT / "harbor"
PACKAGE_ROOT = Path(__file__).resolve().parent
PUBLICATION_RECEIPT = PACKAGE_ROOT / "publication_receipts" / f"harbor-{HARBOR_RESULTS_TAG}.json"
TASK_PUBLICATION_RECEIPT = (
    PACKAGE_ROOT / "publication_receipts" / f"harbor-{DATASET_TAG}-tasks.json"
)
IMMUTABLE_PREVIOUS_RELEASES = (
    {
        "tag": "v1.0.0",
        "ref": "sha256:ed0b501c8d8d6116a46b968353d304a8bed8ba318d95ef7c33a28ed14062fbc9",
        "revision": 1,
    },
    {
        "tag": "v1.1.0",
        "ref": "sha256:3e07546007fff5cc9106a80c4f0431cf3f2c97dccc32b29a0e9839570986cbed",
        "revision": 2,
    },
)
PREVIOUS_DATASET_TAG = str(IMMUTABLE_PREVIOUS_RELEASES[-1]["tag"])
PREVIOUS_DATASET_REF = str(IMMUTABLE_PREVIOUS_RELEASES[-1]["ref"])
PREVIOUS_DATASET_REVISION = int(IMMUTABLE_PREVIOUS_RELEASES[-1]["revision"])
COMMAND = Callable[..., Any]


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


def _run(
    runner: COMMAND,
    arguments: list[str],
    *,
    input_text: str | None = None,
) -> str:
    completed = runner(
        arguments,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "no command output").strip()
        raise ValueError(f"Harbor command failed ({' '.join(arguments)}): {detail}")
    return str(completed.stdout)


def _run_json(runner: COMMAND, arguments: list[str]) -> dict[str, Any]:
    try:
        payload = json.loads(_run(runner, arguments))
    except json.JSONDecodeError as error:
        raise ValueError(f"Harbor command returned malformed JSON: {arguments}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"Harbor command did not return a JSON object: {arguments}")
    return payload


def _local_task_bindings(manifest_path: Path) -> dict[str, str]:
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    bindings: dict[str, str] = {}
    for row in manifest.get("tasks") or []:
        name = row.get("name") if isinstance(row, dict) else None
        digest = row.get("digest") if isinstance(row, dict) else None
        if not isinstance(name, str) or not isinstance(digest, str) or name in bindings:
            raise ValueError("DealBench Harbor task bindings are malformed or duplicated")
        bindings[name] = digest
    if len(bindings) != 100:
        raise ValueError("DealBench Harbor manifest must bind exactly 100 tasks")
    return bindings


def _remote_task_bindings(payload: dict[str, Any]) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for row in payload.get("tasks") or []:
        task = row.get("task_version") if isinstance(row, dict) else None
        package = task.get("package") if isinstance(task, dict) else None
        org = package.get("org") if isinstance(package, dict) else None
        org_name = org.get("name") if isinstance(org, dict) else None
        short_name = package.get("name") if isinstance(package, dict) else None
        digest = task.get("content_hash") if isinstance(task, dict) else None
        if (
            not isinstance(org_name, str)
            or not isinstance(short_name, str)
            or not isinstance(digest, str)
        ):
            raise ValueError("Harbor returned a malformed task binding")
        name = f"{org_name}/{short_name}"
        normalized = digest if digest.startswith("sha256:") else f"sha256:{digest}"
        if name in bindings:
            raise ValueError("Harbor returned duplicate task bindings")
        bindings[name] = normalized
    return bindings


def _remote_file_bindings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for row in payload.get("files") or []:
        if not isinstance(row, dict):
            raise ValueError("Harbor returned a malformed dataset file binding")
        digest = row.get("content_hash")
        if not isinstance(digest, str):
            raise ValueError("Harbor dataset file binding lacks a digest")
        bindings.append(
            {
                "path": row.get("path"),
                "digest": digest if digest.startswith("sha256:") else f"sha256:{digest}",
                "bytes": row.get("size_bytes"),
            }
        )
    return sorted(bindings, key=lambda row: str(row["path"]))


def _validate_remote_version(
    payload: dict[str, Any],
    *,
    expected_ref: str,
    expected_tasks: dict[str, str],
    expected_files: list[dict[str, Any]],
    required_tag: str,
    expected_revision: int | None = None,
) -> int:
    revision = payload.get("revision")
    if (
        payload.get("package") != HARBOR_DATASET_ID
        or payload.get("type") != "dataset"
        or payload.get("visibility") != "public"
        or payload.get("content_hash") != expected_ref
        or required_tag not in (payload.get("tags") or [])
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision <= 0
    ):
        raise ValueError("Harbor dataset identity, visibility, ref, tag, or revision changed")
    if expected_revision is not None and revision != expected_revision:
        raise ValueError("Harbor evaluated dataset revision changed")
    if _remote_task_bindings(payload) != expected_tasks:
        raise ValueError("Harbor dataset task bindings disagree with the checked-in release")
    if _remote_file_bindings(payload) != expected_files:
        raise ValueError("Harbor dataset file bindings disagree with the checked-in release")
    return revision


def _tagged_version(versions_payload: dict[str, Any], tag: str) -> dict[str, Any] | None:
    matches = [
        row
        for row in versions_payload.get("versions") or []
        if isinstance(row, dict) and tag in (row.get("tags") or [])
    ]
    if len(matches) > 1:
        raise ValueError(f"Harbor tag {tag!r} resolves to multiple versions")
    return matches[0] if matches else None


def _validate_previous_release(
    payload: dict[str, Any], expected: dict[str, Any]
) -> None:
    if (
        payload.get("package") != HARBOR_DATASET_ID
        or payload.get("type") != "dataset"
        or payload.get("visibility") != "public"
        or payload.get("content_hash") != expected["ref"]
        or payload.get("revision") != expected["revision"]
        or expected["tag"] not in (payload.get("tags") or [])
    ):
        raise ValueError(
            f"the immutable DealBench {expected['tag']} Harbor release changed"
        )


def publish_exact_task_release(
    *,
    runner: COMMAND = subprocess.run,
    payload_root: Path = HARBOR_PAYLOAD,
    receipt_path: Path = TASK_PUBLICATION_RECEIPT,
) -> dict[str, Any]:
    """Publish and exact-ref verify the qualified task-only release."""

    payload_root = payload_root.resolve()
    if payload_root != HARBOR_PAYLOAD.resolve() or not payload_root.is_dir():
        raise ValueError("Harbor payload must be the generated DealBench release")
    manifest_path = payload_root / "dataset.toml"
    tasks_root = payload_root / "tasks"
    manifest_receipt = local_harbor_manifest(
        dataset_name=HARBOR_DATASET_ID,
        version=BENCHMARK_VERSION,
        manifest_path=manifest_path,
        tasks_path=tasks_root,
    )
    if manifest_receipt["datasetFiles"]:
        raise ValueError("task release must not bind model-run files")
    expected_tasks = _local_task_bindings(manifest_path)

    for previous_release in IMMUTABLE_PREVIOUS_RELEASES:
        previous = _run_json(
            runner,
            [
                "harbor",
                "version",
                "show",
                f"{HARBOR_DATASET_ID}@{previous_release['tag']}",
                "--files",
                "--tasks",
                "--json",
            ],
        )
        _validate_previous_release(previous, previous_release)

    versions = _run_json(
        runner,
        ["harbor", "version", "list", HARBOR_DATASET_ID, "--json"],
    )
    existing = _tagged_version(versions, DATASET_TAG)
    published = existing is None
    if published:
        _run(
            runner,
            ["harbor", "publish", str(tasks_root), "--public", "-t", DATASET_TAG],
            input_text="y\n",
        )
        _run(
            runner,
            [
                "harbor",
                "publish",
                str(payload_root),
                "--no-tasks",
                "--public",
                "-t",
                DATASET_TAG,
            ],
            input_text="y\n",
        )

    remote = _run_json(
        runner,
        [
            "harbor",
            "version",
            "show",
            f"{HARBOR_DATASET_ID}@{DATASET_TAG}",
            "--files",
            "--tasks",
            "--json",
        ],
    )
    release_ref = remote.get("content_hash")
    if (
        not isinstance(release_ref, str)
        or not release_ref.startswith("sha256:")
        or len(release_ref) != 71
        or any(character not in "0123456789abcdef" for character in release_ref[7:])
    ):
        raise ValueError("Harbor task release did not return an immutable SHA-256 ref")
    if existing is not None and existing.get("content_hash") != release_ref:
        raise ValueError(
            f"Harbor {DATASET_TAG} tag changed during publication verification"
        )
    revision = _validate_remote_version(
        remote,
        expected_ref=release_ref,
        expected_tasks=expected_tasks,
        expected_files=[],
        required_tag=DATASET_TAG,
    )
    if revision <= PREVIOUS_DATASET_REVISION:
        raise ValueError(
            f"Harbor {DATASET_TAG} release did not follow {PREVIOUS_DATASET_TAG}"
        )

    temporary_root = Path(tempfile.mkdtemp(prefix="dealbench-harbor-tasks-"))
    try:
        _run(
            runner,
            [
                "harbor",
                "download",
                f"{HARBOR_DATASET_ID}@{release_ref}",
                "--output-dir",
                str(temporary_root),
                "--export",
            ],
        )
        downloaded_root = temporary_root / "dealbench-100-suite"
        round_trip = validate_registry_round_trip(
            tasks_root,
            downloaded_root,
            revision=revision,
        )
        round_trip.update(
            validate_registry_dataset_files(
                revision=revision,
                registry_root=downloaded_root,
                expected_files=[],
            )
        )
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)

    for previous_release in IMMUTABLE_PREVIOUS_RELEASES:
        previous_after = _run_json(
            runner,
            [
                "harbor",
                "version",
                "show",
                f"{HARBOR_DATASET_ID}@{previous_release['tag']}",
                "--files",
                "--tasks",
                "--json",
            ],
        )
        _validate_previous_release(previous_after, previous_release)
    receipt = {
        "schema_version": "dealbench.harbor-task-publication.v1",
        "dataset": HARBOR_DATASET_ID,
        "version": BENCHMARK_VERSION,
        "tag": DATASET_TAG,
        "ref": release_ref,
        "revision": revision,
        "published_now": published,
        "previous_release_unchanged": True,
        "previous_releases": [dict(row) for row in IMMUTABLE_PREVIOUS_RELEASES],
        "manifest": manifest_receipt,
        "registry_round_trip": round_trip,
    }
    _write_json_atomic(receipt_path, receipt)
    return receipt


def publish_exact_results(
    *,
    expected_evaluated_ref: str,
    runner: COMMAND = subprocess.run,
    payload_root: Path = HARBOR_PAYLOAD,
    receipt_path: Path = PUBLICATION_RECEIPT,
) -> dict[str, Any]:
    """Publish one result-only revision and prove its remote bytes."""

    payload_root = payload_root.resolve()
    if payload_root != HARBOR_PAYLOAD.resolve() or not payload_root.is_dir():
        raise ValueError("Harbor payload must be the generated DealBench release")
    if expected_evaluated_ref != DATASET_REF:
        raise ValueError("expected evaluated ref must equal the checked-in DealBench pin")
    model_run = load_published_model_run()
    if model_run is None:
        raise ValueError("refusing to publish without a complete checked-in model run")

    manifest_path = payload_root / "dataset.toml"
    tasks_root = payload_root / "tasks"
    model_bundle_path = payload_root / "model-runs.json"
    manifest_receipt = local_harbor_manifest(
        dataset_name=HARBOR_DATASET_ID,
        version=BENCHMARK_VERSION,
        manifest_path=manifest_path,
        tasks_path=tasks_root,
    )
    expected_files = manifest_receipt["datasetFiles"]
    if [row["path"] for row in expected_files] != ["model-runs.json"]:
        raise ValueError("DealBench Harbor results revision must bind only model-runs.json")
    model_bundle = json.loads(model_bundle_path.read_text(encoding="utf-8"))
    runs = model_bundle.get("runs") or []
    public_artifacts = model_bundle.get("public_artifacts") or {}
    if (
        model_bundle.get("schema_version") != "dealbench.harbor-model-runs.v1"
        or len(runs) != 1
        or runs[0].get("job", {}).get("id") != model_run["job"]["id"]
        or public_artifacts.get("hugging_face_commit") != HF_COMMIT
        or public_artifacts.get("harbor_metadata_tag") != HARBOR_RESULTS_TAG
    ):
        raise ValueError("DealBench Harbor model bundle is not the checked-in publication")

    expected_tasks = _local_task_bindings(manifest_path)

    base = _run_json(
        runner,
        [
            "harbor",
            "version",
            "show",
            f"{HARBOR_DATASET_ID}@{DATASET_TAG}",
            "--files",
            "--tasks",
            "--json",
        ],
    )
    _validate_remote_version(
        base,
        expected_ref=DATASET_REF,
        expected_tasks=expected_tasks,
        expected_files=[],
        required_tag=DATASET_TAG,
        expected_revision=DATASET_REVISION,
    )

    versions = _run_json(
        runner,
        ["harbor", "version", "list", HARBOR_DATASET_ID, "--json"],
    )
    existing = _tagged_version(versions, HARBOR_RESULTS_TAG)
    published = existing is None
    if published:
        _run(
            runner,
            [
                "harbor",
                "publish",
                str(payload_root),
                "--no-tasks",
                "--public",
                "-t",
                HARBOR_RESULTS_TAG,
            ],
            input_text="y\n",
        )

    remote = _run_json(
        runner,
        [
            "harbor",
            "version",
            "show",
            f"{HARBOR_DATASET_ID}@{HARBOR_RESULTS_TAG}",
            "--files",
            "--tasks",
            "--json",
        ],
    )
    results_ref = remote.get("content_hash")
    if (
        not isinstance(results_ref, str)
        or not results_ref.startswith("sha256:")
        or len(results_ref) != 71
        or any(character not in "0123456789abcdef" for character in results_ref[7:])
    ):
        raise ValueError("Harbor results revision did not return an immutable SHA-256 ref")
    if existing is not None and existing.get("content_hash") != results_ref:
        raise ValueError("Harbor results tag changed during publication verification")
    revision = _validate_remote_version(
        remote,
        expected_ref=results_ref,
        expected_tasks=expected_tasks,
        expected_files=expected_files,
        required_tag=HARBOR_RESULTS_TAG,
    )
    if revision <= DATASET_REVISION:
        raise ValueError("Harbor results revision did not follow the evaluated revision")
    base_after = _run_json(
        runner,
        [
            "harbor",
            "version",
            "show",
            f"{HARBOR_DATASET_ID}@{DATASET_TAG}",
            "--files",
            "--tasks",
            "--json",
        ],
    )
    _validate_remote_version(
        base_after,
        expected_ref=DATASET_REF,
        expected_tasks=expected_tasks,
        expected_files=[],
        required_tag=DATASET_TAG,
        expected_revision=DATASET_REVISION,
    )

    temporary_root = Path(tempfile.mkdtemp(prefix="dealbench-harbor-results-"))
    try:
        _run(
            runner,
            [
                "harbor",
                "download",
                f"{HARBOR_DATASET_ID}@{results_ref}",
                "--output-dir",
                str(temporary_root),
                "--export",
            ],
        )
        downloaded_root = temporary_root / "dealbench-100-suite"
        round_trip = validate_registry_round_trip(
            tasks_root,
            downloaded_root,
            revision=revision,
        )
        round_trip.update(
            validate_registry_dataset_files(
                revision=revision,
                registry_root=downloaded_root,
                expected_files=expected_files,
            )
        )
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)

    receipt = {
        "schema_version": "dealbench.harbor-publication.v1",
        "dataset": HARBOR_DATASET_ID,
        "evaluated_ref": DATASET_REF,
        "evaluated_revision": DATASET_REVISION,
        "evaluated_tag": DATASET_TAG,
        "results_ref": results_ref,
        "results_revision": revision,
        "results_tag": HARBOR_RESULTS_TAG,
        "model_job_id": model_run["job"]["id"],
        "published_now": published,
        "manifest": manifest_receipt,
        "registry_round_trip": round_trip,
    }
    _write_json_atomic(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-evaluated-ref")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--publish-exact-results",
        action="store_true",
        help="Publish the result-only metadata revision.",
    )
    mode.add_argument(
        "--publish-exact-tasks",
        action="store_true",
        help="Publish the qualified immutable task release.",
    )
    args = parser.parse_args()
    if args.publish_exact_results:
        if not args.expected_evaluated_ref:
            parser.error("--expected-evaluated-ref is required for result publication")
        receipt = publish_exact_results(
            expected_evaluated_ref=args.expected_evaluated_ref
        )
    else:
        if args.expected_evaluated_ref:
            parser.error("--expected-evaluated-ref is not used for task publication")
        receipt = publish_exact_task_release()
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
