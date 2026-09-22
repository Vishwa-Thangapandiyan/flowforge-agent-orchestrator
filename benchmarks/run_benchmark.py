"""Benchmark runner (D6). Owner: Person C.

Real track:      uv run python benchmarks/run_benchmark.py real --workflow backend/workflows/stripe_to_razorpay.json
Simulated track: uv run python benchmarks/run_benchmark.py sim --graphs 500 --k 4

For each policy S1–S5 (sequential, levels, greedy, fifo, critical_path) × cache on/off:
record makespan, API calls, cache hits, makespan / lower_bound.
Write CSV to benchmarks/results/ and print mean ± 95% CI per strategy.
"""
