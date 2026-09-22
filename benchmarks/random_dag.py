"""Random DAG generator for the simulated track (D6). Owner: Person C.

generate(n_steps, edge_prob, max_parents, durations_ms_sampler, seed) -> Workflow
  - edges only from lower to higher index ⇒ acyclic by construction
  - every step is a `mock` step with duration_ms drawn from the sampler
    (the sampler replays latencies measured in the real track)
"""
