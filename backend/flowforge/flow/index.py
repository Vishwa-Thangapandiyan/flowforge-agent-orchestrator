"""Every Python function in the repo, and which in-repo function each call reaches (D25). Read by `ast`, never run."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import PurePosixPath


@dataclass
class Func:
    module: str                     # "services.geo"
    path: str                       # "services/geo.py"
    name: str                       # "find_place", or "Class.method"
    node: ast.FunctionDef | ast.AsyncFunctionDef

    @property
    def key(self) -> str:
        return f"{self.module}.{self.name}"


@dataclass
class Module:
    name: str
    path: str
    tree: ast.Module
    aliases: dict[str, str] = field(default_factory=dict)   # local name -> dotted name it was imported as
    uses_mcp: bool = False                                  # imports the MCP SDK


def module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(module: Module) -> None:
    package = module.name.rsplit(".", 1)[0] if "." in module.name else ""
    for node in ast.walk(module.tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                module.aliases[(a.asname or a.name).split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
                module.uses_mcp |= a.name == "mcp" or a.name.startswith("mcp.")
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:   # relative: from .geo import x
                up = package.split(".")[: max(0, len(package.split(".")) - node.level + 1)] if package else []
                base = ".".join([*up, base] if base else up)
            module.uses_mcp |= base == "mcp" or base.startswith("mcp.")
            for a in node.names:
                module.aliases[a.asname or a.name] = f"{base}.{a.name}" if base else a.name


class Index:
    """The repo's functions. `resolve` turns a call into the in-repo function it runs, or None."""

    def __init__(self, sources: dict[str, str]):
        self.modules: dict[str, Module] = {}
        self.funcs: dict[str, Func] = {}
        for path, text in sources.items():
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            module = Module(module_name(path), path, tree)
            _imports(module)
            self.modules[module.name] = module
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self._add(Func(module.name, path, node.name, node))
                elif isinstance(node, ast.ClassDef):
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            self._add(Func(module.name, path, f"{node.name}.{item.name}", item))

    def _add(self, func: Func) -> None:
        self.funcs[func.key] = func

    def _known(self, dotted: str) -> str | None:
        if dotted in self.funcs:
            return dotted
        # a src/ layout or a run from a subfolder: match on the trailing parts
        ends = [k for k in self.funcs if k.endswith("." + dotted)]
        return ends[0] if len(ends) == 1 else None

    def resolve(self, call: ast.Call, module: Module, cls: str | None = None) -> str | None:
        f = call.func
        if isinstance(f, ast.Name):
            local = f"{module.name}.{f.id}"
            if local in self.funcs:
                return local
            if f.id in module.aliases:
                return self._known(module.aliases[f.id])
            return None
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            owner = f.value.id
            if owner == "self" and cls:
                return self._known(f"{module.name}.{cls}.{f.attr}")
            if owner in module.aliases:
                return self._known(f"{module.aliases[owner]}.{f.attr}")
            local_class = f"{module.name}.{owner}.{f.attr}"
            if local_class in self.funcs:
                return local_class
        return None

    def callers(self) -> dict[str, set[str]]:
        """func key -> keys of the in-repo functions that call it (module-level code is not a caller)."""
        out: dict[str, set[str]] = {k: set() for k in self.funcs}
        for func in self.funcs.values():
            module = self.modules[func.module]
            cls = func.name.split(".")[0] if "." in func.name else None
            for node in ast.walk(func.node):
                if isinstance(node, ast.Call) and (target := self.resolve(node, module, cls)) and target != func.key:
                    out[target].add(func.key)
        return out
