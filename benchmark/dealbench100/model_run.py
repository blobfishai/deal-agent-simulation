#!/usr/bin/env python3
"""Build and validate one immutable DealBench-100 model-run publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import statistics
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from benchmark.build_first_party_harbor_report import manifest_digest, read_json, sha256_file
from benchmark.build_first_party_model_report import (
    codex_session_trace,
    final_agent_message,
    released_mcp_servers,
    scrub,
)

from .spec import BENCHMARK_NAME, BENCHMARK_VERSION, SCORING_CATEGORIES


PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_RELEASE = PACKAGE_ROOT / "release"
DEFAULT_OUTPUT = PACKAGE_ROOT / "model_runs"

SCHEMA_VERSION = "dealbench.model-run.v1"
TRIAL_SCHEMA_VERSION = "dealbench.model-trial.v1"
RUN_SLUG = "gpt-5.6-luna-v1.1.0-full-100"
JOB_NAME = "dealbench-gpt-5.6-luna-v1.1.0-full-100-run-1"
DATASET_NAME = "blobfishai/dealbench-100-suite"
DATASET_REF = "sha256:3e07546007fff5cc9106a80c4f0431cf3f2c97dccc32b29a0e9839570986cbed"
DATASET_TAG = "v1.1.0"
DATASET_REVISION = 2
HARBOR_VERSION = "0.21.0"
AGENT_NAME = "codex"
AGENT_VERSION = "0.151.0"
MODEL_NAME = "gpt-5.6-luna"
MODEL_PROVIDER = "openai"
MODEL_QUALIFIED_NAME = f"{MODEL_PROVIDER}/{MODEL_NAME}"
REASONING_EFFORT = "max"
REASONING_SUMMARY = "detailed"
WEB_SEARCH = "disabled"
CONCURRENCY = 3
SETUP_TIMEOUT_MULTIPLIER = 3.0
EXPECTED_TASKS = 100
EVALUATED_HF_COMMIT = "4aae831a06b2f9ac9f4dab85bf68199c94808b32"
SOURCE_REPOSITORY = "https://github.com/blobfishai/deal-agent-simulation"
SOURCE_WORLD_COMMIT = "PENDING_V1_1_0_SOURCE_COMMIT"

TASK_ID_PATTERN = re.compile(r"dealbench-\d{3}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
HARBOR_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


def _canonical_sha(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _task_receipts(release_root: Path) -> tuple[dict[str, dict[str, Any]], str]:
    digest_path = release_root / "harbor" / "task-digests.json"
    dataset_path = release_root / "harbor" / "dataset.toml"
    if not digest_path.is_file() or not dataset_path.is_file():
        raise ValueError("DealBench release lacks Harbor task identity receipts")

    digest_payload = read_json(digest_path)
    dataset_payload = tomllib.loads(dataset_path.read_text(encoding="utf-8"))
    dataset = dataset_payload.get("dataset") or {}
    if dataset.get("name") != DATASET_NAME or dataset.get("version") != BENCHMARK_VERSION:
        raise ValueError("DealBench Harbor dataset identity is not the evaluated release")

    digest_rows = digest_payload.get("tasks") or []
    dataset_rows = dataset_payload.get("tasks") or []
    if len(digest_rows) != EXPECTED_TASKS or len(dataset_rows) != EXPECTED_TASKS:
        raise ValueError("DealBench release must contain exactly 100 Harbor tasks")

    receipts: dict[str, dict[str, Any]] = {}
    for row in digest_rows:
        task_id = row.get("task_id") if isinstance(row, dict) else None
        digest = row.get("digest") if isinstance(row, dict) else None
        if (
            not isinstance(task_id, str)
            or TASK_ID_PATTERN.fullmatch(task_id) is None
            or task_id in receipts
            or not isinstance(digest, str)
            or HARBOR_DIGEST_PATTERN.fullmatch(digest) is None
        ):
            raise ValueError("DealBench task digest receipt is malformed or duplicated")
        receipts[task_id] = dict(row)

    configured = {
        str(row.get("name")): str(row.get("digest"))
        for row in dataset_rows
        if isinstance(row, dict)
    }
    expected = {
        f"blobfishai/{task_id}": str(row["digest"])
        for task_id, row in receipts.items()
    }
    if configured != expected:
        raise ValueError("DealBench dataset.toml and task digest receipts disagree")
    return receipts, _canonical_sha(sorted(expected.items()))


def _expected_agent() -> dict[str, Any]:
    return {
        "name": AGENT_NAME,
        "model_name": MODEL_QUALIFIED_NAME,
        "kwargs": {
            "version": AGENT_VERSION,
            "reasoning_effort": REASONING_EFFORT,
            "reasoning_summary": REASONING_SUMMARY,
            "web_search": WEB_SEARCH,
        },
    }


def _validate_job(
    job_dir: Path,
    task_receipts: dict[str, dict[str, Any]],
    *,
    expected_job_id: str | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    config_path = job_dir / "config.json"
    lock_path = job_dir / "lock.json"
    result_path = job_dir / "result.json"
    if not all(path.is_file() for path in (config_path, lock_path, result_path)):
        raise ValueError("model job lacks config.json, lock.json, or result.json")

    config = read_json(config_path)
    lock = read_json(lock_path)
    result = read_json(result_path)
    stats = result.get("stats") or {}

    if result.get("finished_at") in (None, ""):
        raise ValueError("model job is not finished")
    required_counts = {
        "n_total_trials": result.get("n_total_trials"),
        "n_completed_trials": stats.get("n_completed_trials"),
        "n_errored_trials": stats.get("n_errored_trials"),
        "n_running_trials": stats.get("n_running_trials"),
        "n_pending_trials": stats.get("n_pending_trials"),
        "n_cancelled_trials": stats.get("n_cancelled_trials"),
        "n_retries": stats.get("n_retries"),
    }
    if required_counts != {
        "n_total_trials": EXPECTED_TASKS,
        "n_completed_trials": EXPECTED_TASKS,
        "n_errored_trials": 0,
        "n_running_trials": 0,
        "n_pending_trials": 0,
        "n_cancelled_trials": 0,
        "n_retries": 0,
    }:
        raise ValueError(f"model job does not satisfy the complete no-retry gate: {required_counts}")

    job_id = result.get("id")
    if not isinstance(job_id, str) or not job_id:
        raise ValueError("model job lacks an immutable job id")
    if expected_job_id is not None and job_id != expected_job_id:
        raise ValueError("model job id does not match the explicitly approved run")

    if (
        config.get("job_name") != JOB_NAME
        or config.get("n_concurrent_trials") != CONCURRENCY
        or float(config.get("agent_setup_timeout_multiplier", 0))
        != SETUP_TIMEOUT_MULTIPLIER
        or config.get("agents") != [_expected_agent()]
    ):
        raise ValueError("model job configuration is not the pinned DealBench run")
    datasets = config.get("datasets") or []
    if len(datasets) != 1:
        raise ValueError("model job must bind exactly one dataset")
    dataset = datasets[0]
    if (
        dataset.get("name") != DATASET_NAME
        or dataset.get("ref") != DATASET_REF
        or dataset.get("task_names") not in (None, [])
    ):
        raise ValueError("model job dataset is not the exact evaluated registry release")

    if (
        lock.get("schema_version") != 3
        or (lock.get("harbor") or {}).get("version") != HARBOR_VERSION
        or (lock.get("harbor") or {}).get("is_editable") is not False
        or lock.get("n_concurrent_trials") != CONCURRENCY
        or (lock.get("retry") or {}).get("max_retries") != 0
    ):
        raise ValueError("Harbor job lock does not satisfy the pinned no-retry policy")

    locked_trials = lock.get("trials") or []
    if len(locked_trials) != EXPECTED_TASKS:
        raise ValueError("Harbor job lock does not contain exactly 100 trials")
    by_task: dict[str, dict[str, Any]] = {}
    expected_agent = {
        **_expected_agent(),
        "skills": [],
        "resume_trajectory": False,
        "extra_allowed_hosts": [],
        "mcp_servers": [],
    }
    expected_environment = {
        "type": "docker",
        "force_build": False,
        "delete": True,
        "cpu_enforcement_policy": "auto",
        "memory_enforcement_policy": "auto",
        "extra_docker_compose": [],
        "kwargs": {},
        "extra_allowed_hosts": [],
    }
    for trial in locked_trials:
        task = trial.get("task") or {}
        name = task.get("name")
        task_id = str(name).removeprefix("blobfishai/")
        receipt = task_receipts.get(task_id)
        if (
            not isinstance(name, str)
            or receipt is None
            or name in by_task
            or task
            != {
                "name": name,
                "version": BENCHMARK_VERSION,
                "type": "package",
                "digest": receipt["digest"],
                "source": DATASET_NAME,
            }
            or trial.get("schema_version") != 2
            or trial.get("install_only") is not False
            or float(trial.get("timeout_multiplier", 0)) != 1.0
            or float(trial.get("agent_setup_timeout_multiplier", 0))
            != SETUP_TIMEOUT_MULTIPLIER
            or trial.get("agent") != expected_agent
            or trial.get("skills") != []
            or trial.get("environment") != expected_environment
            or trial.get("verifier") != {"disable": False, "environment_mode": "shared"}
        ):
            raise ValueError(f"Harbor job lock contains an unpinned trial: {name}")
        by_task[name] = trial
    if set(by_task) != {f"blobfishai/{task_id}" for task_id in task_receipts}:
        raise ValueError("Harbor job lock does not cover the exact 100-task release")
    return config, lock, result, by_task


def _compact(value: Any, limit: int = 700) -> str:
    value = scrub(value)
    rendered = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
    rendered = " ".join(rendered.split())
    return rendered if len(rendered) <= limit else rendered[: limit - 1].rstrip() + "…"


def _website_events(
    prompt: str,
    trace: list[dict[str, Any]],
    final_response: str,
    verdict: dict[str, Any],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = [
        {
            "index": 1,
            "kind": "message",
            "role": "employee-request",
            "stage": "scope",
            "text": prompt,
        }
    ]
    observed_write = False
    for call_number, row in enumerate(trace, start=1):
        mutation = bool(row.get("mutation"))
        stage = "decide" if mutation else "verify" if observed_write else "investigate"
        events.append(
            {
                "index": len(events) + 1,
                "kind": "tool",
                "stage": stage,
                "call": call_number,
                "tool": str(row.get("tool") or "unknown_tool"),
                "server": row.get("server"),
                "arguments": scrub(row.get("arguments") or {}),
                "outcome": "ok" if row.get("success") is True else "error",
                "result": _compact(row.get("result") or "Recorded response"),
            }
        )
        observed_write = observed_write or (mutation and row.get("success") is True)
    events.extend(
        [
            {
                "index": len(events) + 1,
                "kind": "message",
                "role": "agent-response",
                "stage": "verify",
                "text": final_response,
            },
            {
                "index": len(events) + 2,
                "kind": "message",
                "role": "verifier-receipt",
                "stage": "verify",
                "text": (
                    f"Deterministic verifier: {float(verdict['score']):.2f} DealScore; "
                    f"strict pass {bool(verdict['passed'])}."
                ),
            },
        ]
    )
    return events


def _trajectory_messages(trajectory: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    steps = trajectory.get("steps") or []
    user_steps = [
        step
        for step in steps
        if isinstance(step, dict)
        and step.get("source") == "user"
        and isinstance(step.get("message"), str)
        and step["message"].strip()
    ]
    if not user_steps:
        raise ValueError("Harbor trajectory lacks the benchmark request")
    prompt = str(scrub(user_steps[-1]["message"])).strip()
    messages: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict) or step.get("source") != "agent":
            continue
        message = step.get("message")
        reasoning = step.get("reasoning_content")
        if not (isinstance(message, str) and message.strip()) and not (
            isinstance(reasoning, str) and reasoning.strip()
        ):
            continue
        messages.append(
            {
                "step_id": step.get("step_id"),
                "timestamp": step.get("timestamp"),
                "message": str(scrub(message or "")),
                "reasoning_summary": str(scrub(reasoning or "")),
            }
        )
    return prompt, messages


def _validate_verdict(task_id: str, result: dict[str, Any], verdict: dict[str, Any]) -> None:
    if (
        verdict.get("schema_version") != "dealbench.verdict.v2"
        or verdict.get("task_id") != task_id
        or verdict.get("metric") != "DealScore"
        or verdict.get("gradable") is not True
        or not isinstance(verdict.get("passed"), bool)
        or not isinstance(verdict.get("score"), (int, float))
        or not isinstance(verdict.get("reward"), (int, float))
        or not math.isclose(
            float(verdict["score"]),
            float(verdict["reward"]) * 100,
            rel_tol=0,
            abs_tol=1e-9,
        )
    ):
        raise ValueError(f"{task_id}: verifier verdict is not a valid DealScore receipt")
    result_reward = ((result.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    if not isinstance(result_reward, (int, float)) or not math.isclose(
        float(result_reward), float(verdict["reward"]), rel_tol=0, abs_tol=1e-12
    ):
        raise ValueError(f"{task_id}: Harbor reward and verifier verdict disagree")

    expected_categories = {str(row["key"]) for row in SCORING_CATEGORIES}
    category_scores = verdict.get("category_scores") or {}
    if set(category_scores) != expected_categories or any(
        not isinstance(value, (int, float)) or not 0 <= float(value) <= 100
        for value in category_scores.values()
    ):
        raise ValueError(f"{task_id}: verifier category scores are incomplete")
    if not isinstance(verdict.get("checks"), list) or len(verdict["checks"]) != 35:
        raise ValueError(f"{task_id}: verifier does not contain all 35 exact checks")


def _trial_artifact(
    *,
    job_id: str,
    trial_dir: Path,
    locked_trial: dict[str, Any],
    task_receipt: dict[str, Any],
    release_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    result_path = trial_dir / "result.json"
    config_path = trial_dir / "config.json"
    lock_path = trial_dir / "lock.json"
    trajectory_path = trial_dir / "agent" / "trajectory.json"
    verdict_path = trial_dir / "verifier" / "verdict.json"
    required = (result_path, config_path, lock_path, trajectory_path, verdict_path)
    if not all(path.is_file() for path in required):
        raise ValueError(f"{trial_dir.name}: incomplete Harbor trial artifacts")

    result = read_json(result_path)
    config = read_json(config_path)
    trial_lock = read_json(lock_path)
    trajectory = read_json(trajectory_path)
    verdict = read_json(verdict_path)
    if trial_lock != locked_trial:
        raise ValueError(f"{trial_dir.name}: trial lock disagrees with the immutable job lock")

    task_id = str((locked_trial.get("task") or {}).get("name", "")).removeprefix("blobfishai/")
    task_name = f"blobfishai/{task_id}"
    task_digest = str(task_receipt["digest"])
    trial_id = result.get("id")
    trial_checksum = result.get("task_checksum")
    result_task_id = result.get("task_id") or {}
    result_config = result.get("config") or {}
    if (
        not isinstance(trial_id, str)
        or not trial_id
        or result.get("trial_name") != trial_dir.name
        or result.get("task_name") != task_name
        or result.get("source") != DATASET_NAME
        or result.get("exception_info") is not None
        or not isinstance(trial_checksum, str)
        or SHA256_PATTERN.fullmatch(trial_checksum) is None
        or result_task_id
        != {"org": "blobfishai", "name": task_id, "ref": task_digest}
        or result_config.get("job_id") != job_id
        or (result_config.get("task") or {}).get("ref") != task_digest
        or (result_config.get("task") or {}).get("source") != DATASET_NAME
    ):
        raise ValueError(f"{trial_dir.name}: result does not bind the expected task and job")

    compact_config = {
        "task": {
            "name": task_name,
            "ref": task_digest,
            "source": DATASET_NAME,
        },
        "trial_name": trial_dir.name,
        "trials_dir": str(trial_dir.parent),
        "agent_setup_timeout_multiplier": SETUP_TIMEOUT_MULTIPLIER,
        "agent": _expected_agent(),
        "job_id": job_id,
    }
    if config != compact_config:
        raise ValueError(f"{trial_dir.name}: compact trial config is not the pinned run")

    agent_info = result.get("agent_info") or {}
    model_info = agent_info.get("model_info") or {}
    trajectory_agent = trajectory.get("agent") or {}
    if (
        agent_info.get("name") != AGENT_NAME
        or agent_info.get("version") != AGENT_VERSION
        or model_info != {"name": MODEL_NAME, "provider": MODEL_PROVIDER}
        or trajectory.get("schema_version") != "ATIF-v1.7"
        or trajectory_agent.get("name") != AGENT_NAME
        or trajectory_agent.get("version") != AGENT_VERSION
        or trajectory_agent.get("model_name") != MODEL_NAME
        or not isinstance(trajectory.get("steps"), list)
        or not trajectory["steps"]
    ):
        raise ValueError(f"{trial_dir.name}: trajectory lacks pinned agent/model identity")

    _validate_verdict(task_id, result, verdict)
    released_task = release_root / "harbor" / "tasks" / task_id
    native_trace = codex_session_trace(
        trial_dir,
        allowed_servers=released_mcp_servers(released_task),
    )
    if native_trace is None:
        raise ValueError(f"{trial_dir.name}: immutable Codex MCP event stream is missing")
    trace, trace_path = native_trace
    sanitized_trace = scrub(trace)
    if not isinstance(sanitized_trace, list) or not sanitized_trace:
        raise ValueError(f"{trial_dir.name}: provider-native MCP trace is empty")
    observed_successes = sum(row.get("success") is True for row in trace)
    if (
        len(trace) != verdict.get("tool_calls")
        or observed_successes != verdict.get("successful_tool_calls")
    ):
        raise ValueError(f"{trial_dir.name}: provider trace and verifier call receipt disagree")

    prompt, messages = _trajectory_messages(trajectory)
    final_response = final_agent_message(trajectory)
    agent_result = result.get("agent_result") or {}
    tokens: dict[str, int] = {}
    for public_key, source_key in (
        ("input", "n_input_tokens"),
        ("cached", "n_cache_tokens"),
        ("output", "n_output_tokens"),
    ):
        value = agent_result.get(source_key)
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"{trial_dir.name}: missing {source_key} receipt")
        tokens[public_key] = value
    cost = agent_result.get("cost_usd")
    if not isinstance(cost, (int, float)) or float(cost) < 0:
        raise ValueError(f"{trial_dir.name}: missing non-negative cost receipt")

    source_receipts = {
        "trial_config_sha256": sha256_file(config_path),
        "trial_lock_sha256": sha256_file(lock_path),
        "trial_result_sha256": sha256_file(result_path),
        "trajectory_sha256": sha256_file(trajectory_path),
        "provider_trace_source": trace_path.relative_to(trial_dir).as_posix(),
        "provider_trace_source_sha256": sha256_file(trace_path),
        "provider_trace_sha256": _canonical_sha(sanitized_trace),
        "verdict_sha256": sha256_file(verdict_path),
    }
    artifact = {
        "schema_version": TRIAL_SCHEMA_VERSION,
        "run_slug": RUN_SLUG,
        "trial_id": trial_id,
        "trial_name": trial_dir.name,
        "task_id": task_id,
        "task_name": task_name,
        "harbor_task_digest": task_digest,
        "trial_task_checksum": trial_checksum,
        "model": {
            "provider": MODEL_PROVIDER,
            "name": MODEL_NAME,
            "agent": AGENT_NAME,
            "agent_version": AGENT_VERSION,
            "reasoning_effort": REASONING_EFFORT,
            "reasoning_summary": REASONING_SUMMARY,
            "web_search": WEB_SEARCH,
        },
        "score": float(verdict["score"]),
        "strict_pass": bool(verdict["passed"]),
        "category_scores": verdict["category_scores"],
        "tool_calls": int(verdict["tool_calls"]),
        "successful_tool_calls": int(verdict["successful_tool_calls"]),
        "failed_tool_calls": int(verdict["tool_calls"] - verdict["successful_tool_calls"]),
        "tokens": tokens,
        "cost_usd": float(cost),
        "started_at": result.get("started_at"),
        "finished_at": result.get("finished_at"),
        "prompt": prompt,
        "final_response": final_response,
        "messages": messages,
        "trace_mode": "provider-native",
        "provider_trace": sanitized_trace,
        "website_events": _website_events(prompt, sanitized_trace, final_response, verdict),
        "verifier": scrub(verdict),
        "source_receipts": source_receipts,
        "disclosure": (
            "The provider trace is the sanitized immutable Codex MCP event stream. "
            "It is not an oracle trace or a reconstructed ideal path."
        ),
    }
    receipt = {
        "trial_id": trial_id,
        "task_id": task_id,
        "task_name": task_name,
        "harbor_task_digest": task_digest,
        "trial_task_checksum": trial_checksum,
        "score": float(verdict["score"]),
        "strict_pass": bool(verdict["passed"]),
        "category_scores": verdict["category_scores"],
        "tool_calls": int(verdict["tool_calls"]),
        "successful_tool_calls": int(verdict["successful_tool_calls"]),
        "failed_tool_calls": int(verdict["tool_calls"] - verdict["successful_tool_calls"]),
        "tokens": tokens,
        "cost_usd": float(cost),
        "started_at": result.get("started_at"),
        "finished_at": result.get("finished_at"),
        "final_response_sha256": hashlib.sha256(final_response.encode("utf-8")).hexdigest(),
        **source_receipts,
    }
    serialized_artifact = json.dumps(artifact, ensure_ascii=False, sort_keys=True)
    if scrub(serialized_artifact) != serialized_artifact:
        raise ValueError(f"{trial_dir.name}: public artifact retained a secret or private path")
    return artifact, receipt


def build_model_run(
    job_dir: Path,
    *,
    release_root: Path = DEFAULT_RELEASE,
    output_root: Path = DEFAULT_OUTPUT,
    expected_job_id: str | None = None,
) -> dict[str, Any]:
    """Validate a finished Harbor run and atomically publish its source receipts."""

    job_dir = job_dir.expanduser().resolve()
    release_root = release_root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    if not job_dir.is_dir():
        raise ValueError(f"model job does not exist: {job_dir}")
    if output_root != DEFAULT_OUTPUT.resolve():
        raise ValueError("model-run output must be the package-owned model_runs directory")

    task_receipts, task_set_sha = _task_receipts(release_root)
    config, lock, result, locked_trials = _validate_job(
        job_dir,
        task_receipts,
        expected_job_id=expected_job_id,
    )
    job_id = str(result["id"])
    trial_dirs = sorted(
        path
        for path in job_dir.iterdir()
        if path.is_dir() and (path / "result.json").is_file()
    )
    if len(trial_dirs) != EXPECTED_TASKS:
        raise ValueError(f"model job has {len(trial_dirs)} trial directories, expected 100")

    artifacts: dict[str, dict[str, Any]] = {}
    trial_receipts: list[dict[str, Any]] = []
    trial_ids: set[str] = set()
    for trial_dir in trial_dirs:
        result_payload = read_json(trial_dir / "result.json")
        task_name = result_payload.get("task_name")
        if not isinstance(task_name, str) or task_name not in locked_trials:
            raise ValueError(f"{trial_dir.name}: task is absent from the immutable job lock")
        task_id = task_name.removeprefix("blobfishai/")
        artifact, receipt = _trial_artifact(
            job_id=job_id,
            trial_dir=trial_dir,
            locked_trial=locked_trials[task_name],
            task_receipt=task_receipts[task_id],
            release_root=release_root,
        )
        if task_id in artifacts or str(receipt["trial_id"]) in trial_ids:
            raise ValueError("model job contains duplicate task or trial identities")
        artifacts[task_id] = artifact
        trial_ids.add(str(receipt["trial_id"]))
        trial_receipts.append(receipt)
    if set(artifacts) != set(task_receipts):
        raise ValueError("model trials do not cover the exact DealBench release")
    if len({str(row["trial_task_checksum"]) for row in trial_receipts}) != EXPECTED_TASKS:
        raise ValueError("model trials do not have 100 distinct task checksums")
    if len({str(row["trial_lock_sha256"]) for row in trial_receipts}) != EXPECTED_TASKS:
        raise ValueError("model trials do not have 100 distinct immutable locks")

    evals = (result.get("stats") or {}).get("evals") or {}
    eval_key = f"{AGENT_NAME}__{MODEL_NAME}__{DATASET_NAME}"
    evaluation = evals.get(eval_key) or {}
    scores = [float(row["score"]) for row in trial_receipts]
    mean_score = statistics.fmean(scores)
    reward_metrics = evaluation.get("metrics") or []
    if (
        evaluation.get("n_trials") != EXPECTED_TASKS
        or evaluation.get("n_errors") != 0
        or len(reward_metrics) != 1
        or not math.isclose(
            float(reward_metrics[0].get("mean", -1)) * 100,
            mean_score,
            rel_tol=0,
            abs_tol=1e-9,
        )
    ):
        raise ValueError("Harbor aggregate does not reconcile to the 100 trial verdicts")
    reward_buckets = (evaluation.get("reward_stats") or {}).get("reward") or {}
    aggregate_trial_names = {
        str(trial_name)
        for bucket in reward_buckets.values()
        for trial_name in (bucket if isinstance(bucket, list) else [])
    }
    if aggregate_trial_names != {path.name for path in trial_dirs}:
        raise ValueError("Harbor reward buckets do not bind every trial receipt")

    featured = min(
        trial_receipts,
        key=lambda row: (abs(float(row["score"]) - mean_score), str(row["task_id"])),
    )
    category_scores = {
        str(category["key"]): round(
            statistics.fmean(float(row["category_scores"][str(category["key"])]) for row in trial_receipts),
            2,
        )
        for category in SCORING_CATEGORIES
    }
    aggregate = {
        "task_count": EXPECTED_TASKS,
        "completed_tasks": EXPECTED_TASKS,
        "errored_tasks": 0,
        "retries": 0,
        "mean_score": round(mean_score, 2),
        "minimum_score": round(min(scores), 2),
        "maximum_score": round(max(scores), 2),
        "strict_passes": sum(bool(row["strict_pass"]) for row in trial_receipts),
        "strict_pass_rate": round(
            sum(bool(row["strict_pass"]) for row in trial_receipts) / EXPECTED_TASKS * 100,
            2,
        ),
        "category_scores": category_scores,
        "total_tool_calls": sum(int(row["tool_calls"]) for row in trial_receipts),
        "average_tool_calls": round(
            statistics.fmean(int(row["tool_calls"]) for row in trial_receipts), 2
        ),
        "successful_tool_calls": sum(
            int(row["successful_tool_calls"]) for row in trial_receipts
        ),
        "failed_tool_calls": sum(int(row["failed_tool_calls"]) for row in trial_receipts),
        "trace_coverage": EXPECTED_TASKS,
        "tokens": {
            key: sum(int(row["tokens"][key]) for row in trial_receipts)
            for key in ("input", "cached", "output")
        },
        "cost_usd": round(sum(float(row["cost_usd"]) for row in trial_receipts), 8),
        "average_cost_usd": round(
            statistics.fmean(float(row["cost_usd"]) for row in trial_receipts), 8
        ),
    }
    result_stats = result.get("stats") or {}
    for stats_key, token_key in (
        ("n_input_tokens", "input"),
        ("n_cache_tokens", "cached"),
        ("n_output_tokens", "output"),
    ):
        if result_stats.get(stats_key) != aggregate["tokens"][token_key]:
            raise ValueError(f"Harbor {stats_key} does not reconcile to trial receipts")
    if not math.isclose(
        float(result_stats.get("cost_usd", -1)),
        float(aggregate["cost_usd"]),
        rel_tol=0,
        abs_tol=1e-8,
    ):
        raise ValueError("Harbor cost does not reconcile to trial receipts")

    release_build = read_json(release_root / "reports" / "build.json")
    qualification = read_json(release_root / "reports" / "qualification.json")
    trial_receipts.sort(key=lambda row: str(row["task_id"]))
    with tempfile.TemporaryDirectory(prefix="dealbench-model-run-", dir=PACKAGE_ROOT) as temp:
        temp_root = Path(temp)
        temp_run = temp_root / RUN_SLUG
        for task_id, artifact in sorted(artifacts.items()):
            artifact_path = temp_run / "trials" / f"{task_id}.json"
            _write_json(artifact_path, artifact)
            receipt = next(row for row in trial_receipts if row["task_id"] == task_id)
            receipt["artifact"] = f"{RUN_SLUG}/trials/{task_id}.json"
            receipt["artifact_sha256"] = sha256_file(artifact_path)
            receipt["artifact_bytes"] = artifact_path.stat().st_size

        artifact_tree_sha, artifact_files, artifact_bytes = manifest_digest(temp_run)
        bindings = [
            {
                "task_id": row["task_id"],
                "harbor_task_digest": row["harbor_task_digest"],
                "trial_task_checksum": row["trial_task_checksum"],
                "trial_lock_sha256": row["trial_lock_sha256"],
                "trial_result_sha256": row["trial_result_sha256"],
                "trajectory_sha256": row["trajectory_sha256"],
                "provider_trace_source_sha256": row["provider_trace_source_sha256"],
                "provider_trace_sha256": row["provider_trace_sha256"],
                "verdict_sha256": row["verdict_sha256"],
                "artifact_sha256": row["artifact_sha256"],
                "score": row["score"],
                "strict_pass": row["strict_pass"],
            }
            for row in trial_receipts
        ]
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "run_slug": RUN_SLUG,
            "benchmark": BENCHMARK_NAME,
            "benchmark_version": BENCHMARK_VERSION,
            "metric": "DealScore",
            "model": {
                "provider": MODEL_PROVIDER,
                "name": MODEL_NAME,
                "agent": AGENT_NAME,
                "agent_version": AGENT_VERSION,
                "reasoning_effort": REASONING_EFFORT,
                "reasoning_summary": REASONING_SUMMARY,
                "web_search": WEB_SEARCH,
            },
            "harness": {
                "name": "Harbor",
                "version": HARBOR_VERSION,
                "concurrency": CONCURRENCY,
                "attempts_per_task": 1,
                "max_retries": 0,
                "agent_setup_timeout_multiplier": SETUP_TIMEOUT_MULTIPLIER,
                "environment": "task-isolated Docker; outbound web search disabled",
            },
            "dataset": {
                "name": DATASET_NAME,
                "evaluated_ref": DATASET_REF,
                "evaluated_tag": DATASET_TAG,
                "evaluated_registry_revision": DATASET_REVISION,
                "evaluated_hugging_face_commit": EVALUATED_HF_COMMIT,
                "task_set_sha256": task_set_sha,
                "catalog_sha256": release_build["catalog_sha256"],
                "qualification_sha256": _canonical_sha(qualification),
                "oracle_passes": qualification["oracle"]["passes"],
                "negative_false_accepts": sum(
                    row["false_accepts"]
                    for row in qualification["negative_controls"].values()
                ),
            },
            "source": {
                "repository": SOURCE_REPOSITORY,
                "qualified_world_commit": SOURCE_WORLD_COMMIT,
                "qualified_world_url": f"{SOURCE_REPOSITORY}/tree/{SOURCE_WORLD_COMMIT}",
            },
            "job": {
                "id": job_id,
                "name": JOB_NAME,
                "started_at": result["started_at"],
                "finished_at": result["finished_at"],
                "config_sha256": sha256_file(job_dir / "config.json"),
                "lock_sha256": sha256_file(job_dir / "lock.json"),
                "result_sha256": sha256_file(job_dir / "result.json"),
                "lock_schema": lock["schema_version"],
                "config_receipt_sha256": _canonical_sha(config),
            },
            "aggregate": aggregate,
            "featured_task_id": featured["task_id"],
            "featured_artifact": featured["artifact"],
            "featured_artifact_sha256": featured["artifact_sha256"],
            "trial_bindings_sha256": _canonical_sha(bindings),
            "artifact_tree_sha256": artifact_tree_sha,
            "artifact_files": artifact_files,
            "artifact_bytes": artifact_bytes,
            "trials": trial_receipts,
            "disclosure": (
                "This ranked result contains exactly one no-retry attempt on each of the 100 "
                "version-pinned tasks. Scores come only from DealBench's deterministic verifier. "
                "Oracle and adversarial qualification controls are excluded from the rank."
            ),
        }
        manifest_path = temp_root / f"{RUN_SLUG}.json"
        _write_json(manifest_path, manifest)

        output_root.mkdir(parents=True, exist_ok=True)
        target_run = output_root / RUN_SLUG
        target_manifest = output_root / f"{RUN_SLUG}.json"
        if target_run.exists():
            shutil.rmtree(target_run)
        shutil.move(str(temp_run), str(target_run))
        shutil.move(str(manifest_path), str(target_manifest))
    return manifest


def load_published_model_run(
    output_root: Path = DEFAULT_OUTPUT,
    *,
    expected_task_receipts: dict[str, dict[str, Any]] | None = None,
    expected_catalog_sha256: str | None = None,
) -> dict[str, Any] | None:
    """Load a checked-in run only after re-hashing every public trial artifact."""

    output_root = output_root.resolve()
    manifest_path = output_root / f"{RUN_SLUG}.json"
    if not manifest_path.is_file():
        return None
    manifest = read_json(manifest_path)
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("run_slug") != RUN_SLUG
        or manifest.get("benchmark") != BENCHMARK_NAME
        or manifest.get("benchmark_version") != BENCHMARK_VERSION
        or manifest.get("metric") != "DealScore"
    ):
        raise ValueError("checked-in DealBench model manifest has the wrong identity")
    expected_model = {
        "provider": MODEL_PROVIDER,
        "name": MODEL_NAME,
        "agent": AGENT_NAME,
        "agent_version": AGENT_VERSION,
        "reasoning_effort": REASONING_EFFORT,
        "reasoning_summary": REASONING_SUMMARY,
        "web_search": WEB_SEARCH,
    }
    expected_harness = {
        "name": "Harbor",
        "version": HARBOR_VERSION,
        "concurrency": CONCURRENCY,
        "attempts_per_task": 1,
        "max_retries": 0,
        "agent_setup_timeout_multiplier": SETUP_TIMEOUT_MULTIPLIER,
        "environment": "task-isolated Docker; outbound web search disabled",
    }
    dataset = manifest.get("dataset") or {}
    source = manifest.get("source") or {}
    job = manifest.get("job") or {}
    if (
        manifest.get("model") != expected_model
        or manifest.get("harness") != expected_harness
        or dataset.get("name") != DATASET_NAME
        or dataset.get("evaluated_ref") != DATASET_REF
        or dataset.get("evaluated_tag") != DATASET_TAG
        or dataset.get("evaluated_registry_revision") != DATASET_REVISION
        or dataset.get("evaluated_hugging_face_commit") != EVALUATED_HF_COMMIT
        or dataset.get("oracle_passes") != EXPECTED_TASKS
        or dataset.get("negative_false_accepts") != 0
        or any(
            not isinstance(dataset.get(key), str)
            or SHA256_PATTERN.fullmatch(str(dataset[key])) is None
            for key in ("task_set_sha256", "catalog_sha256", "qualification_sha256")
        )
        or source
        != {
            "repository": SOURCE_REPOSITORY,
            "qualified_world_commit": SOURCE_WORLD_COMMIT,
            "qualified_world_url": f"{SOURCE_REPOSITORY}/tree/{SOURCE_WORLD_COMMIT}",
        }
        or job.get("name") != JOB_NAME
        or job.get("lock_schema") != 3
        or not isinstance(job.get("id"), str)
        or not job["id"]
        or not isinstance(job.get("started_at"), str)
        or not isinstance(job.get("finished_at"), str)
        or any(
            not isinstance(job.get(key), str)
            or SHA256_PATTERN.fullmatch(str(job[key])) is None
            for key in (
                "config_sha256",
                "lock_sha256",
                "result_sha256",
                "config_receipt_sha256",
            )
        )
    ):
        raise ValueError("checked-in DealBench model manifest is not the pinned run")
    aggregate = manifest.get("aggregate") or {}
    trials = manifest.get("trials") or []
    if (
        aggregate.get("task_count") != EXPECTED_TASKS
        or aggregate.get("completed_tasks") != EXPECTED_TASKS
        or aggregate.get("errored_tasks") != 0
        or aggregate.get("retries") != 0
        or aggregate.get("trace_coverage") != EXPECTED_TASKS
        or len(trials) != EXPECTED_TASKS
    ):
        raise ValueError("checked-in DealBench model run is incomplete")
    if expected_catalog_sha256 is not None and (
        dataset.get("catalog_sha256") != expected_catalog_sha256
    ):
        raise ValueError("model run is bound to a different DealBench catalog")
    if expected_task_receipts is not None:
        expected_task_set = {
            f"blobfishai/{task_id}": str(row["digest"])
            for task_id, row in expected_task_receipts.items()
        }
        if dataset.get("task_set_sha256") != _canonical_sha(
            sorted(expected_task_set.items())
        ):
            raise ValueError("model run is bound to a different DealBench task set")

    seen: set[str] = set()
    trial_ids: set[str] = set()
    trial_names: set[str] = set()
    task_checksums: set[str] = set()
    trial_locks: set[str] = set()
    scores: list[float] = []
    strict_passes: list[bool] = []
    category_rows: list[dict[str, float]] = []
    tool_calls: list[int] = []
    successful_calls: list[int] = []
    failed_calls: list[int] = []
    token_rows: list[dict[str, int]] = []
    costs: list[float] = []
    for trial in trials:
        task_id = trial.get("task_id") if isinstance(trial, dict) else None
        relative = trial.get("artifact") if isinstance(trial, dict) else None
        if (
            not isinstance(task_id, str)
            or task_id in seen
            or TASK_ID_PATTERN.fullmatch(task_id) is None
            or relative != f"{RUN_SLUG}/trials/{task_id}.json"
        ):
            raise ValueError("model run has duplicate or non-canonical trial artifacts")
        if expected_task_receipts is not None and (
            task_id not in expected_task_receipts
            or trial.get("harbor_task_digest")
            != expected_task_receipts[task_id].get("digest")
        ):
            raise ValueError(f"{task_id}: model run binds a different Harbor task")
        artifact_path = (output_root / relative).resolve()
        if not artifact_path.is_relative_to(output_root) or not artifact_path.is_file():
            raise ValueError(f"{task_id}: public model artifact is missing")
        if (
            sha256_file(artifact_path) != trial.get("artifact_sha256")
            or artifact_path.stat().st_size != trial.get("artifact_bytes")
        ):
            raise ValueError(f"{task_id}: public model artifact receipt does not match")
        artifact = read_json(artifact_path)
        serialized_artifact = json.dumps(artifact, ensure_ascii=False, sort_keys=True)
        if scrub(serialized_artifact) != serialized_artifact:
            raise ValueError(f"{task_id}: public model artifact is not fully sanitized")
        source_receipts = artifact.get("source_receipts") or {}
        verifier = artifact.get("verifier") or {}
        trace = artifact.get("provider_trace") or []
        tokens = artifact.get("tokens") or {}
        category_scores = artifact.get("category_scores") or {}
        trial_id = trial.get("trial_id")
        trial_name = trial.get("trial_name")
        task_checksum = trial.get("trial_task_checksum")
        trial_lock_sha = trial.get("trial_lock_sha256")
        if (
            not isinstance(trace, list)
            or not trace
            or not all(isinstance(row, dict) for row in trace)
            or not isinstance(artifact.get("prompt"), str)
            or not artifact["prompt"].strip()
            or not isinstance(artifact.get("final_response"), str)
            or not artifact["final_response"].strip()
            or not isinstance(artifact.get("messages"), list)
            or not isinstance(artifact.get("website_events"), list)
            or not isinstance(trial.get("score"), (int, float))
            or isinstance(trial.get("score"), bool)
            or not 0 <= float(trial["score"]) <= 100
            or not isinstance(trial.get("strict_pass"), bool)
            or any(
                not isinstance(trial.get(key), int)
                or isinstance(trial.get(key), bool)
                or int(trial[key]) < 0
                for key in (
                    "tool_calls",
                    "successful_tool_calls",
                    "failed_tool_calls",
                )
            )
            or int(trial["successful_tool_calls"]) + int(trial["failed_tool_calls"])
            != int(trial["tool_calls"])
            or not isinstance(trial.get("started_at"), str)
            or not isinstance(trial.get("finished_at"), str)
        ):
            raise ValueError(f"{task_id}: public model trial content is malformed")
        if (
            artifact.get("schema_version") != TRIAL_SCHEMA_VERSION
            or artifact.get("run_slug") != RUN_SLUG
            or artifact.get("task_id") != task_id
            or artifact.get("task_name") != f"blobfishai/{task_id}"
            or artifact.get("harbor_task_digest") != trial.get("harbor_task_digest")
            or artifact.get("trial_id") != trial_id
            or artifact.get("trial_name") != trial_name
            or artifact.get("trial_task_checksum") != task_checksum
            or artifact.get("model") != expected_model
            or artifact.get("score") != trial.get("score")
            or artifact.get("strict_pass") != trial.get("strict_pass")
            or artifact.get("category_scores") != trial.get("category_scores")
            or artifact.get("tool_calls") != trial.get("tool_calls")
            or artifact.get("successful_tool_calls")
            != trial.get("successful_tool_calls")
            or artifact.get("failed_tool_calls") != trial.get("failed_tool_calls")
            or artifact.get("tokens") != trial.get("tokens")
            or artifact.get("cost_usd") != trial.get("cost_usd")
            or artifact.get("trace_mode") != "provider-native"
            or len(trace) != trial.get("tool_calls")
            or source_receipts.get("provider_trace_sha256") != _canonical_sha(trace)
            or source_receipts.get("provider_trace_sha256")
            != trial.get("provider_trace_sha256")
            or verifier.get("task_id") != task_id
            or verifier.get("score") != trial.get("score")
            or verifier.get("passed") != trial.get("strict_pass")
            or verifier.get("category_scores") != category_scores
            or verifier.get("tool_calls") != trial.get("tool_calls")
            or verifier.get("successful_tool_calls")
            != trial.get("successful_tool_calls")
            or hashlib.sha256(
                str(artifact.get("final_response") or "").encode("utf-8")
            ).hexdigest()
            != trial.get("final_response_sha256")
            or artifact.get("website_events")
            != _website_events(
                str(artifact.get("prompt") or ""),
                trace,
                str(artifact.get("final_response") or ""),
                verifier,
            )
        ):
            raise ValueError(f"{task_id}: public model artifact content is inconsistent")
        _validate_verdict(
            task_id,
            {
                "verifier_result": {
                    "rewards": {"reward": verifier.get("reward")}
                }
            },
            verifier,
        )
        receipt_keys = (
            "trial_config_sha256",
            "trial_lock_sha256",
            "trial_result_sha256",
            "trajectory_sha256",
            "provider_trace_source",
            "provider_trace_source_sha256",
            "provider_trace_sha256",
            "verdict_sha256",
        )
        if any(source_receipts.get(key) != trial.get(key) for key in receipt_keys):
            raise ValueError(f"{task_id}: source receipts disagree with the run manifest")
        if any(
            not isinstance(source_receipts.get(key), str)
            or SHA256_PATTERN.fullmatch(str(source_receipts[key])) is None
            for key in receipt_keys
            if key != "provider_trace_source"
        ):
            raise ValueError(f"{task_id}: source receipt hashes are malformed")
        trace_source = source_receipts.get("provider_trace_source")
        if (
            not isinstance(trace_source, str)
            or not trace_source.startswith("agent/sessions/")
            or not trace_source.endswith(".jsonl")
            or ".." in Path(trace_source).parts
        ):
            raise ValueError(f"{task_id}: provider trace is not an immutable Codex session")
        if (
            not isinstance(trial_id, str)
            or not trial_id
            or trial_id in trial_ids
            or not isinstance(trial_name, str)
            or not trial_name
            or trial_name in trial_names
            or not isinstance(task_checksum, str)
            or SHA256_PATTERN.fullmatch(task_checksum) is None
            or task_checksum in task_checksums
            or not isinstance(trial_lock_sha, str)
            or SHA256_PATTERN.fullmatch(trial_lock_sha) is None
            or trial_lock_sha in trial_locks
            or set(category_scores) != {str(row["key"]) for row in SCORING_CATEGORIES}
            or any(
                not isinstance(value, (int, float)) or isinstance(value, bool)
                for value in category_scores.values()
            )
            or set(tokens) != {"input", "cached", "output"}
            or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in tokens.values()
            )
            or not isinstance(trial.get("cost_usd"), (int, float))
            or isinstance(trial.get("cost_usd"), bool)
            or float(trial["cost_usd"]) < 0
        ):
            raise ValueError(f"{task_id}: public model trial receipt is malformed")
        seen.add(task_id)
        trial_ids.add(trial_id)
        trial_names.add(trial_name)
        task_checksums.add(task_checksum)
        trial_locks.add(trial_lock_sha)
        scores.append(float(trial["score"]))
        strict_passes.append(bool(trial["strict_pass"]))
        category_rows.append({key: float(value) for key, value in category_scores.items()})
        tool_calls.append(int(trial["tool_calls"]))
        successful_calls.append(int(trial["successful_tool_calls"]))
        failed_calls.append(int(trial["failed_tool_calls"]))
        token_rows.append({key: int(value) for key, value in tokens.items()})
        costs.append(float(trial["cost_usd"]))
    if expected_task_receipts is not None and seen != set(expected_task_receipts):
        raise ValueError("model run does not cover the current DealBench task set")
    if [str(row["task_id"]) for row in trials] != sorted(seen):
        raise ValueError("model run trials are not in canonical task order")
    recomputed_aggregate = {
        "task_count": EXPECTED_TASKS,
        "completed_tasks": EXPECTED_TASKS,
        "errored_tasks": 0,
        "retries": 0,
        "mean_score": round(statistics.fmean(scores), 2),
        "minimum_score": round(min(scores), 2),
        "maximum_score": round(max(scores), 2),
        "strict_passes": sum(strict_passes),
        "strict_pass_rate": round(sum(strict_passes) / EXPECTED_TASKS * 100, 2),
        "category_scores": {
            str(category["key"]): round(
                statistics.fmean(
                    row[str(category["key"])] for row in category_rows
                ),
                2,
            )
            for category in SCORING_CATEGORIES
        },
        "total_tool_calls": sum(tool_calls),
        "average_tool_calls": round(statistics.fmean(tool_calls), 2),
        "successful_tool_calls": sum(successful_calls),
        "failed_tool_calls": sum(failed_calls),
        "trace_coverage": EXPECTED_TASKS,
        "tokens": {
            key: sum(row[key] for row in token_rows)
            for key in ("input", "cached", "output")
        },
        "cost_usd": round(sum(costs), 8),
        "average_cost_usd": round(statistics.fmean(costs), 8),
    }
    if aggregate != recomputed_aggregate:
        raise ValueError("model run aggregate score does not reconcile to its trials")
    bindings = [
        {
            "task_id": row["task_id"],
            "harbor_task_digest": row["harbor_task_digest"],
            "trial_task_checksum": row["trial_task_checksum"],
            "trial_lock_sha256": row["trial_lock_sha256"],
            "trial_result_sha256": row["trial_result_sha256"],
            "trajectory_sha256": row["trajectory_sha256"],
            "provider_trace_source_sha256": row["provider_trace_source_sha256"],
            "provider_trace_sha256": row["provider_trace_sha256"],
            "verdict_sha256": row["verdict_sha256"],
            "artifact_sha256": row["artifact_sha256"],
            "score": row["score"],
            "strict_pass": row["strict_pass"],
        }
        for row in trials
    ]
    if _canonical_sha(bindings) != manifest.get("trial_bindings_sha256"):
        raise ValueError("model run trial-binding receipt does not match")
    tree_sha, files, size = manifest_digest(output_root / RUN_SLUG)
    if (
        tree_sha != manifest.get("artifact_tree_sha256")
        or files != manifest.get("artifact_files")
        or size != manifest.get("artifact_bytes")
    ):
        raise ValueError("model run artifact-tree receipt does not match")
    featured = manifest.get("featured_task_id")
    if featured not in seen or manifest.get("featured_artifact") != (
        f"{RUN_SLUG}/trials/{featured}.json"
    ):
        raise ValueError("model run featured trajectory is not bound to a ranked trial")
    featured_trial = next(row for row in trials if row["task_id"] == featured)
    if manifest.get("featured_artifact_sha256") != featured_trial.get(
        "artifact_sha256"
    ):
        raise ValueError("model run featured artifact hash does not match")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--expected-job-id")
    arguments = parser.parse_args()
    manifest = build_model_run(
        arguments.job_dir,
        release_root=arguments.release_root,
        output_root=arguments.output_root,
        expected_job_id=arguments.expected_job_id,
    )
    print(json.dumps(manifest["aggregate"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
