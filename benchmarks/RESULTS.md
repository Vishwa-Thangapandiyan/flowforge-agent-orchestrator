## Simulated track — 200 random DAGs, k = 4

Speedup = sequential makespan / policy makespan on the same graph. Ratio to bound = makespan / the lower bound for that policy's resources (k-slot policies: max(critical path, work/k); greedy: critical path; sequential: total work). Mean ± 95% CI.

| Policy | Cache | Speedup vs sequential | Ratio to bound | API calls |
|---|---|---|---|---|
| sequential | off | 1.00 ± 0.00× | 1.061 ± 0.002 | 23.9 |
| sequential | on | 1.00 ± 0.00× | 0.954 ± 0.012 | 21.3 |
| levels | off | 2.23 ± 0.08× | 1.475 ± 0.033 | 23.9 |
| levels | on | 2.14 ± 0.07× | 1.389 ± 0.037 | 21.3 |
| greedy | off | 3.66 ± 0.22× | 1.036 ± 0.002 | 23.9 |
| greedy | on | 3.48 ± 0.21× | 0.976 ± 0.014 | 21.3 |
| fifo | off | 2.85 ± 0.10× | 1.150 ± 0.016 | 23.9 |
| fifo | on | 2.77 ± 0.09× | 1.066 ± 0.021 | 21.3 |
| critical_path | off | 3.16 ± 0.12× | 1.046 ± 0.003 | 23.9 |
| critical_path | on | 3.04 ± 0.12× | 0.979 ± 0.014 | 21.3 |

**Critical path vs FIFO (same k, cache off):** makespan 8.3% ± 1.1% lower on average; better on 133, within 2% on 66, worse on 1 graphs.

**Cache:** 23.9 → 21.3 API calls per run (10.6% fewer).

### How to read this

- **Setup:** 200 random DAGs (8–40 steps, edge probability 0.05–0.35, at most 4 parents, 10% duplicate calls), `k = 4`, seed 42. Step durations come from lognormal latency models (LLM median 2.5 s, HTTP 0.6 s, MCP 1.5 s), scaled by 1/100. The comparisons are ratios, so the scaling doesn't change them.
- **Overhead:** sequential's ratio of 1.061 is pure scheduling and timer overhead, because in theory it exactly equals its bound. Measured against that baseline, critical path at 1.046 is effectively at the lower bound, while FIFO (1.150) and level-by-level (1.475) leave real time on the table.
- **Ratios below 1 with the cache on:** the bound is computed from total work without deduplication, so a merged duplicate call can put a run under it.
- **Greedy** has unlimited slots, so it shows what extra concurrency would buy. It isn't a fair competitor under the `k = 4` limit.
- **Real track:** not run yet, because it needs a free `NVIDIA_API_KEY`. Its latencies will then feed the next simulated run.

Reproduce with: `uv run python benchmarks/run_benchmark.py sim --graphs 200 --seed 42`
