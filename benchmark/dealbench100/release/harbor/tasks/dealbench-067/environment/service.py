#!/usr/bin/env python3
"""Streamable HTTP MCP service for one isolated DealBench task."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

try:
    from .world import DealWorld, grouped_tool_definitions
except ImportError:  # Copied into a standalone Harbor environment.
    from runtime import DealWorld, grouped_tool_definitions  # type: ignore[no-redef]

MAX_REQUEST_BYTES = 1_000_000
PROTOCOL_VERSION = "2025-06-18"


def _tool_result(result: dict[str, Any]) -> dict[str, Any]:
    response: dict[str, Any] = {
        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, sort_keys=True)}],
        "isError": "error" in result,
    }
    if "error" not in result:
        response["structuredContent"] = result
    return response


def mcp_response(
    world: DealWorld,
    tools_by_server: dict[str, list[dict[str, Any]]],
    server_name: str,
    request: dict[str, Any],
) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")
    if request_id is None and isinstance(method, str) and method.startswith("notifications/"):
        return None
    if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32600, "message": "Invalid Request"}}
    if server_name not in tools_by_server:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Unknown server"}}
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": f"dealbench-{server_name}", "version": str(world.task["benchmark_version"])},
                "instructions": "Operate only on this isolated synthetic deal world. Writes persist to task-local SQLite and outbound communications must remain review-only.",
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools_by_server[server_name]}}
    if method == "tools/call":
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        name = str(params.get("name", ""))
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        allowed = {tool["name"] for tool in tools_by_server[server_name]}
        result = world.call_tool(name, arguments) if name in allowed else {"error": f"tool {name!r} is not exposed by {server_name}"}
        return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(result)}
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}


class DealService(HTTPServer):
    world: DealWorld
    evidence_path: Path
    baseline: dict[str, list[dict[str, Any]]]
    tools_by_server: dict[str, list[dict[str, Any]]]

    def persist_evidence(self) -> None:
        temporary = self.evidence_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"baseline": self.baseline, "snapshot": self.world.snapshot(), "trace": self.world.trace},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(self.evidence_path)


class RequestHandler(BaseHTTPRequestHandler):
    server: DealService
    server_version = "DealBenchMCP/1.0"

    def log_message(self, *_: Any) -> None:
        return

    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("MCP-Protocol-Version", PROTOCOL_VERSION)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send(HTTPStatus.OK, {"status": "ok", "task_id": self.server.world.task["task_id"]})
        else:
            self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/mcp/"):
            self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        server_name = self.path.removeprefix("/mcp/")
        if server_name not in self.server.tools_by_server or self.path != f"/mcp/{server_name}":
            self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 1 or length > MAX_REQUEST_BYTES:
            self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request size"}})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            self._send(HTTPStatus.BAD_REQUEST, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            return
        if isinstance(payload, list):
            responses = [response for item in payload if isinstance(item, dict) and (response := mcp_response(self.server.world, self.server.tools_by_server, server_name, item)) is not None]
            self.server.persist_evidence()
            self._send(HTTPStatus.OK, responses)
            return
        if not isinstance(payload, dict):
            self._send(HTTPStatus.BAD_REQUEST, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
            return
        response = mcp_response(self.server.world, self.server.tools_by_server, server_name, payload)
        self.server.persist_evidence()
        if response is None:
            self.send_response(HTTPStatus.ACCEPTED)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send(HTTPStatus.OK, response)


def main() -> None:
    root = Path(os.environ.get("DEALBENCH_ROOT", "/opt/dealbench"))
    state_dir = Path(os.environ.get("DEALBENCH_STATE_DIR", "/var/lib/dealbench"))
    evidence_path = Path(os.environ.get("DEALBENCH_EVIDENCE_PATH", "/var/lib/dealbench-evidence/evidence.json"))
    os.umask(0o077)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    evidence_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    task = json.loads((root / "task.json").read_text(encoding="utf-8"))
    world = DealWorld.create(task, state_dir / "world.sqlite")
    bind_host = os.environ.get("DEALBENCH_BIND_HOST", "127.0.0.1")
    port = int(os.environ.get("DEALBENCH_PORT", "8765"))
    server = DealService((bind_host, port), RequestHandler)
    server.world = world
    server.evidence_path = evidence_path
    server.baseline = world.snapshot()
    server.tools_by_server = grouped_tool_definitions(task["answer_schema"])
    server.persist_evidence()
    try:
        server.serve_forever()
    finally:
        server.server_close()
        world.close()


if __name__ == "__main__":
    main()
