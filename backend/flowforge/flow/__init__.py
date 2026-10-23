"""Flow order from code (D25, D32): `flow_of(root)` reads a repo's Python (by `ast`) and Dart, JavaScript and
TypeScript (by patterns, `curly`) and draws the order its entry points call their dependencies, with the critical
path's weights and advice on what could run together.

Plain code, read-only: nothing in the repo is imported or run, nothing is sent anywhere, no LLM (D20).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flowforge.flow import curly
from flowforge.flow.advice import advise, written_by_entry, written_ms
from flowforge.flow.index import Func, Index
from flowforge.flow.order import Body, Stmt, flatten, label, preds, reduce
from flowforge.flow.reach import Hit, Reach, writes
from flowforge.flowmap.models import CALL_KINDS, Action, Evidence, Flow, FlowEdge, FlowNode, Op
from flowforge.flowmap.validate import DEFAULT_MS, critical
from flowforge.scan.models import Dependency, ScanResult
from flowforge.scan.scanner import Places, scan_with_places
from flowforge.security.logfilter import Redactor, redact_code

NO_CODE = "Flow order reads Python, Dart, JavaScript and TypeScript."
NO_ENTRY = "No function here calls a dependency yet."
UNWRAP_DEPTH = 5
_redactor = Redactor()


@dataclass
class FlowResult:
    flow: Flow | None
    message: str | None = None
    scan: ScanResult | None = None
    entries: list[str] = field(default_factory=list)


def _excerpt(lines: list[str], line: int) -> tuple[int, list[str]]:
    first = max(1, line - 2)
    return first, [redact_code(raw, _redactor)[:160] for raw in lines[first - 1: line + 2]]


def _evidence(path: str, lines: list[str], line: int, text: str) -> Evidence:
    first, excerpt = _excerpt(lines, line)
    return Evidence(type="code", ref=f"{path}:{line}", text=text, first_line=first, lines=excerpt, highlight=line)


def _makes_its_own_calls(func: Func, reach: Reach) -> bool:
    """Every dependency the function reaches is called inside its own lines: a helper, not a flow."""
    lines = range(func.node.lineno, (func.node.end_lineno or func.node.lineno) + 1)
    own = {d for (path, line), ds in reach.at.items() if path == func.path and line in lines for d in ds}
    return {h.dep for h in reach.function(func)} <= own


def _entries(index: Index, reach: Reach, bodies: dict[str, Body]) -> list[Func]:
    """Functions that reach a dependency and that nothing in the repo calls. A wrapper whose one step is a call into
    another function that works through others is unwrapped (`main` → `asyncio.run(plan())` → `plan`)."""
    callers = index.callers()
    roots = [f for f in index.funcs.values() if reach.function(f) and not callers[f.key]]
    out: list[Func] = []
    for root in sorted(roots, key=lambda f: (f.path, f.node.lineno)):
        func = root
        for _ in range(UNWRAP_DEPTH):
            body = bodies.setdefault(func.key, flatten(func, index, reach))
            steps = [s for s in body.stmts if s.hits]
            if len(steps) != 1:
                break
            module = index.modules[func.module]
            calls = [n for n in ast.walk(steps[0].node) if isinstance(n, ast.Call)]
            inner = [t for t in {index.resolve(c, module) for c in calls} - {None} if reach.function(index.funcs[t])]
            if len(inner) != 1 or _makes_its_own_calls(index.funcs[inner[0]], reach):
                break
            func = index.funcs[inner[0]]
        if func not in out:
            out.append(func)
    return out


class _Python:
    """What the builder asks of a Python function, from its `ast` (D25)."""

    name = "python"

    def __init__(self, index: Index):
        self.index = index

    def start_line(self, func: Func) -> int:
        return func.node.lineno

    def is_async(self, func: Func) -> bool:
        return isinstance(func.node, ast.AsyncFunctionDef)

    def end_line(self, func: Func, s: Stmt) -> int:
        return getattr(s.node, "end_lineno", None) or s.line

    def awaited(self, func: Func, s: Stmt) -> bool:
        return any(isinstance(n, ast.Await) for n in ast.walk(s.node))

    def label(self, func: Func, s: Stmt) -> str:
        return label(s, self.index, func.module)

    def condition(self, func: Func, s: Stmt) -> str:
        return ast.unparse(s.node)

    def question(self, func: Func, body: Body, s: Stmt) -> str:
        return _question(func, body, s, self.index)

    def keep_decision(self, func: Func, body: Body, s: Stmt) -> bool:
        return True


class _Builder:
    """Blocks and lines for every entry point of one repo, with ids unique across the map."""

    def __init__(self, index: Index, reach: Reach, places: Places, deps: dict[str, Dependency],
                 sources: dict[str, str], latencies: dict[str, float]):
        self.index, self.reach, self.places, self.deps = index, reach, places, deps
        self.sources, self.latencies = sources, latencies
        self.nodes: list[FlowNode] = []
        self.edges: set[tuple[str, str]] = set()
        self.whens: dict[tuple[str, str], str] = {}
        self.meta: dict[str, dict[str, Any]] = {}   # step id -> what the advice needs
        self._counters: dict[str, int] = {}

    def _id(self, base: str) -> str:
        self._counters[base] = self._counters.get(base, 0) + 1
        return f"{base}-{self._counters[base]}"[:64]

    def entry(self, func: Any, body: Body, lang: Any) -> None:
        self.lang = lang
        lines = self.sources[func.path].splitlines()
        start = f"start-{func.name.replace('.', '-')}"[:64]
        self.nodes.append(FlowNode(id=start, kind="start", title=f"{func.name}()"[:80],
                                   what=f"An entry point in {func.path}.",
                                   evidence=[_evidence(func.path, lines, lang.start_line(func), "starts here")]))
        decisions = {s.idx for s in body.stmts if s.is_if and (s.stops or any(
            t.hits for t in body.stmts[s.idx + 1: s.block_end + 1])) and lang.keep_decision(func, body, s)}
        enters: dict[int, list[str]] = {}   # statement -> the blocks a line into it lands on
        leaves: dict[int, list[str]] = {}   # statement -> the blocks a line out of it leaves from
        is_async = lang.is_async(func)
        for s in body.stmts:
            ev = _evidence(func.path, lines, s.line, "in your code")
            steps = self._steps(func, lines, s, ev, start, is_async)
            if s.idx in decisions:
                dec = self._decision(func, lines, s, ev, lang.question(func, body, s))
                for step in steps:
                    self.edges.add((step, dec))
                enters[s.idx], leaves[s.idx] = (steps or [dec]), [dec]
            elif steps:
                enters[s.idx] = steps if s.gathered else steps[:1]
                leaves[s.idx] = steps if s.gathered else steps[-1:]
        self._lines(start, body, enters, leaves)

    def _steps(self, func: Func, lines: list[str], s: Stmt, ev: Evidence, start: str, is_async: bool) -> list[str]:
        """One block per dependency the statement calls; several calls in one statement run one after another
        unless the code gathers them."""
        reached = {h.dep for h in s.hits}
        ids: list[str] = []
        for hit in s.hits:
            dep = self.deps.get(hit.dep)
            if dep is None or dep.via in reached:
                continue   # reached through a server this statement calls: drawn off that server below
            node_id = self._id(dep.id)
            measured = dep.kind != "llm" and self.latencies.get(dep.id) is not None
            self.nodes.append(FlowNode(
                id=node_id, kind=dep.kind, title=dep.name[:80], what=_masked(self.lang.label(func, s))[:300],
                catalog=dep.catalog, op=_op(dep, hit), repeats=s.loop, evidence=[ev],
                estimate_ms=float(self.latencies[dep.id]) if measured else DEFAULT_MS.get(dep.kind, 0.0),
                estimate_source="measured" if measured else "estimate"))
            self.meta[node_id] = {"stmt": s.idx, "entry": start, "async": is_async, "line": s.line, "ref": ev.ref,
                                  "awaited": is_async and self.lang.awaited(func, s),
                                  "node": s.node if self.lang.name == "python" else s, "func": func,
                                  "lang": self.lang,
                                  "name": dep.name, "gathered": s.gathered, "loop": s.loop, "ifs": bool(s.ifs),
                                  "write": (dep.kind == "api" and hit.method not in (None, "GET", "HEAD"))
                                  or (dep.kind == "mcp" and writes(hit.tool))}
            if ids and not s.gathered:
                self.edges.add((ids[-1], node_id))
            ids.append(node_id)
            self._through(func, lines, s, dep, node_id)
        return ids

    def _through(self, func: Func, lines: list[str], s: Stmt, server: Dependency, server_id: str) -> None:
        """What this server reaches for the app, named inside the same statement (D21's via): its own block."""
        end = self.lang.end_line(func, s)
        for via in self.deps.values():
            if via.via != server.id:
                continue
            at = next((line for path, line, _ in self.places.by_dep.get(via.id, [])
                       if path == func.path and s.line <= line <= end), None)
            if at is None:
                continue
            via_id = self._id(via.id)
            self.nodes.append(FlowNode(id=via_id, kind=via.kind, title=via.name[:80], what=f"through {server.name}",
                                       catalog=via.catalog, estimate_ms=0.0,
                                       evidence=[_evidence(func.path, lines, at, f"reached through {server.name}")]))
            self.edges.add((server_id, via_id))

    def _decision(self, func: Func, lines: list[str], s: Stmt, ev: Evidence, question: str) -> str:
        dec = f"if-{sum(1 for n in self.nodes if n.kind == 'decision') + 1}"
        cond = _masked(self.lang.condition(func, s))
        self.nodes.append(FlowNode(id=dec, kind="decision", title=_masked(question)[:80], condition=cond[:200],
                                   what=f"if {cond}:"[:300], evidence=[ev]))
        if s.stops:
            stop = self._id("stop")
            self.nodes.append(FlowNode(id=stop, kind="end", title="Stop", what="The code returns here.",
                                       evidence=[_evidence(func.path, lines, s.stop_line, "returns early")]))
            self.edges.add((dec, stop))
            self.whens[(dec, stop)] = s.stops
        return dec

    def _lines(self, start: str, body: Body, enters: dict[int, list[str]], leaves: dict[int, list[str]]) -> None:
        stmt_preds = preds(body)
        memo: dict[int, set[tuple[int, str | None]]] = {}

        def drawn(i: int) -> set[tuple[int, str | None]]:
            """The drawn statements `i` waits for, through plain code in between."""
            if i not in memo:
                memo[i] = set()
                for p, lab in stmt_preds[i]:
                    memo[i] |= {(p, lab)} if p in leaves else {(q, None) for q, _ in drawn(p)}
            return memo[i]

        steps = {i for i, out in leaves.items() if not out[0].startswith("if-")}
        for i, targets in enters.items():
            # does it need a value another call produced? (before reduction hides it behind a decision)
            for b in targets:
                if b in self.meta:
                    self.meta[b]["needs_data"] = any(p in steps for p, _ in drawn(i))
            for p, lab in drawn(i):
                for a in leaves[p]:
                    for b in targets:
                        if a != b:
                            self.edges.add((a, b))
                            if lab and a.startswith("if-"):
                                self.whens[(a, b)] = lab
        writes_in_order = [n for n, m in self.meta.items() if m["entry"] == start and m["write"]]
        for a, b in zip(writes_in_order, writes_in_order[1:], strict=False):
            self.edges.add((a, b))   # two writes keep their written order (D25)
        has_pred = {b for _, b in self.edges}
        for targets in enters.values():
            for b in targets:
                if b not in has_pred:
                    self.edges.add((start, b))

    def flow(self) -> Flow:
        kept = reduce(self.edges)
        edges = [FlowEdge(id=f"{a}__{b}"[:64], source=a, target=b,
                          kind="branch" if (a, b) in self.whens else "flow", when=self.whens.get((a, b)))
                 for a, b in sorted(kept)]
        flow = Flow(kind="flow", source="code", nodes=self.nodes, edges=edges)
        modules = {m.path: m.tree for m in self.index.modules.values()}
        flow.advice = advise(flow, self.meta, self.sources, modules)
        flow.written_ms = written_ms(flow, self.meta)
        flow.actions = _actions(flow, written_by_entry(flow, self.meta))
        return flow


def _actions(flow: Flow, written: dict[str, float]) -> list[Action]:
    """Each entry point on its own (D33): what it reaches, its time as written and could be, slowest first."""
    out = []
    for start in (n for n in flow.nodes if n.kind == "start"):
        reach, queue = {start.id}, [start.id]
        while queue:
            here = queue.pop()
            for e in flow.edges:
                if e.source == here and e.target not in reach:
                    reach.add(e.target)
                    queue.append(e.target)
        sub = Flow(kind="flow", source="code", nodes=[n for n in flow.nodes if n.id in reach],
                   edges=[e for e in flow.edges if e.source in reach and e.target in reach])
        cp = critical(sub)
        calls = sum(1 for n in sub.nodes if n.kind in CALL_KINDS)
        out.append(Action(id=start.id, title=start.title, written_ms=written.get(start.id, 0.0),
                          could_ms=round(cp.length_ms, 1), path=list(cp.path), calls=calls))
    return sorted(out, key=lambda a: (-a.written_ms, a.title))


def _masked(text: str) -> str:
    """Words taken from the code (a condition, a label) are masked like evidence before they are stored (D20)."""
    return redact_code(text, _redactor)


def _question(func: Func, body: Body, s: Stmt, index: Index) -> str:
    """A decision as a whole question, from the code (D25): what it checks, and where that came from. `if place is
    None` after `place = … find the city …` asks 'Did "find the city" fail?'; `if sight` on an input asks 'Was a
    sight given?'. Anything else shows its condition."""
    node, cond = s.node, ast.unparse(s.node)
    name, failed = None, False
    if isinstance(node, ast.Name):
        name = node.id
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not) and isinstance(node.operand, ast.Name):
        name, failed = node.operand.id, True
    elif isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.left, ast.Name) \
            and isinstance(node.comparators[0], ast.Constant) and node.comparators[0].value is None:
        name, failed = node.left.id, isinstance(node.ops[0], ast.Is)
    if name is None:
        return f"Is {cond} true?"
    writer = next((t for t in reversed(body.stmts[: s.idx]) if name in t.writes and t.hits), None)
    if writer is not None and (said := label(writer, index, func.module)):
        return f'Did "{said}" {"fail" if failed else "work"}?'
    words = name.replace("_", " ")
    inputs = {a.arg for a in [*func.node.args.posonlyargs, *func.node.args.args, *func.node.args.kwonlyargs]}
    if name in inputs:
        return f"No {words} given?" if failed else f"Was a {words} given?"
    return f"No {words}?" if failed else f"Has a {words}?"


def _op(dep: Dependency, hit: Hit) -> Op | None:
    if dep.kind == "mcp":
        return Op(tool=hit.tool, read_only=not writes(hit.tool))
    if dep.kind == "api":
        return Op(method=hit.method)
    if dep.kind == "llm":
        return Op(model=dep.model)
    return None


def flow_of(root: str | Path, latencies: dict[str, float] | None = None) -> FlowResult:
    """The flow of every entry point in `root`. `latencies`: dependency id → its last measured check (D24)."""
    root = Path(root).resolve()
    result, places = scan_with_places(root)
    read = lambda path: (root / path).read_text(encoding="utf-8", errors="replace")   # noqa: E731
    sources = {path: read(path) for path in places.facts}
    braced = {path: (lang, read(path)) for path, lang in places.code.items() if lang in curly.LANGUAGES}
    if not sources and not braced:
        return FlowResult(None, NO_CODE, result)
    index = Index(sources)
    reach = Reach(index, places)
    bodies: dict[str, Body] = {}
    entries = _entries(index, reach, bodies) if sources else []
    c_index = curly.Index(braced)
    c_reach = curly.Reach(c_index, places, {d.id for d in result.dependencies})
    c_entries = curly.entries(c_index, c_reach) if braced else []
    if not entries and not c_entries:
        return FlowResult(None, NO_ENTRY, result)
    all_sources = {**sources, **{path: text for path, (_, text) in braced.items()}}
    builder = _Builder(index, reach, places, {d.id: d for d in result.dependencies}, all_sources, latencies or {})
    python, c_lang = _Python(index), curly.Lang(c_index)
    for func in entries:
        builder.entry(func, bodies.setdefault(func.key, flatten(func, index, reach)), python)
    for func in c_entries:
        builder.entry(func, c_lang.read(func, c_reach), c_lang)
    flow = builder.flow()
    flow.patterns = sorted({f.language for f in c_entries})
    return FlowResult(flow, None, result, [f.key for f in entries] + [f.key for f in c_entries])
