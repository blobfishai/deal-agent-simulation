# DealBench-100

DealBench-100 is Blobfish AI's clean-room, executable investment-banking agent benchmark. It contains 100 high-level analyst workflows across ten frozen synthetic transaction worlds and ten workflow families: source control, quality of earnings, trading comparables, precedent transactions, DCF, LBO, merger modeling, bid comparison, model-to-deck consistency, and launch approval.

The benchmark exposes 37 provider-shaped tools across seven logical MCP servers over task-local SQLite state. Each task includes 27 visible evidence files, eighteen required investigations, controlled writes, post-write readbacks, a reference trajectory, and 38 deterministic criteria. The single metric is DealScore (0–100): discovery 15, model accuracy 25, decision 15, committed state 20, deliverable consistency 10, readback 10, and containment 5. No LLM judge is used.

The v1.2 contract grades evidence and outcomes rather than hidden call serialization. Equivalent search wording receives credit only when the returned result contains the required evidence; task-specific units, calculation policies, neutral decision choices, model/workbook/deck targets, and revisions are agent-visible. Natural multi-keyword searches rank matching evidence instead of requiring brittle whole-phrase matches. All ten workflow families use one coherent enterprise-value-to-equity bridge, full-precision intermediates, and disclosed half-up output rounding. Harmless read misses do not count as collateral damage.

## Layout

- `spec.py` authors the ten worlds, ten workflow families, 100 prompts, gold outcomes, and rubrics.
- `schema.sql` defines the 19-table transaction world.
- `world.py` implements the stateful MCP tool surface and strict write boundaries.
- `evaluation.py` implements DealScore, the oracle, deterministic replay, and five negative controls.
- `service.py` exposes the isolated world as JSON-RPC MCP and health endpoints.
- `model_run.py` converts one completed, version-pinned Harbor job into a fail-closed aggregate receipt and 100 provider-native trial receipts.
- `publish_harbor.py` preserves the evaluated Harbor tag, publishes one result-only metadata revision, and proves its 100 task and dataset-file bytes by exact-ref download.
- `release.py` builds the Hugging Face mirror, 100 Harbor task packages, website explorer data, snapshots, trajectories, verifiers, digests, and receipts.
- `release/` is the checked-in v1.2.0 artifact.

## Build and verify

```bash
python3.12 -m benchmark.dealbench100.release
python3.12 -m pytest benchmark/dealbench100/tests/ -q
node products/website/scripts/generate-benchmark-data.mjs \
  --validate products/website/app/benchmarks/dealbench-100/dealbench-data.json
```

Release qualification executes 700 episodes: 100 oracle runs, 100 exact replays, and 500 adversarial controls. The v1.2.0 receipt records 100/100 oracle strict passes, 100/100 deterministic matches, and zero strict false accepts across no-op, answer-only, state-only, wrong-source, and wrong-target controls.

## Immutable task release

Publish the qualified task-only payload before model evaluation. These commands are fail-closed against the previous public release and verify the resulting immutable objects:

```bash
uv run --no-project --python 3.12 --with huggingface-hub \
  python -m benchmark.dealbench100.publish_huggingface \
  --expected-parent 4aae831a06b2f9ac9f4dab85bf68199c94808b32 \
  --publish-task-release

python3.12 -m benchmark.dealbench100.publish_harbor --publish-exact-tasks
```

The evaluated v1.2 task identities are Hugging Face commit `611a1accf503b430600e24b290d04484f8224870` and Harbor digest `sha256:9f8b2d24a04cc39a3bbc75a10ec9eb22ffd406851480b47850799f607b4d74b6` (tag `v1.2.0`, revision 3).

## Ranked model runs

A leaderboard row is published only from one finished Harbor job containing all 100 pinned tasks, with zero errors, retries, pending trials, or cancellations. The receipt builder verifies the exact dataset manifest, task-package digests, Harbor and Codex versions, model identifier, reasoning configuration, concurrency, task checksums, reward buckets, provider-native MCP calls, verifier outputs, token totals, and cost totals. It rejects partial or reconstructed runs.

Run the pinned evaluation, then materialize its public receipts with the immutable Harbor job ID:

```bash
DOCKER_HOST=unix:///Users/samuelchien/.colima/default/docker.sock \
CODEX_FORCE_AUTH_JSON=true \
harbor run -d blobfishai/dealbench-100-suite@v1.2.0 \
  -a codex -m openai/gpt-5.6-luna \
  --ak version=0.151.0 \
  --ak reasoning_effort=max \
  --ak reasoning_summary=detailed \
  --ak web_search=disabled \
  --agent-setup-timeout-multiplier 3 \
  --n-concurrent 3 --n-attempts 1 --max-retries 0 \
  --jobs-dir "$DEALBENCH_JOBS_DIR" \
  --job-name dealbench-gpt-5.6-luna-v1.2.0-full-100-run-1 \
  --yes

python3.12 -m benchmark.dealbench100.model_run \
  "$DEALBENCH_JOBS_DIR/dealbench-gpt-5.6-luna-v1.2.0-full-100-run-1" \
  --expected-job-id "$DEALBENCH_JOB_ID"

uv run --no-project --python 3.12 --with huggingface-hub \
  python -m benchmark.dealbench100.publish_huggingface \
  --expected-parent 611a1accf503b430600e24b290d04484f8224870 \
  --publish-exact-payload
```

The generated aggregate receipt lives at `model_runs/gpt-5.6-luna-v1.2.0-full-100.json`; its 100 content-hashed trial receipts live below the sibling directory of the same name. The public artifacts contain the task prompt, final response, sanitized provider trace, agent-visible reasoning summaries, website events, deterministic verdict, and exact run configuration. Authentication data, private filesystem paths, and harness-only system prompts are excluded.

The Hugging Face publisher refuses a missing model manifest or a remote `main` that no longer equals the checked-in parent commit. After upload it re-reads the immutable revision and verifies every local file against its Git blob or LFS object before printing the new commit and payload-manifest receipt.

Keep `v1.0.0`, `v1.1.0`, and the evaluated `v1.2.0` task tag immutable. A later result-only bundle reuses the exact v1.2 task digests and publishes updated dataset metadata under a dated results tag:

```bash
python3.12 -m benchmark.dealbench100.publish_harbor \
  --expected-evaluated-ref sha256:9f8b2d24a04cc39a3bbc75a10ec9eb22ffd406851480b47850799f607b4d74b6 \
  --publish-exact-results
```

The task publisher proves the v1.0 and v1.1 refs are unchanged, round-trips all 100 v1.2 task digests from the new immutable ref, and binds no result files. The results publisher then refuses a changed evaluated v1.2 ref, revision, visibility, or task set; refuses a conflicting dated tag; uploads no tasks; verifies the remote task and file bindings; downloads the new immutable digest; and recomputes every task plus `model-runs.json` before writing its publication receipt.

## Public artifacts

- Explorer: https://blobfish.ai/benchmarks/dealbench-100
- Hugging Face: https://huggingface.co/datasets/SamuelChien821/dealbench-100
- Harbor: https://hub.harborframework.com/datasets/blobfishai/dealbench-100-suite/latest
- Source world: https://github.com/blobfishai/deal-agent-simulation

## Clean-room boundary

Public APEX, APEX-Accounting, the APEX paper, and Archipelago informed what a reproducible professional benchmark should expose. Mercor's gated APEX-Agents dataset was not downloaded or scraped. Every DealBench company, prompt, asset, value, tool, answer, trajectory, and verifier is independently authored and synthetic. See `release/ANCHORS.md` for the complete receipt and source links.
