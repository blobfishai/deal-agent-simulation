#!/usr/bin/env python3
"""Seal exact-package Harbor oracle receipts for the five first-party releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from benchmark.harbor_receipts import (  # noqa: E402
    bind_trial_task,
    harbor_task_digest,
    validate_job_lock,
)

ORDER = [
    "counselbench-100",
    "salesbench-100",
    "devopsbench-100",
    "ledgerbench-100",
    "factorybench-100",
]
PUBLISH_IGNORED_SUFFIXES = (".pyc", ".pyo", ".swp", ".swo", "~")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_run(value: str) -> tuple[str, str, int, Path, Path, Path]:
    parts = value.split("=", 5)
    if len(parts) != 6:
        raise argparse.ArgumentTypeError(
            "expected slug=version=revision=release-directory=result.json=registry-task-directory"
        )
    slug, version, revision, release, result, registry_tasks = parts
    try:
        parsed_revision = int(revision)
    except ValueError as error:
        raise argparse.ArgumentTypeError("revision must be an integer") from error
    return (
        slug,
        version,
        parsed_revision,
        Path(release).expanduser().resolve(),
        Path(result).expanduser().resolve(),
        Path(registry_tasks).expanduser().resolve(),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_digest(root: Path) -> tuple[str, int, int]:
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.name != ".DS_Store"
        and not path.name.endswith(PUBLISH_IGNORED_SUFFIXES)
    )
    digest = hashlib.sha256()
    total_bytes = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        total_bytes += size
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), len(files), total_bytes


def json_stream_count(path: Path) -> int:
    """Validate a JSON or concatenated-JSON Oracle artifact without normalizing it."""

    raw = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    cursor = 0
    records = 0
    while cursor < len(raw):
        while cursor < len(raw) and raw[cursor].isspace():
            cursor += 1
        if cursor >= len(raw):
            break
        try:
            _, cursor = decoder.raw_decode(raw, cursor)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"{path.parent.parent.name}: invalid Oracle agent JSON at byte {error.pos}"
            ) from error
        records += 1
    if records == 0:
        raise ValueError(f"{path.parent.parent.name}: Oracle agent artifact is empty")
    return records


def oracle_execution_evidence(trial_dir: Path) -> dict[str, Any]:
    """Seal the Oracle agent output and independently written verifier artifacts."""

    agent_path = trial_dir / "agent" / "oracle.txt"
    verifier_dir = trial_dir / "verifier"
    if not agent_path.is_file() or not verifier_dir.is_dir():
        raise ValueError(f"{trial_dir.name}: Oracle execution artifacts are incomplete")
    json_records = json_stream_count(agent_path)
    trace_path = verifier_dir / "trace.json"
    report_path = verifier_dir / "report.json"
    reported_call_count: int | None = None
    reported_call_kind: str | None = None
    if trace_path.is_file():
        trace = read_json(trace_path).get("trace")
        if not isinstance(trace, list) or not trace or not all(
            isinstance(row, dict) for row in trace
        ):
            raise ValueError(f"{trial_dir.name}: Oracle verifier trace is empty or invalid")
        recorded_calls = len(trace)
        count_source = "verifier/trace.json#trace"
        primary_path = trace_path
    else:
        if json_records != 1:
            raise ValueError(
                f"{trial_dir.name}: multi-record Oracle output lacks a verifier trace"
            )
        agent = read_json(agent_path)
        if isinstance(agent.get("successful_tool_calls"), int) and not isinstance(
            agent.get("successful_tool_calls"), bool
        ):
            recorded_calls = int(agent["successful_tool_calls"])
            count_source = "agent/oracle.txt#successful_tool_calls"
            report_key = "successful_tool_calls"
        elif isinstance(agent.get("replayed_steps"), int) and not isinstance(
            agent.get("replayed_steps"), bool
        ):
            recorded_calls = int(agent["replayed_steps"])
            count_source = "agent/oracle.txt#replayed_steps"
            report_key = "n_tool_calls"
        else:
            raise ValueError(
                f"{trial_dir.name}: Oracle agent artifact lacks a call or replay count"
            )
        if recorded_calls <= 0:
            raise ValueError(f"{trial_dir.name}: Oracle agent recorded no execution steps")
        if not report_path.is_file():
            raise ValueError(
                f"{trial_dir.name}: Oracle count lacks an independent verifier report"
            )
        report = read_json(report_path)
        reported = report.get(report_key)
        if isinstance(reported, bool) or not isinstance(reported, int) or reported < 0:
            raise ValueError(
                f"{trial_dir.name}: verifier lacks a valid {report_key} call receipt"
            )
        if reported != recorded_calls:
            raise ValueError(
                f"{trial_dir.name}: Oracle and verifier call counts disagree "
                f"({recorded_calls} != {reported})"
            )
        reported_call_count = reported
        reported_call_kind = report_key
        primary_path = report_path
    verifier_sha256, verifier_files, verifier_bytes = manifest_digest(verifier_dir)
    return {
        "recordedCalls": recorded_calls,
        "countSource": count_source,
        "reportedCallCount": reported_call_count,
        "reportedCallKind": reported_call_kind,
        "agentArtifact": {
            "path": "agent/oracle.txt",
            "sha256": sha256_file(agent_path),
            "bytes": agent_path.stat().st_size,
            "jsonRecords": json_records,
        },
        "verifierArtifacts": {
            "path": "verifier",
            "manifestSha256": verifier_sha256,
            "files": verifier_files,
            "bytes": verifier_bytes,
            "primaryPath": primary_path.relative_to(trial_dir).as_posix(),
            "primarySha256": sha256_file(primary_path),
        },
    }


def validate_oracle_job_config(
    *, slug: str, job_dir: Path, tasks_path: Path
) -> dict[str, Any]:
    """Bind an Oracle run to one full release and the serial no-retry protocol."""

    config_path = job_dir / "config.json"
    if not config_path.is_file():
        raise ValueError(f"{slug}: Harbor job lacks config.json")
    config = read_json(config_path)
    datasets = config.get("datasets") or []
    configured_concurrency = config.get("n_concurrent_trials")
    if (
        config.get("job_name") != job_dir.name
        or configured_concurrency != 1
        or len(datasets) != 1
    ):
        raise ValueError(f"{slug}: Oracle job config is not the required serial run")
    configured_path = datasets[0].get("path")
    if (
        not isinstance(configured_path, str)
        or Path(configured_path).expanduser().resolve() != tasks_path
        or datasets[0].get("task_names") not in (None, [])
    ):
        raise ValueError(f"{slug}: Oracle job config is not bound to the full release")
    return {
        "jobConfigSha256": sha256_file(config_path),
        "nConcurrentTrials": configured_concurrency,
    }


def validate_registry_round_trip(
    source_tasks: Path,
    registry_tasks: Path,
    *,
    revision: int,
    expected_tasks: int = 100,
) -> dict[str, Any]:
    """Prove that one downloaded Harbor revision contains the executed bytes."""

    if not registry_tasks.is_dir():
        raise ValueError(
            f"Harbor revision {revision}: registry task directory does not exist: "
            f"{registry_tasks}"
        )

    def bindings(root: Path) -> tuple[dict[str, str], int, int]:
        task_dirs = sorted(path for path in root.iterdir() if path.is_dir())
        if len(task_dirs) != expected_tasks:
            raise ValueError(
                f"Harbor revision {revision}: found {len(task_dirs)} task directories "
                f"under {root}, expected {expected_tasks}"
            )
        rows: dict[str, str] = {}
        files = 0
        total_bytes = 0
        for task_dir in task_dirs:
            task_toml = task_dir / "task.toml"
            if not task_toml.is_file():
                raise ValueError(
                    f"Harbor revision {revision}: {task_dir} lacks task.toml"
                )
            task = tomllib.loads(task_toml.read_text(encoding="utf-8"))
            task_name = (task.get("task") or {}).get("name")
            if not isinstance(task_name, str) or not task_name or task_name in rows:
                raise ValueError(
                    f"Harbor revision {revision}: duplicate or invalid task identity "
                    f"under {root}: {task_name!r}"
                )
            digest, task_files, task_bytes = harbor_task_digest(task_dir)
            rows[task_name] = digest
            files += task_files
            total_bytes += task_bytes
        return rows, files, total_bytes

    source, source_files, source_bytes = bindings(source_tasks)
    downloaded, downloaded_files, downloaded_bytes = bindings(registry_tasks)
    if source != downloaded:
        missing = sorted(set(source) - set(downloaded))
        unexpected = sorted(set(downloaded) - set(source))
        mismatched = sorted(
            task_id
            for task_id in set(source) & set(downloaded)
            if source[task_id] != downloaded[task_id]
        )
        raise ValueError(
            f"Harbor revision {revision}: downloaded task bindings disagree with the "
            f"executed release (missing={missing}, unexpected={unexpected}, "
            f"mismatched={mismatched})"
        )
    if (source_files, source_bytes) != (downloaded_files, downloaded_bytes):
        raise ValueError(
            f"Harbor revision {revision}: downloaded aggregate task payload differs"
        )
    canonical = json.dumps(
        sorted(source.items()), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "revision": revision,
        "downloadedTasks": len(downloaded),
        "exactTaskDigests": True,
        "taskBindingsSha256": hashlib.sha256(canonical).hexdigest(),
        "publishableFiles": source_files,
        "publishableBytes": source_bytes,
    }


def summarize(
    slug: str,
    version: str,
    revision: int,
    release_path: Path,
    result_path: Path,
    registry_tasks_path: Path,
) -> dict[str, Any]:
    if not release_path.is_dir():
        raise ValueError(f"{slug}: release directory does not exist: {release_path}")
    build_path = release_path / "reports" / "build.json"
    build = read_json(build_path)
    if build.get("version") != version:
        raise ValueError(
            f"{slug}: release build version {build.get('version')!r} does not match {version!r}"
        )
    tasks_path = (release_path / "harbor" / "tasks").resolve()
    task_directories = sorted(
        path.resolve() for path in tasks_path.iterdir() if path.is_dir()
    )
    if len(task_directories) != 100:
        raise ValueError(
            f"{slug}: release has {len(task_directories)} Harbor tasks, expected 100"
        )
    job_config = validate_oracle_job_config(
        slug=slug,
        job_dir=result_path.parent,
        tasks_path=tasks_path,
    )

    result = read_json(result_path)
    job_id = result.get("id")
    if not isinstance(job_id, str) or not job_id:
        raise ValueError(f"{slug}: Harbor job lacks an immutable job id")
    evaluation = next(iter(result["stats"]["evals"].values()))
    metrics = evaluation["metrics"][0]
    passed = len(evaluation["reward_stats"]["reward"].get("1.0", []))
    if result["n_total_trials"] != 100 or result["stats"]["n_completed_trials"] != 100:
        raise ValueError(f"{slug}: exact Harbor suite is incomplete")
    if (
        passed != 100
        or evaluation["n_trials"] != 100
        or evaluation["n_errors"] != 0
        or result["stats"]["n_retries"] != 0
        or result["stats"]["n_running_trials"] != 0
        or result["stats"]["n_pending_trials"] != 0
        or result["stats"]["n_cancelled_trials"] != 0
    ):
        raise ValueError(f"{slug}: exact Harbor suite did not pass 100/100")
    mean_reward = metrics.get("reward", metrics.get("mean"))
    if mean_reward != 1 or ("passed" in metrics and metrics["passed"] != 1):
        raise ValueError(f"{slug}: Harbor oracle did not reach the exact ceiling")
    trial_results = sorted(
        path for path in result_path.parent.glob("*/result.json") if path.is_file()
    )
    if len(trial_results) != 100:
        raise ValueError(
            f"{slug}: found {len(trial_results)} trial receipts, expected 100"
        )

    trial_bindings: list[dict[str, Any]] = []
    trial_locks: list[dict[str, Any]] = []
    observed_task_paths: set[Path] = set()
    observed_task_names: set[str] = set()
    observed_task_checksums: set[str] = set()
    observed_task_digests: set[str] = set()
    observed_lock_hashes: set[str] = set()
    observed_agent_artifact_hashes: set[str] = set()
    observed_verifier_artifact_hashes: set[str] = set()
    recorded_call_counts: list[int] = []
    for trial_result_path in trial_results:
        trial = read_json(trial_result_path)
        rewards = trial.get("verifier_result", {}).get("rewards", {})
        if trial.get("exception_info") is not None:
            raise ValueError(
                f"{slug}: {trial_result_path.parent.name} contains an exception"
            )
        if rewards.get("reward") != 1 or rewards.get("passed", 1) != 1:
            raise ValueError(
                f"{slug}: {trial_result_path.parent.name} did not receive reward 1"
            )
        if (trial.get("config") or {}).get("job_id") != job_id:
            raise ValueError(
                f"{slug}: {trial_result_path.parent.name} belongs to another job"
            )
        resolved_task_path, binding, trial_lock = bind_trial_task(
            slug=slug,
            version=version,
            trial_dir=trial_result_path.parent,
            result=trial,
            tasks_path=tasks_path,
        )
        result_agent = (trial.get("agent_info") or {}).get("name")
        locked_agent = (trial_lock.get("agent") or {}).get("name")
        if result_agent != "oracle" or locked_agent != "oracle":
            raise ValueError(
                f"{slug}: {trial_result_path.parent.name} is not an Oracle run"
            )
        binding["trialResultSha256"] = sha256_file(trial_result_path)
        execution_evidence = oracle_execution_evidence(trial_result_path.parent)
        binding["executionEvidence"] = execution_evidence
        trial_locks.append(trial_lock)
        observed_task_paths.add(resolved_task_path)
        observed_task_names.add(str(binding["taskName"]))
        observed_task_checksums.add(str(binding["trialTaskChecksum"]))
        observed_task_digests.add(str(binding["harborTaskDigest"]))
        observed_lock_hashes.add(str(binding["lockSha256"]))
        observed_agent_artifact_hashes.add(
            str(execution_evidence["agentArtifact"]["sha256"])
        )
        observed_verifier_artifact_hashes.add(
            str(execution_evidence["verifierArtifacts"]["manifestSha256"])
        )
        recorded_call_counts.append(int(execution_evidence["recordedCalls"]))
        trial_bindings.append(binding)

    if observed_task_paths != set(task_directories):
        raise ValueError(
            f"{slug}: trial receipts do not cover the release's exact task set"
        )
    if not all(
        len(values) == 100
        for values in (
            observed_task_names,
            observed_task_checksums,
            observed_task_digests,
            observed_lock_hashes,
        )
    ):
        raise ValueError(
            f"{slug}: task names, digests, checksums, and locks must be unique"
        )
    job_lock = validate_job_lock(
        slug=slug,
        job_dir=result_path.parent,
        trial_locks=trial_locks,
    )
    if job_lock["nConcurrentTrials"] != job_config["nConcurrentTrials"]:
        raise ValueError(f"{slug}: Oracle job config and immutable lock disagree")

    canonical_bindings = json.dumps(
        sorted(trial_bindings, key=lambda item: item["taskId"]),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload_sha256, payload_files, payload_bytes = manifest_digest(tasks_path)
    registry_round_trip = validate_registry_round_trip(
        tasks_path,
        registry_tasks_path,
        revision=revision,
    )
    return {
        "slug": slug,
        "dataset": f"blobfishai/{slug}",
        "version": version,
        "revision": revision,
        "hubUrl": f"https://hub.harborframework.com/datasets/blobfishai/{slug}",
        "tasksAttempted": 100,
        "tasksPassed": 100,
        "meanReward": 1.0,
        "exceptions": 0,
        "retries": int(result["stats"]["n_retries"]),
        "runId": job_id,
        "harness": {"name": "Harbor", "version": job_lock["harborVersion"]},
        "resultSha256": sha256_file(result_path),
        "jobConfigSha256": job_config["jobConfigSha256"],
        "jobLockSha256": job_lock["jobLockSha256"],
        "nConcurrentTrials": job_lock["nConcurrentTrials"],
        "releaseBuildSha256": sha256_file(build_path),
        "harborTaskPayloadSha256": payload_sha256,
        "harborTaskPayloadFiles": payload_files,
        "harborTaskPayloadBytes": payload_bytes,
        "trialBindingsSha256": hashlib.sha256(canonical_bindings).hexdigest(),
        "registryRoundTrip": registry_round_trip,
        "distinctTaskNames": len(observed_task_names),
        "distinctHarborTaskDigests": len(observed_task_digests),
        "distinctTrialTaskChecksums": len(observed_task_checksums),
        "distinctTrialLocks": len(observed_lock_hashes),
        "oracleExecution": {
            "tasksWithBoundAgentArtifacts": len(recorded_call_counts),
            "tasksWithBoundVerifierArtifacts": len(recorded_call_counts),
            "distinctAgentArtifactDigests": len(observed_agent_artifact_hashes),
            "distinctVerifierArtifactDigests": len(
                observed_verifier_artifact_hashes
            ),
            "minimumRecordedCalls": min(recorded_call_counts),
            "maximumRecordedCalls": max(recorded_call_counts),
            "totalRecordedCalls": sum(recorded_call_counts),
        },
        "trialBindings": sorted(trial_bindings, key=lambda item: item["taskId"]),
        "disclosure": (
            "Exact-package Harbor oracle solvability control, bound to all task payloads "
            "with independently recomputed publisher digests, legacy checksums, and "
            "job/trial locks, plus hashed Oracle agent and verifier execution artifacts; "
            "not a model leaderboard result."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", type=parse_run, required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "benchmark" / "reports" / "first-party-harbor-oracle.json",
    )
    args = parser.parse_args()
    by_slug = {
        slug: summarize(slug, version, revision, release, result, registry_tasks)
        for slug, version, revision, release, result, registry_tasks in args.run
    }
    if sorted(by_slug) != sorted(ORDER):
        raise ValueError(f"expected exactly {ORDER}, received {sorted(by_slug)}")
    report = {
        "schemaVersion": "blobfish.first-party-harbor-oracle.v4",
        "observedAt": args.observed_at,
        "runs": [by_slug[slug] for slug in ORDER],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"runs": len(report["runs"]), "tasksPassed": 500}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
