#!/usr/bin/env python3
import json, os, urllib.request
from pathlib import Path
root = Path(__file__).resolve().parent
reference = json.loads((root / "reference.json").read_text())
base = os.environ.get("DEALBENCH_MCP_BASE", "http://world:8765/mcp")
servers = {"benchmark":"dealbench","dealroom":"dealroom","mail":"mail","chat":"chat","sheets":"spreadsheets","markets":"market_data","deals":"deal_management"}
for index, step in enumerate(reference["oracle_steps"], 1):
    server = servers[step["tool"].split(".", 1)[0]]
    payload = json.dumps({"jsonrpc":"2.0","id":index,"method":"tools/call","params":{"name":step["tool"],"arguments":step.get("arguments", {})}}).encode()
    request = urllib.request.Request(f"{base}/{server}", data=payload, headers={"Content-Type":"application/json"})
    response = json.loads(urllib.request.urlopen(request, timeout=60).read())
    if response.get("result", {}).get("isError"):
        raise SystemExit(json.dumps(response))
print(json.dumps({"completed": True, "steps": len(reference["oracle_steps"])}))
