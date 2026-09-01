# DealBench-100

DealBench-100 is Blobfish AI's clean-room, executable investment-banking agent benchmark. It contains 100 high-level analyst workflows across ten frozen synthetic transaction worlds and ten workflow families: source control, quality of earnings, trading comparables, precedent transactions, DCF, LBO, merger modeling, bid comparison, model-to-deck consistency, and launch approval.

The benchmark exposes 36 provider-shaped tools across seven logical MCP servers over task-local SQLite state. Each task includes 26 visible evidence files, fifteen required investigations, controlled writes, post-write readbacks, a reference trajectory, and 35 deterministic criteria. The single metric is DealScore (0–100): discovery 15, model accuracy 25, decision 15, committed state 20, deliverable consistency 10, readback 10, and containment 5. No LLM judge is used.

## Layout

- `spec.py` authors the ten worlds, ten workflow families, 100 prompts, gold outcomes, and rubrics.
- `schema.sql` defines the 19-table transaction world.
- `world.py` implements the stateful MCP tool surface and strict write boundaries.
- `evaluation.py` implements DealScore, the oracle, deterministic replay, and five negative controls.
- `service.py` exposes the isolated world as JSON-RPC MCP and health endpoints.
- `model_run.py` converts one completed, version-pinned Harbor job into a fail-closed aggregate receipt and 100 provider-native trial receipts.
- `release.py` builds the Hugging Face mirror, 100 Harbor task packages, website explorer data, snapshots, trajectories, verifiers, digests, and receipts.
- `release/` is the checked-in v1.0.0 artifact.

## Build and verify

```bash
python3.12 -m benchmark.dealbench100.release
python3.12 -m pytest benchmark/dealbench100/tests/ -q
node products/website/scripts/generate-benchmark-data.mjs \
  --validate products/website/app/benchmarks/dealbench-100/dealbench-data.json
```

Release qualification executes 700 episodes: 100 oracle runs, 100 exact replays, and 500 adversarial controls. The v1.0.0 receipt records 100/100 oracle strict passes, 100/100 deterministic matches, and zero strict false accepts across no-op, answer-only, state-only, wrong-source, and wrong-target controls.

## Ranked model runs

A leaderboard row is published only from one finished Harbor job containing all 100 pinned tasks, with zero errors, retries, pending trials, or cancellations. The receipt builder verifies the exact dataset manifest, task-package digests, Harbor and Codex versions, model identifier, reasoning configuration, concurrency, task checksums, reward buckets, provider-native MCP calls, verifier outputs, token totals, and cost totals. It rejects partial or reconstructed runs.

Run the pinned evaluation, then materialize its public receipts with the immutable Harbor job ID:

```bash
DOCKER_HOST=unix:///Users/samuelchien/.colima/default/docker.sock \
CODEX_FORCE_AUTH_JSON=true \
harbor run -d blobfishai/dealbench-100-suite@v1.0.0 \
  -a codex -m openai/gpt-5.6-luna \
  --ak version=0.151.0 \
  --ak reasoning_effort=max \
  --ak reasoning_summary=detailed \
  --ak web_search=disabled \
  --agent-setup-timeout-multiplier 3 \
  --n-concurrent 3 --n-attempts 1 --max-retries 0 \
  --jobs-dir "$DEALBENCH_JOBS_DIR" \
  --job-name dealbench-gpt-5.6-luna-v1.0.0-full-100-rerun-1 \
  --yes

python3.12 -m benchmark.dealbench100.model_run \
  "$DEALBENCH_JOBS_DIR/dealbench-gpt-5.6-luna-v1.0.0-full-100-rerun-1" \
  --expected-job-id "$DEALBENCH_JOB_ID"
```

The generated aggregate receipt lives at `model_runs/gpt-5.6-luna-v1.0.0-full-100.json`; its 100 content-hashed trial receipts live below the sibling directory of the same name. The public artifacts contain the task prompt, final response, sanitized provider trace, agent-visible reasoning summaries, website events, deterministic verdict, and exact run configuration. Authentication data, private filesystem paths, and harness-only system prompts are excluded.

Harbor's CLI discovers task packages only as immediate children. This release keeps them in a dedicated `tasks/` directory, so publish the exact task versions before the dataset manifest:

```bash
harbor publish benchmark/dealbench100/release/harbor/tasks --public -t v1.0.0
harbor publish benchmark/dealbench100/release/harbor --no-tasks --public -t v1.0.0
```

Keep that evaluated `v1.0.0` tag immutable. A later result-only bundle reuses the exact task digests and publishes the updated dataset metadata under a dated results tag:

```bash
harbor publish benchmark/dealbench100/release/harbor \
  --no-tasks --public -t results-2026-09-01
```

## Public artifacts

- Explorer: https://blobfish.ai/benchmarks/dealbench-100
- Hugging Face: https://huggingface.co/datasets/SamuelChien821/dealbench-100
- Harbor: https://hub.harborframework.com/datasets/blobfishai/dealbench-100-suite/latest
- Source world: https://github.com/blobfishai/deal-agent-simulation

## Clean-room boundary

Public APEX, APEX-Accounting, the APEX paper, and Archipelago informed what a reproducible professional benchmark should expose. Mercor's gated APEX-Agents dataset was not downloaded or scraped. Every DealBench company, prompt, asset, value, tool, answer, trajectory, and verifier is independently authored and synthetic. See `release/ANCHORS.md` for the complete receipt and source links.
