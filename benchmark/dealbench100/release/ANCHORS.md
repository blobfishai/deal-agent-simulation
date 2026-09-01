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
