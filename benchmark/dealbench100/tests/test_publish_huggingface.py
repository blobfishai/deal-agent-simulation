from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from benchmark.dealbench100.huggingface_receipts import git_blob_id

import benchmark.dealbench100.publish_huggingface as publisher


class FakeHfApi:
    def __init__(self, parent: str, commit: str, payload: Path) -> None:
        self.parent = parent
        self.commit = commit
        self.payload = payload
        self.uploads: list[dict[str, Any]] = []

    def dataset_info(
        self,
        repo_id: str,
        *,
        revision: str,
        files_metadata: bool,
    ) -> dict[str, Any]:
        assert repo_id == publisher.HF_DATASET
        assert files_metadata is True
        if revision == "main":
            return {"sha": self.parent, "siblings": []}
        assert revision == self.commit
        return {
            "sha": self.commit,
            "siblings": [
                {
                    "rfilename": path.relative_to(self.payload).as_posix(),
                    "size": path.stat().st_size,
                    "blob_id": git_blob_id(path),
                }
                for path in sorted(self.payload.rglob("*"))
                if path.is_file()
            ],
        }

    def upload_folder(self, **kwargs: Any) -> dict[str, str]:
        self.uploads.append(kwargs)
        return {"oid": self.commit}


def test_publisher_refuses_missing_model_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publisher, "load_published_model_run", lambda: None)
    with pytest.raises(ValueError, match="complete checked-in model run"):
        publisher.publish_exact_payload(
            expected_parent=publisher.HF_COMMIT,
            hf_api=object(),
        )


def test_publisher_refuses_remote_parent_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        publisher,
        "load_published_model_run",
        lambda: {"job": {"id": "job-1"}},
    )
    monkeypatch.setattr(publisher, "HF_COMMIT", "a" * 40)
    api = FakeHfApi("f" * 40, "e" * 40, publisher.HF_PAYLOAD)
    with pytest.raises(ValueError, match="parent changed"):
        publisher.publish_exact_payload(
            expected_parent="a" * 40,
            hf_api=api,
        )
    assert api.uploads == []


def test_publisher_verifies_every_uploaded_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = tmp_path / "huggingface"
    (payload / "data").mkdir(parents=True)
    (payload / "README.md").write_text("# DealBench-100\n")
    (payload / "data" / "tasks.jsonl").write_text('{"task_id":"dealbench-001"}\n')
    parent = "a" * 40
    commit = "b" * 40
    monkeypatch.setattr(publisher, "HF_PAYLOAD", payload)
    monkeypatch.setattr(publisher, "HF_COMMIT", parent)
    monkeypatch.setattr(
        publisher,
        "load_published_model_run",
        lambda: {"job": {"id": "job-1"}},
    )
    api = FakeHfApi(parent, commit, payload)

    receipt = publisher.publish_exact_payload(
        expected_parent=parent,
        hf_api=api,
        payload_root=payload,
    )

    assert receipt["commit"] == commit
    assert receipt["payloadFiles"] == 2
    assert receipt["exactObjectIdentity"] is True
    assert api.uploads[0]["folder_path"] == str(payload.resolve())


def test_task_release_is_exact_without_a_model_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = tmp_path / "huggingface"
    (payload / "data").mkdir(parents=True)
    (payload / "README.md").write_text("# DealBench-100 v1.1.0\n")
    (payload / "data" / "tasks.jsonl").write_text(
        '{"task_id":"dealbench-001"}\n'
    )
    parent = "c" * 40
    commit = "d" * 40
    monkeypatch.setattr(publisher, "HF_PAYLOAD", payload)
    monkeypatch.setattr(publisher, "HF_TASK_RELEASE_PARENT", parent)
    monkeypatch.setattr(publisher, "load_published_model_run", lambda: None)
    api = FakeHfApi(parent, commit, payload)
    receipt_path = tmp_path / "task-publication.json"

    receipt = publisher.publish_exact_payload(
        expected_parent=parent,
        hf_api=api,
        payload_root=payload,
        release_kind="task",
        receipt_path=receipt_path,
    )

    assert receipt["release_kind"] == "task"
    assert receipt["model_job_id"] is None
    assert receipt["commit"] == commit
    assert receipt_path.read_text().endswith("\n")
    assert json.loads(receipt_path.read_text()) == receipt
