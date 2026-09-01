from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

import pytest

from benchmark.dealbench100.release import _bind_harbor_dataset_file


def test_model_run_bundle_is_digest_bound_once(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.toml"
    dataset.write_text(
        '[dataset]\nname = "blobfishai/dealbench-100-suite"\nversion = "1.0.0"\n'
    )
    bundle = tmp_path / "model-runs.json"
    bundle.write_text('{"schema_version":"dealbench.harbor-model-runs.v1"}\n')

    _bind_harbor_dataset_file(dataset, bundle)

    parsed = tomllib.loads(dataset.read_text())
    assert parsed["files"] == [
        {
            "path": "model-runs.json",
            "digest": f"sha256:{hashlib.sha256(bundle.read_bytes()).hexdigest()}",
        }
    ]
    with pytest.raises(ValueError, match="already contains"):
        _bind_harbor_dataset_file(dataset, bundle)


def test_model_run_bundle_must_be_a_dataset_sibling(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.toml"
    dataset.write_text("[dataset]\n")
    nested = tmp_path / "nested"
    nested.mkdir()
    bundle = nested / "model-runs.json"
    bundle.write_text("{}\n")

    with pytest.raises(ValueError, match="sibling release files"):
        _bind_harbor_dataset_file(dataset, bundle)
