from __future__ import annotations

import json
import hashlib
import math
import shutil
import tempfile
import tomllib
from pathlib import Path

import pytest

from benchmark.dealbench100.evaluation import policy_steps, qualify, run_episode
from benchmark.dealbench100.model_run import (
    DEFAULT_OUTPUT as MODEL_RUNS_ROOT,
    RUN_SLUG as MODEL_RUN_SLUG,
    _website_events,
    load_published_model_run,
)
from benchmark.dealbench100.release import (
    DEFAULT_OUTPUT,
    HF_COMMIT,
    HF_PAYLOAD_MANIFEST_SHA256,
    WEBSITE_DATA,
    harbor_task_digest,
)
from benchmark.dealbench100.service import mcp_response
from benchmark.dealbench100.spec import (
    FAMILIES,
    SCORING_CATEGORIES,
    WORLDS,
    build_tasks,
    catalog_digest,
)
from benchmark.dealbench100.world import DealWorld, grouped_tool_definitions, tool_definitions


def test_catalog_has_100_distinct_grounded_tasks() -> None:
    tasks = build_tasks()
    assert len(tasks) == 100
    assert len({task["task_id"] for task in tasks}) == 100
    assert len({task["prompt"] for task in tasks}) == 100
    assert len({task["project_code"] for task in tasks}) == len(WORLDS) == 10
    assert {task["metadata"]["category"] for task in tasks} == {family["key"] for family in FAMILIES}
    assert all(len(task["context_files"]) == 27 for task in tasks)
    assert all(len(task["required_investigations"]) == 18 for task in tasks)
    assert all(len(task["rubric"]) == 38 for task in tasks)
    assert all(
        math.isclose(
            sum(check["points"] for check in task["rubric"]),
            100,
            rel_tol=0,
            abs_tol=1e-9,
        )
        for task in tasks
    )
    assert all("Leave unrelated projects and records unchanged" in task["prompt"] for task in tasks)
    assert all("Company=" not in task["prompt"] and "contentId=" not in task["prompt"] for task in tasks)
    assert len(catalog_digest(tasks)) == 64


def test_deal_score_is_one_hundred_points_across_seven_categories() -> None:
    assert len(SCORING_CATEGORIES) == 7
    assert sum(category["weight"] for category in SCORING_CATEGORIES) == 100
    categories = {category["key"] for category in SCORING_CATEGORIES}
    for task in build_tasks():
        assert {criterion["category"] for criterion in task["rubric"]} == categories


def test_oracle_and_controls_are_discriminating() -> None:
    report = qualify(build_tasks())
    assert report["qualification_passed"] is True
    assert report["oracle"] == {"passes": 100, "mean_score": 100.0}
    assert report["determinism"] == {"replays": 100, "exact_episode_matches": 100, "mismatches": 0}
    assert report["executions"] == 700
    assert all(control["strict_passes"] == 0 for control in report["negative_controls"].values())
    assert all(control["false_accepts"] == 0 for control in report["negative_controls"].values())


def test_task_specific_state_and_readbacks_are_required() -> None:
    tasks = build_tasks()
    for task in (tasks[1], tasks[7], tasks[9]):
        oracle = run_episode(task, policy_steps(task, "oracle"))["verdict"]
        shortcut = run_episode(task, policy_steps(task, "shortcut"))["verdict"]
        state_only = run_episode(task, policy_steps(task, "state_only"))["verdict"]
        assert oracle["passed"] is True and oracle["score"] == 100
        assert shortcut["passed"] is False and shortcut["score"] < 50
        assert state_only["passed"] is False and state_only["category_scores"]["discovery"] == 0


def test_mcp_contract_groups_every_tool_and_persists_state() -> None:
    task = build_tasks()[0]
    definitions = tool_definitions(task["answer_schema"])
    assert len(definitions) == 37
    assert all(tool["inputSchema"]["additionalProperties"] is False for tool in definitions)
    grouped = grouped_tool_definitions(task["answer_schema"])
    assert set(grouped) == {"dealbench", "dealroom", "mail", "chat", "spreadsheets", "market_data", "deal_management"}
    assert sum(len(tools) for tools in grouped.values()) == len(definitions)
    with tempfile.TemporaryDirectory() as temporary:
        world = DealWorld.create(task, Path(temporary) / "world.sqlite")
        response = mcp_response(
            world,
            grouped,
            "dealbench",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert response is not None
        assert response["result"]["tools"]
        result = world.call_tool("benchmark.get_task", {"task_id": task["task_id"]})
        assert result["project_code"] == task["project_code"]
        assert "expected_answer" not in result
        world.close()


def test_model_trajectory_projection_preserves_roles_and_write_stages() -> None:
    verdict = {"score": 42.0, "passed": False}
    trace = [
        {
            "tool": "dealroom.search_files",
            "server": "dealroom",
            "arguments": {"query": "operative forecast"},
            "result": {"matches": 2},
            "success": True,
            "mutation": False,
        },
        {
            "tool": "spreadsheets.update_model",
            "server": "spreadsheets",
            "arguments": {"model_id": "model-1"},
            "result": {"updated": True},
            "success": True,
            "mutation": True,
        },
        {
            "tool": "spreadsheets.get_model",
            "server": "spreadsheets",
            "arguments": {"model_id": "model-1"},
            "result": {"status": "draft"},
            "success": True,
            "mutation": False,
        },
    ]
    events = _website_events("Run the deal", trace, "Prepared for review", verdict)
    assert [event["stage"] for event in events[1:4]] == [
        "investigate",
        "decide",
        "verify",
    ]
    assert events[-2]["role"] == "agent-response"
    assert events[-2]["text"] == "Prepared for review"
    assert events[-1]["role"] == "verifier-receipt"
    assert "42.00 DealScore" in events[-1]["text"]


def test_checked_in_release_is_harbor_and_website_complete() -> None:
    assert DEFAULT_OUTPUT.is_dir()
    build = json.loads((DEFAULT_OUTPUT / "reports" / "build.json").read_text())
    qualification = json.loads((DEFAULT_OUTPUT / "reports" / "qualification.json").read_text())
    assert build["task_count"] == 100
    assert build["world_count"] == 10
    assert build["tool_count"] == 37
    assert build["qualification_passed"] is True
    assert qualification["oracle"]["passes"] == 100
    task_dirs = sorted((DEFAULT_OUTPUT / "harbor" / "tasks").iterdir())
    assert len(task_dirs) == 100
    dataset = tomllib.loads((DEFAULT_OUTPUT / "harbor" / "dataset.toml").read_text())
    assert dataset["dataset"]["name"] == "blobfishai/dealbench-100-suite"
    assert len(dataset["tasks"]) == 100
    expected_digests = {entry["name"].split("/", 1)[1]: entry["digest"] for entry in dataset["tasks"]}
    for task_dir in (task_dirs[0], task_dirs[49], task_dirs[-1]):
        digest, files, size = harbor_task_digest(task_dir)
        assert digest == expected_digests[task_dir.name]
        assert files > 20 and size > 10_000
    page = json.loads(WEBSITE_DATA.read_text())
    assert page["benchmark"]["taskCount"] == 100
    assert len(page["tasks"]) == 100
    assert len(page["samples"]) == 100
    assert page["evaluationControls"][0]["score"] == 100
    assert all(row["kind"] == "reference" for row in page["evaluationControls"])
    assert page["benchmark"]["publicationReceipt"] == {
        "huggingFaceCommit": HF_COMMIT,
        "payloadManifestSha256": HF_PAYLOAD_MANIFEST_SHA256,
        "exactObjectIdentity": True,
        "receiptUrl": f"https://huggingface.co/datasets/SamuelChien821/dealbench-100/tree/{HF_COMMIT}",
    }
    assert len(list((DEFAULT_OUTPUT / "huggingface" / "verifiers").glob("*.json"))) == 100
    assert all(f"/blob/{HF_COMMIT}/" in task["datasetUrl"] for task in page["tasks"])
    assert all(
        f"/resolve/{HF_COMMIT}/" in asset["url"]
        for sample in page["samples"].values()
        for asset in sample["assets"]
    )
    assert all(f"/blob/{HF_COMMIT}/" in trajectory["transcriptUrl"] for trajectory in page["trajectories"])
    assert all(f"/blob/{HF_COMMIT}/" in trajectory["verifierUrl"] for trajectory in page["trajectories"])

    digest_payload = json.loads(
        (DEFAULT_OUTPUT / "harbor" / "task-digests.json").read_text()
    )
    task_receipts = {row["task_id"]: row for row in digest_payload["tasks"]}
    model_run = load_published_model_run(
        expected_task_receipts=task_receipts,
        expected_catalog_sha256=build["catalog_sha256"],
    )
    if model_run is None:
        assert len(page["trajectories"]) == 10
        assert all(row["kind"] == "reference" for row in page["trajectories"])
        assert page["leaderboard"] == []
        assert build["ranked_model_run"] is None
        assert page["benchmark"]["modelRunReceipt"] is None
        assert dataset.get("files", []) == []
        assert not (DEFAULT_OUTPUT / "harbor" / "model-runs.json").exists()
    else:
        assert len(page["trajectories"]) == 11
        assert page["trajectories"][0]["kind"] == "model"
        assert page["trajectories"][0]["traceMode"] == "provider-native"
        assert page["trajectories"][0]["tokens"]["output"] > 0
        assert page["trajectories"][0]["costUsd"] >= 0
        assert len(page["leaderboard"]) == 1
        ranked = page["leaderboard"][0]
        assert ranked["name"] == "GPT-5.6 Luna"
        assert ranked["kind"] == "model"
        assert ranked["tasks"] == 100
        assert ranked["score"] > 0
        assert ranked["runUrl"].endswith(f"/model-runs/{MODEL_RUN_SLUG}.json")
        assert len(
            list(
                (
                    DEFAULT_OUTPUT
                    / "huggingface"
                    / "model-runs"
                    / MODEL_RUN_SLUG
                    / "trials"
                ).glob("*.json")
            )
        ) == 100
        model_bundle = DEFAULT_OUTPUT / "harbor" / "model-runs.json"
        assert model_bundle.is_file()
        assert dataset["files"] == [
            {
                "path": "model-runs.json",
                "digest": f"sha256:{hashlib.sha256(model_bundle.read_bytes()).hexdigest()}",
            }
        ]
        assert model_run["aggregate"]["task_count"] == 100
        assert model_run["aggregate"]["errored_tasks"] == 0
        assert model_run["aggregate"]["retries"] == 0
        assert model_run["aggregate"]["trace_coverage"] == 100
        assert build["ranked_model_run"]["job_id"] == model_run["job"]["id"]
        assert page["benchmark"]["modelRunReceipt"]["jobId"] == model_run["job"]["id"]


def test_published_model_run_rejects_a_tampered_trial(tmp_path: Path) -> None:
    if not MODEL_RUNS_ROOT.is_dir():
        pytest.skip("no ranked model run is published in this task-only release")
    copied = tmp_path / "model_runs"
    shutil.copytree(MODEL_RUNS_ROOT, copied)
    manifest = json.loads((copied / f"{MODEL_RUN_SLUG}.json").read_text())
    task_id = manifest["trials"][0]["task_id"]
    artifact_path = copied / MODEL_RUN_SLUG / "trials" / f"{task_id}.json"
    artifact = json.loads(artifact_path.read_text())
    artifact["score"] = float(artifact["score"]) + 1
    artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    with pytest.raises(ValueError, match="artifact receipt"):
        load_published_model_run(copied)


def test_clean_room_anchor_receipt_is_explicit() -> None:
    anchors = (DEFAULT_OUTPUT / "ANCHORS.md").read_text()
    for url in (
        "https://www.mercor.com/apex/apex-agents-leaderboard/",
        "https://www.mercor.com/apex/apex-accounting-leaderboard/",
        "https://github.com/Mercor-Intelligence/archipelago",
        "https://arxiv.org/abs/2509.25721",
        "https://huggingface.co/datasets/mercor/apex-agents",
        "https://hub.harborframework.com/datasets/Enterprise-Bench/l1-l2-bench/latest",
        "https://hub.harborframework.com/datasets/agentic-labs/erp-bench/latest",
    ):
        assert url in anchors
    assert "No gated task" in anchors
    assert "not downloaded or scraped" in anchors
