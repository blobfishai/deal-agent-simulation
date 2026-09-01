from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
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
        methodology = world.call_tool(
            "sheets.read_range",
            {
                "workbook_id": f"WB-{task['project_code']}",
                "range": "Methodology!A1:B40",
            },
        )
        project = world.call_tool(
            "deals.get_project", {"project_code": task["project_code"]}
        )
        world.close()

    assert contract["schema_version"] == "dealbench.agent-contract.v3"
    assert "expected_answer" not in contract
    assert "gold_output" not in contract
    assert f"Task ID: `{task['task_id']}`" in contract["prompt"]
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
    assert workbooks["workbooks"][0]["input_ranges"] == [
        "Inputs!A1:D30",
        "Methodology!A1:B40",
    ]
    assert workbooks["workbooks"][0]["controlled_output_range"] == "Outputs!B2:G2"
    assert channels["channels"] == [f"deal-{task['project_code'].lower()}"]
    assert ["Category", "discounted_cash_flow"] in methodology["values"]
    assert ["Policy schema", "dealbench.calculation-policy.v1"] in methodology["values"]
    assert contract["calculation_policy"]["range"] == "Methodology!A1:B40"
    assert {row["id"] for row in contract["evidence_checklist"]} >= {
        "task_contract",
        "qoe_bridge",
        "current_assumptions",
        "workbook_methodology",
    }
    assert "deals.update_bid_status" not in contract["allowed_write_tools"]
    assert project["linked_records"]["approval_id"] == f"APR-{task['project_code']}"
    serialized = json.dumps(contract, sort_keys=True)
    assert '"selected"' not in serialized


def test_equivalent_search_phrasing_receives_discovery_credit() -> None:
    task = build_tasks()[4]
    steps = policy_steps(task, "oracle")
    _replace_step(
        steps,
        "dealroom.search_files",
        {"query": "DCF forecast WACC terminal growth valuation"},
    )
    _replace_step(
        steps,
        "mail.search_messages",
        {"query": "defensible DCF current valuation request"},
    )
    _replace_step(
        steps,
        "chat.search_messages",
        {"query": "discounted cash flow current authority"},
    )

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


def test_every_headline_is_enterprise_value_with_consistent_equity_bridge() -> None:
    for task in build_tasks():
        world = task["world"]
        expected = task["expected_answer"]
        net_debt = Decimal(str(world["debt"])) - Decimal(str(world["cash"]))
        expected_equity = (
            Decimal(str(expected["headline_value_usd_m"])) - net_debt
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        expected_per_share = (
            expected_equity / Decimal(str(world["shares"]))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert Decimal(str(expected["equity_value_usd_m"])) == expected_equity
        assert Decimal(str(expected["per_share_value_usd"])) == expected_per_share


def test_qoe_normalization_excludes_unsupported_addbacks_without_double_subtracting() -> None:
    task = build_tasks()[1]
    world = task["world"]
    expected = task["expected_answer"]
    normalized_ebitda = (
        Decimal(str(world["revenue"])) * Decimal(str(world["ebitda_margin"]))
        + Decimal(str(world["allowed_addbacks"]))
    )
    expected_precedent_ev = (
        normalized_ebitda * Decimal(str(world["precedent_multiple"]))
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert Decimal(str(expected["primary_metric"])) == normalized_ebitda.quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    assert Decimal(str(expected["headline_value_usd_m"])) == expected_precedent_ev
    assert expected["secondary_metric"] == world["disallowed_addbacks"]


def test_dcf_policy_reproduces_gold_from_disclosed_inputs() -> None:
    task = build_tasks()[4]
    world = task["world"]
    one = Decimal("1")
    growth = Decimal(str(world["growth"]))
    wacc = Decimal(str(world["wacc"]))
    terminal_growth = Decimal(str(world["terminal_growth"]))
    revenue = Decimal(str(world["revenue"]))
    normalized_ebitda = (
        revenue * Decimal(str(world["ebitda_margin"]))
        + Decimal(str(world["allowed_addbacks"]))
    )
    previous_revenue = revenue
    pv = Decimal("0")
    fcf = Decimal("0")
    for year in range(1, 6):
        revenue *= one + growth
        normalized_ebitda *= one + growth
        fcf = normalized_ebitda * (one - Decimal(str(world["tax_rate"])))
        fcf -= revenue * Decimal(str(world["capex_pct"]))
        fcf -= (revenue - previous_revenue) * Decimal(str(world["nwc_pct"]))
        pv += fcf / ((one + wacc) ** year)
        previous_revenue = revenue
    terminal_value = fcf * (one + terminal_growth) / (wacc - terminal_growth)
    enterprise_value = pv + terminal_value / ((one + wacc) ** 5)
    assert enterprise_value.quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    ) == Decimal(str(task["expected_answer"]["headline_value_usd_m"]))


def test_task_family_write_scope_rejects_irrelevant_mutations() -> None:
    task = build_tasks()[4]
    with tempfile.TemporaryDirectory(prefix="dealbench-write-scope-") as temporary:
        world = DealWorld.create(task, Path(temporary) / "world.sqlite")
        result = world.call_tool(
            "deals.update_bid_status",
            {
                "bid_id": f"{task['project_code']}-BID-A",
                "status": "recommended_for_board_review",
                "rationale": "irrelevant mutation",
                "task_id": task["task_id"],
            },
        )
        world.close()
    assert result == {"error": "write tool is not allowed for this task family"}
