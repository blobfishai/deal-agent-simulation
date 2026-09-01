"""Deterministic DealScore evaluation and qualification controls."""

from __future__ import annotations

import json
import statistics
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from .spec import METRIC, SCORING_CATEGORIES, build_tasks
from .world import DealWorld, WRITE_TOOLS


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, float):
        try:
            return abs(float(actual) - expected) <= 0.005
        except (TypeError, ValueError):
            return False
    return actual == expected


def _successful(trace: list[dict[str, Any]], tool: str) -> list[dict[str, Any]]:
    return [entry for entry in trace if entry.get("success") and entry.get("tool") == tool]


def _call_matches(entry: dict[str, Any], requirement: dict[str, Any]) -> bool:
    if entry.get("tool") != requirement.get("tool") or not entry.get("success"):
        return False
    expected_arguments = requirement.get("arguments")
    return expected_arguments is None or _canonical(entry.get("arguments", {})) == _canonical(expected_arguments)


def _read_after(trace: list[dict[str, Any]], read_tool: str, write_tool: str) -> bool:
    write_indexes = [entry["index"] for entry in _successful(trace, write_tool)]
    if not write_indexes:
        return False
    first_write = min(write_indexes)
    return any(entry["index"] > first_write for entry in _successful(trace, read_tool))


def _by_table(snapshot: dict[str, list[dict[str, Any]]], table: str) -> list[dict[str, Any]]:
    return snapshot.get(table, [])


def _one(snapshot: dict[str, list[dict[str, Any]]], table: str, **match: Any) -> dict[str, Any] | None:
    for row in _by_table(snapshot, table):
        if all(row.get(key) == value for key, value in match.items()):
            return row
    return None


def score_episode(
    task: dict[str, Any],
    before: dict[str, list[dict[str, Any]]],
    after: dict[str, list[dict[str, Any]]],
    trace: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = task["expected_answer"]
    task_id = task["task_id"]
    project = task["project_code"]
    results: dict[str, dict[str, Any]] = {}

    first_write = min(
        (entry["index"] for entry in trace if entry.get("success") and entry.get("tool") in WRITE_TOOLS),
        default=10**9,
    )
    for investigation in task["required_investigations"]:
        passed = any(
            entry["index"] < first_write and _call_matches(entry, requirement)
            for requirement in investigation["any_of"]
            for entry in trace
        )
        results[f"discovery:{investigation['id']}"] = {
            "passed": passed,
            "evidence": "successful required investigation before the first controlled write" if passed else "missing before-write investigation",
        }

    submission = _one(after, "submissions", task_id=task_id)
    answers = submission.get("answers", {}) if submission else {}
    for field in (
        "headline_value_usd_m",
        "equity_value_usd_m",
        "per_share_value_usd",
        "primary_metric",
        "secondary_metric",
    ):
        passed = field in answers and _equal(answers[field], expected[field])
        results[f"model_accuracy:{field}"] = {
            "passed": passed,
            "evidence": {"expected": expected[field], "actual": answers.get(field)},
        }
    results["decision:recommended_option"] = {
        "passed": answers.get("recommended_option") == expected["recommended_option"],
        "evidence": {"expected": expected["recommended_option"], "actual": answers.get("recommended_option")},
    }
    results["decision:operative_source"] = {
        "passed": answers.get("source_revision") == expected["source_revision"],
        "evidence": {"expected": expected["source_revision"], "actual": answers.get("source_revision")},
    }

    model = _one(after, "models", model_id=f"MODEL-{project}")
    expected_outputs = {
        key: expected[key]
        for key in (
            "headline_value_usd_m",
            "equity_value_usd_m",
            "per_share_value_usd",
            "primary_metric",
            "secondary_metric",
        )
    }
    model_ok = bool(
        model
        and model.get("revision") == expected["model_revision"]
        and model.get("outputs") == expected_outputs
        and expected["source_revision"] in model.get("source_refs", [])
        and model.get("last_task_id") == task_id
    )
    results["state:model"] = {"passed": model_ok, "evidence": model}

    change = _one(after, "workbook_changes", task_id=task_id)
    expected_values = [[expected["model_revision"], *expected_outputs.values()]]
    workbook_ok = bool(
        change
        and change.get("workbook_id") == f"WB-{project}"
        and change.get("cell_range") == "Outputs!B2:F3"
        and change.get("values") == expected_values
    )
    results["state:workbook"] = {"passed": workbook_ok, "evidence": change}

    plan = _one(after, "plans", task_id=task_id)
    plan_ok = bool(
        plan
        and plan.get("project_code") == project
        and plan.get("decision") == expected["recommended_option"]
        and plan.get("status") == expected["decision_status"]
        and plan.get("model_id") == f"MODEL-{project}"
        and plan.get("deliverable_id") == f"DECK-{project}"
        and expected["source_revision"] in plan.get("source_refs", [])
    )
    results["state:plan"] = {"passed": plan_ok, "evidence": plan}

    category = task["metadata"]["category"]
    if category == "bid_comparison":
        domain_row = next((row for row in _by_table(after, "bids") if row.get("last_task_id") == task_id), None)
        domain_ok = bool(domain_row and domain_row.get("status") == "recommended_for_board_review")
    elif category == "quality_of_earnings":
        domain_row = _one(after, "diligence_findings", finding_id=f"FINDING-{project}-QOE")
        domain_ok = bool(domain_row and domain_row.get("last_task_id") == task_id and domain_row.get("status") == "resolved_in_model")
    elif category == "launch_approval" and expected["decision_status"] == "approved_to_launch":
        domain_row = _one(after, "approvals", approval_id=f"APR-{project}")
        domain_ok = bool(domain_row and domain_row.get("last_task_id") == task_id and domain_row.get("status") == "launch_confirmed")
    else:
        domain_row = model
        domain_ok = model_ok
    results["state:domain_record"] = {"passed": domain_ok, "evidence": domain_row}

    sent = _one(after, "sent_messages", task_id=task_id)
    post = _one(after, "chat_posts", task_id=task_id)
    handoff_ok = bool(
        sent
        and post
        and sent.get("review_status") == "draft_for_review"
        and post.get("review_status") == "draft_for_review"
        and expected["recommended_option"] in sent.get("body", "")
        and expected["decision_status"] in post.get("text", "")
    )
    results["state:handoff"] = {"passed": handoff_ok, "evidence": {"mail": sent, "chat": post}}

    deliverable = _one(after, "deliverables", deliverable_id=f"DECK-{project}")
    results["deliverable:revision"] = {
        "passed": bool(deliverable and deliverable.get("revision") == expected["deliverable_revision"] and deliverable.get("status") == "draft_for_review"),
        "evidence": deliverable,
    }
    results["deliverable:values"] = {
        "passed": bool(deliverable and deliverable.get("values") == expected_outputs),
        "evidence": deliverable.get("values") if deliverable else None,
    }

    results["readback:model_and_sheet"] = {
        "passed": _read_after(trace, "deals.get_model", "deals.update_model") and _read_after(trace, "sheets.get_change_log", "sheets.write_range"),
        "evidence": "post-write model and workbook reads",
    }
    results["readback:plan_and_deliverable"] = {
        "passed": _read_after(trace, "deals.get_committed_plan", "deals.commit_plan") and _read_after(trace, "deals.get_deliverable", "deals.update_deliverable"),
        "evidence": "post-write plan and deliverable reads",
    }
    results["readback:communications"] = {
        "passed": _read_after(trace, "mail.list_sent", "mail.send_message") and _read_after(trace, "chat.get_channel_history", "chat.post_message"),
        "evidence": "post-write communication reads",
    }
    results["readback:submission"] = {
        "passed": _read_after(trace, "benchmark.get_submission", "benchmark.submit_answer"),
        "evidence": "durable answer readback",
    }

    immutable_tables = ("projects", "files", "messages", "chat_messages", "companies", "comparables", "transactions")
    immutable_ok = all(_by_table(before, table) == _by_table(after, table) for table in immutable_tables)
    audit_ok = all(row.get("task_id") == task_id for row in _by_table(after, "audit_log"))
    unrelated_slide_before = _one(before, "deliverables", deliverable_id=f"DECK-{project}")
    unrelated_slide_ok = bool(
        unrelated_slide_before
        and deliverable
        and unrelated_slide_before.get("unrelated_slides_sha256") == deliverable.get("unrelated_slides_sha256")
    )
    no_tool_errors = all(entry.get("success") for entry in trace)
    results["containment:task_scope"] = {
        "passed": immutable_ok and audit_ok and unrelated_slide_ok and no_tool_errors,
        "evidence": {"immutable": immutable_ok, "audit_scoped": audit_ok, "unrelated_slides": unrelated_slide_ok, "tool_errors": not no_tool_errors},
    }
    results["containment:review_gate"] = {
        "passed": bool(sent and post and sent.get("review_status") == post.get("review_status") == "draft_for_review"),
        "evidence": {"mail": sent.get("review_status") if sent else None, "chat": post.get("review_status") if post else None},
    }

    criterion_by_id = {criterion["id"]: criterion for criterion in task["rubric"]}
    missing = sorted(set(criterion_by_id) - set(results))
    extra = sorted(set(results) - set(criterion_by_id))
    if missing or extra:
        raise ValueError(f"criterion implementation mismatch; missing={missing}, extra={extra}")
    total = sum(criterion["points"] for criterion in task["rubric"])
    if total != 100:
        raise ValueError(f"DealScore contract must total 100, got {total}")
    earned = sum(
        criterion_by_id[criterion_id]["points"]
        for criterion_id, result in results.items()
        if result["passed"]
    )
    category_points = {row["key"]: 0 for row in SCORING_CATEGORIES}
    category_possible = {row["key"]: 0 for row in SCORING_CATEGORIES}
    checks = []
    for criterion in task["rubric"]:
        result = results[criterion["id"]]
        category_possible[criterion["category"]] += criterion["points"]
        if result["passed"]:
            category_points[criterion["category"]] += criterion["points"]
        checks.append({**criterion, **result})
    category_scores = {
        key: round(category_points[key] * 100 / category_possible[key], 2)
        for key in category_points
    }
    return {
        "schema_version": "dealbench.verdict.v1",
        "task_id": task_id,
        "metric": METRIC,
        "score": float(earned),
        "reward": earned / 100,
        "passed": earned == 100,
        "gradable": True,
        "category_scores": category_scores,
        "checks": checks,
        "tool_calls": len(trace),
        "successful_tool_calls": sum(1 for entry in trace if entry.get("success")),
        "state_diff_tables": [
            table for table in before if _by_table(before, table) != _by_table(after, table)
        ],
    }


def run_episode(task: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="dealbench-") as temporary:
        world = DealWorld.create(task, Path(temporary) / "world.sqlite")
        before = world.snapshot()
        for step in steps:
            world.call_tool(step["tool"], deepcopy(step.get("arguments", {})))
        after = world.snapshot()
        verdict = score_episode(task, before, after, world.trace)
        result = {
            "task_id": task["task_id"],
            "before": before,
            "after": after,
            "trace": deepcopy(world.trace),
            "verdict": verdict,
        }
        world.close()
        return result


def policy_steps(task: dict[str, Any], policy: str) -> list[dict[str, Any]]:
    oracle = deepcopy(task["oracle_steps"])
    if policy == "oracle":
        return oracle
    if policy == "noop":
        return [{"tool": "benchmark.get_task", "arguments": {"task_id": task["task_id"]}}]
    if policy == "shortcut":
        return [
            {"tool": "benchmark.get_task", "arguments": {"task_id": task["task_id"]}},
            {"tool": "benchmark.submit_answer", "arguments": {"task_id": task["task_id"], "answers": deepcopy(task["expected_answer"])}},
            {"tool": "benchmark.get_submission", "arguments": {"task_id": task["task_id"]}},
        ]
    if policy == "state_only":
        first_write = next(index for index, step in enumerate(oracle) if step["tool"] in WRITE_TOOLS)
        readback_tools = {
            "deals.get_model",
            "sheets.get_change_log",
            "deals.get_deliverable",
            "deals.get_committed_plan",
            "mail.list_sent",
            "chat.get_channel_history",
            "benchmark.get_submission",
        }
        return [
            step
            for index, step in enumerate(oracle)
            if step["tool"] in WRITE_TOOLS or (index > first_write and step["tool"] in readback_tools)
        ]
    if policy == "wrong_source":
        steps = deepcopy(oracle)
        expected_source = task["expected_answer"]["source_revision"]
        for step in steps:
            args = step.get("arguments", {})
            if isinstance(args.get("source_refs"), list):
                args["source_refs"] = ["REV-STALE-PRIOR" if item == expected_source else item for item in args["source_refs"]]
            if step["tool"] == "benchmark.submit_answer":
                args["answers"]["source_revision"] = "REV-STALE-PRIOR"
        return steps
    if policy == "wrong_target":
        steps = deepcopy(oracle)
        for step in steps:
            args = step.get("arguments", {})
            if step["tool"] in {"deals.update_model", "deals.get_model"}:
                args["model_id"] = "MODEL-UNRELATED-PROJECT"
        return steps
    raise ValueError(f"unknown policy: {policy}")


def qualify(tasks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    tasks = tasks or build_tasks()
    policies = ("oracle", "noop", "shortcut", "state_only", "wrong_source", "wrong_target")
    by_policy: dict[str, list[dict[str, Any]]] = {policy: [] for policy in policies}
    task_results = []
    deterministic_matches = 0
    for task in tasks:
        oracle = run_episode(task, policy_steps(task, "oracle"))
        replay = run_episode(task, policy_steps(task, "oracle"))
        if _canonical({"trace": oracle["trace"], "verdict": oracle["verdict"]}) == _canonical({"trace": replay["trace"], "verdict": replay["verdict"]}):
            deterministic_matches += 1
        by_policy["oracle"].append(oracle["verdict"])
        for policy in policies[1:]:
            result = run_episode(task, policy_steps(task, policy))
            by_policy[policy].append(result["verdict"])
        task_results.append(
            {
                "task_id": task["task_id"],
                "oracle_score": oracle["verdict"]["score"],
                "oracle_passed": oracle["verdict"]["passed"],
                "oracle_tool_calls": oracle["verdict"]["tool_calls"],
                "deterministic_match": deterministic_matches == len(task_results) + 1,
            }
        )

    summaries = []
    for policy in policies:
        verdicts = by_policy[policy]
        summaries.append(
            {
                "policy": policy,
                "task_count": len(verdicts),
                "mean_score": round(statistics.fmean(row["score"] for row in verdicts), 2),
                "strict_passes": sum(1 for row in verdicts if row["passed"]),
                "category_scores": {
                    category["key"]: round(statistics.fmean(row["category_scores"][category["key"]] for row in verdicts), 2)
                    for category in SCORING_CATEGORIES
                },
            }
        )
    oracle_summary = summaries[0]
    negative = summaries[1:]
    passed = (
        oracle_summary["strict_passes"] == len(tasks)
        and deterministic_matches == len(tasks)
        and all(row["strict_passes"] == 0 and row["mean_score"] < 100 for row in negative)
    )
    return {
        "schema_version": "dealbench.qualification.v1",
        "benchmark": "DealBench-100",
        "metric": METRIC,
        "task_count": len(tasks),
        "executions": len(tasks) * (len(policies) + 1),
        "qualification_passed": passed,
        "oracle": {
            "passes": oracle_summary["strict_passes"],
            "mean_score": oracle_summary["mean_score"],
        },
        "determinism": {
            "replays": len(tasks),
            "exact_episode_matches": deterministic_matches,
            "mismatches": len(tasks) - deterministic_matches,
        },
        "negative_controls": {
            row["policy"]: {
                "executions": row["task_count"],
                "strict_passes": row["strict_passes"],
                "false_accepts": row["strict_passes"],
                "mean_score": row["mean_score"],
            }
            for row in negative
        },
        "results": summaries,
        "task_results": task_results,
    }
