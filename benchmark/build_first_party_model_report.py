#!/usr/bin/env python3
"""Build fail-closed, exact-release receipts for first-party model runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from benchmark.build_first_party_harbor_report import (
    manifest_digest,
    read_json,
    sha256_file,
)
from benchmark.harbor_receipts import bind_trial_task, validate_job_lock

ORDER = [
    "counselbench-100",
    "salesbench-100",
    "devopsbench-100",
    "ledgerbench-100",
    "factorybench-100",
]
ALLOWED_CONCURRENT_TRIALS = frozenset({1, 2, 3, 4})
REQUIRED_SETUP_TIMEOUT_MULTIPLIER = 3.0
RUNTIME_LOCKS_PATH = REPO_ROOT / "benchmark" / "model-runtime-locks.json"
EFFECTIVE_AGENT_RUNTIME_TARGET = "/home/agent/.nvm"
AGENT_RUNTIME_TARGETS = frozenset({"/root/.nvm", EFFECTIVE_AGENT_RUNTIME_TARGET})
MCP_CONTROL_PLANE_TOOLS = frozenset(
    {"list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource"}
)
SOURCE_MODEL_RUN_SCHEMA_VERSION = "factorybench.model-run.v1"
FACTORY_SOURCE_URL = "https://github.com/blobfishai/factory-agent-simulation"
SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "client_secret",
    "code_verifier",
    "cookie",
    "credential",
    "csrf",
    "oauth_code",
    "password",
    "private_key",
    "secret",
    "session_id",
    "token",
)
SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)(\b(?:access[_-]?token|api[_-]?key|authorization|client[_-]?secret|"
        r"code[_-]?verifier|password|refresh[_-]?token)\b\s*[:=]\s*[\"']?)[^\s,;\"'}]+"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{12,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bpat-[a-z0-9-]{2,12}-[A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(
        r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----.*?-----END(?: [A-Z]+)? PRIVATE KEY-----",
        re.DOTALL,
    ),
)
PRIVATE_PATH_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])/(?:Users|home)/[^/\s\"']+(?:/[^\s,;\"'}]*)?"),
    re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+(?:\\[^\s,;\"'}]*)?"),
)


def parse_run(value: str) -> tuple[str, str, int, Path, Path]:
    parts = value.split("=", 4)
    if len(parts) != 5:
        raise argparse.ArgumentTypeError(
            "expected slug=version=revision=release-directory=job-directory"
        )
    slug, version, revision, release, job = parts
    try:
        parsed_revision = int(revision)
    except ValueError as error:
        raise argparse.ArgumentTypeError("revision must be an integer") from error
    return (
        slug,
        version,
        parsed_revision,
        Path(release).expanduser().resolve(),
        Path(job).expanduser().resolve(),
    )


def scrub(value: Any, key: str = "") -> Any:
    lowered = key.casefold()
    if any(part in lowered for part in SENSITIVE_KEY_PARTS):
        return "<redacted>"
    if isinstance(value, dict):
        return {
            str(child_key): scrub(child, str(child_key))
            for child_key, child in value.items()
        }
    if isinstance(value, list):
        return [scrub(child) for child in value]
    if isinstance(value, str):
        for pattern in SENSITIVE_TEXT_PATTERNS:
            if pattern.groups:
                value = pattern.sub(r"\1<redacted>", value)
            else:
                value = pattern.sub("<redacted>", value)
        for pattern in PRIVATE_PATH_PATTERNS:
            value = pattern.sub("<redacted-home-path>", value)
    return value


def compact(value: Any, limit: int = 600) -> str:
    sanitized = scrub(value)
    if isinstance(sanitized, str):
        rendered = sanitized
    else:
        rendered = json.dumps(sanitized, ensure_ascii=False, sort_keys=True)
    rendered = " ".join(rendered.split())
    return rendered if len(rendered) <= limit else rendered[: limit - 1].rstrip() + "…"


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    """Commit a complete JSON receipt with one same-filesystem replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def agent_runtime_binding(
    job_config: dict[str, Any],
    *,
    locks_path: Path = RUNTIME_LOCKS_PATH,
) -> dict[str, Any]:
    """Bind the effective read-only agent runtime mount to a checked-in digest."""

    environment = job_config.get("environment")
    mounts = environment.get("mounts") if isinstance(environment, dict) else None
    if not isinstance(mounts, list):
        raise ValueError("model job must declare its agent runtime mounts")
    runtime_mounts = [
        mount
        for mount in mounts
        if isinstance(mount, dict) and mount.get("target") in AGENT_RUNTIME_TARGETS
    ]
    if (
        len(runtime_mounts) != len(mounts)
        or {mount.get("target") for mount in runtime_mounts} != AGENT_RUNTIME_TARGETS
    ):
        raise ValueError("model job must use only the exact sealed runtime target set")
    effective_mounts = [
        mount
        for mount in runtime_mounts
        if mount.get("target") == EFFECTIVE_AGENT_RUNTIME_TARGET
    ]
    if len(effective_mounts) != 1:
        raise ValueError(
            f"model job must use exactly one {EFFECTIVE_AGENT_RUNTIME_TARGET} runtime mount"
        )

    mount = effective_mounts[0]
    source = mount.get("source")
    runtime_targets = [str(runtime_mount.get("target")) for runtime_mount in runtime_mounts]
    if (
        not isinstance(source, str)
        or not source
        or len(set(runtime_targets)) != len(runtime_targets)
        or any(
            runtime_mount.get("type") != "bind"
            or runtime_mount.get("read_only") is not True
            or runtime_mount.get("source") != source
            for runtime_mount in runtime_mounts
        )
    ):
        raise ValueError(
            "model job agent runtime targets must be read-only bind mounts of one source"
        )
    runtime_root = Path(source).expanduser().resolve()
    if not runtime_root.is_dir():
        raise ValueError(
            "model job agent runtime source is not an inspectable directory"
        )

    agents = job_config.get("agents") or []
    if len(agents) != 1:
        raise ValueError("model job agent runtime cannot be bound without one agent")
    configured_agent = agents[0]
    agent_name = configured_agent.get("name")
    agent_version = (configured_agent.get("kwargs") or {}).get("version")
    locks = read_json(locks_path)
    if locks.get("schemaVersion") != "blobfish.agent-runtime-locks.v1":
        raise ValueError("unsupported agent runtime lock schema")
    candidates = [
        lock
        for lock in locks.get("runtimes") or []
        if lock.get("agent") == agent_name
        and lock.get("agentVersion") == agent_version
        and lock.get("mountTarget") == mount.get("target")
        and lock.get("mountTargets") == sorted(AGENT_RUNTIME_TARGETS)
        and isinstance(lock.get("nvmVersion"), str)
        and bool(lock["nvmVersion"])
    ]
    if len(candidates) != 1:
        raise ValueError("model job agent runtime has no unique checked-in lock")
    lock = candidates[0]
    required_paths = lock.get("requiredPaths") or []
    if not required_paths or not all(
        isinstance(relative, str) and (runtime_root / relative).is_file()
        for relative in required_paths
    ):
        raise ValueError("model job agent runtime lacks a required executable path")
    forbidden_paths = lock.get("forbiddenPaths") or []
    if any(
        not isinstance(relative, str)
        or not relative
        or (runtime_root / relative).exists()
        for relative in forbidden_paths
    ):
        raise ValueError("model job agent runtime contains a forbidden path")

    tree_sha256, files, total_bytes = manifest_digest(runtime_root)
    if (
        tree_sha256 != lock.get("treeSha256")
        or files != lock.get("files")
        or total_bytes != lock.get("bytes")
    ):
        raise ValueError("model job agent runtime disagrees with its checked-in lock")
    return {
        "id": lock["id"],
        "agent": lock["agent"],
        "agentVersion": lock["agentVersion"],
        "nodeVersion": lock["nodeVersion"],
        "nvmVersion": lock["nvmVersion"],
        "platform": lock["platform"],
        "mountTarget": lock["mountTarget"],
        "mountTargets": sorted(runtime_targets),
        "readOnly": True,
        "treeSha256": tree_sha256,
        "files": files,
        "bytes": total_bytes,
    }


def harbor_trajectory_trace(trajectory: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten Harbor's native agent trajectory into authenticated provider calls."""

    trace: list[dict[str, Any]] = []
    for step in trajectory.get("steps") or []:
        if not isinstance(step, dict):
            continue
        results = {
            row.get("source_call_id"): row
            for row in ((step.get("observation") or {}).get("results") or [])
            if isinstance(row, dict) and isinstance(row.get("source_call_id"), str)
        }
        for call in step.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            call_id = call.get("tool_call_id")
            tool = call.get("function_name")
            arguments = call.get("arguments")
            if (
                not isinstance(call_id, str)
                or not isinstance(tool, str)
                or not isinstance(arguments, dict)
            ):
                raise ValueError(
                    "Harbor trajectory contains an unbound provider tool call"
                )
            result = results.get(call_id)
            trace.append(
                {
                    "provider_call_id": call_id,
                    "tool": tool,
                    "arguments": arguments,
                    "result": result.get("content")
                    if result
                    else "No provider result recorded",
                    "success": call_succeeded(result) if result is not None else False,
                    "model": step.get("model_name"),
                }
            )
    return trace


def released_mcp_servers(task_dir: Path) -> set[str]:
    task_path = task_dir / "task.toml"
    task = tomllib.loads(task_path.read_text(encoding="utf-8"))
    rows = (task.get("environment") or {}).get("mcp_servers") or []
    if not isinstance(rows, list):
        raise ValueError(
            f"{task_dir.name}: task.toml has invalid MCP server declarations"
        )
    servers: set[str] = set()
    for row in rows:
        name = row.get("name") if isinstance(row, dict) else None
        if not isinstance(name, str) or not name or name in servers:
            raise ValueError(
                f"{task_dir.name}: task.toml has duplicate or invalid MCP server identity"
            )
        servers.add(name)
    return servers


def codex_session_trace(
    trial_dir: Path,
    *,
    allowed_servers: set[str] | None = None,
) -> tuple[list[dict[str, Any]], Path] | None:
    """Recover provider-native calls from Codex's immutable rollout event stream."""

    sessions_root = trial_dir / "agent" / "sessions"
    if not sessions_root.is_dir():
        return None

    trace: list[dict[str, Any]] = []
    contributing_sources: list[Path] = []
    for path in sorted(sessions_root.rglob("*.jsonl")):
        source_contributed = False
        with path.open("r", encoding="utf-8") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                if not raw_line.strip():
                    continue
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"{trial_dir.name}: invalid Codex event JSON at "
                        f"{path.relative_to(trial_dir)}:{line_number}"
                    ) from error
                payload = event.get("payload") or {}
                item = payload.get("item") or {}
                if not (
                    event.get("type") == "event_msg"
                    and payload.get("type") == "item_completed"
                    and item.get("type") == "McpToolCall"
                ):
                    continue
                call_id = item.get("id")
                server = item.get("server")
                tool = item.get("tool")
                arguments = item.get("arguments")
                if not all(
                    isinstance(value, str) and value
                    for value in (call_id, server, tool)
                ):
                    raise ValueError(
                        f"{trial_dir.name}: Codex MCP event lacks call, server, or tool identity"
                    )
                if allowed_servers is not None and server not in allowed_servers:
                    continue
                if not isinstance(arguments, dict):
                    raise ValueError(
                        f"{trial_dir.name}: Codex MCP event has non-object arguments"
                    )
                result = item.get("result")
                structured_result = (
                    result.get("structuredContent")
                    if isinstance(result, dict)
                    and isinstance(result.get("structuredContent"), dict)
                    else {}
                )
                status = str(item.get("status") or "").casefold()
                is_error = bool(
                    (result or {}).get("isError") if isinstance(result, dict) else False
                ) or bool(structured_result.get("isError"))
                success = status == "completed" and not is_error
                qualified_tool = (
                    tool if tool.startswith(f"{server}.") else f"{server}.{tool}"
                )
                if qualified_tool.rsplit(".", 1)[-1] in MCP_CONTROL_PLANE_TOOLS:
                    continue
                trace.append(
                    {
                        "provider_call_id": call_id,
                        "server": server,
                        "tool": qualified_tool,
                        "arguments": arguments,
                        "result": result if result is not None else {"status": status},
                        "success": success,
                        "mutation": item.get("readOnlyHint") is False,
                    }
                )
                source_contributed = True
        if source_contributed:
            contributing_sources.append(path)

    if not trace:
        return None
    if len(contributing_sources) != 1:
        raise ValueError(
            f"{trial_dir.name}: provider calls span {len(contributing_sources)} Codex "
            "session files; one immutable no-retry rollout was required"
        )
    return trace, contributing_sources[0]


def provider_trace(
    trial_dir: Path,
    trajectory: dict[str, Any] | None = None,
    *,
    allowed_servers: set[str] | None = None,
) -> tuple[list[dict[str, Any]], Path]:
    candidates = [
        trial_dir / "verifier" / "trace.json",
        trial_dir / "verifier" / "report.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        payload = read_json(path)
        trace = payload.get("trace")
        if trace is None and isinstance(payload.get("episode"), dict):
            trace = payload["episode"].get("trace")
        if (
            trace
            and isinstance(trace, list)
            and all(isinstance(row, dict) for row in trace)
        ):
            return trace, path
    codex_trace = codex_session_trace(
        trial_dir,
        allowed_servers=allowed_servers,
    )
    if codex_trace is not None:
        return codex_trace
    trajectory_path = trial_dir / "agent" / "trajectory.json"
    trajectory_payload = (
        trajectory if trajectory is not None else read_json(trajectory_path)
    )
    trace = harbor_trajectory_trace(trajectory_payload)
    if trace or (
        isinstance(trajectory_payload.get("steps"), list)
        and bool(trajectory_payload["steps"])
    ):
        return trace, trajectory_path
    raise ValueError(
        f"{trial_dir.name}: neither verifier nor Harbor trajectory exported provider calls"
    )


def final_agent_message(trajectory: dict[str, Any]) -> str:
    for step in reversed(trajectory.get("steps") or []):
        if (
            isinstance(step, dict)
            and step.get("source") == "agent"
            and isinstance(step.get("message"), str)
            and step["message"].strip()
        ):
            message = scrub(step["message"])
            if not isinstance(message, str):
                raise ValueError("Harbor trajectory final agent message is not text")
            return message.strip()
    raise ValueError("Harbor trajectory has no final agent message")


def strict_pass(trial_dir: Path, rewards: dict[str, Any], reward: float) -> bool:
    for filename in ("verdict.json", "report.json"):
        path = trial_dir / "verifier" / filename
        if not path.is_file():
            continue
        payload = read_json(path)
        for key in ("strict_pass", "passed", "pass"):
            if isinstance(payload.get(key), bool):
                return bool(payload[key])
    if isinstance(rewards.get("passed"), (int, float, bool)):
        return bool(rewards["passed"])
    return math.isclose(reward, 1.0, rel_tol=0, abs_tol=1e-12)


def is_mutation_call(row: dict[str, Any]) -> bool:
    tool = str(row.get("tool") or row.get("name") or "").casefold()
    return bool(row.get("mutation")) or any(
        token in tool
        for token in (
            ".create",
            ".send",
            ".update",
            "append",
            "approve",
            "close",
            "deploy",
            "insert",
            "merge",
            "promote",
            "resolve",
            "rollback",
            "write",
        )
    )


def call_succeeded(row: dict[str, Any]) -> bool:
    """Interpret common Harbor, MCP, and verifier success envelopes conservatively."""

    result = row.get("result") or row.get("observation")
    if isinstance(result, dict):
        if result.get("error") not in (None, "", False, []):
            return False
        for key in ("is_error", "isError"):
            if isinstance(result.get(key), bool) and result[key]:
                return False
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            for key in ("is_error", "isError"):
                if isinstance(structured.get(key), bool) and structured[key]:
                    return False
    for key in ("success", "ok"):
        if isinstance(row.get(key), bool):
            return bool(row[key])
    for key in ("is_error", "isError"):
        if isinstance(row.get(key), bool):
            return not bool(row[key])
    if row.get("error") not in (None, "", False, []):
        return False
    outcome = str(row.get("outcome") or row.get("status") or "").casefold()
    if outcome in {"error", "failed", "failure", "rejected"}:
        return False
    return True


def verifier_call_receipt(
    trial_dir: Path,
    *,
    trace: list[dict[str, Any]],
    trace_path: Path,
    trace_mode: str,
) -> dict[str, Any]:
    """Reconcile rollout calls with an independently written verifier artifact."""

    native = trace_mode == "provider-native"
    observed_total = len(trace) if native else 0
    observed_successful = sum(call_succeeded(row) for row in trace) if native else 0
    observed_failed = observed_total - observed_successful
    if trace_path.parent.name == "verifier":
        receipt_source = trace_path
        reported_total: int | None = observed_total
        reported_successful: int | None = observed_successful
        reported_failed: int | None = observed_failed
    else:
        verifier_trace_source = trial_dir / "verifier" / "trace.json"
        if verifier_trace_source.is_file():
            receipt_source = verifier_trace_source
            verifier_trace = read_json(receipt_source).get("trace")
            if not isinstance(verifier_trace, list) or not all(
                isinstance(row, dict) for row in verifier_trace
            ):
                raise ValueError(
                    f"{trial_dir.name}: verifier trace has an invalid call receipt"
                )
            reported_total = len(verifier_trace)
            reported_successful = sum(
                call_succeeded(row) for row in verifier_trace
            )
            reported_failed = reported_total - reported_successful

            def call_signature(row: dict[str, Any]) -> dict[str, Any]:
                arguments = row.get("arguments") or row.get("args") or {}
                if not isinstance(arguments, dict):
                    raise ValueError(
                        f"{trial_dir.name}: verifier/provider call has invalid arguments"
                    )
                return {
                    "tool": str(row.get("tool") or row.get("name") or ""),
                    "arguments": scrub(arguments),
                    "success": call_succeeded(row),
                }

            if native and sorted(
                json.dumps(
                    call_signature(row),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for row in verifier_trace
            ) != sorted(
                json.dumps(
                    call_signature(row),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for row in trace
            ):
                raise ValueError(
                    f"{trial_dir.name}: verifier and provider trace call identities disagree"
                )
        else:
            receipt_source = trial_dir / "verifier" / "report.json"
            if not receipt_source.is_file():
                raise ValueError(
                    f"{trial_dir.name}: native/session trace lacks an independent verifier call receipt"
                )
            report = read_json(receipt_source)
            values: dict[str, int | None] = {}
            for output_key, report_key in (
                ("total", "n_tool_calls"),
                ("successful", "successful_tool_calls"),
                ("failed", "failed_tool_calls"),
            ):
                value = report.get(report_key)
                if value is None:
                    values[output_key] = None
                    continue
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError(
                        f"{trial_dir.name}: verifier has an invalid {report_key} receipt"
                    )
                values[output_key] = value
            reported_total = values["total"]
            reported_successful = values["successful"]
            reported_failed = values["failed"]
            if all(value is None for value in values.values()):
                raise ValueError(
                    f"{trial_dir.name}: verifier report does not account for provider calls"
                )
        comparisons = (
            ("total", reported_total, observed_total),
            ("successful", reported_successful, observed_successful),
            ("failed", reported_failed, observed_failed),
        )
        mismatched = [
            f"{label}={reported} (trace={observed})"
            for label, reported, observed in comparisons
            if reported is not None and reported != observed
        ]
        if mismatched:
            raise ValueError(
                f"{trial_dir.name}: verifier and provider trace call counts disagree: "
                + ", ".join(mismatched)
            )
    return {
        "source": receipt_source.relative_to(trial_dir).as_posix(),
        "sha256": sha256_file(receipt_source),
        "observedProviderCalls": observed_total,
        "observedSuccessfulProviderCalls": observed_successful,
        "observedFailedProviderCalls": observed_failed,
        "reportedTotalCalls": reported_total,
        "reportedSuccessfulCalls": reported_successful,
        "reportedFailedCalls": reported_failed,
    }


def trace_events(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    observed_write = False
    for index, row in enumerate(trace, start=1):
        tool = str(row.get("tool") or row.get("name") or "unknown_tool")
        mutation = is_mutation_call(row)
        stage = "Act" if mutation else "Verify" if observed_write else "Investigate"
        success = call_succeeded(row)
        events.append(
            {
                "index": index,
                "stage": stage,
                "tool": tool,
                "server": row.get("server"),
                "arguments": scrub(row.get("arguments") or row.get("args") or {}),
                "outcome": "ok" if success else "error",
                "result": compact(
                    row.get("result") or row.get("observation") or "Recorded response"
                ),
            }
        )
        observed_write = observed_write or mutation
    return events


def load_source_model_run(
    release_path: Path,
    *,
    slug: str,
    version: str,
    job_id: str,
) -> tuple[Path, dict[str, Any]] | None:
    """Resolve the one source-repository receipt for this exact Harbor job."""

    model_runs_root = release_path / "model-runs"
    matches: list[tuple[Path, dict[str, Any]]] = []
    if model_runs_root.is_dir():
        for path in sorted(model_runs_root.glob("*.json")):
            payload = read_json(path)
            if (
                payload.get("schema_version") == SOURCE_MODEL_RUN_SCHEMA_VERSION
                and payload.get("benchmark_version") == version
                and payload.get("job_id") == job_id
            ):
                matches.append((path, payload))
    if len(matches) > 1:
        raise ValueError(f"{slug}: multiple source model receipts claim this Harbor job")
    if not matches:
        if slug == "factorybench-100":
            raise ValueError(
                f"{slug}: exact release lacks its source model-run receipt"
            )
        return None
    return matches[0]


def source_model_run_binding(
    source_receipt: tuple[Path, dict[str, Any]],
    *,
    release_path: Path,
    slug: str,
    job_id: str,
    trials: list[dict[str, Any]],
    featured_task_id: str,
    model_identity: dict[str, str],
    harbor_version: str,
    runtime_binding: dict[str, Any],
) -> dict[str, Any]:
    """Prove the v4 report and source/HF/Harbor v1 mirrors describe one run."""

    manifest_path, manifest = source_receipt
    source_trials = manifest.get("trials") or []
    source_model = manifest.get("model") or {}
    source_harness = manifest.get("harness") or {}
    source_overlay = manifest.get("runtime_overlay") or {}
    source_runtime = source_overlay.get("runtime") or {}
    source_mount = source_overlay.get("runtime_mount") or {}
    if (
        manifest.get("job_id") != job_id
        or not isinstance(manifest.get("run_slug"), str)
        or not manifest["run_slug"]
        or manifest.get("featured_task_id") != featured_task_id
        or not isinstance(source_trials, list)
        or len(source_trials) != 100
        or source_model
        != {
            "name": model_identity["name"],
            "provider": model_identity["provider"],
            "agent": model_identity["agent"],
            "agent_version": model_identity["agentVersion"],
            "reasoning_effort": model_identity["reasoningEffort"],
        }
        or source_harness != {"name": "Harbor", "version": harbor_version}
        or source_runtime.get("codex") != runtime_binding.get("agentVersion")
        or source_runtime.get("node") != runtime_binding.get("nodeVersion")
        or source_runtime.get("nvm") != runtime_binding.get("nvmVersion")
        or source_mount.get("id") != runtime_binding.get("id")
        or set(source_mount.get("targets") or [])
        != set(runtime_binding.get("mountTargets") or [])
        or source_mount.get("tree_sha256") != runtime_binding.get("treeSha256")
        or source_mount.get("files") != runtime_binding.get("files")
        or source_mount.get("bytes") != runtime_binding.get("bytes")
    ):
        raise ValueError(f"{slug}: source model receipt has inconsistent run identity")
    source_by_task = {
        str(trial.get("task_id")): trial
        for trial in source_trials
        if isinstance(trial, dict) and isinstance(trial.get("task_id"), str)
    }
    v4_by_task = {str(trial["taskId"]): trial for trial in trials}
    if len(source_by_task) != 100 or set(source_by_task) != set(v4_by_task):
        raise ValueError(f"{slug}: source and v4 receipts do not cover the same tasks")

    shared_rows: list[dict[str, Any]] = []
    for task_id in sorted(v4_by_task):
        source_trial = source_by_task[task_id]
        v4_trial = v4_by_task[task_id]
        source_hashes = source_trial.get("source_receipts") or {}
        source_row = {
            "taskId": task_id,
            "harborTaskDigest": source_trial.get("harbor_task_digest"),
            "trialTaskChecksum": source_trial.get("trial_task_checksum"),
            "lockSha256": source_trial.get("trial_lock_sha256"),
            "trialResultSha256": source_hashes.get("result_sha256"),
            "trajectorySha256": source_hashes.get("trajectory_sha256"),
            "verifierTraceSha256": source_hashes.get("trace_sha256"),
            "finalResponseSha256": source_trial.get("final_response_sha256"),
            "score": round(float(source_trial.get("score")), 6),
            "strictPass": source_trial.get("strict_pass"),
        }
        v4_row = {
            "taskId": task_id,
            "harborTaskDigest": v4_trial.get("harborTaskDigest"),
            "trialTaskChecksum": v4_trial.get("trialTaskChecksum"),
            "lockSha256": v4_trial.get("lockSha256"),
            "trialResultSha256": v4_trial.get("trialResultSha256"),
            "trajectorySha256": v4_trial.get("trajectorySha256"),
            "verifierTraceSha256": v4_trial.get("verifierTraceSha256"),
            "finalResponseSha256": v4_trial.get("finalResponseSha256"),
            "score": round(float(v4_trial.get("score")), 6),
            "strictPass": v4_trial.get("strictPass"),
        }
        if source_row != v4_row:
            raise ValueError(
                f"{slug}: source and v4 trial receipts disagree for {task_id}"
            )
        shared_rows.append(v4_row)

    run_slug = str(manifest["run_slug"])
    expected_manifest = release_path / "model-runs" / f"{run_slug}.json"
    if manifest_path.resolve() != expected_manifest.resolve():
        raise ValueError(f"{slug}: source model manifest path is not canonical")
    mirror_roots = (
        release_path / "model-runs",
        release_path / "huggingface" / "model-runs",
        release_path / "harbor" / "model-runs",
    )
    mirror_manifest_paths = [root / f"{run_slug}.json" for root in mirror_roots]
    if not all(path.is_file() for path in mirror_manifest_paths):
        raise ValueError(f"{slug}: source/Hugging Face/Harbor model manifests diverge")
    mirror_manifest_hashes = {sha256_file(path) for path in mirror_manifest_paths}
    if len(mirror_manifest_hashes) != 1:
        raise ValueError(f"{slug}: source/Hugging Face/Harbor model manifests diverge")
    mirror_artifact_receipts = [manifest_digest(root / run_slug) for root in mirror_roots]
    if len(set(mirror_artifact_receipts)) != 1:
        raise ValueError(f"{slug}: source/Hugging Face/Harbor model artifacts diverge")
    artifact_tree_sha256, artifact_files, artifact_bytes = mirror_artifact_receipts[0]
    if artifact_files != 101 or artifact_bytes <= 0:
        raise ValueError(f"{slug}: source model artifact tree is incomplete")
    featured_source = source_by_task[featured_task_id]
    featured_v4 = v4_by_task[featured_task_id]
    featured_artifact = featured_source.get("artifact")
    expected_artifact = f"{run_slug}/trials/{featured_task_id}.json"
    if featured_artifact != expected_artifact:
        raise ValueError(f"{slug}: featured source trial artifact path is not canonical")
    featured_artifact_path = release_path / "model-runs" / expected_artifact
    if not featured_artifact_path.is_file():
        raise ValueError(f"{slug}: featured source trial artifact is missing")
    harbor_bundle_path = release_path / "harbor" / "model-runs.json"
    if not harbor_bundle_path.is_file():
        raise ValueError(f"{slug}: Harbor model-run bundle is missing")
    bundled_trials: list[dict[str, Any]] = []
    for source_trial in source_trials:
        relative = source_trial.get("artifact")
        if not isinstance(relative, str):
            raise ValueError(f"{slug}: source trial artifact path is invalid")
        source_artifact = (release_path / "model-runs" / relative).resolve()
        if (
            (release_path / "model-runs").resolve() not in source_artifact.parents
            or not source_artifact.is_file()
        ):
            raise ValueError(f"{slug}: source trial artifact escapes its release")
        bundled_trials.append(
            {
                "path": f"model-runs/{relative}",
                "record": read_json(source_artifact),
            }
        )
    runtime_relative = source_overlay.get("artifact")
    if not isinstance(runtime_relative, str):
        raise ValueError(f"{slug}: source runtime-overlay artifact path is invalid")
    runtime_artifact = (release_path / "model-runs" / runtime_relative).resolve()
    if (
        (release_path / "model-runs").resolve() not in runtime_artifact.parents
        or not runtime_artifact.is_file()
    ):
        raise ValueError(f"{slug}: source runtime-overlay artifact escapes its release")
    expected_harbor_bundle = {
        "schema_version": "factorybench.harbor-model-runs.v1",
        "benchmark": manifest.get("benchmark"),
        "benchmark_version": manifest.get("benchmark_version"),
        "runs": [
            {
                "manifest_path": f"model-runs/{run_slug}.json",
                "manifest": manifest,
                "trial_artifacts": bundled_trials,
                "runtime_overlay_artifact": {
                    "path": f"model-runs/{runtime_relative}",
                    "record": read_json(runtime_artifact),
                },
            }
        ],
    }
    if read_json(harbor_bundle_path) != expected_harbor_bundle:
        raise ValueError(f"{slug}: Harbor model-run bundle diverges from source artifacts")
    return {
        "schemaVersion": "blobfish.source-model-run-binding.v1",
        "runSlug": run_slug,
        "jobId": job_id,
        "taskCount": 100,
        "manifestArtifact": f"model-runs/{run_slug}.json",
        "manifestSha256": sha256_file(manifest_path),
        "mirrorCount": 3,
        "artifactTreeSha256": artifact_tree_sha256,
        "artifactFiles": artifact_files,
        "artifactBytes": artifact_bytes,
        "harborModelRunBundleArtifact": "model-runs.json",
        "harborModelRunBundleSha256": sha256_file(harbor_bundle_path),
        "harborModelRunBundleBytes": harbor_bundle_path.stat().st_size,
        "sourceManifestUrl": f"{FACTORY_SOURCE_URL}/blob/main/model_runs/{run_slug}.json",
        "sharedTrialBindingsSha256": canonical_json_sha256(shared_rows),
        "featuredTaskId": featured_task_id,
        "featuredTrajectorySha256": featured_v4["trajectorySha256"],
        "featuredVerifierTraceSha256": featured_v4["verifierTraceSha256"],
        "featuredFinalResponseSha256": featured_v4["finalResponseSha256"],
        "featuredArtifact": f"model-runs/{expected_artifact}",
        "featuredArtifactSha256": sha256_file(featured_artifact_path),
        "featuredArtifactUrl": f"{FACTORY_SOURCE_URL}/blob/main/model_runs/{expected_artifact}",
    }


def summarize(
    slug: str,
    version: str,
    revision: int,
    release_path: Path,
    job_dir: Path,
    *,
    harbor_version: str,
    runtime_locks_path: Path = RUNTIME_LOCKS_PATH,
) -> dict[str, Any]:
    build_path = release_path / "reports" / "build.json"
    build = read_json(build_path)
    if build.get("version") != version:
        raise ValueError(f"{slug}: supplied version does not match reports/build.json")
    tasks_path = (release_path / "harbor" / "tasks").resolve()
    released_tasks = sorted(
        path.resolve() for path in tasks_path.iterdir() if path.is_dir()
    )
    if len(released_tasks) != 100:
        raise ValueError(f"{slug}: exact release must contain 100 Harbor tasks")

    job_config_path = job_dir / "config.json"
    job_config = read_json(job_config_path)
    configured_agents = job_config.get("agents") or []
    configured_datasets = job_config.get("datasets") or []
    configured_concurrency = job_config.get("n_concurrent_trials")
    setup_timeout_multiplier = job_config.get("agent_setup_timeout_multiplier")
    if (
        job_config.get("job_name") != job_dir.name
        or len(configured_agents) != 1
        or len(configured_datasets) != 1
        or isinstance(configured_concurrency, bool)
        or configured_concurrency not in ALLOWED_CONCURRENT_TRIALS
        or not isinstance(setup_timeout_multiplier, (int, float))
        or isinstance(setup_timeout_multiplier, bool)
        or not math.isclose(
            float(setup_timeout_multiplier),
            REQUIRED_SETUP_TIMEOUT_MULTIPLIER,
            rel_tol=0,
            abs_tol=1e-12,
        )
    ):
        raise ValueError(
            f"{slug}: model job config disagrees with the required bounded setup-3x "
            "execution policy"
        )
    runtime_binding = agent_runtime_binding(job_config, locks_path=runtime_locks_path)
    configured_dataset_path = configured_datasets[0].get("path")
    if (
        not isinstance(configured_dataset_path, str)
        or Path(configured_dataset_path).expanduser().resolve() != tasks_path
        or configured_datasets[0].get("task_names") not in (None, [])
    ):
        raise ValueError(
            f"{slug}: model job config is not bound to the full release task set"
        )

    job_path = job_dir / "result.json"
    job = read_json(job_path)
    job_id = job.get("id")
    if (
        not isinstance(job_id, str)
        or not job_id
        or not isinstance(job.get("started_at"), str)
        or not job["started_at"]
        or not isinstance(job.get("finished_at"), str)
        or not job["finished_at"]
    ):
        raise ValueError(f"{slug}: model job lacks immutable id and timing receipts")
    stats = job.get("stats") or {}
    if (
        job.get("n_total_trials") != 100
        or stats.get("n_completed_trials") != 100
        or stats.get("n_errored_trials") != 0
        or stats.get("n_running_trials") != 0
        or stats.get("n_pending_trials") != 0
        or stats.get("n_cancelled_trials") != 0
        or stats.get("n_retries") != 0
    ):
        raise ValueError(f"{slug}: model job is not a clean 100-task run")
    source_receipt = load_source_model_run(
        release_path,
        slug=slug,
        version=version,
        job_id=job_id,
    )
    if slug == "factorybench-100" and build.get("model_run_count") != 1:
        raise ValueError(
            f"{slug}: release build must contain exactly one source model run"
        )

    trial_dirs = sorted(
        path
        for path in job_dir.iterdir()
        if path.is_dir() and (path / "result.json").is_file()
    )
    if len(trial_dirs) != 100:
        raise ValueError(
            f"{slug}: found {len(trial_dirs)} trial receipts, expected 100"
        )

    trials: list[dict[str, Any]] = []
    trial_locks: list[dict[str, Any]] = []
    trial_ids: set[str] = set()
    task_paths: set[Path] = set()
    task_names: set[str] = set()
    task_checksums: set[str] = set()
    task_digests: set[str] = set()
    lock_hashes: set[str] = set()
    agents: set[str] = set()
    agent_versions: set[str] = set()
    models: set[str] = set()
    providers: set[str] = set()
    reasoning_efforts: set[str] = set()
    reasoning_summaries: set[str] = set()
    web_search_modes: set[str] = set()
    trial_dir_by_task: dict[str, Path] = {}
    final_message_by_task: dict[str, str] = {}
    mcp_servers_by_task: dict[str, set[str]] = {}

    for trial_dir in trial_dirs:
        result_path = trial_dir / "result.json"
        result = read_json(result_path)
        if result.get("exception_info") is not None:
            raise ValueError(f"{slug}: {trial_dir.name} contains an exception")
        trial_id = result.get("id")
        if (
            not isinstance(trial_id, str)
            or not trial_id
            or trial_id in trial_ids
            or result.get("trial_name") != trial_dir.name
            or not isinstance(result.get("started_at"), str)
            or not result["started_at"]
            or not isinstance(result.get("finished_at"), str)
            or not result["finished_at"]
        ):
            raise ValueError(
                f"{slug}: {trial_dir.name} lacks unique execution identity and timing"
            )
        trial_ids.add(trial_id)
        rewards = (result.get("verifier_result") or {}).get("rewards") or {}
        reward_value = rewards.get("reward")
        if (
            not isinstance(reward_value, (int, float))
            or not 0 <= float(reward_value) <= 1
        ):
            raise ValueError(
                f"{slug}: {trial_dir.name} has an invalid deterministic reward"
            )
        reward = float(reward_value)
        if (result.get("config") or {}).get("job_id") != job_id:
            raise ValueError(f"{slug}: {trial_dir.name} belongs to another job")
        resolved_task, task_binding, trial_lock = bind_trial_task(
            slug=slug,
            version=version,
            trial_dir=trial_dir,
            result=result,
            tasks_path=tasks_path,
        )
        task_name = str(task_binding["taskName"])
        task_checksum = str(task_binding["trialTaskChecksum"])

        info = result.get("agent_info") or {}
        model_info = info.get("model_info") or {}
        config_agent = (result.get("config") or {}).get("agent") or {}
        config_kwargs = config_agent.get("kwargs") or {}
        reasoning_effort = config_kwargs.get("reasoning_effort")
        reasoning_summary = config_kwargs.get("reasoning_summary")
        web_search = config_kwargs.get("web_search")
        trajectory_path = trial_dir / "agent" / "trajectory.json"
        trajectory = read_json(trajectory_path)
        trajectory_agent = trajectory.get("agent") or {}
        agent_name = str(info.get("name") or trajectory_agent.get("name") or "")
        agent_version = str(
            info.get("version") or trajectory_agent.get("version") or ""
        )
        model_name = str(
            model_info.get("name") or trajectory_agent.get("model_name") or ""
        )
        provider = str(model_info.get("provider") or "")
        if not all(
            (
                agent_name,
                agent_version,
                model_name,
                provider,
                reasoning_effort,
                reasoning_summary,
                web_search,
            )
        ):
            raise ValueError(f"{slug}: {trial_dir.name} lacks pinned model metadata")
        if web_search != "disabled":
            raise ValueError(
                f"{slug}: {trial_dir.name} model run is not closed-sandbox"
            )
        locked_agent = trial_lock.get("agent") or {}
        locked_kwargs = locked_agent.get("kwargs") or {}
        if (
            locked_agent.get("name") != agent_name
            or locked_agent.get("model_name") != model_name
            or locked_kwargs.get("reasoning_effort") != reasoning_effort
            or locked_kwargs.get("reasoning_summary") != reasoning_summary
            or locked_kwargs.get("web_search") != web_search
            or config_agent.get("name") != agent_name
            or config_agent.get("model_name") != model_name
        ):
            raise ValueError(
                f"{slug}: {trial_dir.name} model metadata disagrees with its lock"
            )

        task_mcp_servers = released_mcp_servers(resolved_task)
        trace, trace_path = provider_trace(
            trial_dir,
            trajectory,
            allowed_servers=task_mcp_servers,
        )
        trace_source = trace_path.relative_to(trial_dir).as_posix()
        trace_mode = (
            "harbor-agent-fallback"
            if trace_path == trajectory_path
            else "provider-native"
        )
        successful_calls = sum(call_succeeded(row) for row in trace)
        rendered_trace = trace_events(trace)
        call_receipt = verifier_call_receipt(
            trial_dir,
            trace=trace,
            trace_path=trace_path,
            trace_mode=trace_mode,
        )
        verifier_manifest_sha256, verifier_files, verifier_bytes = manifest_digest(
            trial_dir / "verifier"
        )
        if verifier_files <= 0 or verifier_bytes <= 0:
            raise ValueError(f"{slug}: {trial_dir.name} lacks verifier artifacts")
        evidence_reads = sum(
            call_succeeded(row)
            and not is_mutation_call(row)
            and "submit_answer"
            not in str(row.get("tool") or row.get("name") or "").casefold()
            for row in trace
        )
        agent_result = result.get("agent_result") or {}
        cost_usd = agent_result.get("cost_usd")
        if cost_usd is not None and (
            isinstance(cost_usd, bool)
            or not isinstance(cost_usd, (int, float))
            or float(cost_usd) < 0
        ):
            raise ValueError(f"{slug}: {trial_dir.name} has an invalid cost receipt")
        token_receipt = {
            "input": agent_result.get("n_input_tokens"),
            "cached": agent_result.get("n_cache_tokens"),
            "output": agent_result.get("n_output_tokens"),
        }
        for token_kind, token_count in token_receipt.items():
            if token_count is not None and (
                isinstance(token_count, bool)
                or not isinstance(token_count, int)
                or token_count < 0
            ):
                raise ValueError(
                    f"{slug}: {trial_dir.name} has an invalid {token_kind} token receipt"
                )
        final_response = final_agent_message(trajectory)
        trial = {
            "trialId": trial_id,
            "taskId": resolved_task.name,
            "taskName": task_name,
            "harborTaskDigest": task_binding["harborTaskDigest"],
            "trialTaskChecksum": task_checksum,
            "lockSha256": task_binding["lockSha256"],
            "publishedFileCount": task_binding["publishedFileCount"],
            "publishedBytes": task_binding["publishedBytes"],
            "score": round(reward * 100, 6),
            "strictPass": strict_pass(trial_dir, rewards, reward),
            "toolCalls": len(trace),
            "evidenceReads": evidence_reads,
            "successfulToolCalls": successful_calls,
            "rejectedToolCalls": len(trace) - successful_calls,
            "costUsd": float(cost_usd) if cost_usd is not None else None,
            "tokens": token_receipt,
            "startedAt": result.get("started_at"),
            "finishedAt": result.get("finished_at"),
            "trialResultSha256": sha256_file(result_path),
            "trajectorySha256": sha256_file(trajectory_path),
            "finalResponseSha256": canonical_json_sha256(final_response),
            "verifierTraceSha256": (
                sha256_file(trial_dir / "verifier" / "trace.json")
                if (trial_dir / "verifier" / "trace.json").is_file()
                else None
            ),
            "providerTraceSha256": sha256_file(trace_path),
            "providerTraceSource": trace_source,
            "traceMode": trace_mode,
            "traceEventsSha256": canonical_json_sha256(rendered_trace),
            "providerNativeToolCalls": call_receipt["observedProviderCalls"],
            "providerNativeSuccessfulCalls": call_receipt[
                "observedSuccessfulProviderCalls"
            ],
            "providerNativeFailedCalls": call_receipt["observedFailedProviderCalls"],
            "verifierCallReceipt": call_receipt,
            "verifierCallReceiptSha256": canonical_json_sha256(call_receipt),
            "verifierArtifactManifestSha256": verifier_manifest_sha256,
            "verifierArtifactFiles": verifier_files,
            "verifierArtifactBytes": verifier_bytes,
        }
        trials.append(trial)
        trial_dir_by_task[resolved_task.name] = trial_dir
        mcp_servers_by_task[resolved_task.name] = task_mcp_servers
        final_message_by_task[resolved_task.name] = final_response
        task_paths.add(resolved_task)
        task_names.add(task_name)
        task_checksums.add(task_checksum)
        task_digests.add(str(task_binding["harborTaskDigest"]))
        lock_hashes.add(str(task_binding["lockSha256"]))
        trial_locks.append(trial_lock)
        agents.add(agent_name)
        agent_versions.add(agent_version)
        models.add(model_name)
        providers.add(provider)
        reasoning_efforts.add(str(reasoning_effort))
        reasoning_summaries.add(str(reasoning_summary))
        web_search_modes.add(str(web_search))

    if task_paths != set(released_tasks):
        raise ValueError(
            f"{slug}: model trials do not cover the exact release task set"
        )
    if len(trial_ids) != 100:
        raise ValueError(f"{slug}: model trials do not have 100 unique immutable ids")
    if not all(
        len(values) == 100
        for values in (task_names, task_checksums, task_digests, lock_hashes)
    ):
        raise ValueError(
            f"{slug}: task names, digests, checksums, and locks must be unique"
        )
    if not all(
        len(values) == 1
        for values in (
            agents,
            agent_versions,
            models,
            providers,
            reasoning_efforts,
            reasoning_summaries,
            web_search_modes,
        )
    ):
        raise ValueError(
            f"{slug}: model, agent, provider, and reasoning settings must be pinned"
        )
    job_lock = validate_job_lock(
        slug=slug,
        job_dir=job_dir,
        trial_locks=trial_locks,
        expected_harbor_version=harbor_version,
    )
    configured_agent = configured_agents[0]
    if (
        configured_agent.get("name") != next(iter(agents))
        or configured_agent.get("model_name") != next(iter(models))
        or (configured_agent.get("kwargs") or {})
        != ((trial_locks[0].get("agent") or {}).get("kwargs") or {})
        or job_lock.get("nConcurrentTrials") != configured_concurrency
    ):
        raise ValueError(
            f"{slug}: model job config disagrees with its immutable trial locks"
        )

    scores = [float(trial["score"]) for trial in trials]
    if not any(score > 0 for score in scores):
        raise ValueError(f"{slug}: model run has no positive task FactoryScore")
    calls = [int(trial["toolCalls"]) for trial in trials]
    costs = [
        float(trial["costUsd"]) for trial in trials if trial["costUsd"] is not None
    ]
    native_trace_tasks = sum(
        trial["traceMode"] == "provider-native" for trial in trials
    )
    fallback_trace_tasks = len(trials) - native_trace_tasks
    native_tool_calls = sum(int(trial["providerNativeToolCalls"]) for trial in trials)
    native_successful_calls = sum(
        int(trial["providerNativeSuccessfulCalls"]) for trial in trials
    )
    native_failed_calls = sum(
        int(trial["providerNativeFailedCalls"]) for trial in trials
    )
    if len(costs) not in (0, len(trials)):
        raise ValueError(f"{slug}: model job has partial cost reporting")
    token_coverage = {
        key: sum(trial["tokens"][key] is not None for trial in trials)
        for key in ("input", "cached", "output")
    }
    if any(count not in (0, len(trials)) for count in token_coverage.values()):
        raise ValueError(f"{slug}: model job has partial token reporting")
    mean_score = statistics.mean(scores)
    evaluations = stats.get("evals") or {}
    if len(evaluations) != 1:
        raise ValueError(f"{slug}: model job must contain one aggregate evaluation")
    evaluation = next(iter(evaluations.values()))
    metrics = evaluation.get("metrics") or []
    if (
        evaluation.get("n_trials") != 100
        or evaluation.get("n_errors") != 0
        or len(metrics) != 1
    ):
        raise ValueError(f"{slug}: model aggregate evaluation is incomplete")
    aggregate_reward = metrics[0].get("reward", metrics[0].get("mean"))
    if not isinstance(aggregate_reward, (int, float)) or not math.isclose(
        float(aggregate_reward) * 100,
        mean_score,
        rel_tol=0,
        abs_tol=1e-6,
    ):
        raise ValueError(
            f"{slug}: aggregate reward does not match the 100 trial receipts"
        )
    reward_buckets = (evaluation.get("reward_stats") or {}).get("reward") or {}
    aggregate_trial_names = {
        str(trial_name) for bucket in reward_buckets.values() for trial_name in bucket
    }
    if aggregate_trial_names != {path.name for path in trial_dirs}:
        raise ValueError(
            f"{slug}: aggregate reward buckets do not bind every trial receipt"
        )
    featured_pool = [
        trial
        for trial in trials
        if trial["traceMode"] == "provider-native" and int(trial["toolCalls"]) > 0
    ]
    if not featured_pool:
        featured_pool = [
            trial for trial in trials if int(trial["toolCalls"]) > 0
        ] or trials
    if source_receipt is not None:
        source_featured_task_id = source_receipt[1].get("featured_task_id")
        featured = next(
            (
                trial
                for trial in trials
                if trial["taskId"] == source_featured_task_id
            ),
            None,
        )
        if featured is None:
            raise ValueError(f"{slug}: source receipt selects an unknown featured task")
    else:
        featured = min(
            featured_pool,
            key=lambda trial: (
                abs(float(trial["score"]) - mean_score),
                trial["taskId"],
            ),
        )
    featured_trace, _ = provider_trace(
        trial_dir_by_task[str(featured["taskId"])],
        allowed_servers=mcp_servers_by_task[str(featured["taskId"])],
    )
    featured_events = trace_events(featured_trace)
    if canonical_json_sha256(featured_events) != featured["traceEventsSha256"]:
        raise ValueError(
            f"{slug}: featured provider trace changed after its trial receipt was bound"
        )
    payload_sha256, payload_files, payload_bytes = manifest_digest(tasks_path)
    bindings = json.dumps(
        [
            {
                "trialId": trial["trialId"],
                "taskId": trial["taskId"],
                "harborTaskDigest": trial["harborTaskDigest"],
                "trialTaskChecksum": trial["trialTaskChecksum"],
                "lockSha256": trial["lockSha256"],
                "trialResultSha256": trial["trialResultSha256"],
                "trajectorySha256": trial["trajectorySha256"],
                "finalResponseSha256": trial["finalResponseSha256"],
                "verifierTraceSha256": trial["verifierTraceSha256"],
                "providerTraceSha256": trial["providerTraceSha256"],
                "providerTraceSource": trial["providerTraceSource"],
                "traceMode": trial["traceMode"],
                "traceEventsSha256": trial["traceEventsSha256"],
                "providerNativeToolCalls": trial["providerNativeToolCalls"],
                "verifierCallReceiptSha256": trial["verifierCallReceiptSha256"],
                "verifierArtifactManifestSha256": trial[
                    "verifierArtifactManifestSha256"
                ],
                "score": trial["score"],
                "strictPass": trial["strictPass"],
            }
            for trial in sorted(trials, key=lambda item: item["taskId"])
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    source_binding = (
        source_model_run_binding(
            source_receipt,
            release_path=release_path,
            slug=slug,
            job_id=job_id,
            trials=trials,
            featured_task_id=str(featured["taskId"]),
            model_identity={
                "name": next(iter(models)),
                "provider": next(iter(providers)),
                "agent": next(iter(agents)),
                "agentVersion": next(iter(agent_versions)),
                "reasoningEffort": next(iter(reasoning_efforts)),
            },
            harbor_version=job_lock["harborVersion"],
            runtime_binding=runtime_binding,
        )
        if source_receipt is not None
        else None
    )
    return {
        "slug": slug,
        "dataset": f"blobfishai/{slug}",
        "version": version,
        "revision": revision,
        "runId": job_id,
        "startedAt": job.get("started_at"),
        "finishedAt": job.get("finished_at"),
        "selection": "All 100 tasks in the exact published release; no retries.",
        "model": {
            "name": next(iter(models)),
            "provider": next(iter(providers)),
            "agent": next(iter(agents)),
            "agentVersion": next(iter(agent_versions)),
            "reasoningEffort": next(iter(reasoning_efforts)),
            "reasoningSummary": next(iter(reasoning_summaries)),
            "webSearch": next(iter(web_search_modes)),
        },
        "harness": {"name": "Harbor", "version": job_lock["harborVersion"]},
        "agentRuntime": runtime_binding,
        "executionPolicy": {
            "concurrentTrials": configured_concurrency,
            "agentSetupTimeoutMultiplier": float(setup_timeout_multiplier),
            "maxRetries": 0,
            "attemptsPerTask": 1,
        },
        "executionBoundary": {
            "scoringSurface": "released-task-state-and-answer",
            "builtInWebSearch": "disabled",
            "osLevelNoEgress": "not-claimed",
        },
        "aggregate": {
            "tasks": 100,
            "meanScore": round(mean_score, 2),
            "strictPasses": sum(bool(trial["strictPass"]) for trial in trials),
            "strictPassRate": round(
                sum(bool(trial["strictPass"]) for trial in trials) / len(trials) * 100,
                2,
            ),
            "averageToolCalls": round(statistics.mean(calls), 2),
            "providerNativeTraceTasks": native_trace_tasks,
            "harborAgentFallbackTasks": fallback_trace_tasks,
            "providerNativeToolCalls": native_tool_calls,
            "providerNativeSuccessfulCalls": native_successful_calls,
            "providerNativeFailedCalls": native_failed_calls,
            "averageCostUsd": round(statistics.mean(costs), 6) if costs else None,
            "totalCostUsd": round(sum(costs), 6) if costs else None,
            "costCoverageTasks": len(costs),
            "tokenCoverageTasks": token_coverage,
        },
        "releaseBinding": {
            "releaseBuildSha256": sha256_file(build_path),
            "harborTaskPayloadSha256": payload_sha256,
            "harborTaskPayloadFiles": payload_files,
            "harborTaskPayloadBytes": payload_bytes,
            "trialBindingsSha256": hashlib.sha256(bindings).hexdigest(),
            "sourceModelRun": source_binding,
            "verifierArtifactFiles": sum(
                int(trial["verifierArtifactFiles"]) for trial in trials
            ),
            "verifierArtifactBytes": sum(
                int(trial["verifierArtifactBytes"]) for trial in trials
            ),
            "distinctVerifierArtifactDigests": len(
                {str(trial["verifierArtifactManifestSha256"]) for trial in trials}
            ),
            "distinctTaskNames": len(task_names),
            "distinctHarborTaskDigests": len(task_digests),
            "distinctTrialTaskChecksums": len(task_checksums),
            "distinctTrialLocks": len(lock_hashes),
            "jobResultSha256": sha256_file(job_path),
            "jobConfigSha256": sha256_file(job_config_path),
            "jobLockSha256": job_lock["jobLockSha256"],
            "jobLockSchema": job_lock["jobLockSchema"],
            "trialLockSchema": job_lock["trialLockSchema"],
        },
        "featuredTrajectory": {
            "taskId": featured["taskId"],
            "score": featured["score"],
            "strictPass": featured["strictPass"],
            "toolCalls": featured["toolCalls"],
            "traceMode": featured["traceMode"],
            "traceSource": featured["providerTraceSource"],
            "eventsSha256": featured["traceEventsSha256"],
            "events": featured_events,
            "finalResponseSha256": featured["finalResponseSha256"],
            "finalResponse": final_message_by_task[str(featured["taskId"])],
            "sourceManifestUrl": (
                source_binding["sourceManifestUrl"] if source_binding else None
            ),
            "sourceManifest": (
                source_binding["manifestArtifact"] if source_binding else None
            ),
            "sourceArtifactUrl": (
                source_binding["featuredArtifactUrl"] if source_binding else None
            ),
            "sourceArtifact": (
                source_binding["featuredArtifact"] if source_binding else None
            ),
        },
        "trials": sorted(trials, key=lambda trial: trial["taskId"]),
        "disclosure": (
            "Full 100/100-task version-pinned model run derived from the exact Harbor "
            "trial artifacts; "
            "no oracle or deterministic-control trials are ranked. Scoring observes only "
            "released task state and answers, Codex built-in web search was disabled, and "
            "OS-level no-egress isolation is not claimed. Provider-native trace provenance "
            f"is reported per task ({native_trace_tasks}/100 native, "
            f"{fallback_trace_tasks}/100 explicit Harbor agent fallbacks); trials with no "
            "recorded MCP operation retain that fallback rather than being presented as "
            "provider calls."
        ),
    }


def assemble_report(
    runs: dict[str, dict[str, Any]],
    *,
    observed_at: str,
) -> dict[str, Any]:
    """Assemble any non-empty subset of independently complete benchmark runs."""

    received = set(runs)
    expected = set(ORDER)
    if not received or not received <= expected:
        raise ValueError(
            f"expected a non-empty subset of {ORDER}, received {sorted(received)}"
        )
    execution_policies = {
        json.dumps(run["executionPolicy"], sort_keys=True, separators=(",", ":"))
        for run in runs.values()
    }
    if len(execution_policies) != 1:
        raise ValueError("published model runs must use one identical execution policy")
    runtime_bindings = {
        json.dumps(run.get("agentRuntime"), sort_keys=True, separators=(",", ":"))
        for run in runs.values()
    }
    if len(runtime_bindings) != 1 or runtime_bindings == {"null"}:
        raise ValueError(
            "published model runs must use one identical sealed agent runtime"
        )
    return {
        "schemaVersion": "blobfish.first-party-model-runs.v4",
        "observedAt": observed_at,
        "runs": [runs[slug] for slug in ORDER if slug in runs],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", type=parse_run, required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--harbor-version", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "benchmark" / "reports" / "first-party-model-runs.json",
    )
    args = parser.parse_args()
    by_slug = {
        slug: summarize(
            slug,
            version,
            revision,
            release,
            job,
            harbor_version=args.harbor_version,
        )
        for slug, version, revision, release, job in args.run
    }
    if len(by_slug) != len(args.run):
        raise ValueError("each benchmark slug may be supplied only once")
    report = assemble_report(by_slug, observed_at=args.observed_at)
    write_json_atomic(args.output, report)
    print(
        json.dumps(
            {
                "runs": len(report["runs"]),
                "trials": sum(
                    int(run["aggregate"]["tasks"]) for run in report["runs"]
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
