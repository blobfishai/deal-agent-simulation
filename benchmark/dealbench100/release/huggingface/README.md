---
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

# Public design anchors and clean-room boundary

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
