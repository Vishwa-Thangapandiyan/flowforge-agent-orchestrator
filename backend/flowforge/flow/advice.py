"""What could run together (D25), from the drawn flow and its weights.

Each step starts as early as its lines allow (its earliest start). Steps of one entry point that would start at the
same moment, but that the code awaits one after another, are one piece of advice: running them together saves the
time of all but the slowest. Steps the code already gathers, and steps in a loop, get none.
"""

from __future__ import annotations

import ast
from collections import defaultdict

from flowforge.flow.rewrite import Call, change, prompt
from flowforge.flowmap.models import Advice, Flow
from flowforge.scheduler.graph import DAG, topological_order

MIN_SAVING_MS = 50   # below this, advice is noise


def _starts(flow: Flow) -> dict[str, float]:
    parents: dict[str, list[str]] = {n.id: [] for n in flow.nodes}
    children: dict[str, list[str]] = {n.id: [] for n in flow.nodes}
    for e in flow.edges:
        parents[e.target].append(e.source)
        children[e.source].append(e.target)
    weight = {n.id: n.estimate_ms or 0.0 for n in flow.nodes}
    start: dict[str, float] = {}
    for node in topological_order(DAG(nodes=[n.id for n in flow.nodes], parents=parents, children=children)):
        start[node] = max((start[p] + weight[p] for p in parents[node]), default=0.0)
    return start


def advise(flow: Flow, meta: dict[str, dict], sources: dict[str, str] | None = None,
           modules: dict[str, ast.Module] | None = None) -> list[Advice]:
    start = _starts(flow)
    by_id = {n.id: n for n in flow.nodes}
    groups: dict[tuple[str, float], list[str]] = defaultdict(list)
    for node_id, m in meta.items():
        if not m["gathered"] and not m["loop"]:
            groups[(m["entry"], round(start[node_id], 3))].append(node_id)
    out: list[Advice] = []
    for (_, _), ids in groups.items():
        stmts = {meta[i]["stmt"] for i in ids}
        if len(ids) < 2 or len(stmts) < 2:
            continue
        weights = [by_id[i].estimate_ms or 0.0 for i in ids]
        saved = sum(weights) - max(weights)
        if saved < MIN_SAVING_MS:
            continue
        ids.sort(key=lambda i: meta[i]["line"])
        how = ("start them together with asyncio.gather" if all(meta[i]["async"] for i in ids)
               else "they could run at the same time, for example in a thread pool")
        names = [meta[i]["name"] for i in ids]
        text = f"None of these uses another's result: {how}."
        caveat = _caveat(flow, ids, meta, names)
        advice = Advice(nodes=ids, refs=[meta[i]["ref"] for i in ids], text=text, saved_ms=round(saved, 1),
                        caveat=caveat)
        if sources is not None and modules is not None and all("node" in meta[i] for i in ids):
            func = meta[ids[0]]["func"]
            calls = [Call(stmt=meta[i]["node"], func=meta[i]["func"].node, path=meta[i]["func"].path,
                          words=by_id[i].what or by_id[i].title, ref=meta[i]["ref"], weight=by_id[i].estimate_ms or 0.0)
                     for i in ids]
            if all(isinstance(c.stmt, ast.stmt) for c in calls):
                advice.change = change(calls, sources[func.path], modules[func.path])
            advice.prompt = prompt(calls, by_id[meta[ids[0]]["entry"]].title, advice.saved_ms, caveat,
                                   all(meta[i]["async"] for i in ids))
        out.append(advice)
    return sorted(out, key=lambda a: -a.saved_ms)


def _caveat(flow: Flow, ids: list[str], meta: dict[str, dict], names: list[str]) -> str | None:
    """Steps that need no other call's result, only an early return's go-ahead: they could start even before that
    check, but when the code stops there, those calls are wasted."""
    into: dict[str, list[str]] = defaultdict(list)
    for e in flow.edges:
        into[e.target].append(e.source)
    by_id = {n.id: n for n in flow.nodes}
    early, guard = [], None
    for i in ids:
        sources = into[i]
        if sources and not meta[i]["ifs"] and not meta[i].get("needs_data") \
                and all(by_id[s].kind == "decision" for s in sources):
            stops = [s for s in sources if any(e.source == s and by_id[e.target].kind == "end" for e in flow.edges)]
            if stops and len(stops) == len(sources):
                early.append(meta[i]["name"])
                guard = by_id[stops[0]].evidence[0].ref
    if not early or guard is None:
        return None
    who = early[0] if len(early) == 1 else f"{', '.join(early[:-1])} and {early[-1]}"
    return (f"{who} only need what was known before the check at {guard}, so they could start even earlier, "
            "but when the code stops there, those calls are wasted.")


def written_ms(flow: Flow, meta: dict[str, dict]) -> float:
    """Every call one after another, as the code is written; calls the code already gathers count once, at the
    slowest."""
    by_id = {n.id: n for n in flow.nodes}
    total, gathered = 0.0, defaultdict(list)
    for node_id, m in meta.items():
        w = by_id[node_id].estimate_ms or 0.0
        if m["gathered"]:
            gathered[(m["entry"], m["stmt"])].append(w)
        else:
            total += w
    return round(total + sum(max(ws) for ws in gathered.values()), 1)
