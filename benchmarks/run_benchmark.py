"""Benchmark runner (D6). Owner: Person C.

Simulated track (free, no network):
    uv run python benchmarks/run_benchmark.py sim --graphs 500 --k 4
Real track (needs a free NVIDIA_API_KEY in .env; respects the NIM rate limit):
    uv run python benchmarks/run_benchmark.py real --workflow backend/workflows/stripe_to_razorpay.json

Every policy (sequential, levels, greedy, fifo, critical_path) runs with the cache off and on.
Results go to benchmarks/results/ as CSV plus a markdown summary. The real track also
saves measured per-type call latencies, which the simulated track then samples from.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from flowforge.nodes.http_node import HTTPNode
from flowforge.nodes.llm_node import LLMNode
from flowforge.nodes.mcp_node import MCPNode
from flowforge.nodes.mock_node import MockNode
from flowforge.schema import Workflow
from flowforge.scheduler import graph
from flowforge.scheduler.critical_path import critical_path, lower_bound_ms
from flowforge.scheduler.executor import POLICIES, RunResult, StepState, run_workflow
from flowforge.scheduler.rate_limit import TokenBucket

sys.path.insert(0, str(Path(__file__).parent))
from random_dag import LatencyModel, generate  # noqa: E402

RESULTS = Path(__file__).parent / "results"
LATENCIES = RESULTS / "latencies.json"


# --- statistics -------------------------------------------------------------------------

def mean_ci(values: list[float]) -> tuple[float, float]:
    """Mean and 95% CI half-width (normal approximation; n is in the hundreds)."""
    if not values:
        return math.nan, math.nan
    if len(values) == 1:
        return values[0], 0.0
    return statistics.fmean(values), 1.96 * statistics.stdev(values) / math.sqrt(len(values))


def fmt(mean: float, ci: float, digits: int = 3) -> str:
    return f"{mean:.{digits}f} ± {ci:.{digits}f}"


# --- simulated track -----------------------------------------------------------------------

def bound_for(policy: str, dag: graph.DAG, weights: dict[str, float], k: int) -> float:
    """The lower bound that applies to each policy's own resources."""
    if policy == "sequential":
        return sum(weights.values())
    if policy == "greedy":
        return critical_path(dag, weights).length_ms
    return lower_bound_ms(dag, weights, k)


async def simulate(args: argparse.Namespace) -> list[dict[str, Any]]:
    rng = random.Random(args.seed)
    latency = LatencyModel.load(LATENCIES)
    source = "measured latencies" if latency.samples else "default lognormal latencies"
    print(f"simulated track: {args.graphs} graphs, k={args.k}, {source}, time scale {args.scale}")

    rows = []
    variants = [(p, c) for p in POLICIES for c in (False, True)]
    for g in range(args.graphs):
        n = rng.randint(args.min_steps, args.max_steps)
        edge_prob = rng.choice([0.05, 0.1, 0.2, 0.35])
        dag_spec = generate(rng, n_steps=n, edge_prob=edge_prob, k=args.k, dup_prob=args.dup_prob,
                            latency=latency, time_scale=args.scale, wf_id=f"sim{g}")
        wf, weights = dag_spec.workflow, dag_spec.weights_ms
        dag = graph.build_dag(wf)
        layers = graph.levels(dag)
        shape = {
            "graph": g, "n_steps": n, "edge_prob": edge_prob,
            "n_edges": sum(len(p) for p in dag.parents.values()),
            "depth": len(layers), "width": max(len(l) for l in layers),
            "cp_ms": critical_path(dag, weights).length_ms, "work_ms": sum(weights.values()),
        }
        rng.shuffle(variants)  # no systematic warm-up advantage for any policy
        for policy, cache in variants:
            result = await run_workflow(wf, {"mock": MockNode()}, policy=policy, use_cache=cache)
            bound = bound_for(policy, dag, weights, args.k)
            rows.append({**shape, "policy": policy, "cache": cache,
                         "makespan_ms": result.makespan_ms, "bound_ms": bound,
                         "ratio_to_bound": result.makespan_ms / bound,
                         "api_calls": result.api_calls, "cache_hits": result.cache_hits})
        if (g + 1) % max(1, args.graphs // 10) == 0:
            print(f"  {g + 1}/{args.graphs} graphs")
    return rows


def summarize_sim(rows: list[dict[str, Any]], k: int) -> str:
    by_graph: dict[tuple[int, bool], dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in rows:
        by_graph[(r["graph"], r["cache"])][r["policy"]] = r

    lines = [
        f"## Simulated track — {len({r['graph'] for r in rows})} random DAGs, k = {k}",
        "",
        "Speedup = sequential makespan / policy makespan on the same graph. "
        "Ratio to bound = makespan / the lower bound for that policy's resources "
        "(k-slot policies: max(critical path, work/k); greedy: critical path; sequential: total work). "
        "Mean ± 95% CI.",
        "",
        "| Policy | Cache | Speedup vs sequential | Ratio to bound | API calls |",
        "|---|---|---|---|---|",
    ]
    for policy in POLICIES:
        for cache in (False, True):
            group = [g[policy] for key, g in by_graph.items() if key[1] == cache]
            speedup = [g["sequential"]["makespan_ms"] / g[policy]["makespan_ms"]
                       for key, g in by_graph.items() if key[1] == cache]
            lines.append(
                f"| {policy} | {'on' if cache else 'off'} | {fmt(*mean_ci(speedup), 2)}× | "
                f"{fmt(*mean_ci([r['ratio_to_bound'] for r in group]))} | "
                f"{statistics.fmean(r['api_calls'] for r in group):.1f} |"
            )

    # paired: FlowForge vs FIFO under the same k, cache off
    diffs, wins, ties, losses = [], 0, 0, 0
    for (_, cache), g in by_graph.items():
        if cache:
            continue
        cp, fifo = g["critical_path"]["makespan_ms"], g["fifo"]["makespan_ms"]
        change = (fifo - cp) / fifo * 100
        diffs.append(change)
        if abs(change) < 2:
            ties += 1
        elif change > 0:
            wins += 1
        else:
            losses += 1
    m, ci = mean_ci(diffs)
    calls_off = statistics.fmean(r["api_calls"] for r in rows if r["policy"] == "critical_path" and not r["cache"])
    calls_on = statistics.fmean(r["api_calls"] for r in rows if r["policy"] == "critical_path" and r["cache"])
    lines += [
        "",
        f"**Critical path vs FIFO (same k, cache off):** makespan {m:.1f}% ± {ci:.1f}% lower on average; "
        f"better on {wins}, within 2% on {ties}, worse on {losses} graphs.",
        "",
        f"**Cache:** {calls_off:.1f} → {calls_on:.1f} API calls per run "
        f"({(1 - calls_on / calls_off) * 100:.1f}% fewer).",
    ]
    return "\n".join(lines)


# --- real track ----------------------------------------------------------------------------

async def real(args: argparse.Namespace) -> list[dict[str, Any]]:
    if not os.getenv("NVIDIA_API_KEY"):
        sys.exit("NVIDIA_API_KEY is not set — get a free key at build.nvidia.com and add it to .env")
    wf = Workflow.model_validate(json.loads(Path(args.workflow).read_text()))
    types = {s.id: s.type for s in wf.steps}
    bucket = {"nim": TokenBucket(float(os.getenv("NIM_RPM", "40")))}
    nodes = {"llm": LLMNode(), "http": HTTPNode(), "mcp": MCPNode(), "mock": MockNode()}
    latencies: dict[str, list[float]] = json.loads(LATENCIES.read_text()) if LATENCIES.exists() else {}

    rows = []
    variants = [(p, c) for p in POLICIES for c in (False, True)]
    try:
        for rep in range(args.repeats):
            for i, (policy, cache) in enumerate(variants):
                print(f"  run {rep + 1}.{i + 1}: {policy}, cache {'on' if cache else 'off'} … ", end="", flush=True)
                # no storage: the cross-run disk cache would make later runs look free
                result = await run_workflow(wf, nodes, policy=policy, use_cache=cache, rate_limits=bucket)
                print(f"{result.status}, {result.makespan_ms / 1000:.1f} s, {result.api_calls} calls")
                rows.append(real_row(rep, policy, cache, result, wf, types))
                for sid, r in result.steps.items():
                    if r.state == StepState.SUCCEEDED and r.call_ms is not None and types[sid] != "mock":
                        latencies.setdefault(types[sid], []).append(round(r.call_ms, 1))
                await asyncio.sleep(args.pause)
    finally:
        for node in nodes.values():
            await node.aclose()
    RESULTS.mkdir(exist_ok=True)
    LATENCIES.write_text(json.dumps(latencies, indent=1))
    print(f"saved {sum(map(len, latencies.values()))} measured latencies to {LATENCIES}")
    return rows


def real_row(rep: int, policy: str, cache: bool, result: RunResult, wf: Workflow, types: dict[str, str]) -> dict[str, Any]:
    tokens = sum(
        (r.output or {}).get("usage", {}).get("prompt_tokens", 0) + (r.output or {}).get("usage", {}).get("completion_tokens", 0)
        for sid, r in result.steps.items() if types[sid] == "llm" and r.state == StepState.SUCCEEDED and not r.cache_hit
    )
    return {"repeat": rep, "workflow": wf.id, "policy": policy, "cache": cache, "status": result.status,
            "makespan_ms": result.makespan_ms, "api_calls": result.api_calls, "cache_hits": result.cache_hits,
            "llm_tokens": tokens, "actual_critical_path": " > ".join(result.actual_critical_path)}


def summarize_real(rows: list[dict[str, Any]]) -> str:
    lines = [f"## Real track — {rows[0]['workflow']}", "",
             "| Policy | Cache | Makespan (s) | API calls | LLM tokens | Status |", "|---|---|---|---|---|---|"]
    groups: dict[tuple[str, bool], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[(r["policy"], r["cache"])].append(r)
    for (policy, cache), rs in groups.items():
        lines.append(
            f"| {policy} | {'on' if cache else 'off'} | {fmt(*mean_ci([r['makespan_ms'] / 1000 for r in rs]), 1)} | "
            f"{statistics.fmean(r['api_calls'] for r in rs):.1f} | {statistics.fmean(r['llm_tokens'] for r in rs):.0f} | "
            f"{', '.join(sorted({r['status'] for r in rs}))} |"
        )
    return "\n".join(lines)


# --- entry point ---------------------------------------------------------------------------

def write(rows: list[dict[str, Any]], summary: str, name: str) -> None:
    RESULTS.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    csv_path = RESULTS / f"{name}_{stamp}.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (RESULTS / f"{name}_{stamp}.md").write_text(summary + "\n")
    print(f"\n{summary}\n\nwrote {csv_path} and {csv_path.with_suffix('.md')}")


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="track", required=True)

    sim = sub.add_parser("sim", help="random DAGs with mock steps")
    sim.add_argument("--graphs", type=int, default=100)
    sim.add_argument("--k", type=int, default=4)
    sim.add_argument("--min-steps", type=int, default=8)
    sim.add_argument("--max-steps", type=int, default=40)
    sim.add_argument("--dup-prob", type=float, default=0.1)
    sim.add_argument("--scale", type=float, default=0.01, help="multiply latencies by this (default 1/100)")
    sim.add_argument("--seed", type=int, default=0)

    rl = sub.add_parser("real", help="an example workflow against real NIM/HTTP/MCP")
    rl.add_argument("--workflow", default="backend/workflows/stripe_to_razorpay.json")
    rl.add_argument("--repeats", type=int, default=1)
    rl.add_argument("--pause", type=float, default=10.0, help="seconds between runs, lets the rate limit refill")

    args = parser.parse_args(argv)
    if args.track == "sim":
        rows = asyncio.run(simulate(args))
        write(rows, summarize_sim(rows, args.k), "sim")
    else:
        rows = asyncio.run(real(args))
        write(rows, summarize_real(rows), "real")


if __name__ == "__main__":
    main()
