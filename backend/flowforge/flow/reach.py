"""Which dependencies a statement or a function reaches (D25), from the scan's own places (D21).

A place counts only when it shows a call: an HTTP call, a program run, a server started, an LLM client created or
asked for a model. A place that only mentions an address (a link, a constant) is not a call. MCP servers are reached
when their configured name is passed to code that uses the MCP SDK (D21's `via` rule).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from flowforge.flow.index import Func, Index, Module
from flowforge.scan.scanner import Places

CALL_TEXTS = frozenset({"calls it", "runs it", "starts it", "creates the client", "the model"})
HTTP_METHODS = {"get": "GET", "head": "HEAD", "post": "POST", "put": "PUT", "patch": "PATCH", "delete": "DELETE",
                "request": None, "stream": None}
# an MCP tool whose name starts with one of these changes something; any other is read as read-only (D25)
WRITE_VERBS = ("write", "create", "delete", "remove", "update", "set", "send", "post", "put", "insert", "upload",
               "move", "add", "edit", "publish", "pay", "charge", "refund", "cancel", "push", "commit", "merge")
GATHER = ("gather", "TaskGroup", "create_task", "wait", "as_completed")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:56]


@dataclass
class Hit:
    """One dependency a statement reaches: how (an HTTP method, an MCP tool) and from where."""

    dep: str
    method: str | None = None
    tool: str | None = None


def writes(tool: str | None) -> bool:
    return bool(tool) and tool.lower().startswith(WRITE_VERBS)


class Reach:
    def __init__(self, index: Index, places: Places):
        self.index = index
        self.servers = {s: f"mcp-{_slug(s)}" for s in places.app_servers}
        # (path, line) -> dependencies a call there reaches
        self.at: dict[tuple[str, int], list[str]] = {}
        for dep_id, items in places.by_dep.items():
            for path, line, text in items:
                if text in CALL_TEXTS:
                    self.at.setdefault((path, line), []).append(dep_id)
        # module-level names whose definition is a call place: `client = OpenAI(...)` -> its dependency
        self.names: dict[tuple[str, str], list[str]] = {}
        for module in index.modules.values():
            for node in module.tree.body:
                if isinstance(node, (ast.Assign, ast.AnnAssign)) and (deps := self._lines(module.path, node)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in targets:
                        if isinstance(t, ast.Name):
                            self.names[(module.name, t.id)] = deps
        self._memo: dict[str, list[Hit]] = {}

    def _lines(self, path: str, node: ast.AST) -> list[str]:
        out: list[str] = []
        for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
            out += [d for d in self.at.get((path, line), []) if d not in out]
        return out

    def function(self, func: Func) -> list[Hit]:
        """Everything a function reaches, in the order its code reaches it (memoised; recursion ends)."""
        if func.key in self._memo:
            return self._memo[func.key]
        self._memo[func.key] = []
        module = self.index.modules[func.module]
        cls = func.name.split(".")[0] if "." in func.name else None
        hits: list[Hit] = []
        for stmt in func.node.body:
            for hit in self.statement(stmt, module, cls):
                if not any(h.dep == hit.dep for h in hits):
                    hits.append(hit)
        self._memo[func.key] = hits
        return hits

    def statement(self, node: ast.AST, module: Module, cls: str | None = None) -> list[Hit]:
        """What one statement (or expression) reaches: places inside it, module-level clients it uses, MCP servers
        it names, and the in-repo functions it calls, followed through."""
        found: list[tuple[int, int, Hit]] = []   # (line, col) keeps the code's own order
        for sub in ast.walk(node):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)) and sub is not node:
                continue
            at = (getattr(sub, "lineno", 0), getattr(sub, "col_offset", 0))
            if isinstance(sub, ast.Call):
                for dep in self.at.get((module.path, sub.lineno), []):
                    found.append((*at, Hit(dep, method=_method(sub))))
                target = self.index.resolve(sub, module, cls)
                if target is not None:
                    callee = self.index.funcs[target]
                    if self.index.modules[callee.module].uses_mcp:
                        strings = [a.value for a in sub.args
                                   if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                        server = next((self.servers[s] for s in strings if s in self.servers), None)
                        if server:
                            tool = next((s for s in strings if s not in self.servers), None)
                            found.append((*at, Hit(server, tool=tool)))
                            continue
                    found += [(*at, h) for h in self.function(callee)]
            elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                key = (module.name, sub.id)
                if key not in self.names and sub.id in module.aliases and "." in module.aliases[sub.id]:
                    owner, _, name = module.aliases[sub.id].rpartition(".")   # from config import CLIENT
                    key = (owner, name)
                found += [(*at, Hit(d)) for d in self.names.get(key, [])]
            elif isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id in module.aliases:
                dotted = module.aliases[sub.value.id]
                owner = self.index.modules.get(dotted)
                if owner is not None:
                    found += [(*at, Hit(d)) for d in self.names.get((owner.name, sub.attr), [])]
        found.sort(key=lambda f: (f[0], f[1]))
        out: list[Hit] = []
        for _, _, hit in found:
            same = next((h for h in out if h.dep == hit.dep), None)
            if same is None:
                out.append(hit)
            else:
                same.method = same.method or hit.method
                same.tool = same.tool or hit.tool
        return out


def _method(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute) and call.func.attr in HTTP_METHODS:
        return HTTP_METHODS[call.func.attr]
    return None


def gathers(node: ast.AST) -> bool:
    """The statement runs its calls together: asyncio.gather, a TaskGroup, create_task (D25)."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
            if name in GATHER:
                return True
    return False
