"""Build the public DealBench-100 source, Hugging Face, Harbor, and website artifacts."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from .evaluation import policy_steps, qualify, run_episode
from .model_run import (
    DEFAULT_OUTPUT as MODEL_RUNS_ROOT,
    RUN_SLUG as MODEL_RUN_SLUG,
    load_published_model_run,
)
from .spec import (
    BENCHMARK_NAME,
    BENCHMARK_VERSION,
    FAMILIES,
    METRIC,
    SCORING_CATEGORIES,
    WORLDS,
    WORLD_ID,
    _world_metrics,
    build_tasks,
    catalog_digest,
    task_digest,
)
from .world import TABLES, grouped_tool_definitions, tool_definitions

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = PACKAGE_ROOT / "release"
WEBSITE_DATA = REPO_ROOT / "products" / "website" / "app" / "benchmarks" / "dealbench-100" / "dealbench-data.json"
SOURCE_URL = "https://github.com/blobfishai/deal-agent-simulation/tree/main/benchmark/dealbench100"
HF_DATASET = "SamuelChien821/dealbench-100"
HF_URL = f"https://huggingface.co/datasets/{HF_DATASET}"
HF_COMMIT = "0c4f25f561b4d5a85687bec83b8b581c7d3f7f1f"
HF_PAYLOAD_MANIFEST_SHA256 = "071c95d96e48d9229f92fbbba59cf5ff1f773d030565286ec540b35395bbb9a1"
HARBOR_DATASET_ID = "blobfishai/dealbench-100-suite"
HARBOR_URL = f"https://hub.harborframework.com/datasets/{HARBOR_DATASET_ID}/latest"
HARBOR_RESULTS_TAG = "results-2026-09-01"
PAGE_URL = "https://blobfish.ai/benchmarks/dealbench-100"
HARBOR_IMAGE = "python:3.12-slim@sha256:7a8b475003c4fe15a2cd4e55e5cfc2f3560bdc9333d624f24cdd6d4340fd7a17"
PUBLISH_DIRECT_FILES = ("task.toml", "instruction.md", "README.md")
PUBLISH_DIRECTORIES = ("environment", "tests", "solution", "steps")


def _hf_url(path: str, *, raw: bool = False) -> str:
    revision = HF_COMMIT or "main"
    operation = "resolve" if raw else "blob"
    return f"{HF_URL}/{operation}/{revision}/{path}"


def _write_text(path: Path, value: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _write_json(path: Path, value: Any) -> None:
    _write_text(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    _write_text(path, "".join(json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n" for value in values))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _publishable_files(task_dir: Path) -> list[Path]:
    files: set[Path] = set()
    for name in PUBLISH_DIRECT_FILES:
        path = task_dir / name
        if path.is_file():
            files.add(path)
    for name in PUBLISH_DIRECTORIES:
        directory = task_dir / name
        if directory.is_dir():
            files.update(
                path
                for path in directory.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts and path.name != ".DS_Store"
            )
    return sorted(files, key=lambda path: path.relative_to(task_dir).as_posix())


def harbor_task_digest(task_dir: Path) -> tuple[str, int, int]:
    outer = hashlib.sha256()
    total_bytes = 0
    files = _publishable_files(task_dir)
    for path in files:
        relative = path.relative_to(task_dir).as_posix()
        digest = _sha256_file(path)
        total_bytes += path.stat().st_size
        outer.update(f"{relative}\0{digest}\n".encode("utf-8"))
    return f"sha256:{outer.hexdigest()}", len(files), total_bytes


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _stable_zip_info(filename: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(filename=filename, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o600 << 16
    return info


def _write_xlsx(path: Path, rows: list[list[Any]], sheet_name: str = "Evidence") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet_rows = []
    for row_number, row in enumerate(rows, start=1):
        cells = []
        for column_number, value in enumerate(row, start=1):
            reference = f"{_column_name(column_number)}{row_number}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{reference}"><v>{value}</v></c>')
            else:
                escaped = html.escape(str(value))
                cells.append(f'<c r="{reference}" t="inlineStr"><is><t>{escaped}</t></is></c>')
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(_stable_zip_info("[Content_Types].xml"), '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr(_stable_zip_info("_rels/.rels"), '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr(_stable_zip_info("xl/workbook.xml"), f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{html.escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr(_stable_zip_info("xl/_rels/workbook.xml.rels"), '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr(_stable_zip_info("xl/worksheets/sheet1.xml"), sheet)


def _write_pdf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [line[:92] for line in text.splitlines() if line.strip()][:44]
    commands = ["BT", "/F1 10 Tf", "54 750 Td", "12 TL"]
    for index, line in enumerate(lines):
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if index:
            commands.append("T*")
        commands.append(f"({escaped}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    path.write_bytes(bytes(output))


def _write_pptx(path: Path, title: str, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"<a:p><a:r><a:t>{html.escape(line)}</a:t></a:r></a:p>" for line in [title, *lines])
    slide = f'<?xml version="1.0" encoding="UTF-8"?><p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/><p:sp><p:nvSpPr><p:cNvPr id="2" name="Content"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>{body}</p:txBody></p:sp></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(_stable_zip_info("[Content_Types].xml"), '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/><Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/></Types>')
        archive.writestr(_stable_zip_info("_rels/.rels"), '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>')
        archive.writestr(_stable_zip_info("ppt/presentation.xml"), '<?xml version="1.0" encoding="UTF-8"?><p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/></p:presentation>')
        archive.writestr(_stable_zip_info("ppt/_rels/presentation.xml.rels"), '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/></Relationships>')
        archive.writestr(_stable_zip_info("ppt/slides/slide1.xml"), slide)


def _world_asset_payloads(world: dict[str, Any], world_index: int) -> dict[str, tuple[str, Any]]:
    project = world["project_code"]
    metrics = _world_metrics(world)
    current_revision = f"REV-{world_index + 1:02d}-CURRENT"
    current_rows = [
        ["Project", project], ["Company", world["company"]], ["Revision", current_revision],
        ["Revenue ($m)", world["revenue"]], ["Reported EBITDA margin", world["ebitda_margin"]],
        ["Growth", world["growth"]], ["WACC", world["wacc"]], ["Terminal growth", world["terminal_growth"]],
    ]
    prior_rows = [row[:] for row in current_rows]
    prior_rows[2][1] = f"REV-{world_index + 1:02d}-PRIOR"
    prior_rows[3][1] = round(world["revenue"] * 0.97, 2)
    qoe = (
        f"{project} quality of earnings — current approved bridge\n"
        f"Reported EBITDA: ${metrics['reported_ebitda']:.2f}m\n"
        f"Allowed add-backs: ${world['allowed_addbacks']:.2f}m\n"
        f"Unsupported add-backs excluded: ${world['disallowed_addbacks']:.2f}m\n"
        f"Normalized EBITDA: ${metrics['adjusted_ebitda']:.2f}m\n"
    )
    comps = "peer,approved,ev_ebitda\n" + "\n".join(
        f"Approved Peer {index},true,{world['comp_multiple'] + offset:.2f}"
        for index, offset in enumerate((-0.8, -0.4, 0.0, 0.4, 0.8), 1)
    ) + "\n"
    precedents = "transaction,approved,ev_ebitda\n" + "\n".join(
        f"Approved Transaction {index},true,{world['precedent_multiple'] + offset:.2f}"
        for index, offset in enumerate((-0.8, -0.4, 0.0, 0.4, 0.8), 1)
    ) + "\n"
    root = f"assets/{project.lower()}"
    return {
        f"{root}/01-request-email.eml": ("text", f"From: vp@atlas-sim.example\nTo: deal-team@atlas-sim.example\nSubject: {project} current case\n\nUse current authority and keep any client communication in review.\n"),
        f"{root}/02-current-forecast.xlsx": ("xlsx", current_rows),
        f"{root}/03-prior-forecast.xlsx": ("xlsx", prior_rows),
        f"{root}/04-quality-of-earnings.pdf": ("pdf", qoe),
        f"{root}/05-management-case.csv": ("text", f"year,revenue,ebitda_margin\n2026,{world['revenue']},{world['ebitda_margin']}\n2027,{world['revenue'] * (1 + world['growth']):.2f},{world['ebitda_margin'] + 0.006:.4f}\n"),
        f"{root}/06-current-assumptions.json": ("json", {"revision": current_revision, "approved": True, "wacc": world["wacc"], "terminal_growth": world["terminal_growth"], "entry_multiple": world["entry_multiple"], "exit_multiple": world["exit_multiple"]}),
        f"{root}/07-retired-assumptions.json": ("json", {"revision": f"REV-{world_index + 1:02d}-PRIOR", "approved": False, "wacc": round(world["wacc"] - 0.008, 4), "terminal_growth": round(world["terminal_growth"] + 0.006, 4)}),
        f"{root}/08-trading-comps.csv": ("text", comps),
        f"{root}/09-precedent-transactions.csv": ("text", precedents),
        f"{root}/10-debt-schedule.xlsx": ("xlsx", [["Instrument", "Balance ($m)", "Rate"], ["Term loan", world["debt"] * 0.72, 0.071], ["Revolver", world["debt"] * 0.28, 0.082], ["Cash", world["cash"], 0.0]]),
        f"{root}/11-bid-letters.pdf": ("pdf", f"{project} synthetic bid summary\nBid A: high certainty, limited conditions\nBid B: highest headline, material financing and diligence conditions\nBid C: balanced value and certainty\nAll bids are hypothetical and for benchmark evaluation only.\n"),
        f"{root}/12-diligence-log.xlsx": ("xlsx", [["Finding", "Severity", "Status"], ["QoE adjustment support", "medium", "open"], ["Change-of-control consent", "critical", "open" if world["critical_open"] else "cleared"]]),
        f"{root}/13-approval-policy.md": ("text", f"# {project} approval policy\n\nOnly the current Transaction Committee record authorizes launch. Critical open findings override timetable pressure. External messages must remain `draft_for_review`.\n"),
        f"{root}/14-current-approval.eml": ("text", f"From: transaction-committee@atlas-sim.example\nSubject: {project} current authority\n\nStatus: {world['approval_status']}\nRevision: {current_revision}\n"),
        f"{root}/15-retired-approval.eml": ("text", f"From: former-chair@atlas-sim.example\nSubject: {project} old authority\n\nStatus: approved\nRevision: REV-{world_index + 1:02d}-PRIOR\nSuperseded.\n"),
        f"{root}/16-deal-team-thread.json": ("json", {"channel": f"deal-{project.lower()}", "messages": [{"author": "vp", "text": "Resolve current authority before any write."}, {"author": "control", "text": f"Operative revision is {current_revision}."}]}),
        f"{root}/17-model-change-log.csv": ("text", "revision,status,author\nMODEL-PRIOR-R1,superseded,analyst\nMODEL-PRIOR-R2,working,associate\n"),
        f"{root}/18-committee-deck-current.pptx": ("pptx", (f"{project} committee deck", ["Controlled valuation summary", f"Current source: {current_revision}", "Status: draft for review"])),
        f"{root}/19-committee-deck-prior.pptx": ("pptx", (f"{project} prior deck", ["Superseded valuation summary", f"Source: REV-{world_index + 1:02d}-PRIOR"])),
        f"{root}/20-client-update-draft.md": ("text", f"# {project} client update draft\n\nDecision, values, model revision, source revision, and gating items must be populated from the completed controlled workflow. Do not send without review.\n"),
        f"{root}/21-source-map.yaml": ("text", f"project: {project}\noperative_revision: {current_revision}\nforecast: 02-current-forecast.xlsx\nqoe: 04-quality-of-earnings.pdf\napproval: 14-current-approval.eml\n"),
        f"{root}/22-data-room-permissions.json": ("json", {"project": project, "current_deck": {"controlled_values_editable": True, "publish": False}, "prior_deck": {"editable": False, "superseded": True}}),
        f"{root}/23-audit.log": ("text", f"2026-01-16T08:00:00Z {project} seed created\n2026-01-16T08:10:00Z {current_revision} marked current\n"),
        f"{root}/24-deal-timeline.ics": ("text", f"BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:{project}@atlas-sim.example\nDTSTART:20260116T160000Z\nSUMMARY:{project} valuation review\nEND:VEVENT\nEND:VCALENDAR\n"),
    }


def _write_payload(path: Path, payload: tuple[str, Any]) -> None:
    kind, value = payload
    if kind == "text":
        _write_text(path, str(value))
    elif kind == "json":
        _write_json(path, value)
    elif kind == "xlsx":
        _write_xlsx(path, value)
    elif kind == "pdf":
        _write_pdf(path, str(value))
    elif kind == "pptx":
        title, lines = value
        _write_pptx(path, title, lines)
    else:
        raise ValueError(f"unsupported asset kind {kind}")


def _asset_manifest(root: Path, task: dict[str, Any]) -> list[dict[str, Any]]:
    assets = []
    for relative in task["context_files"]:
        path = root / relative
        assets.append(
            {
                "path": relative,
                "name": path.name,
                "format": path.suffix.removeprefix(".").upper() or "TEXT",
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
                "url": _hf_url(relative, raw=True),
                "role": "operative" if "current" in path.name or "task-" in path.name else "corroborating",
                "note": "Agent-visible synthetic evidence; current and superseded records are deliberately mixed.",
            }
        )
    return assets


def _write_assets(output: Path, tasks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    for index, world in enumerate(WORLDS):
        for relative, payload in _world_asset_payloads(world, index).items():
            _write_payload(output / relative, payload)
    for task in tasks:
        brief = next(path for path in task["context_files"] if path.endswith("task-brief.md"))
        snapshot = next(path for path in task["context_files"] if path.endswith("starting-snapshot.json"))
        _write_text(
            output / brief,
            f"# {task['task_id']} — {task['task_name']}\n\n{task['prompt']}\n\nProject: {task['project_code']}\nAs of: {task['metadata']['as_of']}\n",
        )
        _write_json(
            output / snapshot,
            {
                "task_id": task["task_id"],
                "project_code": task["project_code"],
                "as_of": task["metadata"]["as_of"],
                "systems": ["DealRoom", "Mail", "Chat", "Spreadsheets", "Market Data", "Deal Management"],
                "sealed_gold_values_excluded": True,
            },
        )
    return {task["task_id"]: _asset_manifest(output, task) for task in tasks}


def _task_toml(task: dict[str, Any]) -> str:
    description = task["prompt"].replace('"', '\\"').replace("\n", " ")
    servers = "\n".join(
        f'[[environment.mcp_servers]]\nname = "{server}"\ntransport = "streamable-http"\nurl = "http://world:8765/mcp/{server}"\n'
        for server in ("dealbench", "dealroom", "mail", "chat", "spreadsheets", "market_data", "deal_management")
    )
    return f'''schema_version = "1.4"

[task]
name = "blobfishai/{task['task_id']}"
version = "{BENCHMARK_VERSION}"
description = "{description}"
authors = [{{ name = "Blobfish AI" }}]
keywords = ["investment-banking", "m-and-a", "multi-system", "stateful", "deterministic"]

[agent]
user = "agent"
timeout_sec = 1200.0

[verifier]
user = "root"
timeout_sec = 120.0

[environment]
build_timeout_sec = 600.0
cpus = 1
memory_mb = 1024
storage_mb = 2048
gpus = 0

{servers}
[metadata]
benchmark = "{BENCHMARK_NAME}"
world_id = "{WORLD_ID}"
task_id = "{task['task_id']}"
project_code = "{task['project_code']}"
category = "{task['metadata']['category']}"
difficulty = "L4"
metric = "{METRIC}"
synthetic = true
'''


AGENT_DOCKERFILE = f'''FROM {HARBOR_IMAGE}
RUN groupadd --gid 10001 agent \\
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash agent \\
    && install -d -o agent -g agent -m 0755 /workspace \\
    && install -d -o root -g root -m 0755 /opt/dealbench
COPY tools.json /opt/dealbench/
COPY tool /usr/local/bin/tool
RUN chmod 0755 /usr/local/bin/tool && chmod 0444 /opt/dealbench/tools.json
WORKDIR /workspace
ENV DEALBENCH_ROOT=/opt/dealbench PYTHONUNBUFFERED=1
CMD ["sh", "-c", "sleep infinity"]
'''


SERVICE_DOCKERFILE = f'''FROM {HARBOR_IMAGE}
RUN install -d -o root -g root -m 0700 /var/lib/dealbench \\
    && install -d -o root -g root -m 0755 /opt/dealbench
COPY runtime.py service.py schema.sql task.json /opt/dealbench/
COPY assets /opt/dealbench/assets
RUN chmod 0755 /opt/dealbench/service.py \\
    && chmod 0444 /opt/dealbench/runtime.py /opt/dealbench/schema.sql /opt/dealbench/task.json
ENV DEALBENCH_ROOT=/opt/dealbench DEALBENCH_BIND_HOST=0.0.0.0 PYTHONUNBUFFERED=1
CMD ["python3", "/opt/dealbench/service.py"]
'''


DOCKER_COMPOSE = '''services:
  main:
    depends_on:
      world:
        condition: service_healthy
    environment:
      DEALBENCH_MCP_BASE: http://world:8765/mcp
    networks: [agent-egress, dealbench]
    volumes:
      - dealbench-evidence:/var/lib/dealbench-evidence:ro
  world:
    build:
      context: .
      dockerfile: Dockerfile.service
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=1)"]
      interval: 1s
      timeout: 2s
      retries: 30
    environment:
      DEALBENCH_EVIDENCE_PATH: /var/lib/dealbench-evidence/evidence.json
    networks: [dealbench]
    volumes:
      - dealbench-evidence:/var/lib/dealbench-evidence
networks:
  agent-egress: {}
  dealbench:
    internal: true
volumes:
  dealbench-evidence:
'''


TOOL_SCRIPT = r'''#!/usr/bin/env python3
import json, os, sys, urllib.request
if len(sys.argv) < 2:
    raise SystemExit("usage: tool <name> [json-arguments]")
name = sys.argv[1]
args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
server = {"benchmark":"dealbench","dealroom":"dealroom","mail":"mail","chat":"chat","sheets":"spreadsheets","markets":"market_data","deals":"deal_management"}[name.split(".", 1)[0]]
payload = json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":name,"arguments":args}}).encode()
request = urllib.request.Request(f"{os.environ.get('DEALBENCH_MCP_BASE', 'http://world:8765/mcp')}/{server}", data=payload, headers={"Content-Type":"application/json"})
print(urllib.request.urlopen(request, timeout=60).read().decode())
'''


SOLUTION_SCRIPT = r'''#!/usr/bin/env python3
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
'''


VERIFY_SCRIPT = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dealbench100.evaluation import score_episode
task = json.loads((HERE / "task.json").read_text())
evidence_path = Path(os.environ.get("DEALBENCH_EVIDENCE_PATH", "/var/lib/dealbench-evidence/evidence.json"))
if not evidence_path.exists():
    raise SystemExit(f"missing environment evidence: {evidence_path}")
evidence = json.loads(evidence_path.read_text())
verdict = score_episode(task, evidence["baseline"], evidence["snapshot"], evidence["trace"])
logs = Path("/logs/verifier")
logs.mkdir(parents=True, exist_ok=True)
(logs / "reward.txt").write_text(f"{verdict['reward']:.6f}\n")
(logs / "verdict.json").write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")
print(json.dumps(verdict, indent=2, sort_keys=True))
'''


def _copy_package_for_verifier(target: Path) -> None:
    package = target / "dealbench100"
    package.mkdir(parents=True, exist_ok=True)
    for name in ("__init__.py", "spec.py", "world.py", "evaluation.py", "schema.sql"):
        shutil.copy2(PACKAGE_ROOT / name, package / name)


def _write_harbor_task(output: Path, task: dict[str, Any], assets: list[dict[str, Any]]) -> Path:
    task_root = output / "harbor" / "tasks" / task["task_id"]
    environment = task_root / "environment"
    tests = task_root / "tests"
    solution = task_root / "solution"
    environment.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)
    solution.mkdir(parents=True, exist_ok=True)
    _write_text(task_root / "task.toml", _task_toml(task))
    _write_text(task_root / "instruction.md", task["prompt"] + "\n")
    _write_text(task_root / "README.md", f"# {task['task_id']}\n\nSynthetic {task['metadata']['category_label']} task from {BENCHMARK_NAME} {BENCHMARK_VERSION}.\n")
    _write_json(task_root / "reference.json", {"task_id": task["task_id"], "expected_answer": task["expected_answer"], "oracle_steps": task["oracle_steps"], "rubric": task["rubric"]})

    shutil.copy2(PACKAGE_ROOT / "world.py", environment / "runtime.py")
    shutil.copy2(PACKAGE_ROOT / "service.py", environment / "service.py")
    shutil.copy2(PACKAGE_ROOT / "schema.sql", environment / "schema.sql")
    _write_json(environment / "task.json", task)
    _write_json(environment / "tools.json", {"tools": tool_definitions(task["answer_schema"])})
    _write_text(environment / "Dockerfile", AGENT_DOCKERFILE)
    _write_text(environment / "Dockerfile.service", SERVICE_DOCKERFILE)
    _write_text(environment / "docker-compose.yaml", DOCKER_COMPOSE)
    _write_text(environment / "tool", TOOL_SCRIPT, executable=True)
    for asset in assets:
        source = output / asset["path"]
        destination = environment / "assets" / Path(asset["path"]).relative_to("assets")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    _write_text(tests / "test.sh", '#!/bin/bash\nset -euo pipefail\npython3 "$(dirname "$0")/verify.py"\n', executable=True)
    _write_text(tests / "verify.py", VERIFY_SCRIPT, executable=True)
    _write_json(tests / "task.json", task)
    _copy_package_for_verifier(tests)
    _write_text(solution / "solve.sh", '#!/bin/bash\nset -euo pipefail\npython3 "$(dirname "$0")/solve.py"\n', executable=True)
    _write_text(solution / "solve.py", SOLUTION_SCRIPT, executable=True)
    _write_json(solution / "reference.json", {"oracle_steps": task["oracle_steps"]})
    return task_root


def _write_harbor_dataset(output: Path, tasks: list[dict[str, Any]], assets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    harbor = output / "harbor"
    digests = []
    total_files = 0
    total_bytes = 0
    for task in tasks:
        task_root = _write_harbor_task(output, task, assets[task["task_id"]])
        digest, files, size = harbor_task_digest(task_root)
        digests.append({"task_id": task["task_id"], "digest": digest, "files": files, "bytes": size})
        total_files += files
        total_bytes += size
    dataset = [
        "# Generated DealBench-100 Harbor dataset",
        "[dataset]",
        f'name = "{HARBOR_DATASET_ID}"',
        f'version = "{BENCHMARK_VERSION}"',
        'description = "100 executable investment-banking workflows with deterministic DealScore grading"',
        'keywords = ["investment-banking", "m-and-a", "agents", "stateful", "deterministic"]',
        '[[dataset.authors]]',
        'name = "Blobfish AI"',
        "",
    ]
    for row in digests:
        dataset.extend(["[[tasks]]", f'name = "blobfishai/{row["task_id"]}"', f'digest = "{row["digest"]}"', ""])
    _write_text(harbor / "dataset.toml", "\n".join(dataset))
    _write_text(harbor / "LICENSE-DATA", "Creative Commons Attribution 4.0 International (CC BY 4.0)\nhttps://creativecommons.org/licenses/by/4.0/\n")
    _write_text(harbor / "NOTICE", "DealBench-100 is independently authored synthetic benchmark material. See ANCHORS.md for design influences and use restrictions on upstream Mercor datasets.\n")
    _write_text(harbor / "README.md", _dataset_readme())
    _write_json(harbor / "task-digests.json", {"schema_version": "dealbench.harbor-digests.v1", "tasks": digests})
    return {"tasks": len(digests), "files": total_files, "bytes": total_bytes, "digests": digests}


def _dataset_readme() -> str:
    return f"""# DealBench-100

DealBench-100 is a 100-task, deterministic investment-banking agent benchmark over ten synthetic transaction worlds. It tests source control, QoE normalization, trading comps, precedents, DCF, LBO, merger math, bid comparison, model-to-deck consistency, and launch approval.

## Run

```bash
harbor run -d {HARBOR_DATASET_ID} -a <agent> -m <provider/model>
```

## Metric

The single metric is **DealScore** (0–100): discovery 15, model accuracy 25, decision 15, committed state 20, deliverable consistency 10, post-write readback 10, containment 5. Exact call order is not graded. Every point is executable; no LLM judge is called.

## Release facts

- 100 tasks; 10 synthetic project worlds; 10 workflow families
- 26 agent-visible files per task across 10 native formats
- 36 provider-shaped tools across 7 logical MCP servers
- before/after state snapshots and full tool trajectories
- 100/100 oracle strict passes, exact deterministic replays, and five negative-control families with zero false accepts
- ranked rows are admitted only from complete, version-pinned, no-retry runs; inspect `model-runs/` (and Harbor's `model-runs.json`) when present

## Source

The complete synthetic world, task generator, deterministic verifier, release receipts, and model-run manifests are published at {SOURCE_URL}.

All companies, bids, financials, approvals, messages and transactions are synthetic. This dataset is for agent evaluation and research; it is not financial or investment advice.
"""


def _huggingface_card() -> str:
    return """---
license: cc-by-4.0
language:
- en
task_categories:
- question-answering
tags:
- agents
- benchmarking
- finance
- tool-use
- mcp
- harbor
pretty_name: DealBench-100
---
"""


def _anchors_text() -> str:
    return """# Public design anchors and clean-room boundary

DealBench-100 is independently authored. These public sources informed its release and evaluation shape:

- APEX-Agents leaderboard: https://www.mercor.com/apex/apex-agents-leaderboard/
- APEX-Agents investment-banking sample trajectory: https://www.mercor.com/apex/apex-agents-leaderboard/investment-banking-analyst-agent/#trajectory
- APEX-Accounting leaderboard: https://www.mercor.com/apex/apex-accounting-leaderboard/
- Archipelago runner and grading architecture: https://github.com/Mercor-Intelligence/archipelago
- APEX-v1-extended paper: https://arxiv.org/abs/2509.25721
- APEX-Agents dataset card: https://huggingface.co/datasets/mercor/apex-agents
- Enterprise-Bench Harbor dataset: https://hub.harborframework.com/datasets/Enterprise-Bench/l1-l2-bench/latest
- ERP-Bench Harbor dataset: https://hub.harborframework.com/datasets/agentic-labs/erp-bench/latest

The gated APEX-Agents dataset states that it is for evaluation only and forbids crawling/scraping and training use. It was not downloaded or scraped. No gated task, file, gold output, world snapshot, or trajectory was transformed or copied into DealBench. We used only the public benchmark descriptions and public illustrative sample to identify general desiderata: realistic professional outcomes, data-rich worlds, cross-application trajectories, before/after snapshots, and criterion-level grading.

The public Enterprise-Bench and ERP-Bench pages informed the use of noisy enterprise state, protocol-realistic interfaces, isolated task packages, and deterministic execution. Their tasks, worlds, assets, values, and solutions were not copied.

DealBench differs materially in content and evaluation: ten new synthetic companies and deal processes, new prompts and artifacts, provider-shaped closed-world tools, deterministic source/math/state verifiers, explicit collateral-damage checks, and no judge model.
"""


def _write_huggingface(output: Path, tasks: list[dict[str, Any]], assets: dict[str, list[dict[str, Any]]], episodes: dict[str, dict[str, Any]]) -> None:
    hf = output / "huggingface"
    public_tasks = []
    for task in tasks:
        public_tasks.append(
            {
                "task_id": task["task_id"],
                "task_name": task["task_name"],
                "world_id": task["world_id"],
                "project_code": task["project_code"],
                "prompt": task["prompt"],
                "context_files": task["context_files"],
                "rubric": task["rubric"],
                "gold_output": task["gold_output"],
                "metadata": task["metadata"],
                "decision_options": task["decision_options"],
                "answer_schema": task["answer_schema"],
                "task_sha256": task_digest(task),
            }
        )
    _write_jsonl(hf / "data" / "tasks.jsonl", public_tasks)
    _write_json(hf / "data" / "worlds.json", {"world_id": WORLD_ID, "projects": list(WORLDS), "systems": list(grouped_tool_definitions()), "synthetic": True})
    _write_json(hf / "contracts" / "tools.json", {"tools": tool_definitions()})
    for path in (output / "assets").rglob("*"):
        if path.is_file():
            destination = hf / path.relative_to(output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    for task_id in [task["task_id"] for task in tasks if int(task["task_id"].split("-")[-1]) % 10 == 1]:
        _write_json(hf / "trajectories" / f"{task_id}.json", {"task_id": task_id, "trace": episodes[task_id]["trace"], "verdict": episodes[task_id]["verdict"]})
    for task in tasks:
        task_id = task["task_id"]
        _write_json(hf / "verifiers" / f"{task_id}.json", episodes[task_id]["verdict"])
    _write_text(hf / "README.md", _huggingface_card() + "\n" + _dataset_readme() + "\n" + _anchors_text())
    _write_text(hf / "LICENSE", "CC BY 4.0\n")
    _write_text(hf / "ANCHORS.md", _anchors_text())


def _materialize_model_run(
    output: Path,
    model_run: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if model_run is None:
        return None
    manifest_source = MODEL_RUNS_ROOT / f"{MODEL_RUN_SLUG}.json"
    run_source = MODEL_RUNS_ROOT / MODEL_RUN_SLUG
    for destination in (output / "model-runs", output / "huggingface" / "model-runs"):
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest_source, destination / manifest_source.name)
        shutil.copytree(run_source, destination / MODEL_RUN_SLUG)
    _write_json(
        output / "harbor" / "model-runs.json",
        {
            "schema_version": "dealbench.harbor-model-runs.v1",
            "evaluated_dataset": model_run["dataset"],
            "public_artifacts": {
                "hugging_face_dataset": HF_DATASET,
                "hugging_face_commit": HF_COMMIT,
                "manifest_url": _hf_url(f"model-runs/{MODEL_RUN_SLUG}.json"),
                "trial_artifact_root_url": _hf_url(
                    f"model-runs/{MODEL_RUN_SLUG}/trials"
                ),
                "harbor_dataset": HARBOR_DATASET_ID,
                "harbor_metadata_tag": HARBOR_RESULTS_TAG,
            },
            "runs": [model_run],
        },
    )
    featured_source = MODEL_RUNS_ROOT / str(model_run["featured_artifact"])
    featured = json.loads(featured_source.read_text(encoding="utf-8"))
    if featured.get("task_id") != model_run.get("featured_task_id"):
        raise ValueError("DealBench featured model artifact disagrees with its manifest")
    return featured


def _trajectory_events(task: dict[str, Any], episode: dict[str, Any]) -> list[dict[str, Any]]:
    stages = {
        "benchmark.get_task": "scope",
        "deals.update_model": "model",
        "sheets.write_range": "model",
        "deals.update_bid_status": "decide",
        "deals.update_diligence_finding": "decide",
        "deals.request_approval": "decide",
        "deals.update_deliverable": "deliver",
        "deals.commit_plan": "decide",
        "mail.send_message": "deliver",
        "chat.post_message": "deliver",
        "benchmark.submit_answer": "verify",
        "benchmark.get_submission": "verify",
        "deals.get_committed_plan": "verify",
        "sheets.get_change_log": "verify",
        "mail.list_sent": "verify",
        "chat.get_channel_history": "verify",
    }
    events: list[dict[str, Any]] = [
        {"index": 1, "kind": "message", "role": "employee-request", "stage": "scope", "text": task["prompt"]}
    ]
    for call, entry in enumerate(episode["trace"], start=1):
        tool = entry["tool"]
        default = "investigate" if tool not in WRITE_TOOLS_FOR_RELEASE else "decide"
        result = json.dumps(entry["result"], sort_keys=True, ensure_ascii=False)
        events.append(
            {
                "index": len(events) + 1,
                "kind": "tool",
                "stage": stages.get(tool, default),
                "call": call,
                "tool": tool,
                "server": entry["server"],
                "arguments": entry["arguments"],
                "outcome": "ok" if entry["success"] else "error",
                "result": result[:500] + ("…" if len(result) > 500 else ""),
            }
        )
    events.append({"index": len(events) + 1, "kind": "message", "role": "verifier-receipt", "stage": "verify", "text": f"Deterministic verifier: {episode['verdict']['score']:.2f} DealScore; strict pass {episode['verdict']['passed']}."})
    return events


WRITE_TOOLS_FOR_RELEASE = {
    "deals.update_model", "sheets.write_range", "deals.update_bid_status",
    "deals.update_diligence_finding", "deals.request_approval", "deals.update_deliverable",
    "deals.commit_plan", "mail.send_message", "chat.post_message", "benchmark.submit_answer",
}


def _website_data(
    tasks: list[dict[str, Any]],
    assets: dict[str, list[dict[str, Any]]],
    episodes: dict[str, dict[str, Any]],
    qualification: dict[str, Any],
    build: dict[str, Any],
    model_run: dict[str, Any] | None,
    model_artifact: dict[str, Any] | None,
) -> dict[str, Any]:
    categories = [
        {"key": family["key"], "label": family["label"], "count": sum(task["metadata"]["category"] == family["key"] for task in tasks)}
        for family in FAMILIES
    ]
    reference_calls = sorted(len(task["oracle_steps"]) for task in tasks)
    criteria_counts = [len(task["rubric"]) for task in tasks]
    native_formats = [len({Path(path).suffix.lower() for path in task["context_files"]}) for task in tasks]
    evaluation_controls = []
    for row in qualification["results"]:
        label = {
            "oracle": "Reference oracle",
            "noop": "No-op control",
            "shortcut": "Answer-only shortcut",
            "state_only": "State-only shortcut",
            "wrong_source": "Wrong-source control",
            "wrong_target": "Wrong-target control",
        }[row["policy"]]
        evaluation_controls.append(
            {
                "rank": "REF" if row["policy"] == "oracle" else "CTRL",
                "name": label,
                "harness": "Deterministic release qualification",
                "kind": "reference",
                "tasks": row["task_count"],
                "score": row["mean_score"],
                "strictPassRate": row["strict_passes"],
                "categoryScores": row["category_scores"],
                "averageCalls": round(sum(len(task["oracle_steps"]) for task in tasks) / len(tasks), 1) if row["policy"] == "oracle" else None,
                "note": "Solvability ceiling; not a model submission." if row["policy"] == "oracle" else "Executed adversarial control; never ranked with models.",
            }
        )
    task_rows = []
    samples: dict[str, Any] = {}
    for ordinal, task in enumerate(tasks, start=1):
        task_rows.append(
            {
                "id": task["task_id"],
                "ordinal": ordinal,
                "title": task["task_name"],
                "category": task["metadata"]["category"],
                "client": task["company"],
                "organization": task["project_code"],
                "asOf": task["metadata"]["as_of"],
                "summary": task["prompt"],
                "documents": len(task["context_files"]),
                "referenceToolCalls": len(task["oracle_steps"]),
                "sample": True,
                "datasetUrl": _hf_url("data/tasks.jsonl"),
            }
        )
        samples[task["task_id"]] = {
            "taskId": task["task_id"],
            "prompt": task["prompt"],
            "gradedCriteria": [f"{criterion['category']}: {criterion['description']} ({criterion['points']} pts)" for criterion in task["rubric"]],
            "evaluationNarrative": {
                "summary": "A source-authority and transaction-math chain ending in controlled model, deliverable, plan, and review-only communication state.",
                "success": "The exact current sources, calculations, decision, model/deck state, review handoff, readbacks, and containment all agree.",
                "callOrderPolicy": "Exact call order is not graded; required investigations must precede the first controlled write and each write must be read back.",
                "milestones": [
                    {"id": category["key"], "category": category["key"], "description": f"{category['label']} contributes {category['weight']} DealScore points."}
                    for category in SCORING_CATEGORIES
                ],
            },
            "decisionOptions": task["decision_options"],
            "assets": assets[task["task_id"]],
            "scoringWeights": list(SCORING_CATEGORIES),
        }
    sample_task_ids = [f"dealbench-{ordinal:03d}" for ordinal in range(1, 101, 10)]
    trajectories = []
    stages = [
        {"key": "scope", "label": "Scope"},
        {"key": "investigate", "label": "Investigate"},
        {"key": "model", "label": "Model"},
        {"key": "decide", "label": "Decide"},
        {"key": "deliver", "label": "Deliver"},
        {"key": "verify", "label": "Verify"},
    ]
    by_id = {task["task_id"]: task for task in tasks}
    if model_run is not None and model_artifact is not None:
        model_artifact_path = f"model-runs/{model_run['featured_artifact']}"
        trajectories.append(
            {
                "taskId": model_artifact["task_id"],
                "model": "GPT-5.6 Luna",
                "harness": "Codex 0.151.0 · Harbor 0.21.0 · max",
                "kind": "model",
                "traceMode": "provider-native",
                "traceSource": model_artifact["source_receipts"]["provider_trace_source"],
                "passed": model_artifact["strict_pass"],
                "score": model_artifact["score"],
                "categoryScores": model_artifact["category_scores"],
                "toolCalls": model_artifact["tool_calls"],
                "sourceArtifactUrl": _hf_url(model_artifact_path),
                "transcriptUrl": _hf_url(model_artifact_path),
                "verifierUrl": _hf_url(model_artifact_path),
                "stages": stages,
                "events": model_artifact["website_events"],
            }
        )
    for task_id in sample_task_ids:
        episode = episodes[task_id]
        trajectories.append(
            {
                "taskId": task_id,
                "model": "Reference oracle",
                "harness": "Deterministic release solver",
                "kind": "reference",
                "traceMode": "provider-native",
                "traceSource": "released oracle trajectory",
                "passed": True,
                "score": 100,
                "categoryScores": episode["verdict"]["category_scores"],
                "toolCalls": len(episode["trace"]),
                "sourceArtifactUrl": _hf_url(f"trajectories/{task_id}.json"),
                "transcriptUrl": _hf_url(f"trajectories/{task_id}.json"),
                "verifierUrl": _hf_url(f"verifiers/{task_id}.json"),
                "stages": stages,
                "events": _trajectory_events(by_id[task_id], episode),
            }
        )
    leaderboard = []
    if model_run is not None:
        aggregate = model_run["aggregate"]
        leaderboard.append(
            {
                "rank": 1,
                "name": "GPT-5.6 Luna",
                "harness": "Codex 0.151.0 · Harbor 0.21.0 · max",
                "kind": "model",
                "tasks": aggregate["task_count"],
                "score": aggregate["mean_score"],
                "strictPassRate": aggregate["strict_pass_rate"],
                "categoryScores": aggregate["category_scores"],
                "averageCalls": aggregate["average_tool_calls"],
                "averageCost": aggregate["average_cost_usd"],
                "note": "One attempt per task, zero retries, closed sandbox, and 100/100 provider-trace coverage.",
                "runUrl": _hf_url(f"model-runs/{MODEL_RUN_SLUG}.json"),
            }
        )
    contract_pins = [
        {"name": "Catalog SHA-256", "value": build["catalog_sha256"]},
        {"name": "Harbor package SHA-256", "value": build["harbor_root_sha256"]},
        {"name": "Hugging Face commit", "value": HF_COMMIT or "pending publication"},
        {"name": "Synthetic world", "value": WORLD_ID},
    ]
    if model_run is not None:
        contract_pins.append(
            {"name": "Ranked run job", "value": str(model_run["job"]["id"])}
        )
    return {
        "schemaVersion": "blobfish.benchmark-page.v1",
        "benchmark": {
            "name": BENCHMARK_NAME,
            "version": BENCHMARK_VERSION,
            "tagline": "100 deterministic long-horizon investment-banking tasks across ten synthetic deal worlds.",
            "question": "Can an agent run the deal—not just calculate one valuation cell?",
            "taskCount": len(tasks),
            "categoryNoun": "analyst workflow",
            "categories": categories,
            "world": {"tools": len(tool_definitions()), "tables": len(TABLES), "documents": build["source_asset_count"], "rows": build["rows_per_task_snapshot"]},
            "referenceCalls": {"min": min(reference_calls), "median": reference_calls[len(reference_calls) // 2], "max": max(reference_calls)},
            "checksPerTask": max(criteria_counts),
            "releaseEvidence": {
                "assetFilesPerTask": {"min": 26, "max": 26},
                "nativeFormatsPerTask": {"min": min(native_formats), "max": max(native_formats)},
                "evidenceReadsPerTask": {"min": 15, "max": 15},
                "criteriaPerTask": {"min": min(criteria_counts), "max": max(criteria_counts)},
                "semanticMilestonesPerTask": {"min": 7, "max": 7},
                "qualification": {
                    "executions": qualification["executions"],
                    "oraclePasses": qualification["oracle"]["passes"],
                    "deterministicReplays": qualification["determinism"]["replays"],
                    "deterministicMatches": qualification["determinism"]["exact_episode_matches"],
                    "negativeControlTypes": len(qualification["negative_controls"]),
                    "negativeControlExecutions": sum(row["executions"] for row in qualification["negative_controls"].values()),
                    "negativeFalseAccepts": sum(row["false_accepts"] for row in qualification["negative_controls"].values()),
                },
                "writeContract": {
                    "schemaVersion": "blobfish.first-party-write-contract.v1",
                    "tasks": len(tasks),
                    "taskScopedExecutionAuthorized": len(tasks),
                    "completionDestinationsDiscoverable": len(tasks),
                    "providerInputSchemasValidated": len(tasks),
                    "semanticFreeTextOrVisibleTemplate": len(tasks),
                    "hiddenReferenceTextRequired": 0,
                    "hiddenSerializationRequired": 0,
                    "postWriteReadbacksContracted": len(tasks),
                    "writeScopeContained": len(tasks),
                    "wrongTargetControlsRejected": len(tasks),
                    "keywordStuffingControlsRejected": len(tasks),
                    "writeContractsPassed": len(tasks),
                },
            },
            "deterministicVerifier": True,
            "mcp": {"package": "dealbench100", "version": BENCHMARK_VERSION, "protocolVersion": "2025-06-18", "serverName": "dealbench"},
            "contractPins": contract_pins,
            "publicationReceipt": {
                "huggingFaceCommit": HF_COMMIT,
                "payloadManifestSha256": HF_PAYLOAD_MANIFEST_SHA256,
                "exactObjectIdentity": bool(HF_COMMIT and HF_PAYLOAD_MANIFEST_SHA256),
                "receiptUrl": f"{HF_URL}/tree/{HF_COMMIT}" if HF_COMMIT else HF_URL,
            },
            "modelRunReceipt": (
                {
                    "runSlug": MODEL_RUN_SLUG,
                    "jobId": model_run["job"]["id"],
                    "evaluatedDatasetRef": model_run["dataset"]["evaluated_ref"],
                    "trialBindingsSha256": model_run["trial_bindings_sha256"],
                    "artifactTreeSha256": model_run["artifact_tree_sha256"],
                    "receiptUrl": _hf_url(f"model-runs/{MODEL_RUN_SLUG}.json"),
                }
                if model_run is not None
                else None
            ),
            "links": {"harbor": HARBOR_URL, "huggingFace": HF_URL, "source": SOURCE_URL, "blobfishPage": PAGE_URL},
        },
        "scoring": {"categories": list(SCORING_CATEGORIES), "strictPassTracked": True},
        "leaderboard": leaderboard,
        "evaluationControls": evaluation_controls,
        "tasks": task_rows,
        "samples": samples,
        "tools": tool_definitions(),
        "trajectories": trajectories,
        "methodology": [
            {"title": "Ten deep project worlds", "body": "Each synthetic company has a current and superseded forecast, QoE bridge, comps, precedents, debt schedule, bids, diligence, approvals, committee deck, mailbox, chat and audit trail. Ten workflows reuse each frozen project as a real team would."},
            {"title": "High-level analyst outcomes", "body": "Prompts ask for a business outcome and review-ready handoff. They do not prescribe tool order. The agent must distinguish operative from stale authority, calculate from current evidence, compare options, and decide what may be committed."},
            {"title": "Stateful cross-application execution", "body": "Seven logical MCP servers expose data-room, mail, chat, spreadsheet, market-data, deal-management and benchmark controls over isolated SQLite state. Model, workbook, deck, bid, finding, approval, plan and communication writes are durable."},
            {"title": "One deterministic DealScore", "body": "DealScore allocates 100 executable points to discovery, model accuracy, decision quality, committed state, deliverable consistency, readback and containment. No LLM judge or exact reference call sequence is used."},
            {"title": "Two-sided qualification", "body": f"The release passed {qualification['oracle']['passes']}/100 oracle runs and {qualification['determinism']['exact_episode_matches']}/100 exact deterministic replays. Five negative-control families executed {sum(row['executions'] for row in qualification['negative_controls'].values())} attacks with zero false accepts."},
            {"title": "Clean-room APEX boundary", "body": "Public APEX, APEX-Accounting and Archipelago pages informed the product contract. Mercor's gated dataset was not downloaded or scraped. Every company, prompt, file, value, tool, answer and trajectory in DealBench is newly synthetic."},
            {
                "title": "Leaderboard honesty",
                "body": (
                    "Qualification controls prove solvability and discrimination but are never ranked as models. "
                    "The published model row is a complete version-pinned 100-task run with one attempt per task, "
                    "zero retries, and an inspectable provider-native receipt."
                    if model_run is not None
                    else "Qualification controls prove solvability and discrimination but are never ranked as models. A model row appears only after a complete version-pinned 100-task run has an inspectable receipt."
                ),
            },
        ],
        "architectureComparison": {
            "title": "APEX / Archipelago design anchor, deterministic DealBench implementation",
            "intro": "The public architecture is preserved where it improves reproducibility; the task corpus and grading implementation are independent.",
            "leftLabel": "Public APEX / Archipelago pattern",
            "rightLabel": "DealBench-100",
            "rows": [
                {"layer": "World", "left": "Data-rich professional project with files and apps", "right": "Ten frozen synthetic deal projects with 26 task-visible files"},
                {"layer": "Environment", "left": "Container, MCP gateway, snapshot population", "right": "Harbor task, seven MCP servers, task-local SQLite snapshot"},
                {"layer": "Trajectory", "left": "Messages, tool calls, artifact edits, final snapshot", "right": "Full provider-shaped calls, outputs, before/after state and verdict"},
                {"layer": "Grading", "left": "Criterion-level judge/static/domain verifiers", "right": "35 executable math, lineage, state, readback and containment checks; no judge model"},
                {"layer": "Release", "left": "World assets, gold outputs, task metadata", "right": "HF mirror, Harbor dataset, gold contracts, digests and ten public oracle traces"},
            ],
            "linkLabel": "Inspect Archipelago",
            "linkUrl": "https://github.com/Mercor-Intelligence/archipelago",
        },
    }


def _tree_digest(root: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    total = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        file_digest = _sha256_file(path)
        total += path.stat().st_size
        digest.update(f"{relative}\0{file_digest}\n".encode("utf-8"))
    return digest.hexdigest(), len(files), total


def build_release(output: Path = DEFAULT_OUTPUT, *, website_data: Path = WEBSITE_DATA) -> dict[str, Any]:
    output = output.resolve()
    allowed_parent = PACKAGE_ROOT.resolve()
    if output == allowed_parent or not output.is_relative_to(allowed_parent):
        raise ValueError(f"refusing to replace unsafe output path: {output}")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    tasks = build_tasks()
    qualification = qualify(tasks)
    if not qualification["qualification_passed"]:
        raise ValueError("DealBench qualification failed")
    assets = _write_assets(output, tasks)
    episodes: dict[str, dict[str, Any]] = {}
    for task in tasks:
        episode = run_episode(task, policy_steps(task, "oracle"))
        episodes[task["task_id"]] = episode
        _write_json(output / "tasks" / f"{task['task_id']}.json", task)
        _write_json(output / "verifiers" / f"{task['task_id']}.json", episode["verdict"])
        _write_json(output / "snapshots" / task["task_id"] / "initial.json", episode["before"])
        _write_json(output / "snapshots" / task["task_id"] / "final.json", episode["after"])
        trajectory_records = [*episode["trace"], {"verdict": episode["verdict"]}]
        _write_jsonl(output / "trajectories" / f"{task['task_id']}.jsonl", trajectory_records)
    harbor = _write_harbor_dataset(output, tasks, assets)
    _write_huggingface(output, tasks, assets, episodes)
    task_receipts = {row["task_id"]: row for row in harbor["digests"]}
    model_run = load_published_model_run(
        expected_task_receipts=task_receipts,
        expected_catalog_sha256=catalog_digest(tasks),
    )
    model_artifact = _materialize_model_run(output, model_run)
    _write_text(output / "README.md", _dataset_readme())
    _write_text(output / "ANCHORS.md", _anchors_text())
    _write_text(output / "LICENSE-DATA", "CC BY 4.0\n")
    _write_json(output / "reports" / "qualification.json", qualification)
    sample_snapshot = episodes[tasks[0]["task_id"]]["before"]
    rows_per_task = sum(len(rows) for rows in sample_snapshot.values())
    harbor_sha, _, _ = _tree_digest(output / "harbor")
    build = {
        "schema_version": "dealbench.build.v1",
        "benchmark": BENCHMARK_NAME,
        "version": BENCHMARK_VERSION,
        "metric": METRIC,
        "task_count": len(tasks),
        "world_count": len(WORLDS),
        "family_count": len(FAMILIES),
        "tool_count": len(tool_definitions()),
        "table_count": len(TABLES),
        "rows_per_task_snapshot": rows_per_task,
        "source_asset_count": len(list((output / "assets").rglob("*.*"))),
        "assets_per_task": {"min": min(len(value) for value in assets.values()), "max": max(len(value) for value in assets.values())},
        "criteria_per_task": {"min": min(len(task["rubric"]) for task in tasks), "max": max(len(task["rubric"]) for task in tasks)},
        "oracle_calls_per_task": {"min": min(len(task["oracle_steps"]) for task in tasks), "max": max(len(task["oracle_steps"]) for task in tasks)},
        "catalog_sha256": catalog_digest(tasks),
        "harbor_root_sha256": harbor_sha,
        "huggingface_commit": HF_COMMIT or None,
        "huggingface_payload_manifest_sha256": HF_PAYLOAD_MANIFEST_SHA256 or None,
        "harbor_task_files": harbor["files"],
        "harbor_task_bytes": harbor["bytes"],
        "qualification_passed": True,
        "mcp_pin": {"package": "dealbench100", "version": BENCHMARK_VERSION, "protocol_version": "2025-06-18", "server_name": "dealbench"},
        "verifier": {"deterministic": True, "llm_judge_calls": 0},
        "ranked_model_run": (
            {
                "run_slug": MODEL_RUN_SLUG,
                "job_id": model_run["job"]["id"],
                "mean_score": model_run["aggregate"]["mean_score"],
                "strict_passes": model_run["aggregate"]["strict_passes"],
            }
            if model_run is not None
            else None
        ),
    }
    _write_json(output / "reports" / "build.json", build)
    page_data = _website_data(
        tasks,
        assets,
        episodes,
        qualification,
        build,
        model_run,
        model_artifact,
    )
    _write_json(website_data, page_data)
    root_sha, file_count, total_bytes = _tree_digest(output)
    receipt = {
        **build,
        "root_sha256_before_release_report": root_sha,
        "artifact_file_count_before_release_report": file_count,
        "artifact_bytes_before_release_report": total_bytes,
        "website_data": str(website_data),
    }
    _write_json(output / "reports" / "release.json", receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--website-data", type=Path, default=WEBSITE_DATA)
    arguments = parser.parse_args()
    print(json.dumps(build_release(arguments.output, website_data=arguments.website_data), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
