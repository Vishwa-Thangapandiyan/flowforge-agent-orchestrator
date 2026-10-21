"""The order one entry function calls its dependencies (D25): statements, what each reads and writes, the `if`s
around them and the early returns before them, projected onto the blocks the map draws.

A line A → B means B can't start before A is done: it reads something A wrote (directly or through plain code in
between), it sits in an `if` A decides, or A returns early and B comes after. Lines are transitively reduced.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from flowforge.flow.index import Func, Index
from flowforge.flow.reach import Hit, Reach, gathers

MUTATORS = frozenset({"append", "extend", "update", "add", "insert", "pop", "remove", "clear", "setdefault", "write",
                      "sort", "discard", "appendleft", "put"})


@dataclass
class Stmt:
    idx: int
    node: ast.AST                 # a simple statement, or an `if`'s test, or a loop / with header
    line: int
    reads: set[str]
    writes: set[str]
    hits: list[Hit]
    ifs: list[tuple[int, str]]    # enclosing (if statement, "yes" | "no"), outermost first
    loop: bool = False
    returns: bool = False
    gathered: bool = False
    is_if: bool = False
    block_end: int = -1           # an `if`: index of the last statement inside it
    stops: str | None = None      # an `if` that returns early: the branch that returns ("yes" | "no")
    stop_line: int = 0


def _reads(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def _writes(node: ast.AST) -> set[str]:
    out = {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))}
    for n in ast.walk(node):
        if isinstance(n, (ast.Subscript, ast.Attribute)) and isinstance(n.ctx, ast.Store):
            base = n.value
            while isinstance(base, (ast.Subscript, ast.Attribute)):
                base = base.value
            if isinstance(base, ast.Name):
                out.add(base.id)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in MUTATORS \
                and isinstance(n.func.value, ast.Name):
            out.add(n.func.value.id)   # facts.append(x) writes facts
    return out


@dataclass
class Body:
    """One function's statements, flattened in source order."""

    func: Func
    stmts: list[Stmt] = field(default_factory=list)


def flatten(func: Func, index: Index, reach: Reach) -> Body:
    module = index.modules[func.module]
    cls = func.name.split(".")[0] if "." in func.name else None
    body = Body(func)

    def add(node: ast.AST, line: int, ifs: list[tuple[int, str]], loop: bool, *, reads: set[str] | None = None,
            writes: set[str] | None = None, hit_node: ast.AST | None = None, is_if: bool = False) -> Stmt:
        s = Stmt(idx=len(body.stmts), node=node, line=line, reads=_reads(node) if reads is None else reads,
                 writes=_writes(node) if writes is None else writes,
                 hits=reach.statement(hit_node if hit_node is not None else node, module, cls) if hit_node is not False
                 else [], ifs=list(ifs), loop=loop, returns=isinstance(node, (ast.Return, ast.Raise)),
                 gathered=gathers(node), is_if=is_if)
        body.stmts.append(s)
        return s

    def walk(stmts: list[ast.stmt], ifs: list[tuple[int, str]], loop: bool) -> None:
        for st in stmts:
            if isinstance(st, ast.If):
                test = add(st.test, st.lineno, ifs, loop, is_if=True)
                first = len(body.stmts)
                walk(st.body, [*ifs, (test.idx, "yes")], loop)
                after_body = len(body.stmts)
                walk(st.orelse, [*ifs, (test.idx, "no")], loop)
                test.block_end = len(body.stmts) - 1
                returns_yes = next((s for s in body.stmts[first:after_body] if s.returns and not s.loop), None)
                returns_no = next((s for s in body.stmts[after_body:] if s.returns and not s.loop), None)
                if returns_yes and not returns_no:
                    test.stops, test.stop_line = "yes", returns_yes.line
                elif returns_no and not returns_yes:
                    test.stops, test.stop_line = "no", returns_no.line
            elif isinstance(st, (ast.For, ast.AsyncFor)):
                add(st.iter, st.lineno, ifs, loop, writes=_writes(st.target) | {n.id for n in ast.walk(st.target)
                                                                             if isinstance(n, ast.Name)})
                walk(st.body, ifs, True)
                walk(st.orelse, ifs, loop)
            elif isinstance(st, ast.While):
                add(st.test, st.lineno, ifs, loop, writes=set())
                walk(st.body, ifs, True)
                walk(st.orelse, ifs, loop)
            elif isinstance(st, (ast.With, ast.AsyncWith)):
                header = ast.Tuple(elts=[i.context_expr for i in st.items], ctx=ast.Load())
                ast.copy_location(header, st)
                names = {n.id for i in st.items if i.optional_vars is not None for n in ast.walk(i.optional_vars)
                         if isinstance(n, ast.Name)}
                add(header, st.lineno, ifs, loop, writes=names)
                walk(st.body, ifs, loop)
            elif isinstance(st, ast.Try) or type(st).__name__ == "TryStar":
                walk(st.body, ifs, loop)
                for handler in st.handlers:
                    walk(handler.body, ifs, loop)
                walk(st.orelse, ifs, loop)
                walk(st.finalbody, ifs, loop)
            elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                add(st, st.lineno, ifs, loop, reads=set(), writes={st.name}, hit_node=False)
            else:
                add(st, st.lineno, ifs, loop)

    walk(func.node.body, [], False)
    return body


def label(stmt: Stmt, index: Index, module_name: str) -> str:
    """The code's own words for a step: a string it passes (`attempt("find the city (Nominatim)", …)`), without the
    trailing note in brackets; else the function it calls, as words (`packing_list` → "packing list")."""
    for sub in ast.walk(stmt.node):
        if isinstance(sub, ast.Call):
            for arg in sub.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and " " in arg.value.strip():
                    return re.sub(r"\s*\([^)]*\)\s*$", "", arg.value.strip())[:120]
    for sub in ast.walk(stmt.node):
        if isinstance(sub, ast.Call):
            target = index.resolve(sub, index.modules[module_name])
            if target:
                return target.rsplit(".", 1)[-1].replace("_", " ").strip()
    return ""


def preds(body: Body) -> dict[int, list[tuple[int, str | None]]]:
    """Statement-level: what each statement waits for, and the branch label when it is an `if`'s own control."""
    out: dict[int, list[tuple[int, str | None]]] = {}
    for s in body.stmts:
        found: dict[int, str | None] = {}
        for name in s.reads:
            for t in body.stmts[: s.idx]:
                if name in t.writes:
                    found.setdefault(t.idx, None)
        if s.ifs:
            d, lab = s.ifs[-1]
            found[d] = lab
        for g in body.stmts[: s.idx]:
            if g.stops and g.block_end < s.idx and all(i != g.idx for i, _ in s.ifs):
                found[g.idx] = "no" if g.stops == "yes" else "yes"   # the branch that carries on
        out[s.idx] = sorted(found.items())
    return out


def reduce(edges: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """Transitive reduction of a DAG: drop A → C when A reaches C another way."""
    children: dict[str, set[str]] = {}
    for a, b in edges:
        children.setdefault(a, set()).add(b)

    def reaches(a: str, target: str, skip: tuple[str, str]) -> bool:
        stack, seen = [a], set()
        while stack:
            here = stack.pop()
            for nxt in children.get(here, ()):
                if (here, nxt) == skip or nxt in seen:
                    continue
                if nxt == target:
                    return True
                seen.add(nxt)
                stack.append(nxt)
        return False

    return {e for e in edges if not reaches(e[0], e[1], e)}
