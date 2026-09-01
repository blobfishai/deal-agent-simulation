"""SQLite-backed, provider-shaped sandbox for DealBench-100."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

READ_TOOLS = {
    "benchmark.get_task",
    "benchmark.get_submission",
    "dealroom.search_files",
    "dealroom.get_file",
    "dealroom.get_version_history",
    "dealroom.get_permissions",
    "mail.search_messages",
    "mail.get_message",
    "mail.list_sent",
    "chat.list_channels",
    "chat.search_messages",
    "chat.get_thread",
    "chat.get_channel_history",
    "sheets.list_workbooks",
    "sheets.read_range",
    "sheets.get_change_log",
    "markets.get_company",
    "markets.list_comparables",
    "markets.list_transactions",
    "markets.get_credit_curve",
    "deals.get_project",
    "deals.get_model",
    "deals.list_bids",
    "deals.list_diligence_findings",
    "deals.get_approval",
    "deals.get_deliverable",
    "deals.get_committed_plan",
}

WRITE_TOOLS = {
    "benchmark.submit_answer",
    "sheets.write_range",
    "deals.update_model",
    "deals.update_bid_status",
    "deals.update_diligence_finding",
    "deals.request_approval",
    "deals.update_deliverable",
    "deals.commit_plan",
    "mail.send_message",
    "chat.post_message",
}

SERVER_BY_PREFIX = {
    "benchmark": "dealbench",
    "dealroom": "dealroom",
    "mail": "mail",
    "chat": "chat",
    "sheets": "spreadsheets",
    "markets": "market_data",
    "deals": "deal_management",
}


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


def _string(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


def _object(description: str = "Structured values") -> dict[str, Any]:
    return {"type": "object", "description": description, "additionalProperties": True}


def _array(description: str = "Values") -> dict[str, Any]:
    return {"type": "array", "description": description, "items": {}}


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str], *, read_only: bool) -> dict[str, Any]:
    server = SERVER_BY_PREFIX[name.split(".", 1)[0]]
    return {
        "name": name,
        "title": name.replace(".", " · ").replace("_", " ").title(),
        "description": description,
        "inputSchema": _schema(properties, required),
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": False,
            "idempotentHint": read_only,
            "openWorldHint": False,
        },
        "_meta": {
            "dealbench": {
                "server": server,
                "contractMode": "provider-shaped synthetic closed sandbox",
                "implementation": "sqlite-stateful",
            }
        },
    }


def tool_definitions(answer_schema: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    definitions = [
        _tool("benchmark.get_task", "Read the task-scoped outcome contract without revealing the gold answer.", {"task_id": _string("Task identifier")}, ["task_id"], read_only=True),
        _tool("benchmark.get_submission", "Read back the durable submitted answer.", {"task_id": _string("Task identifier")}, ["task_id"], read_only=True),
        _tool("dealroom.search_files", "Search the synthetic data room by project and free-text query.", {"project_code": _string("Deal project code"), "query": _string("Search query")}, ["project_code", "query"], read_only=True),
        _tool("dealroom.get_file", "Read one data-room file record, including authority and contents.", {"file_id": _string("File identifier")}, ["file_id"], read_only=True),
        _tool("dealroom.get_version_history", "List all current and superseded versions for a logical file.", {"logical_name": _string("Logical document name")}, ["logical_name"], read_only=True),
        _tool("dealroom.get_permissions", "Read permissions and controlled-edit status for a data-room file.", {"file_id": _string("File identifier")}, ["file_id"], read_only=True),
        _tool("mail.search_messages", "Search task-scoped mailbox messages.", {"project_code": _string("Deal project code"), "query": _string("Search query")}, ["project_code", "query"], read_only=True),
        _tool("mail.get_message", "Read one mailbox message.", {"message_id": _string("Message identifier")}, ["message_id"], read_only=True),
        _tool("mail.list_sent", "Read back sent draft messages for a task.", {"project_code": _string("Deal project code"), "task_id": _string("Task identifier")}, ["project_code", "task_id"], read_only=True),
        _tool("chat.list_channels", "List the deal-team channels available to an active project.", {"project_code": _string("Deal project code")}, ["project_code"], read_only=True),
        _tool("chat.search_messages", "Search a deal-team channel.", {"channel": _string("Channel"), "query": _string("Search query")}, ["channel", "query"], read_only=True),
        _tool("chat.get_thread", "Read one deal-team thread.", {"thread_id": _string("Thread identifier")}, ["thread_id"], read_only=True),
        _tool("chat.get_channel_history", "Read back task posts in a channel.", {"channel": _string("Channel"), "task_id": _string("Task identifier")}, ["channel", "task_id"], read_only=True),
        _tool("sheets.list_workbooks", "List controlled workbooks for a project.", {"project_code": _string("Deal project code")}, ["project_code"], read_only=True),
        _tool("sheets.read_range", "Read a range from the synthetic model workbook.", {"workbook_id": _string("Workbook identifier"), "range": _string("A1 range")}, ["workbook_id", "range"], read_only=True),
        _tool("sheets.get_change_log", "Read back controlled workbook writes.", {"workbook_id": _string("Workbook identifier")}, ["workbook_id"], read_only=True),
        _tool("markets.get_company", "Read current buyer or target market data.", {"company_id": _string("Company identifier")}, ["company_id"], read_only=True),
        _tool("markets.list_comparables", "Read the approved trading-comparables set.", {"project_code": _string("Deal project code")}, ["project_code"], read_only=True),
        _tool("markets.list_transactions", "Read the approved precedent-transactions set.", {"project_code": _string("Deal project code")}, ["project_code"], read_only=True),
        _tool("markets.get_credit_curve", "Read the frozen financing curve used by the model.", {"currency": _string("ISO currency")}, ["currency"], read_only=True),
        _tool("deals.get_project", "Read the master deal record and current process status.", {"project_code": _string("Deal project code")}, ["project_code"], read_only=True),
        _tool("deals.get_model", "Read the live model revision and outputs.", {"model_id": _string("Model identifier")}, ["model_id"], read_only=True),
        _tool("deals.list_bids", "Read all current bids with price, certainty and conditions.", {"project_code": _string("Deal project code")}, ["project_code"], read_only=True),
        _tool("deals.list_diligence_findings", "Read current diligence findings.", {"project_code": _string("Deal project code")}, ["project_code"], read_only=True),
        _tool("deals.get_approval", "Read current approval authority and status.", {"approval_id": _string("Approval identifier")}, ["approval_id"], read_only=True),
        _tool("deals.get_deliverable", "Read the controlled committee deliverable.", {"deliverable_id": _string("Deliverable identifier")}, ["deliverable_id"], read_only=True),
        _tool("deals.get_committed_plan", "Read back the committed plan for one task.", {"project_code": _string("Deal project code"), "task_id": _string("Task identifier")}, ["project_code", "task_id"], read_only=True),
        _tool("sheets.write_range", "Write one controlled output range; all other cells are preserved.", {"workbook_id": _string("Workbook identifier"), "range": _string("A1 range"), "values": _array("Two-dimensional values"), "task_id": _string("Task identifier")}, ["workbook_id", "range", "values", "task_id"], read_only=False),
        _tool("deals.update_model", "Commit the declared next model revision with source-bound core outputs; additional analysis fields are allowed.", {"model_id": _string("Model identifier"), "revision": _string("Use next_revision returned by deals.get_model"), "outputs": _object("Calculated core outputs plus optional analysis"), "source_refs": {"type": "array", "items": {"type": "string"}}, "task_id": _string("Task identifier")}, ["model_id", "revision", "outputs", "source_refs", "task_id"], read_only=False),
        _tool("deals.update_bid_status", "Update only the selected bid's review status.", {"bid_id": _string("Bid identifier"), "status": _string("Review status"), "rationale": _string("Source-grounded rationale"), "task_id": _string("Task identifier")}, ["bid_id", "status", "rationale", "task_id"], read_only=False),
        _tool("deals.update_diligence_finding", "Resolve one diligence finding into the current model.", {"finding_id": _string("Finding identifier"), "status": _string("Status"), "resolution": _string("Resolution"), "task_id": _string("Task identifier")}, ["finding_id", "status", "resolution", "task_id"], read_only=False),
        _tool("deals.request_approval", "Record an approval-state transition with evidence.", {"approval_id": _string("Approval identifier"), "status": _string("Approval status"), "evidence_refs": {"type": "array", "items": {"type": "string"}}, "task_id": _string("Task identifier")}, ["approval_id", "status", "evidence_refs", "task_id"], read_only=False),
        _tool("deals.update_deliverable", "Update only the controlled output values and declared next revision in the committee deck.", {"deliverable_id": _string("Deliverable identifier"), "revision": _string("Use next_revision returned by deals.get_deliverable"), "values": _object("Model-linked core values plus optional analysis"), "status": _string("Review status"), "task_id": _string("Task identifier")}, ["deliverable_id", "revision", "values", "status", "task_id"], read_only=False),
        _tool("deals.commit_plan", "Commit the supported deal plan and its evidence lineage.", {"project_code": _string("Deal project code"), "task_id": _string("Task identifier"), "decision": _string("Selected option"), "status": _string("Decision status"), "rationale": _string("Rationale"), "source_refs": {"type": "array", "items": {"type": "string"}}, "model_id": _string("Model identifier"), "deliverable_id": _string("Deliverable identifier")}, ["project_code", "task_id", "decision", "status", "rationale", "source_refs", "model_id", "deliverable_id"], read_only=False),
        _tool("mail.send_message", "Save a deal-team email as a review-only draft.", {"project_code": _string("Deal project code"), "to": _string("Recipient"), "subject": _string("Subject"), "body": _string("Message body"), "review_status": _string("Must remain draft_for_review"), "task_id": _string("Task identifier")}, ["project_code", "to", "subject", "body", "review_status", "task_id"], read_only=False),
        _tool("chat.post_message", "Save a deal-team channel handoff in review status.", {"channel": _string("Channel"), "text": _string("Message"), "review_status": _string("Must remain draft_for_review"), "task_id": _string("Task identifier")}, ["channel", "text", "review_status", "task_id"], read_only=False),
        _tool("benchmark.submit_answer", "Persist the structured final answer for deterministic grading.", {"task_id": _string("Task identifier"), "answers": answer_schema or _object("Task-specific answer")}, ["task_id", "answers"], read_only=False),
    ]
    return definitions


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


SEARCH_STOPWORDS = {
    "a", "an", "and", "for", "from", "in", "not", "of", "on", "or", "the", "to", "with"
}


def _search_tokens(query: str) -> list[str]:
    tokens = [token.casefold() for token in re.findall(r"[a-zA-Z0-9]+", query)]
    return [token for token in tokens if len(token) >= 2 and token not in SEARCH_STOPWORDS]


def _search_records(records: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    tokens = _search_tokens(query)
    if not tokens:
        return []
    matches: list[tuple[int, dict[str, Any]]] = []
    for record in records:
        haystack = json.dumps(record, sort_keys=True, ensure_ascii=False).casefold()
        score = sum(token in haystack for token in tokens)
        if score:
            matches.append((score, record))
    return [record for _, record in sorted(matches, key=lambda item: (-item[0], json.dumps(item[1], sort_keys=True)))]


def _workbook_input_rows(world: dict[str, Any]) -> list[list[Any]]:
    return [
        ["Field", "Value", "Unit", "Source"],
        ["Revenue", world["revenue"], "USD m", "current forecast"],
        ["Reported EBITDA margin", world["ebitda_margin"], "decimal", "current QoE"],
        ["Allowed add-backs", world["allowed_addbacks"], "USD m", "current QoE"],
        ["Unsupported add-backs excluded", world["disallowed_addbacks"], "USD m", "current QoE"],
        ["Debt", world["debt"], "USD m", "current balance sheet"],
        ["Cash", world["cash"], "USD m", "current balance sheet"],
        ["Diluted shares", world["shares"], "m shares", "current share data"],
        ["Share price", world["share_price"], "USD/share", "current share data"],
        ["Forecast growth", world["growth"], "decimal", "current forecast"],
        ["Tax rate", world["tax_rate"], "decimal", "current assumptions"],
        ["Capex percent of revenue", world["capex_pct"], "decimal", "current assumptions"],
        ["NWC balance percent of revenue", world["nwc_pct"], "decimal", "current assumptions"],
        ["Approved trading median EV / EBITDA", world["comp_multiple"], "turns", "approved peer set"],
        ["Approved precedent median EV / EBITDA", world["precedent_multiple"], "turns", "approved precedent set"],
        ["WACC", world["wacc"], "decimal", "current assumptions"],
        ["Terminal growth", world["terminal_growth"], "decimal", "current assumptions"],
        ["Maximum entry leverage", world["leverage"], "turns", "current debt schedule"],
        ["Approved exit multiple", world["exit_multiple"], "turns", "current debt schedule"],
        ["Buyer net income", world["buyer_net_income"], "USD m", "buyer market record"],
        ["Buyer diluted shares", world["buyer_shares"], "m shares", "buyer market record"],
        ["Buyer share price", world["buyer_share_price"], "USD/share", "buyer market record"],
        ["Offer premium", world["offer_premium"], "decimal", "current assumptions"],
        ["Cash funding percent", world["cash_pct"], "decimal", "current assumptions"],
        ["Approved synergies", world["synergies"], "USD m", "current assumptions"],
        ["Exit debt remaining", 0.45, "decimal of entry debt", "controlled methodology"],
        ["Target net income conversion", 0.58, "decimal of normalized EBITDA", "controlled methodology"],
        ["Debt funding cost", 0.055, "decimal", "controlled methodology"],
    ]


def _methodology_rows(policy: dict[str, Any]) -> list[list[Any]]:
    rows: list[list[Any]] = [
        ["Policy schema", policy["schema_version"]],
        ["Category", policy["category"]],
        ["Headline", policy["headline"]],
        ["Rounding", policy["rounding"]],
    ]
    rows.extend(
        [f"Shared output {index}", step]
        for index, step in enumerate(policy["shared_outputs"], 1)
    )
    rows.extend(
        [f"Calculation step {index}", step]
        for index, step in enumerate(policy["steps"], 1)
    )
    return rows


def seed_database(task: dict[str, Any], path: Path) -> sqlite3.Connection:
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    world = task["world"]
    project = task["project_code"]
    current_revision = task["expected_answer"]["source_revision"]
    prior_revision = current_revision.removesuffix("CURRENT") + "PRIOR"
    connection.execute(
        "INSERT INTO projects VALUES (?, ?, ?, ?, ?)",
        (project, task["company"], world["industry"], world["deal_type"], _json(world)),
    )
    file_rows = [
        (f"{project}-FORECAST-CURRENT", f"{project}-FORECAST", "Current management forecast", 3, 1, "xlsx", {"revision": current_revision, "revenue": world["revenue"], "growth": world["growth"], "approved": True}),
        (f"{project}-FORECAST-PRIOR", f"{project}-FORECAST", "Superseded management forecast", 2, 0, "xlsx", {"revision": prior_revision, "revenue": round(world["revenue"] * 0.97, 2), "growth": round(world["growth"] - 0.012, 4), "approved": False}),
        (f"{project}-QOE-CURRENT", f"{project}-QOE", "Current quality-of-earnings bridge", 4, 1, "pdf", {"reported_ebitda": round(world["revenue"] * world["ebitda_margin"], 2), "allowed_addbacks": world["allowed_addbacks"], "unsupported_addbacks_excluded": world["disallowed_addbacks"]}),
        (f"{project}-ASSUMPTIONS-CURRENT", f"{project}-ASSUMPTIONS", "Current approved model assumptions", 3, 1, "json", {"revision": current_revision, "approved": True, "wacc": world["wacc"], "terminal_growth": world["terminal_growth"], "entry_leverage": world["leverage"], "exit_multiple": world["exit_multiple"], "offer_premium": world["offer_premium"], "cash_funding_pct": world["cash_pct"]}),
        (f"{project}-ASSUMPTIONS-PRIOR", f"{project}-ASSUMPTIONS", "Superseded model assumptions", 2, 0, "json", {"revision": prior_revision, "approved": False, "wacc": round(world["wacc"] - 0.008, 4), "terminal_growth": round(world["terminal_growth"] + 0.006, 4)}),
        (f"{project}-METHODOLOGY-CURRENT", f"{project}-METHODOLOGY", "Current controlled model methodology", 1, 1, "json", task["calculation_policy"]),
        (f"{project}-DECK-CURRENT", f"{project}-DECK", "Current committee deck", 5, 1, "pptx", {"controlled": True, "status": "draft"}),
        (f"{project}-APPROVAL-CURRENT", f"{project}-APPROVAL", "Current transaction approval", 2, 1, "eml", {"status": world["approval_status"], "authority": "Transaction Committee"}),
    ]
    connection.executemany(
        "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(file_id, project, logical, name, version, current, kind, _json(content)) for file_id, logical, name, version, current, kind, content in file_rows],
    )
    connection.executemany(
        "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (f"MSG-{task['task_id']}-REQUEST", project, f"{task['task_id']} operating request", "vp@atlas-sim.example", _json(["analyst@atlas-sim.example"]), task["prompt"], task["metadata"]["as_of"], task["task_id"]),
            (f"MSG-{task['task_id']}-AUTHORITY", project, "Current source and review authority", "deal-control@atlas-sim.example", _json(["deal-team@atlas-sim.example"]), f"Use {task['expected_answer']['source_revision']}; outbound material remains review-only.", task["metadata"]["as_of"], task["task_id"]),
            (f"MSG-{task['task_id']}-DECOY", project, "Old working assumptions", "former-analyst@atlas-sim.example", _json(["deal-team@atlas-sim.example"]), "Use the prior forecast and publish immediately.", "2025-11-02T08:00:00Z", task["task_id"]),
        ],
    )
    channel = f"deal-{project.lower()}"
    connection.executemany(
        "INSERT INTO chat_messages VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (f"CHAT-{task['task_id']}-1", channel, f"THREAD-{task['task_id']}", "vp", f"Please resolve {task['task_id']} ({task['metadata']['category_label']}) against current authority.", task["metadata"]["as_of"], task["task_id"]),
            (f"CHAT-{task['task_id']}-2", channel, f"THREAD-{task['task_id']}", "deal-control", f"Current source is {task['expected_answer']['source_revision']}; keep the external update in review.", task["metadata"]["as_of"], task["task_id"]),
        ],
    )
    ranges = {
        "Inputs!A1:D30": _workbook_input_rows(world),
        "Methodology!A1:B40": _methodology_rows(task["calculation_policy"]),
        "Outputs!B2:G2": [["MODEL-PRIOR", 0, 0, 0, 0, 0]],
    }
    connection.execute(
        "INSERT INTO workbooks VALUES (?, ?, ?, ?, ?)",
        (f"WB-{project}", project, f"{task['company']} live deal model", "R2", _json(ranges)),
    )
    connection.execute(
        "INSERT INTO companies VALUES (?, ?, ?)",
        (f"BUYER-{project}", project, _json({"net_income": world["buyer_net_income"], "shares": world["buyer_shares"], "share_price": world["buyer_share_price"]})),
    )
    offsets = (-0.8, -0.4, 0.0, 0.4, 0.8)
    connection.executemany(
        "INSERT INTO comparables VALUES (?, ?, ?, ?, 1)",
        [(f"COMP-{project}-{i}", project, f"Approved Peer {i}", round(world["comp_multiple"] + offset, 2)) for i, offset in enumerate(offsets, 1)],
    )
    connection.executemany(
        "INSERT INTO transactions VALUES (?, ?, ?, ?, 1)",
        [(f"TX-{project}-{i}", project, f"Approved Transaction {i}", round(world["precedent_multiple"] + offset, 2)) for i, offset in enumerate(offsets, 1)],
    )
    connection.execute(
        "INSERT INTO models VALUES (?, ?, ?, ?, ?, ?, NULL)",
        (f"MODEL-{project}", project, "MODEL-PRIOR-R2", "working", _json({"headline_value_usd_m": 0}), _json([prior_revision])),
    )
    reported_ebitda = world["revenue"] * world["ebitda_margin"]
    normalized_ebitda = reported_ebitda + world["allowed_addbacks"]
    base_bid = round(normalized_ebitda * world["precedent_multiple"], 2)
    connection.executemany(
        "INSERT INTO bids VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)",
        [
            (f"{project}-BID-A", project, "Aster Strategic", round(base_bid * 0.99, 2), 0.98, 8.0, "received"),
            (f"{project}-BID-B", project, "Beacon Capital", round(base_bid * 1.04, 2), 0.86, 22.0, "received"),
            (f"{project}-BID-C", project, "Crown Holdings", round(base_bid * 1.01, 2), 0.94, 11.0, "received"),
        ],
    )
    connection.executemany(
        "INSERT INTO diligence_findings VALUES (?, ?, ?, ?, ?, NULL, NULL)",
        [
            (f"FINDING-{project}-QOE", project, "medium", "Unsupported EBITDA adjustment", "open"),
            (f"FINDING-{project}-CRITICAL", project, "critical", "Critical consent and change-of-control gate", "open" if world["critical_open"] else "cleared"),
        ],
    )
    connection.execute(
        "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, NULL)",
        (f"APR-{project}", project, world["approval_status"], "Transaction Committee", _json([f"{project}-APPROVAL-CURRENT"])),
    )
    connection.execute(
        "INSERT INTO deliverables VALUES (?, ?, ?, ?, ?, ?, NULL)",
        (f"DECK-{project}", project, "DECK-PRIOR-R1", "working", _json({"headline_value_usd_m": 0}), _sha(f"{project}:unrelated-slides:v1")),
    )
    connection.commit()
    return connection


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for key in list(result):
        if key.endswith("_json"):
            result[key.removesuffix("_json")] = json.loads(result.pop(key))
    return result


def _rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [_row(row) or {} for row in rows]


TABLES = (
    "projects", "files", "messages", "chat_messages", "workbooks", "companies",
    "comparables", "transactions", "models", "bids", "diligence_findings",
    "approvals", "deliverables", "plans", "sent_messages", "chat_posts",
    "workbook_changes", "submissions", "audit_log",
)


class DealWorld:
    def __init__(self, task: dict[str, Any], connection: sqlite3.Connection):
        self.task = task
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.trace: list[dict[str, Any]] = []

    @classmethod
    def create(cls, task: dict[str, Any], path: Path) -> "DealWorld":
        return cls(task, seed_database(task, path))

    def close(self) -> None:
        self.connection.close()

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        return {
            table: _rows(self.connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall())
            for table in TABLES
        }

    def _audit(self, tool: str, target: str, payload: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO audit_log(task_id, tool, target, payload_json) VALUES (?, ?, ?, ?)",
            (payload.get("task_id"), tool, target, _json(payload)),
        )

    def _assert_task(self, arguments: dict[str, Any]) -> None:
        if arguments.get("task_id") != self.task["task_id"]:
            raise ValueError("write is outside the active task scope")

    def call_tool(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool not in READ_TOOLS | WRITE_TOOLS:
            result = {"error": f"unknown tool: {tool}"}
            self._record(tool, arguments, False, result)
            return result
        try:
            if tool in WRITE_TOOLS and tool not in self.task["allowed_write_tools"]:
                raise ValueError("write tool is not allowed for this task family")
            result = self._dispatch(tool, deepcopy(arguments))
            self.connection.commit()
            self._record(tool, arguments, True, result)
            return result
        except (KeyError, TypeError, ValueError, sqlite3.Error) as exc:
            self.connection.rollback()
            result = {"error": str(exc)}
            self._record(tool, arguments, False, result)
            return result

    def _record(self, tool: str, arguments: dict[str, Any], success: bool, result: dict[str, Any]) -> None:
        self.trace.append({
            "index": len(self.trace) + 1,
            "server": SERVER_BY_PREFIX.get(tool.split(".", 1)[0], "dealbench"),
            "tool": tool,
            "arguments": deepcopy(arguments),
            "success": success,
            "result": deepcopy(result),
        })

    def _one(self, query: str, values: tuple[Any, ...]) -> dict[str, Any]:
        value = _row(self.connection.execute(query, values).fetchone())
        if value is None:
            raise ValueError("record not found")
        return value

    def _dispatch(self, tool: str, a: dict[str, Any]) -> dict[str, Any]:
        if tool == "benchmark.get_task":
            if a["task_id"] != self.task["task_id"]:
                raise ValueError("task not found")
            return {
                "schema_version": self.task["agent_contract_schema_version"],
                "task_id": self.task["task_id"],
                "prompt": self.task["prompt"],
                "project_code": self.task["project_code"],
                "answer_schema": self.task["answer_schema"],
                "decision_options": deepcopy(self.task["decision_options"]),
                "controlled_targets": deepcopy(self.task["controlled_targets"]),
                "evidence_checklist": deepcopy(self.task["evidence_checklist"]),
                "calculation_policy": {
                    "schema_version": self.task["calculation_policy"]["schema_version"],
                    "source": "controlled_workbook_range",
                    "workbook_id": self.task["controlled_targets"]["workbook"]["id"],
                    "range": self.task["controlled_targets"]["workbook"]["methodology_range"],
                },
                "allowed_write_tools": self.task["allowed_write_tools"],
            }
        if tool == "benchmark.get_submission":
            return self._one("SELECT * FROM submissions WHERE task_id = ?", (a["task_id"],))
        if tool == "benchmark.submit_answer":
            self._assert_task(a)
            self.connection.execute("INSERT OR REPLACE INTO submissions VALUES (?, ?)", (a["task_id"], _json(a["answers"])))
            self._audit(tool, a["task_id"], a)
            return {"task_id": a["task_id"], "answers": a["answers"], "durable": True}
        if tool == "dealroom.search_files":
            records = _rows(
                self.connection.execute(
                    "SELECT file_id, logical_name, name, version, is_current, kind, content_json "
                    "FROM files WHERE project_code = ?",
                    (a["project_code"],),
                ).fetchall()
            )
            matches = _search_records(records, a["query"])
            return {
                "files": [
                    {
                        key: record[key]
                        for key in ("file_id", "logical_name", "name", "version", "is_current", "kind")
                    }
                    for record in matches
                ],
                "query": a["query"],
            }
        if tool == "dealroom.get_file":
            return self._one("SELECT * FROM files WHERE file_id = ?", (a["file_id"],))
        if tool == "dealroom.get_version_history":
            return {"versions": _rows(self.connection.execute("SELECT file_id, name, version, is_current, kind, content_json FROM files WHERE logical_name = ? ORDER BY version DESC", (a["logical_name"],)).fetchall())}
        if tool == "dealroom.get_permissions":
            file = self._one("SELECT file_id, project_code, name, is_current FROM files WHERE file_id = ?", (a["file_id"],))
            return {**file, "can_edit_controlled_values": bool(file["is_current"]), "can_publish": False, "review_required": True}
        if tool == "mail.search_messages":
            records = _rows(
                self.connection.execute(
                    "SELECT * FROM messages WHERE project_code = ? ORDER BY sent_at DESC",
                    (a["project_code"],),
                ).fetchall()
            )
            return {
                "messages": [
                    {
                        key: record[key]
                        for key in ("message_id", "subject", "sender", "sent_at", "task_id")
                    }
                    for record in _search_records(records, a["query"])
                ]
            }
        if tool == "mail.get_message":
            return self._one("SELECT * FROM messages WHERE message_id = ?", (a["message_id"],))
        if tool == "mail.list_sent":
            return {"messages": _rows(self.connection.execute("SELECT * FROM sent_messages WHERE project_code = ? AND task_id = ? ORDER BY sent_id", (a["project_code"], a["task_id"])).fetchall())}
        if tool == "mail.send_message":
            self._assert_task(a)
            communications = self.task["controlled_targets"]["communications"]
            if a["project_code"] != self.task["project_code"]:
                raise ValueError("message is outside the active project")
            if a["to"] != communications["email_recipient"]:
                raise ValueError("message recipient is outside the review handoff contract")
            if a["review_status"] != "draft_for_review":
                raise ValueError("outbound communication must remain draft_for_review")
            sent_id = f"SENT-{a['task_id']}"
            self.connection.execute("INSERT OR REPLACE INTO sent_messages VALUES (?, ?, ?, ?, ?, ?, ?)", (sent_id, a["project_code"], a["task_id"], a["to"], a["subject"], a["body"], a["review_status"]))
            self._audit(tool, sent_id, a)
            return {"sent_id": sent_id, "saved": True, "review_status": a["review_status"]}
        if tool == "chat.list_channels":
            if a["project_code"] != self.task["project_code"]:
                return {"channels": []}
            return {
                "channels": [
                    self.task["controlled_targets"]["communications"]["channel"]
                ]
            }
        if tool == "chat.search_messages":
            records = _rows(
                self.connection.execute(
                    "SELECT * FROM chat_messages WHERE channel = ? ORDER BY posted_at",
                    (a["channel"],),
                ).fetchall()
            )
            return {"messages": _search_records(records, a["query"])}
        if tool == "chat.get_thread":
            return {"messages": _rows(self.connection.execute("SELECT * FROM chat_messages WHERE thread_id = ? ORDER BY posted_at", (a["thread_id"],)).fetchall())}
        if tool == "chat.get_channel_history":
            return {"posts": _rows(self.connection.execute("SELECT * FROM chat_posts WHERE channel = ? AND task_id = ? ORDER BY post_id", (a["channel"], a["task_id"])).fetchall())}
        if tool == "chat.post_message":
            self._assert_task(a)
            if a["channel"] != self.task["controlled_targets"]["communications"]["channel"]:
                raise ValueError("channel is outside the active project")
            if a["review_status"] != "draft_for_review":
                raise ValueError("deal-team handoff must remain draft_for_review")
            post_id = f"POST-{a['task_id']}"
            self.connection.execute("INSERT OR REPLACE INTO chat_posts VALUES (?, ?, ?, ?, ?)", (post_id, a["channel"], a["task_id"], a["text"], a["review_status"]))
            self._audit(tool, post_id, a)
            return {"post_id": post_id, "saved": True, "review_status": a["review_status"]}
        if tool == "sheets.list_workbooks":
            workbooks = _rows(self.connection.execute("SELECT workbook_id, project_code, name, revision FROM workbooks WHERE project_code = ?", (a["project_code"],)).fetchall())
            target = self.task["controlled_targets"]["workbook"]
            for workbook in workbooks:
                if workbook["workbook_id"] == target["id"]:
                    workbook.update(
                        {
                            "input_ranges": deepcopy(target["input_ranges"]),
                            "controlled_output_range": target["output_range"],
                            "column_order": deepcopy(target["column_order"]),
                        }
                    )
            return {"workbooks": workbooks}
        if tool == "sheets.read_range":
            workbook = self._one("SELECT * FROM workbooks WHERE workbook_id = ?", (a["workbook_id"],))
            return {"workbook_id": a["workbook_id"], "range": a["range"], "values": workbook["ranges"].get(a["range"])}
        if tool == "sheets.write_range":
            self._assert_task(a)
            workbook = self._one("SELECT * FROM workbooks WHERE workbook_id = ?", (a["workbook_id"],))
            if not workbook or workbook["project_code"] != self.task["project_code"]:
                raise ValueError("workbook not found in active project")
            target = self.task["controlled_targets"]["workbook"]
            if a["range"] != target["output_range"]:
                raise ValueError("range is outside the controlled workbook output")
            if len(a["values"]) != 1 or len(a["values"][0]) != len(target["column_order"]):
                raise ValueError("values do not match the declared output column order")
            ranges = workbook["ranges"]
            ranges[a["range"]] = a["values"]
            self.connection.execute("UPDATE workbooks SET ranges_json = ?, revision = ? WHERE workbook_id = ?", (_json(ranges), self.task["expected_answer"]["model_revision"], a["workbook_id"]))
            change_id = f"CHANGE-{a['task_id']}"
            self.connection.execute("INSERT OR REPLACE INTO workbook_changes VALUES (?, ?, ?, ?, ?)", (change_id, a["workbook_id"], a["task_id"], a["range"], _json(a["values"])))
            self._audit(tool, a["workbook_id"], a)
            return {"change_id": change_id, "updatedRange": a["range"], "updatedRows": len(a["values"])}
        if tool == "sheets.get_change_log":
            return {"changes": _rows(self.connection.execute("SELECT * FROM workbook_changes WHERE workbook_id = ? ORDER BY change_id", (a["workbook_id"],)).fetchall())}
        if tool == "markets.get_company":
            return self._one("SELECT * FROM companies WHERE company_id = ?", (a["company_id"],))
        if tool == "markets.list_comparables":
            return {"comparables": _rows(self.connection.execute("SELECT * FROM comparables WHERE project_code = ? ORDER BY ev_ebitda", (a["project_code"],)).fetchall()), "as_of": self.task["metadata"]["as_of"]}
        if tool == "markets.list_transactions":
            return {"transactions": _rows(self.connection.execute("SELECT * FROM transactions WHERE project_code = ? ORDER BY ev_ebitda", (a["project_code"],)).fetchall()), "as_of": self.task["metadata"]["as_of"]}
        if tool == "markets.get_credit_curve":
            return {"currency": a["currency"], "as_of": self.task["metadata"]["as_of"], "base_rate_pct": 4.25, "spread_pct": 3.15, "sponsor_return_floor_pct": 20.0, "return_horizon_years": 5, "source": "frozen synthetic financing desk curve"}
        if tool == "deals.get_project":
            project = self._one("SELECT * FROM projects WHERE project_code = ?", (a["project_code"],))
            project["linked_records"] = {
                "approval_id": f"APR-{a['project_code']}",
                "model_id": self.task["controlled_targets"]["model"]["id"],
                "deliverable_id": self.task["controlled_targets"]["deliverable"]["id"],
                "workbook_id": self.task["controlled_targets"]["workbook"]["id"],
                "channel": self.task["controlled_targets"]["communications"]["channel"],
            }
            return project
        if tool == "deals.get_model":
            model = self._one("SELECT * FROM models WHERE model_id = ?", (a["model_id"],))
            if model["model_id"] == self.task["controlled_targets"]["model"]["id"]:
                model.update(
                    {
                        "next_revision": self.task["expected_answer"]["model_revision"],
                        "required_output_keys": deepcopy(
                            self.task["controlled_targets"]["model"]["required_output_keys"]
                        ),
                    }
                )
            return model
        if tool == "deals.update_model":
            self._assert_task(a)
            current = self._one("SELECT project_code FROM models WHERE model_id = ?", (a["model_id"],))
            if not current or current["project_code"] != self.task["project_code"]:
                raise ValueError("model is outside the active project")
            if a["revision"] != self.task["expected_answer"]["model_revision"]:
                raise ValueError("revision does not match the model's declared next_revision")
            self.connection.execute("UPDATE models SET revision = ?, status = 'updated_for_review', outputs_json = ?, source_refs_json = ?, last_task_id = ? WHERE model_id = ?", (a["revision"], _json(a["outputs"]), _json(a["source_refs"]), a["task_id"], a["model_id"]))
            self._audit(tool, a["model_id"], a)
            return self._one("SELECT * FROM models WHERE model_id = ?", (a["model_id"],))
        if tool == "deals.list_bids":
            return {"bids": _rows(self.connection.execute("SELECT * FROM bids WHERE project_code = ? ORDER BY bid_id", (a["project_code"],)).fetchall())}
        if tool == "deals.update_bid_status":
            self._assert_task(a)
            cursor = self.connection.execute("UPDATE bids SET status = ?, rationale = ?, last_task_id = ? WHERE bid_id = ? AND project_code = ?", (a["status"], a["rationale"], a["task_id"], a["bid_id"], self.task["project_code"]))
            if cursor.rowcount != 1:
                raise ValueError("bid not found in active project")
            self._audit(tool, a["bid_id"], a)
            return self._one("SELECT * FROM bids WHERE bid_id = ?", (a["bid_id"],))
        if tool == "deals.list_diligence_findings":
            return {"findings": _rows(self.connection.execute("SELECT * FROM diligence_findings WHERE project_code = ? ORDER BY finding_id", (a["project_code"],)).fetchall())}
        if tool == "deals.update_diligence_finding":
            self._assert_task(a)
            cursor = self.connection.execute("UPDATE diligence_findings SET status = ?, resolution = ?, last_task_id = ? WHERE finding_id = ? AND project_code = ?", (a["status"], a["resolution"], a["task_id"], a["finding_id"], self.task["project_code"]))
            if cursor.rowcount != 1:
                raise ValueError("diligence finding not found in active project")
            self._audit(tool, a["finding_id"], a)
            return self._one("SELECT * FROM diligence_findings WHERE finding_id = ?", (a["finding_id"],))
        if tool == "deals.get_approval":
            return self._one("SELECT * FROM approvals WHERE approval_id = ?", (a["approval_id"],))
        if tool == "deals.request_approval":
            self._assert_task(a)
            cursor = self.connection.execute("UPDATE approvals SET status = ?, evidence_refs_json = ?, last_task_id = ? WHERE approval_id = ? AND project_code = ?", (a["status"], _json(a["evidence_refs"]), a["task_id"], a["approval_id"], self.task["project_code"]))
            if cursor.rowcount != 1:
                raise ValueError("approval not found in active project")
            self._audit(tool, a["approval_id"], a)
            return self._one("SELECT * FROM approvals WHERE approval_id = ?", (a["approval_id"],))
        if tool == "deals.get_deliverable":
            deliverable = self._one("SELECT * FROM deliverables WHERE deliverable_id = ?", (a["deliverable_id"],))
            if deliverable["deliverable_id"] == self.task["controlled_targets"]["deliverable"]["id"]:
                deliverable.update(
                    {
                        "next_revision": self.task["expected_answer"]["deliverable_revision"],
                        "required_value_keys": deepcopy(
                            self.task["controlled_targets"]["deliverable"]["required_value_keys"]
                        ),
                    }
                )
            return deliverable
        if tool == "deals.update_deliverable":
            self._assert_task(a)
            target = self.task["controlled_targets"]["deliverable"]
            if a["revision"] != self.task["expected_answer"]["deliverable_revision"]:
                raise ValueError("revision does not match the deliverable's declared next_revision")
            if a["status"] != target["status"]:
                raise ValueError("deliverable must remain draft_for_review")
            cursor = self.connection.execute("UPDATE deliverables SET revision = ?, status = ?, values_json = ?, last_task_id = ? WHERE deliverable_id = ? AND project_code = ?", (a["revision"], a["status"], _json(a["values"]), a["task_id"], a["deliverable_id"], self.task["project_code"]))
            if cursor.rowcount != 1:
                raise ValueError("deliverable not found in active project")
            self._audit(tool, a["deliverable_id"], a)
            return self._one("SELECT * FROM deliverables WHERE deliverable_id = ?", (a["deliverable_id"],))
        if tool == "deals.commit_plan":
            self._assert_task(a)
            if a["project_code"] != self.task["project_code"]:
                raise ValueError("plan is outside the active project")
            target = self.task["controlled_targets"]["plan"]
            if a["model_id"] != target["model_id"] or a["deliverable_id"] != target["deliverable_id"]:
                raise ValueError("plan references an uncontrolled model or deliverable")
            allowed_decisions = {option["id"] for option in self.task["decision_options"]}
            if a["decision"] not in allowed_decisions:
                raise ValueError("decision is not an allowed task option")
            allowed_statuses = self.task["answer_schema"]["properties"]["decision_status"]["enum"]
            if a["status"] not in allowed_statuses:
                raise ValueError("decision status is not allowed by the task contract")
            plan_id = f"PLAN-{a['task_id']}"
            self.connection.execute("INSERT OR REPLACE INTO plans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (plan_id, a["project_code"], a["task_id"], a["decision"], a["status"], a["rationale"], _json(a["source_refs"]), a["model_id"], a["deliverable_id"]))
            self._audit(tool, plan_id, a)
            return self._one("SELECT * FROM plans WHERE plan_id = ?", (plan_id,))
        if tool == "deals.get_committed_plan":
            return self._one("SELECT * FROM plans WHERE project_code = ? AND task_id = ?", (a["project_code"], a["task_id"]))
        raise ValueError(f"unimplemented tool: {tool}")


def grouped_tool_definitions(answer_schema: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for tool in tool_definitions(answer_schema):
        server = tool["_meta"]["dealbench"]["server"]
        grouped.setdefault(server, []).append(tool)
    return grouped
