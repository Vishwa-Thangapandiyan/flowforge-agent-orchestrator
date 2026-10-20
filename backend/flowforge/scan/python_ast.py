"""Facts from a Python file through the stdlib `ast` (D21). Nothing is imported or run."""

from __future__ import annotations

import ast

from flowforge.scan.facts import FileFacts, LLMClient, Ref, UrlHit
from flowforge.scan.urls import clean_url

HTTP_CALLS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "request", "stream", "urlopen",
                        "Request", "fetch"})
# verbs that dicts and caches have too: an HTTP call only on something that looks like an HTTP client
AMBIGUOUS_CALLS = frozenset({"get", "delete", "head", "options"})
HTTP_RECEIVERS = ("client", "session", "http", "requests", "httpx", "aiohttp", "api", "urllib")
BASE_URL_KEYS = frozenset({"base_url", "api_base", "endpoint", "host"})
URL_KEYS = frozenset({"url", "uri", "base_url", "api_base", "api_url", "endpoint"})
MAX_STRING = 120
SUBPROCESS_CALLS = frozenset({"run", "Popen", "call", "check_call", "check_output"})
INTERPRETERS = frozenset({"python", "python3", "node", "bash", "sh", "ruby", "perl", "deno", "bun", "php", "pwsh"})


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _callee(call: ast.Call) -> str | None:
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None


def _call_strings(call: ast.AST | None) -> tuple[str, ...]:
    if not isinstance(call, ast.Call):
        return ()
    return tuple(a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str))


def _receiver(call: ast.Call) -> str:
    """The lower-cased name the method is called on: `self.client.get` → "client", `requests.get` → "requests"."""
    f = call.func
    owner = f.value if isinstance(f, ast.Attribute) else None
    if isinstance(owner, ast.Attribute):
        return owner.attr.lower()
    return owner.id.lower() if isinstance(owner, ast.Name) else ""


def _is_http_call(call: ast.Call) -> bool:
    name = _callee(call)
    if name not in HTTP_CALLS:
        return False
    return name not in AMBIGUOUS_CALLS or any(hint in _receiver(call) for hint in HTTP_RECEIVERS)


def _context(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> tuple[bool, tuple[str, ...]]:
    """(is it where a URL goes, the enclosing call's string arguments).

    Recognised: the first argument of an HTTP call, a url=/base_url= keyword, or the value of a "url" key in a
    dict (directly or as a call argument: call("fetch", "fetch", {"url": ...})).
    """
    parent = parents.get(node)
    if isinstance(parent, ast.Call):
        return bool(parent.args) and parent.args[0] is node and _is_http_call(parent), _call_strings(parent)
    if isinstance(parent, ast.keyword):
        return parent.arg in URL_KEYS, _call_strings(parents.get(parent))
    if isinstance(parent, ast.Dict) and node in parent.values:
        key = parent.keys[parent.values.index(node)]
        is_url = isinstance(key, ast.Constant) and key.value in URL_KEYS
        return is_url, _call_strings(parents.get(parent))
    return False, ()


def _ref(node: ast.AST | None) -> Ref:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return Ref(literal=node.value)
    if isinstance(node, ast.Name):
        return Ref(name=node.id)
    if isinstance(node, ast.Attribute):   # config.BASE_URL
        return Ref(name=node.attr)
    return Ref()


def _env_read(call: ast.Call) -> tuple[str | None, ast.AST | None]:
    """(name, default) for os.getenv("X", d) / os.environ.get("X", d); (None, None) for any other call."""
    f = call.func
    is_getenv = isinstance(f, ast.Attribute) and f.attr == "getenv" or isinstance(f, ast.Name) and f.id == "getenv"
    is_environ_get = isinstance(f, ast.Attribute) and f.attr == "get" and isinstance(f.value, ast.Attribute) \
        and f.value.attr == "environ"
    if not (is_getenv or is_environ_get) or not call.args:
        return None, None
    first = call.args[0]
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        return None, None
    default = call.args[1] if len(call.args) > 1 else next((k.value for k in call.keywords if k.arg == "default"), None)
    return first.value, default


def _imports(tree: ast.AST, facts: FileFacts) -> dict[str, str]:
    """Record imported packages; return local name -> package for the names a client class can come from."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                facts.imports.append((a.name, node.lineno))
                aliases[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            facts.imports.append((node.module, node.lineno))
            for a in node.names:
                aliases[a.asname or a.name] = node.module
                facts.imports.append((f"{node.module}.{a.name}", node.lineno))   # from google import genai
    return aliases


def extract(path: str, text: str) -> FileFacts:
    facts = FileFacts(path=path, language="python")
    tree = ast.parse(text)
    parents = _parents(tree)
    aliases = _imports(tree, facts)
    for stmt in tree.body:  # module-level NAME = "..." (or os.getenv(..., "...")) constants
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            value = stmt.value
            if isinstance(value, ast.Call):
                value = _env_read(value)[1]
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                facts.constants[stmt.targets[0].id] = (value.value, stmt.lineno)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if len(node.value) <= MAX_STRING:
                facts.strings.add(node.value)
            if isinstance(parents.get(node), ast.JoinedStr):
                continue   # f-string pieces: only a leading URL counts, handled with the f-string below
            url = clean_url(node.value)
            if url:
                confirmed, call = _context(node, parents)
                facts.urls.append(UrlHit(line=node.lineno, url=url, confirmed=confirmed, call_strings=call))
        elif isinstance(node, ast.JoinedStr) and node.values:
            first = node.values[0]
            confirmed, call = _context(node, parents)
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and (url := clean_url(first.value)):
                facts.urls.append(UrlHit(line=node.lineno, url=url, confirmed=confirmed, call_strings=call))
            elif isinstance(first, ast.FormattedValue) and isinstance(first.value, ast.Name):   # f"{BASE}/x"
                facts.urls.append(UrlHit(line=node.lineno, name=first.value.id, confirmed=confirmed,
                                         call_strings=call))
        elif isinstance(node, ast.Name) and (where := _context(node, parents))[0]:
            facts.urls.append(UrlHit(line=node.lineno, name=node.id, confirmed=True, call_strings=where[1]))
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) \
                and node.value.attr == "environ" and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str):
            _env(facts, node.slice.value, node, parents)
        elif isinstance(node, ast.Call):
            _call(node, aliases, facts, parents)
    return facts


def _env(facts: FileFacts, name: str, node: ast.AST, parents: dict[ast.AST, ast.AST]) -> None:
    """An env var name belongs to every line of its statement, so a call split over lines keeps it (D21)."""
    stmt = node
    while stmt in parents and not isinstance(stmt, ast.stmt):
        stmt = parents[stmt]
    first = getattr(stmt, "lineno", getattr(node, "lineno", 1))
    last = getattr(stmt, "end_lineno", None) or first
    facts.env.extend((name, line) for line in range(first, last + 1))


def _strings_in_order(node: ast.AST) -> list[str]:
    """String literals inside an expression, left to right: str(HERE / "tools" / "x.py") → ["tools", "x.py"]."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    return [s for child in ast.iter_child_nodes(node) for s in _strings_in_order(child)]


def _program(parts: list[ast.AST]) -> list[str] | None:
    """[program] or [interpreter, script] from an argv given as AST nodes; None when it isn't literal."""
    if not parts:
        return None
    first = parts[0]
    if isinstance(first, ast.Attribute) and first.attr == "executable":   # sys.executable
        program = "python"
    elif isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value.strip():
        program = first.value.split()[0]
    else:
        return None
    if program.rsplit("/", 1)[-1] in INTERPRETERS and len(parts) > 1:
        script = "/".join(_strings_in_order(parts[1]))
        if "." in script.rsplit("/", 1)[-1]:
            return [program, script]
    return [program]


def _subprocess(node: ast.Call, aliases: dict[str, str]) -> list[str] | None:
    f = node.func
    owner = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else None
    name = _callee(node)
    if name in SUBPROCESS_CALLS and (owner == "subprocess" or (owner is None and aliases.get(name) == "subprocess")):
        arg = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "args"), None)
        if isinstance(arg, (ast.List, ast.Tuple)):
            return _program(list(arg.elts))
        return _program([arg]) if arg is not None else None
    if owner == "os" and name in ("system", "popen") and node.args:
        return _program([node.args[0]])
    if name == "create_subprocess_exec":
        return _program(list(node.args))
    if name == "create_subprocess_shell" and node.args:
        return _program([node.args[0]])
    return None


def _stdio_server(node: ast.Call) -> list[str] | None:
    """StdioServerParameters(command="uvx", args=["mcp-server-git", …]) with literal values: the argv."""
    if _callee(node) != "StdioServerParameters":
        return None
    kw = {k.arg: k.value for k in node.keywords}
    command, args = kw.get("command"), kw.get("args")
    if not (isinstance(command, ast.Constant) and isinstance(command.value, str)):
        return None
    rest = [a.value for a in args.elts if isinstance(a, ast.Constant) and isinstance(a.value, str)] \
        if isinstance(args, (ast.List, ast.Tuple)) else []
    return [command.value, *rest]


def _call(node: ast.Call, aliases: dict[str, str], facts: FileFacts, parents: dict[ast.AST, ast.AST]) -> None:
    facts.call_strings.update(_call_strings(node))
    name, _ = _env_read(node)
    if name:
        _env(facts, name, node, parents)
        return
    server = _stdio_server(node)
    if server:
        facts.stdio.append((server, node.lineno))
        return
    command = _subprocess(node, aliases)
    if command:
        facts.commands.append((command, node.lineno))
        return
    f = node.func
    sdk = None
    if isinstance(f, ast.Name) and f.id[:1].isupper():                       # OpenAI(...) from openai
        sdk = aliases.get(f.id)
    elif isinstance(f, ast.Attribute) and f.attr[:1].isupper() and isinstance(f.value, ast.Name):
        sdk = aliases.get(f.value.id)                                       # anthropic.Anthropic(...)
    if sdk is not None:
        base = next((k.value for k in node.keywords if k.arg in BASE_URL_KEYS), None)
        facts.clients.append(LLMClient(line=node.lineno, sdk=sdk, base_url=_ref(base)))
    model = next((k.value for k in node.keywords if k.arg == "model"), None)
    if model is not None:
        ref = _ref(model)
        if ref.literal or ref.name:
            facts.models.append((ref, node.lineno))
