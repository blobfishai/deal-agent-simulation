# DealBench-100

DealBench-100 is a 100-task, deterministic investment-banking agent benchmark over ten synthetic transaction worlds. It tests source control, QoE normalization, trading comps, precedents, DCF, LBO, merger math, bid comparison, model-to-deck consistency, and launch approval.

## Run

```bash
harbor run -d blobfishai/dealbench-100-suite -a <agent> -m <provider/model>
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

The complete synthetic world, task generator, deterministic verifier, release receipts, and model-run manifests are published at https://github.com/blobfishai/deal-agent-simulation/tree/main/benchmark/dealbench100.

All companies, bids, financials, approvals, messages and transactions are synthetic. This dataset is for agent evaluation and research; it is not financial or investment advice.
