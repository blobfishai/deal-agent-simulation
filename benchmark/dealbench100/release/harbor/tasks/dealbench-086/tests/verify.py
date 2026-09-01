#!/usr/bin/env python3
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
