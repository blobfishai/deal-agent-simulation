# deal-agent-simulation

> **Simulation only.** Every company, transaction, document, person, approval,
> market input, and financial figure in this repository is synthetic test data.

`deal-agent-simulation` is the executable source repository for
[DealBench-100](https://blobfish.ai/benchmarks/dealbench-100), Blobfish AI's
clean-room investment-banking agent benchmark. It models long-horizon analyst
work across ten frozen transaction worlds, seven provider-shaped MCP systems,
and 100 independently verifiable tasks.

The environment is built for outcome-level evaluation: an agent must identify
operative evidence, calculate from the right sources, make an authorized
decision, commit durable state, prepare a review-ready handoff, and read its
writes back. Task prompts do not prescribe a tool sequence or leak fixture
identifiers.

## What is included

- 100 high-level deal workflows across ten synthetic project worlds and ten
  workflow families.
- 27 task-visible evidence files in ten native formats per task, including an
  explicit family-specific calculation policy.
- 37 tools across data-room, mail, chat, spreadsheet, market-data,
  deal-management, and benchmark-control MCP servers.
- Task-local SQLite state with controlled writes and exact before/after
  snapshots.
- One deterministic 100-point metric, DealScore, with 38 executable checks per
  task and no language-model judge.
- 100 Harbor task packages, a Hugging Face publication mirror, ten complete
  reference trajectories, and immutable release receipts.
- A fail-closed importer for full, version-pinned model runs and sanitized
  provider-native MCP traces.

## Release facts

The v1.2.0 qualification suite executed 700 episodes: 100 oracle runs, 100 exact
deterministic replays, and 500 adversarial controls. It recorded 100/100 oracle
strict passes, 100/100 exact replay matches, and zero strict false accepts.

Ranked model results are separate from qualification controls. A leaderboard
row is admitted only when one Harbor job completes all 100 pinned tasks with
zero errors and zero retries, and every public trial receipt reconciles to the
job lock, task digest, native MCP event stream, verifier, token usage, and cost.

## Repository layout

```text
benchmark/dealbench100/
├── spec.py                 worlds, prompts, gold outcomes, and rubrics
├── schema.sql              durable transaction-world state
├── world.py                provider-shaped MCP tool surface
├── evaluation.py           DealScore, oracle, replay, and negative controls
├── service.py              JSON-RPC MCP and health endpoints
├── model_run.py            fail-closed ranked-run receipt builder
├── release.py              source, Hugging Face, Harbor, and site artifacts
├── tests/
├── model_runs/             checked-in ranked-run receipts when published
└── release/                qualified v1.2.0 artifact tree
```

## Verify locally

Requirements: Python 3.12 or newer. The deterministic qualification path does
not need a model API key.

```bash
python3.12 -m pytest benchmark/dealbench100/tests/ -q
python3.12 -m benchmark.dealbench100.release
```

Run the published Harbor suite with any supported agent/model pair:

```bash
harbor run -d blobfishai/dealbench-100-suite@v1.2.0 \
  -a <agent> -m <provider/model>
```

See [benchmark/dealbench100/README.md](benchmark/dealbench100/README.md) for the
exact ranked-run and publication commands.

## Public artifacts

- Explorer: https://blobfish.ai/benchmarks/dealbench-100
- Hugging Face: https://huggingface.co/datasets/SamuelChien821/dealbench-100
- Harbor: https://hub.harborframework.com/datasets/blobfishai/dealbench-100-suite/latest
- Monorepo integration: https://github.com/blobfishai/blobfishai/tree/main/benchmark/dealbench100

## Clean-room boundary

Public APEX/APEX-Accounting product pages, Archipelago, the APEX paper,
Enterprise-Bench, and ERP-Bench informed the inspection and execution contract.
Mercor's gated APEX-Agents corpus was not downloaded or scraped. No upstream
prompt, asset, value, world snapshot, solution, or trajectory was copied. See
[benchmark/dealbench100/release/ANCHORS.md](benchmark/dealbench100/release/ANCHORS.md)
for the complete source receipt.

Dataset artifacts are released under CC BY 4.0 as recorded in
`benchmark/dealbench100/release/LICENSE-DATA`.
