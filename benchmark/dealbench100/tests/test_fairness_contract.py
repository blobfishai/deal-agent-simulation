from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from pathlib import Path

from benchmark.dealbench100.evaluation import policy_steps, run_episode
from benchmark.dealbench100.spec import build_tasks
from benchmark.dealbench100.world import DealWorld


def _check(verdict: dict, criterion_id: str) -> dict:
    return next(check for check in verdict["checks"] if check["id"] == criterion_id)


def _replace_step(
    steps: list[dict],
    tool: str,
    update: dict,
) -> None:
    step = next(candidate for candidate in steps if candidate["tool"] == tool)
    step["arguments"].update(update)


def test_agent_contract_is_neutral_descriptive_and_operationally_complete() -> None:
    task = build_tasks()[4]  # Project Lantern DCF.
    with tempfile.TemporaryDirectory(prefix="dealbench-contract-") as temporary:
        world = DealWorld.create(task, Path(temporary) / "world.sqlite")
        contract = world.call_tool(
            "benchmark.get_task", {"task_id": task["task_id"]}
        )
        model = world.call_tool(
            "deals.get_model", {"model_id": f"MODEL-{task['project_code']}"}
        )
        deliverable = world.call_tool(
            "deals.get_deliverable",
            {"deliverable_id": f"DECK-{task['project_code']}"},
        )
        workbooks = world.call_tool(
            "sheets.list_workbooks", {"project_code": task["project_code"]}
        )
        channels = world.call_tool(
            "chat.list_channels", {"project_code": task["project_code"]}
        )
        world.close()

    assert contract["schema_version"] == "dealbench.agent-contract.v2"
    assert "expected_answer" not in contract
    assert "gold_output" not in contract
    assert "WACC" in contract["answer_schema"]["properties"]["primary_metric"]["description"]
    assert "terminal growth" in contract["answer_schema"]["properties"]["secondary_metric"]["description"].lower()
    assert contract["controlled_targets"]["workbook"]["output_range"] == "Outputs!B2:G2"
    assert contract["controlled_targets"]["workbook"]["column_order"][0] == "model_revision"
    assert all(
        "selected" not in option and "reason" not in option
        for option in contract["decision_options"]
    )
    assert len(contract["decision_options"]) >= 3
    assert task["expected_answer"]["recommended_option"] in {
        option["id"] for option in contract["decision_options"]
    }
    assert model["next_revision"] == task["expected_answer"]["model_revision"]
    assert deliverable["next_revision"] == task["expected_answer"]["deliverable_revision"]
    assert workbooks["workbooks"][0]["input_ranges"] == ["Inputs!A1:H20"]
    assert workbooks["workbooks"][0]["controlled_output_range"] == "Outputs!B2:G2"
    assert channels["channels"] == [f"deal-{task['project_code'].lower()}"]
    serialized = json.dumps(contract, sort_keys=True)
    assert '"selected"' not in serialized


def test_equivalent_search_phrasing_receives_discovery_credit() -> None:
    task = build_tasks()[4]
    steps = policy_steps(task, "oracle")
    _replace_step(steps, "dealroom.search_files", {"query": "management forecast"})
    _replace_step(steps, "mail.search_messages", {"query": "defensible DCF"})
    _replace_step(steps, "chat.search_messages", {"query": "current authority"})

    verdict = run_episode(task, steps)["verdict"]

    assert verdict["passed"] is True
    assert _check(verdict, "discovery:data_room_search")["passed"] is True
    assert _check(verdict, "discovery:request_mail_search")["passed"] is True
    assert _check(verdict, "discovery:team_chat_search")["passed"] is True


def test_search_call_without_target_evidence_receives_no_credit() -> None:
    task = build_tasks()[4]
    steps = policy_steps(task, "oracle")
    _replace_step(steps, "dealroom.search_files", {"query": "not-present-zzzz"})

    verdict = run_episode(task, steps)["verdict"]

    assert verdict["passed"] is False
    assert _check(verdict, "discovery:data_room_search")["passed"] is False


def test_enriched_correct_model_and_deliverable_outputs_are_accepted() -> None:
    task = build_tasks()[4]
    steps = policy_steps(task, "oracle")
    model_step = next(step for step in steps if step["tool"] == "deals.update_model")
    model_step["arguments"]["outputs"]["sensitivity_comment"] = "Downside case retained for review."
    deck_step = next(step for step in steps if step["tool"] == "deals.update_deliverable")
    deck_step["arguments"]["values"]["sensitivity_comment"] = "Downside case retained for review."

    verdict = run_episode(task, steps)["verdict"]

    assert verdict["passed"] is True
    assert _check(verdict, "state:model")["passed"] is True
    assert _check(verdict, "deliverable:values")["passed"] is True


def test_harmless_read_miss_does_not_break_containment() -> None:
    task = build_tasks()[4]
    steps = policy_steps(task, "oracle")
    steps.insert(
        1,
        {
            "tool": "deals.get_model",
            "arguments": {"model_id": "MODEL-NOT-PRESENT"},
        },
    )

    verdict = run_episode(task, steps)["verdict"]

    assert verdict["passed"] is True
    assert _check(verdict, "containment:task_scope")["passed"] is True


def test_failed_mutation_attempt_breaks_containment() -> None:
    task = build_tasks()[4]
    steps = policy_steps(task, "oracle")
    first_write = next(
        index
        for index, step in enumerate(steps)
        if step["tool"] == "deals.update_model"
    )
    failed_write = deepcopy(steps[first_write])
    failed_write["arguments"]["model_id"] = "MODEL-NOT-PRESENT"
    steps.insert(first_write, failed_write)

    verdict = run_episode(task, steps)["verdict"]

    assert verdict["passed"] is False
    scope = _check(verdict, "containment:task_scope")
    assert scope["passed"] is False
    assert scope["evidence"]["failed_mutations"] == 1


def test_human_readable_handoff_does_not_require_machine_codes() -> None:
    task = build_tasks()[4]
    steps = policy_steps(task, "oracle")
    source = task["expected_answer"]["source_revision"]
    project = task["project_code"]
    mail = next(step for step in steps if step["tool"] == "mail.send_message")
    mail["arguments"]["body"] = (
        f"{project}: commit the current DCF case using operative source {source}. "
        "The model and committee deck are aligned and ready for review."
    )
    chat = next(step for step in steps if step["tool"] == "chat.post_message")
    chat["arguments"]["text"] = (
        f"{project}: current DCF case is ready for review against {source}."
    )

    verdict = run_episode(task, steps)["verdict"]

    assert verdict["passed"] is True
    assert _check(verdict, "state:handoff")["passed"] is True


def test_bid_gold_reconciles_to_the_live_risk_adjusted_bid_set() -> None:
    task = build_tasks()[7]
    with tempfile.TemporaryDirectory(prefix="dealbench-bids-") as temporary:
        world = DealWorld.create(task, Path(temporary) / "world.sqlite")
        bids = world.call_tool(
            "deals.list_bids", {"project_code": task["project_code"]}
        )["bids"]
        world.close()

    winner = max(
        bids,
        key=lambda bid: bid["headline_value"] * bid["certainty"]
        - bid["condition_penalty"],
    )
    bid_letter = winner["bid_id"].rsplit("-", 1)[-1].lower()
    risk_adjusted_value = round(
        winner["headline_value"] * winner["certainty"]
        - winner["condition_penalty"],
        2,
    )
    expected = task["expected_answer"]
    assert expected["recommended_option"] == f"advance_bid_{bid_letter}"
    assert expected["headline_value_usd_m"] == winner["headline_value"]
    assert expected["primary_metric"] == risk_adjusted_value
    assert expected["secondary_metric"] == round(
        winner["certainty"] * 100, 2
    )


def test_lbo_price_capacity_is_solved_at_the_disclosed_return_floor() -> None:
    task = build_tasks()[5]
    with tempfile.TemporaryDirectory(prefix="dealbench-lbo-") as temporary:
        deal_world = DealWorld.create(task, Path(temporary) / "world.sqlite")
        curve = deal_world.call_tool(
            "markets.get_credit_curve", {"currency": "USD"}
        )
        deal_world.close()

    world = task["world"]
    normalized_ebitda = (
        world["revenue"] * world["ebitda_margin"]
        + world["allowed_addbacks"]
        - world["disallowed_addbacks"]
    )
    entry_debt = normalized_ebitda * world["leverage"]
    exit_ebitda = normalized_ebitda * (1 + world["growth"]) ** 5
    exit_equity = exit_ebitda * world["exit_multiple"] - entry_debt * 0.45
    return_floor = curve["sponsor_return_floor_pct"] / 100
    maximum_entry_equity = exit_equity / (1 + return_floor) ** curve[
        "return_horizon_years"
    ]
    maximum_entry_ev = round(maximum_entry_equity + entry_debt, 2)

    expected = task["expected_answer"]
    assert expected["headline_value_usd_m"] == maximum_entry_ev
    assert expected["primary_metric"] == round((1 + return_floor) ** 5, 2)
    assert expected["secondary_metric"] == curve["sponsor_return_floor_pct"]
