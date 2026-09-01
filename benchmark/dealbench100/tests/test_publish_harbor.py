from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

import benchmark.dealbench100.publish_harbor as publisher


def _task_bindings(payload_root: Path) -> dict[str, str]:
    manifest = tomllib.loads((payload_root / "dataset.toml").read_text())
    return {str(row["name"]): str(row["digest"]) for row in manifest["tasks"]}


def _remote_tasks(bindings: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "task_version": {
                "package": {
                    "org": {"name": name.split("/", 1)[0]},
                    "name": name.split("/", 1)[1],
                },
                "content_hash": digest.removeprefix("sha256:"),
            }
        }
        for name, digest in sorted(bindings.items())
    ]


class FakeRunner:
    def __init__(self, payload_root: Path) -> None:
        self.payload_root = payload_root
        self.bindings = _task_bindings(payload_root)
        model_bundle = payload_root / "model-runs.json"
        self.file_binding = {
            "path": "model-runs.json",
            "content_hash": hashlib.sha256(model_bundle.read_bytes()).hexdigest(),
            "size_bytes": model_bundle.stat().st_size,
        }
        self.results_ref = "sha256:" + "b" * 64
        self.published = False
        self.calls: list[list[str]] = []

    def _version(self, results: bool) -> dict[str, Any]:
        return {
            "package": publisher.HARBOR_DATASET_ID,
            "type": "dataset",
            "visibility": "public",
            "revision": (
                publisher.DATASET_REVISION + 1
                if results
                else publisher.DATASET_REVISION
            ),
            "content_hash": self.results_ref if results else publisher.DATASET_REF,
            "tags": (
                ["latest", publisher.HARBOR_RESULTS_TAG]
                if results
                else [publisher.DATASET_TAG]
            ),
            "files": [self.file_binding] if results else [],
            "tasks": _remote_tasks(self.bindings),
        }

    def __call__(
        self, arguments: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(arguments)
        if arguments[1:4] == [
            "version",
            "show",
            f"{publisher.HARBOR_DATASET_ID}@{publisher.DATASET_TAG}",
        ]:
            output = json.dumps(self._version(False))
        elif arguments[1:4] == ["version", "list", publisher.HARBOR_DATASET_ID]:
            versions = []
            if self.published:
                versions.append(
                    {
                        "revision": publisher.DATASET_REVISION + 1,
                        "content_hash": self.results_ref,
                        "tags": ["latest", publisher.HARBOR_RESULTS_TAG],
                    }
                )
            output = json.dumps({"versions": versions})
        elif arguments[1:4] == [
            "version",
            "show",
            f"{publisher.HARBOR_DATASET_ID}@{publisher.HARBOR_RESULTS_TAG}",
        ]:
            if not self.published:
                return subprocess.CompletedProcess(arguments, 1, "", "missing")
            output = json.dumps(self._version(True))
        elif arguments[1] == "publish":
            assert kwargs["input"] == "y\n"
            self.published = True
            output = "Published 1 dataset(s)\n"
        elif arguments[1] == "download":
            destination = Path(arguments[arguments.index("--output-dir") + 1])
            exported = destination / "dealbench-100-suite"
            shutil.copytree(self.payload_root / "tasks", exported)
            shutil.copy2(self.payload_root / "model-runs.json", exported)
            output = "Downloaded 100 tasks\n"
        else:
            raise AssertionError(arguments)
        return subprocess.CompletedProcess(arguments, 0, output, "")


class FakeTaskReleaseRunner:
    def __init__(self, payload_root: Path) -> None:
        self.payload_root = payload_root
        self.bindings = _task_bindings(payload_root)
        self.release_ref = "sha256:" + "c" * 64
        self.published = False
        self.calls: list[list[str]] = []

    def _previous(self, release: dict[str, Any]) -> dict[str, Any]:
        return {
            "package": publisher.HARBOR_DATASET_ID,
            "type": "dataset",
            "visibility": "public",
            "revision": release["revision"],
            "content_hash": release["ref"],
            "tags": [release["tag"]],
            "files": [],
            "tasks": [],
        }

    def _release(self) -> dict[str, Any]:
        return {
            "package": publisher.HARBOR_DATASET_ID,
            "type": "dataset",
            "visibility": "public",
            "revision": publisher.PREVIOUS_DATASET_REVISION + 1,
            "content_hash": self.release_ref,
            "tags": ["latest", publisher.DATASET_TAG],
            "files": [],
            "tasks": _remote_tasks(self.bindings),
        }

    def __call__(
        self, arguments: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(arguments)
        target = arguments[3] if len(arguments) > 3 else ""
        previous = next(
            (
                release
                for release in publisher.IMMUTABLE_PREVIOUS_RELEASES
                if target.endswith(f"@{release['tag']}")
            ),
            None,
        )
        if arguments[1:3] == ["version", "show"] and previous is not None:
            output = json.dumps(self._previous(previous))
        elif arguments[1:4] == ["version", "list", publisher.HARBOR_DATASET_ID]:
            versions = (
                [
                    {
                        "revision": publisher.PREVIOUS_DATASET_REVISION + 1,
                        "content_hash": self.release_ref,
                        "tags": ["latest", publisher.DATASET_TAG],
                    }
                ]
                if self.published
                else []
            )
            output = json.dumps({"versions": versions})
        elif arguments[1:3] == ["version", "show"] and target.endswith(
            f"@{publisher.DATASET_TAG}"
        ):
            if not self.published:
                return subprocess.CompletedProcess(arguments, 1, "", "missing")
            output = json.dumps(self._release())
        elif arguments[1] == "publish":
            assert kwargs["input"] == "y\n"
            if "--no-tasks" in arguments:
                self.published = True
            output = "Published\n"
        elif arguments[1] == "download":
            destination = Path(arguments[arguments.index("--output-dir") + 1])
            exported = destination / "dealbench-100-suite"
            shutil.copytree(self.payload_root / "tasks", exported)
            output = "Downloaded 100 tasks\n"
        else:
            raise AssertionError(arguments)
        return subprocess.CompletedProcess(arguments, 0, output, "")


def _payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    source = publisher.HARBOR_PAYLOAD
    payload = tmp_path / "harbor"
    shutil.copytree(source, payload)
    manifest_path = payload / "dataset.toml"
    manifest_path.write_text(
        manifest_path.read_text().replace(
            'version = "1.0.0"', f'version = "{publisher.BENCHMARK_VERSION}"'
        )
    )
    monkeypatch.setattr(publisher, "DATASET_REF", "sha256:" + "a" * 64)
    monkeypatch.setattr(publisher, "DATASET_REVISION", 2)
    model_job_id = "job-1"
    model_bundle = {
        "schema_version": "dealbench.harbor-model-runs.v1",
        "public_artifacts": {
            "hugging_face_commit": publisher.HF_COMMIT,
            "harbor_metadata_tag": publisher.HARBOR_RESULTS_TAG,
        },
        "runs": [{"job": {"id": model_job_id}}],
    }
    (payload / "model-runs.json").write_text(json.dumps(model_bundle) + "\n")
    manifest = manifest_path.read_text().split("[[files]]", 1)[0].rstrip()
    digest = hashlib.sha256((payload / "model-runs.json").read_bytes()).hexdigest()
    manifest_path.write_text(
        manifest
        + "\n\n[[files]]\npath = \"model-runs.json\"\n"
        + f'digest = "sha256:{digest}"\n'
    )
    monkeypatch.setattr(publisher, "HARBOR_PAYLOAD", payload)
    monkeypatch.setattr(
        publisher,
        "load_published_model_run",
        lambda: {"job": {"id": model_job_id}},
    )
    return payload, model_job_id


def test_publisher_refuses_missing_model_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publisher, "load_published_model_run", lambda: None)
    with pytest.raises(ValueError, match="complete checked-in model run"):
        publisher.publish_exact_results(expected_evaluated_ref=publisher.DATASET_REF)


def test_publisher_refuses_changed_evaluated_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, _ = _payload(tmp_path, monkeypatch)
    runner = FakeRunner(payload)
    base = runner._version(False)
    base["content_hash"] = "sha256:" + "f" * 64

    def changed_base(
        arguments: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        if arguments[1:3] == ["version", "show"] and arguments[3].endswith(
            f"@{publisher.DATASET_TAG}"
        ):
            return subprocess.CompletedProcess(arguments, 0, json.dumps(base), "")
        return runner(arguments, **kwargs)

    with pytest.raises(ValueError, match="identity, visibility, ref"):
        publisher.publish_exact_results(
            expected_evaluated_ref=publisher.DATASET_REF,
            runner=changed_base,
            payload_root=payload,
            receipt_path=tmp_path / "receipt.json",
        )
    assert not runner.published


def test_publisher_round_trips_tasks_and_model_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, model_job_id = _payload(tmp_path, monkeypatch)
    runner = FakeRunner(payload)
    receipt_path = tmp_path / "receipt.json"

    receipt = publisher.publish_exact_results(
        expected_evaluated_ref=publisher.DATASET_REF,
        runner=runner,
        payload_root=payload,
        receipt_path=receipt_path,
    )

    assert receipt["results_revision"] == publisher.DATASET_REVISION + 1
    assert receipt["model_job_id"] == model_job_id
    assert receipt["registry_round_trip"]["downloadedTasks"] == 100
    assert receipt["registry_round_trip"]["exactTaskDigests"] is True
    assert receipt["registry_round_trip"]["exactDatasetFiles"] is True
    assert receipt["registry_round_trip"]["datasetFiles"][0]["path"] == "model-runs.json"
    assert json.loads(receipt_path.read_text()) == receipt
    assert sum(call[1] == "publish" for call in runner.calls) == 1


def test_publisher_is_idempotent_for_the_exact_existing_results_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload, _ = _payload(tmp_path, monkeypatch)
    runner = FakeRunner(payload)
    runner.published = True

    receipt = publisher.publish_exact_results(
        expected_evaluated_ref=publisher.DATASET_REF,
        runner=runner,
        payload_root=payload,
        receipt_path=tmp_path / "receipt.json",
    )

    assert receipt["published_now"] is False
    assert sum(call[1] == "publish" for call in runner.calls) == 0


def test_task_publisher_round_trips_v1_2_and_preserves_release_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = tmp_path / "harbor"
    shutil.copytree(publisher.HARBOR_PAYLOAD, payload)
    manifest_path = payload / "dataset.toml"
    manifest_path.write_text(
        manifest_path.read_text().replace(
            'version = "1.0.0"', f'version = "{publisher.BENCHMARK_VERSION}"'
        )
    )
    monkeypatch.setattr(publisher, "HARBOR_PAYLOAD", payload)
    runner = FakeTaskReleaseRunner(payload)
    receipt_path = tmp_path / "task-receipt.json"

    receipt = publisher.publish_exact_task_release(
        runner=runner,
        payload_root=payload,
        receipt_path=receipt_path,
    )

    assert receipt["ref"] == runner.release_ref
    assert receipt["registry_round_trip"]["downloadedTasks"] == 100
    assert receipt["registry_round_trip"]["exactTaskDigests"] is True
    assert receipt["registry_round_trip"]["exactDatasetFiles"] is True
    assert receipt["previous_release_unchanged"] is True
    assert sum(call[1] == "publish" for call in runner.calls) == 2
    assert json.loads(receipt_path.read_text()) == receipt
