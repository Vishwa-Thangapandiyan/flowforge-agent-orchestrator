"""Advice written out (D27): one `asyncio.gather` in place of awaits that don't need each other, when plain code can
write it safely, and a prompt that hands the whole advice to a coding agent. Nothing here edits a file.

Safe means: the calls are in one block of one async function, each a plain `x = await …` or `await …`, and nothing
between them reads their results or changes what they read. Calls of the same advice elsewhere are listed to move
by hand.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from flowforge.flowmap.models import Change
from flowforge.security.logfilter import redact_code


@dataclass
class Call:
    """One awaited call of a piece of advice."""

    stmt: ast.stmt
    func: ast.FunctionDef | ast.AsyncFunctionDef
    path: str
    words: str          # what it does, in the code's words ("find the sight")
    ref: str            # "planner.py:58"
    weight: float


def _blocks(func: ast.AST) -> dict[int, tuple[ast.AST, list[ast.stmt]]]:
    """Each statement's block: the node that owns it and the list it sits in."""
    out: dict[int, tuple[ast.AST, list[ast.stmt]]] = {}
    for node in ast.walk(func):
        for attr in ("body", "orelse", "finalbody"):
            stmts = getattr(node, attr, None)
            if isinstance(stmts, list):
                for st in stmts:
                    if isinstance(st, ast.stmt):
                        out[id(st)] = (node, stmts)
        for handler in getattr(node, "handlers", []) or []:
            for st in handler.body:
                out[id(st)] = (handler, handler.body)
    return out


def _where(owner: ast.AST) -> str:
    if isinstance(owner, ast.If):
        return f"inside `if {redact_code(ast.unparse(owner.test))[:60]}:`"
    if isinstance(owner, ast.AsyncWith):
        return "inside the `async with` block"
    if isinstance(owner, ast.With):
        return "inside the `with` block"
    if isinstance(owner, (ast.Try, ast.ExceptHandler)) or type(owner).__name__ == "TryStar":
        return "inside a `try`"
    if isinstance(owner, (ast.For, ast.AsyncFor, ast.While)):
        return "inside a loop"
    return "in another block"


def _awaited(st: ast.stmt) -> tuple[str, ast.expr] | None:
    """`x = await e` → ("x", e); `await e` → ("_", e); anything else → None."""
    if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.value, ast.Await):
        return ast.unparse(st.targets[0]), st.value.value
    if isinstance(st, ast.AnnAssign) and isinstance(st.value, ast.Await) and st.simple:
        return ast.unparse(st.target), st.value.value
    if isinstance(st, ast.Expr) and isinstance(st.value, ast.Await):
        return "_", st.value.value
    return None


def _names(node: ast.AST, ctx: type) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ctx)}


def _quoted(c: Call) -> str:
    return f'"{c.words}" ({c.ref})'


def change(calls: list[Call], source: str, module: ast.Module) -> Change | None:
    """The gather for the largest group of calls that share a block, or None when it can't be written safely."""
    func = calls[0].func
    if not isinstance(func, ast.AsyncFunctionDef) or any(c.func is not func for c in calls):
        return None
    blocks = _blocks(func)
    groups: dict[int, list[Call]] = {}
    for c in calls:
        if id(c.stmt) in blocks:
            groups.setdefault(id(blocks[id(c.stmt)][1]), []).append(c)
    if not groups:
        return None
    chosen = max(groups.values(), key=lambda g: (len(g), -g[0].stmt.lineno))
    plain = [c for c in chosen if _awaited(c.stmt)]
    if len(plain) < 2:
        return None
    plain.sort(key=lambda c: c.stmt.lineno)
    body = blocks[id(plain[0].stmt)][1]
    first, last = body.index(plain[0].stmt), body.index(plain[-1].stmt)
    members = {id(c.stmt) for c in plain}
    targets = set().union(*(_names(c.stmt, ast.Store) for c in plain))
    reads = set().union(*(_names(_awaited(c.stmt)[1], ast.Load) for c in plain))
    for st in body[first: last + 1]:
        if id(st) not in members and (_names(st, ast.Load) & targets or _names(st, ast.Store) & reads):
            return None   # code between them uses a result, or changes what a call reads

    lines = source.splitlines()
    indent = lines[plain[0].stmt.lineno - 1][: plain[0].stmt.col_offset]
    names = [_awaited(c.stmt)[0] for c in plain]
    lhs = "" if all(n == "_" for n in names) else f"{', '.join(names)} = "
    gather = [f"{indent}{lhs}await asyncio.gather(",
              *(f"{indent}    {ast.unparse(_awaited(c.stmt)[1])}," for c in plain), f"{indent})"]
    end = plain[-1].stmt.end_lineno or plain[-1].stmt.lineno
    spans = [(c.stmt.lineno, c.stmt.end_lineno or c.stmt.lineno) for c in plain]
    after: list[str] = []
    for n in range(plain[0].stmt.lineno, end + 1):
        if n == spans[0][0]:
            after += gather
        elif not any(a <= n <= b for a, b in spans):
            after.append(lines[n - 1])
    weights = [c.weight for c in plain]
    imported = any(isinstance(n, ast.Import) and any(a.name == "asyncio" for a in n.names) for n in ast.walk(module))
    left = [c for c in calls if c not in plain]
    return Change(
        path=plain[0].path, first_line=plain[0].stmt.lineno,
        before=[redact_code(x) for x in lines[plain[0].stmt.lineno - 1: end]],
        after=[redact_code(x) for x in after], saved_ms=round(sum(weights) - max(weights), 1),
        by_hand=[f"{_quoted(c)}: {_where(blocks[id(c.stmt)][0]) if id(c.stmt) in blocks else 'in another block'}"
                 for c in sorted(left, key=lambda c: c.stmt.lineno)],
        needs_import=not imported)


def prompt(calls: list[Call], entry: str, saved_ms: float, caveat: str | None, how: str) -> str:
    """The advice for a coding agent: where, what, why, and what not to touch. Masked; no code beyond the words."""
    paths = sorted({c.path for c in calls})
    lines = [f"In {', '.join(paths)}, {entry} waits for each of these calls before starting the next, "
             "but none of them uses another's result:",
             *(f"- line {c.ref.rsplit(':', 1)[1]}: \"{c.words}\"" for c in sorted(calls, key=lambda c: c.stmt.lineno)),
             f"Make them run at the same time, {how}, so the slowest one sets the time. "
             f"FlowForge estimates about {saved_ms / 1000:.1f} s saved."]
    if caveat:
        lines.append(f"Note: {caveat}")
    lines.append("Keep the behaviour the same: the same results, the same error handling, and the same checks before "
                 "each call. Change nothing else, and run the tests.")
    return redact_code("\n".join(lines))[:3000]
