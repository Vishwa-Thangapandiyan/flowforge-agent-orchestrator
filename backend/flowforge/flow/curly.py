"""Flow order for Dart, JavaScript and TypeScript (D32): the same statements, reads, writes and calls as Python's
reader (D25), found by patterns in code whose comments and string contents are blanked out first. Nothing is run.

Less exact than Python's AST, and the map says so (`Flow.patterns`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from flowforge.connectors.presets import CLIENTS
from flowforge.flow.order import Body, Stmt
from flowforge.flow.reach import CALL_TEXTS, Hit
from flowforge.flow.rewrite import Call
from flowforge.flowmap.models import Change
from flowforge.scan import services
from flowforge.scan.scanner import Places
from flowforge.security.logfilter import redact_code

LANGUAGES = frozenset({"dart", "javascript", "typescript"})
KEYWORDS = frozenset({
    "if", "else", "for", "while", "do", "switch", "case", "default", "break", "continue", "return", "throw", "try",
    "catch", "finally", "on", "new", "await", "async", "function", "var", "let", "const", "final", "late", "typeof",
    "instanceof", "in", "of", "is", "as", "this", "super", "null", "true", "false", "undefined", "void", "yield",
    "assert", "class", "extends", "implements", "with", "import", "export", "from", "required", "static", "get", "set",
    "rethrow", "delete", "dynamic", "external", "factory", "operator", "part", "show", "hide", "sync", "abstract",
    "interface", "type", "enum", "public", "private", "protected", "readonly", "declare", "namespace", "mixin",
})
_IDENT = r"[A-Za-z_$][\w$]*"
_CALL = re.compile(rf"(?<![\w$.])({_IDENT})\s*(?:<[^<>();{{}}]*>)?\s*\(")
_STATIC_CALL = re.compile(rf"(?<![\w$.])([A-Z][\w$]*)\.({_IDENT})\s*\(")
_NAME = re.compile(rf"(?<![\w$.])({_IDENT})")
_CLASS = re.compile(rf"\b(?:class|mixin|extension)\s+({_IDENT})[^{{;]*\{{")
_ARROW = re.compile(rf"(?:\b(?:const|let|var|final)\s+|^\s*(?:(?:public|private|protected|static|readonly)\s+)*)"
                    rf"({_IDENT})\s*(?::\s*[^=;{{]+)?=\s*(async\s*)?(?:function\b\s*{_IDENT}?\s*)?"
                    rf"(?:\((?:[^()]|\([^()]*\))*\)|{_IDENT})\s*(?::\s*[^=;{{]+?)?\s*(=>|\{{)", re.MULTILINE)
_GETTER = re.compile(rf"\bget\s+({_IDENT})\s*(=>|\{{)")
_DECL = re.compile(rf"^\s*(?:@{_IDENT}\s+)*(?:late\s+)?(final|var|const|let)\s+(?:[\w$<>?,\[\]. ]+?\s+)?({_IDENT})\s*"
                   rf"(?::\s*([^=;]+?))?\s*(?:=|;|$)")
_DESTRUCT = re.compile(r"^\s*(?:final|var|const|let)\s*[\[({]([^=]*?)[\])}]\s*(?::[^=]+)?=")
_TYPED = re.compile(rf"^\s*([A-Z][\w$]*(?:<[^=;]*>)?\??)\s+({_IDENT})\s*=(?!=)")
_ASSIGN = re.compile(rf"^\s*({_IDENT})(?:\s*\.\s*{_IDENT}|\[[^\]]*\])*\s*(?:[-+*/%&|^]|\?\?)?=(?![=>])")
_MUTATE = re.compile(rf"(?<![\w$.])({_IDENT})\.(?:add|addAll|insert|insertAll|remove|removeAt|removeWhere|removeLast|"
                     r"clear|sort|push|pop|shift|unshift|splice|set|delete|putIfAbsent|update|addEntries)\s*\(")
_INCREMENT = re.compile(rf"(?<![\w$.])({_IDENT})\s*(?:\+\+|--)|(?:\+\+|--)\s*({_IDENT})")
_FOR_IN = re.compile(rf"\(\s*(?:final|var|const|let)?\s*(?:[\w<>?]+\s+)?({_IDENT})\s+(?:in|of)\b")
_GATHER = re.compile(r"\bFuture\.wait\s*\(|\)\s*\.wait\b|\bPromise\.(?:all|allSettled|race|any)\s*\(")
_AWAIT = re.compile(r"\bawait\b")
_HTTP_METHOD = re.compile(r"\.(get|post|put|patch|delete|head)\s*\(", re.IGNORECASE)
_FETCH_METHOD = re.compile(r"""method\s*:\s*['"](\w+)['"]""")
# an SDK call that changes something: data written, or the session (sign in, sign out) changed
_SDK_WRITE = re.compile(r"\.(?:insert|update|upsert|delete|remove|set|add|rpc|invoke|upload)\s*\(|\.auth\.\w+\s*\(")
# anonymous functions: a callback runs later, so its calls aren't the statement's (D25 skips lambdas the same way)
_CLOSURE = re.compile(rf"(?:(?<=[(,=:?\[])|(?<==>)|(?<=\breturn)|(?<=\bawait))\s*(?:async\s+)?"
                      rf"(?:function\s*{_IDENT}?\s*)?\((?:[^()]|\([^()]*\))*\)\s*(?:async\*?\s*)?(\{{|=>)")
_CLOSURE_ONE = re.compile(rf"(?<=[(,=:])\s*(?:async\s+)?{_IDENT}\s*=>")
_LOCAL = re.compile(rf"(?:\b(?:final|var|const|let|late)\s+(?:[\w$<>?,\[\]. ]+?\s+)?"
                    rf"|\b[A-Z][\w$]*(?:<[^=;()]*>)?\??\s+)({_IDENT})\s*(?=[=;:,)]|\s+(?:in|of)\b)")
_FIELD_WRITE = re.compile(rf"(?<![\w$.])({_IDENT})(?:\s*\[[^\]]*\])?\s*(?:[-+*/%&|^]|\?\?)?=(?![=>])")
_CONTINUES = re.compile(r"(?:else|catch|finally|on|while)\b")
_STRING = re.compile(r"""(['"`])((?:(?!\1).)*)\1""")


def mask(text: str, language: str) -> str:
    """The same text with comments and string contents blanked (newlines and quotes kept). `${…}` interpolations,
    and Dart's `$name`, stay code, so what a string reads still counts."""
    dart = language == "dart"
    out = list(text)
    n = len(text)

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    stack: list[list] = [["code", 0]]
    i = 0
    while i < n:
        frame, c = stack[-1], text[i]
        if frame[0] == "code":
            if text.startswith("//", i):
                j = text.find("\n", i)
                j = n if j < 0 else j
                blank(i, j)
                i = j
            elif text.startswith("/*", i):
                j = text.find("*/", i + 2)
                j = n if j < 0 else j + 2
                blank(i, j)
                i = j
            elif c == "{":
                frame[1] += 1
                i += 1
            elif c == "}":
                if frame[1] == 0 and len(stack) > 1:   # the end of an interpolation: back into the string
                    blank(i, i + 1)
                    stack.pop()
                else:
                    frame[1] -= 1
                i += 1
            elif c in "'\"" or (c == "`" and not dart):
                raw = dart and i > 0 and text[i - 1] == "r" and (i < 2 or not _word_char(text[i - 2]))
                quote = c * 3 if dart and text.startswith(c * 3, i) else c
                stack.append(["str", quote, raw, (dart and not raw) or c == "`"])
                i += len(quote)
            else:
                i += 1
            continue
        _, quote, raw, interp = frame
        if text.startswith(quote, i):
            stack.pop()
            i += len(quote)
        elif c == "\n" and len(quote) == 1 and quote != "`":
            stack.pop()   # an unclosed string ends at the line
            i += 1
        elif c == "\\" and not raw:
            blank(i, i + 2)
            i += 2
        elif interp and text.startswith("${", i):
            blank(i, i + 2)
            stack.append(["code", 0])
            i += 2
        elif interp and dart and c == "$" and i + 1 < n and (text[i + 1].isalpha() or text[i + 1] == "_"):
            blank(i, i + 1)
            i += 1
            while i < n and (text[i].isalnum() or text[i] == "_"):
                i += 1
        else:
            blank(i, i + 1)
            i += 1
    return "".join(out)


def _word_char(c: str) -> bool:
    return c.isalnum() or c in "_$"


def _match(code: str, i: int) -> int:
    """The index of the bracket that closes the one at `i` (or the end)."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = [pairs[code[i]]]
    for j in range(i + 1, len(code)):
        c = code[j]
        if c in pairs:
            stack.append(pairs[c])
        elif c in ")]}":
            if stack and c == stack[-1]:
                stack.pop()
                if not stack:
                    return j
    return len(code) - 1


def _skip(code: str, i: int, end: int | None = None) -> int:
    end = len(code) if end is None else end
    while i < end and code[i].isspace():
        i += 1
    return i


def _word(code: str, i: int) -> str:
    m = re.match(_IDENT, code[i:i + 64])
    return m.group(0) if m else ""


def words(name: str) -> str:
    """`getItineraryItems` → "get itinerary items", `_dayRoutes` → "day routes"."""
    parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name.lstrip("_$"))
    return " ".join(p.lower() for p in parts)


@dataclass
class Func:
    """One function of a Dart/JS/TS file. `body` is the span inside its braces, or its arrow expression."""

    path: str
    name: str            # "downloadTrip", or "Class.method"
    language: str
    line: int
    is_async: bool
    body: tuple[int, int]
    params: set[str] = field(default_factory=set)

    @property
    def key(self) -> str:
        return f"{self.path}:{self.name}"

    @property
    def short(self) -> str:
        return self.name.rsplit(".", 1)[-1]


@dataclass
class Source:
    path: str
    language: str
    text: str
    code: str                                   # masked
    starts: list[int] = field(default_factory=list)   # offset of each line's start

    def line(self, offset: int) -> int:
        lo, hi = 0, len(self.starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1


def _params(code: str, open_paren: int) -> set[str]:
    """Parameter names: TS `city: string` → city, Dart `String tripId` / `{required int n = 1}` → tripId, n."""
    names = set()
    for part in re.split(r"[,{}\[\]]", code[open_paren + 1:_match(code, open_paren)]):
        part = part.split("=")[0]
        tokens = [t for t in re.findall(_IDENT, part.split(":")[0] if ":" in part else part) if t not in KEYWORDS]
        if tokens:
            names.add(tokens[-1] if ":" not in part else tokens[0])
    return names


class Index:
    """Every function in the Dart/JS/TS files, and the names bound to a known service's client."""

    def __init__(self, sources: dict[str, tuple[str, str]]):
        self.files: dict[str, Source] = {}
        self.funcs: dict[str, Func] = {}
        self.getters: dict[tuple[str, str], tuple[int, int]] = {}   # (path, name) -> its expression span
        self.closures: dict[str, list[tuple[int, int]]] = {}         # path -> anonymous function bodies
        self._effects: dict[str, tuple[set[str], set[str]]] = {}
        for path, (language, text) in sources.items():
            code = mask(text, language)
            src = Source(path, language, text, code, [0] + [m.end() for m in re.finditer("\n", text)])
            self.files[path] = src
            self._functions(src)
            self.closures[path] = self._closures(code)

    def _class_at(self, src: str, classes: list[tuple[int, int, str]], at: int) -> str | None:
        inside = [c for c in classes if c[0] < at < c[1]]
        return max(inside, key=lambda c: c[0])[2] if inside else None

    def _add(self, src: Source, name: str, cls: str | None, at: int, is_async: bool, body: tuple[int, int],
             params: set[str]) -> None:
        full = cls if name == cls else f"{cls}.{name}" if cls else name   # a constructor is named for its class
        key = f"{src.path}:{full}"
        if key not in self.funcs:
            self.funcs[key] = Func(src.path, full, src.language, src.line(at), is_async, body, params)

    def _functions(self, src: Source) -> None:
        code = src.code
        classes = [(m.end() - 1, _match(code, m.end() - 1), m.group(1)) for m in _CLASS.finditer(code)]
        for m in _GETTER.finditer(code):
            start = m.end()
            end = _match(code, m.end() - 1) if m.group(2) == "{" else self._expr_end(code, start)
            self.getters[(src.path, m.group(1))] = (start, end)
        for m in _CALL.finditer(code):
            name = m.group(1)
            if name in KEYWORDS:
                continue
            before = code[:m.start()].rstrip()
            prev = re.search(rf"({_IDENT})\s*$", before)
            # a declaration follows a type (`Future<Trip?>`, `void`), `function`, or the end of something else
            if before.endswith((".", "=", ",", "(", "!", ":", "&", "|", "+", "-", "*", "/", "[")) \
                    or (prev and prev.group(1) in {"new", "await", "return", "throw", "yield", "case", "else", "get"}):
                continue
            paren = m.end() - 1
            close = _match(code, paren)
            j = _skip(code, close + 1)
            if code.startswith(":", j):   # a TS return type, or a Dart constructor's initialisers
                brace = code.find("{", j)
                arrow = code.find("=>", j)
                semi = code.find(";", j)
                stops = [x for x in (brace, arrow, semi) if x >= 0]
                if not stops or min(stops) == semi:
                    continue
                j = min(stops)
            is_async = False
            tail = re.match(r"(async\*?|sync\*)\s*", code[j:j + 12])
            if tail:
                is_async = tail.group(1).startswith("async")
                j += tail.end()
            head = code[max(0, before.rfind("\n", 0, len(before)) + 1):m.start()]
            is_async = is_async or bool(re.search(r"\basync\b", head))
            if code.startswith("{", j):
                body = (j + 1, _match(code, j))
            elif code.startswith("=>", j):
                body = (j + 2, self._expr_end(code, j + 2))
            else:
                continue
            self._add(src, name, self._class_at(src.path, classes, m.start()), m.start(), is_async, body,
                      _params(code, paren))
        for m in _ARROW.finditer(code):
            name = m.group(1)
            if name in KEYWORDS:
                continue
            if m.group(3) == "{":
                body = (m.end(), _match(code, m.end() - 1))
            else:
                j = _skip(code, m.end())
                body = (j + 1, _match(code, j)) if code.startswith("{", j) else (j, self._expr_end(code, j))
            paren = code.find("(", m.start(), m.end())
            self._add(src, name, self._class_at(src.path, classes, m.start()), m.start(), bool(m.group(2)), body,
                      _params(code, paren) if paren >= 0 else set())

    def _closures(self, code: str) -> list[tuple[int, int]]:
        out = []
        for m in _CLOSURE.finditer(code):
            out.append((m.end(), _match(code, m.end() - 1)) if m.group(1) == "{" else
                       (m.end(), self._expr_end(code, m.end())))
        for m in _CLOSURE_ONE.finditer(code):
            j = _skip(code, m.end())
            out.append((j + 1, _match(code, j)) if code.startswith("{", j) else (j, self._expr_end(code, j)))
        return out

    def skips(self, func: Func, span: tuple[int, int]) -> list[tuple[int, int]]:
        """What inside `span` doesn't run as part of it: other functions declared there, and callbacks. A statement
        that gathers (`Future.wait`, `Promise.all`) runs its callbacks now, so they count."""
        inner = [b for b in self.nested(func, span) if b != func.body]
        if _GATHER.search(self.files[func.path].code[span[0]:span[1]]):
            return inner
        return inner + [c for c in self.closures.get(func.path, [])
                        if span[0] <= c[0] and c[1] <= span[1] and c != func.body]

    def effects(self, func: Func) -> tuple[set[str], set[str]]:
        """The names outside a function (fields, globals) that it reads and writes, through the repo functions it
        calls too: `loadTrips()` filling `_trips` orders it before a line that reads `_trips` (D32)."""
        if func.key in self._effects:
            return self._effects[func.key]
        self._effects[func.key] = (set(), set())
        a, b = func.body
        text = self.files[func.path].code[a:b].replace("this.", "")
        local = set(_LOCAL.findall(text)) | func.params | set(_FOR_IN.findall(text))
        writes = {n for n in _FIELD_WRITE.findall(text)} | set(_MUTATE.findall(text)) \
            | {x or y for x, y in _INCREMENT.findall(text)}
        reads = {n for n in _NAME.findall(text) if n not in KEYWORDS}
        reads, writes = reads - local, (writes - local) - KEYWORDS
        for _, target in self.calls(func):
            r, w = self.effects(target)
            reads |= r
            writes |= w
        self._effects[func.key] = (reads, writes)
        return reads, writes

    @staticmethod
    def _expr_end(code: str, i: int) -> int:
        """Where an arrow's expression ends: the `;`, or the `,` / closing bracket of what holds it, at depth 0."""
        depth = 0
        for j in range(i, len(code)):
            c = code[j]
            if c in "([{":
                depth += 1
            elif c in ")]}":
                if depth == 0:
                    return j
                depth -= 1
            elif c in ";," and depth == 0:
                return j
        return len(code)

    def resolve(self, name: str, func: Func) -> Func | None:
        """A call by name: a method of the same class, then the same file, then a name unique in the repo."""
        if "." in name:
            found = [f for f in self.funcs.values() if f.name == name]
            return found[0] if len(found) == 1 else None
        cls = func.name.rsplit(".", 1)[0] if "." in func.name else None
        for key in ([f"{func.path}:{cls}.{name}"] if cls else []) + [f"{func.path}:{name}"]:
            if key in self.funcs:
                return self.funcs[key]
        found = [f for f in self.funcs.values() if f.short == name and "." not in f.name]
        return found[0] if len(found) == 1 else None

    def calls(self, func: Func, span: tuple[int, int] | None = None) -> list[tuple[int, Func]]:
        """The repo functions called in `span` (default: the whole body), with where."""
        src = self.files[func.path]
        a, b = span or func.body
        skip = self.skips(func, (a, b))
        out: list[tuple[int, Func]] = []
        for m in _CALL.finditer(src.code, a, b):
            target = self.resolve(m.group(1), func)
            if target is not None and target is not func and not any(x <= m.start() < y for x, y in skip):
                out.append((m.start(), target))
        for m in _STATIC_CALL.finditer(src.code, a, b):
            target = self.resolve(f"{m.group(1)}.{m.group(2)}", func)
            if target is not None and target is not func and not any(x <= m.start() < y for x, y in skip):
                out.append((m.start(), target))
        return sorted(out, key=lambda c: c[0])

    def nested(self, func: Func, span: tuple[int, int]) -> list[tuple[int, int]]:
        """Bodies of other functions declared inside `span`: their calls belong to them, not to this statement."""
        return [f.body for f in self.funcs.values()
                if f.path == func.path and f is not func and span[0] <= f.body[0] and f.body[1] <= span[1]]

    def callers(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {k: set() for k in self.funcs}
        for func in self.funcs.values():
            for _, target in self.calls(func):
                out[target.key].add(func.key)
        return out


class Reach:
    """Which dependencies a Dart/JS/TS statement or function reaches: the scan's call places inside it, a known
    service's client it uses, and the repo functions it calls, followed through (D32)."""

    def __init__(self, index: Index, places: Places, dep_ids: set[str]):
        self.index = index
        self.at: dict[tuple[str, int], list[str]] = {}
        for dep_id, items in places.by_dep.items():
            for path, line, text in items:
                if text in CALL_TEXTS and path in index.files:
                    self.at.setdefault((path, line), []).append(dep_id)
        # a service's client: its own expression, and every name the repo binds to it
        self.clients: list[tuple[re.Pattern, str]] = []
        for service_id, patterns in CLIENTS.items():
            service = services.by_id(service_id)
            slug = re.sub(r"[^a-z0-9]+", "-", service_id.lower()).strip("-")
            dep_id = f"{service['kind']}-{slug}" if service else None
            if dep_id not in dep_ids:
                continue
            expr = re.compile("|".join(patterns))
            self.clients.append((expr, dep_id))
            for src in index.files.values():
                for (path, name), (a, b) in index.getters.items():
                    if path == src.path and expr.search(src.code[a:b]):
                        self.clients.append((re.compile(rf"(?<![\w$.]){re.escape(name)}\b"), dep_id))
                for m in re.finditer(rf"({_IDENT})\s*(?::[^=;]+)?=\s*(?:await\s+)?([^;\n]+)", src.code):
                    if expr.search(m.group(2)) and m.group(1) not in KEYWORDS:
                        self.clients.append((re.compile(rf"(?<![\w$.]){re.escape(m.group(1))}\b"), dep_id))
        self._memo: dict[str, list[Hit]] = {}

    def statement(self, func: Func, span: tuple[int, int]) -> list[Hit]:
        src = self.index.files[func.path]
        skip = self.index.skips(func, span)
        inside = lambda at: span[0] <= at < span[1] and not any(a <= at < b for a, b in skip)   # noqa: E731
        text = src.code[span[0]:span[1]]
        method = _method(text)
        found: list[tuple[int, Hit]] = []
        for line in range(src.line(span[0]), src.line(max(span[0], span[1] - 1)) + 1):
            at = src.starts[line - 1]
            if any(a <= at and src.starts[min(line, len(src.starts) - 1)] <= b for a, b in skip):
                continue
            for dep in self.at.get((func.path, line), []):
                found.append((max(at, span[0]), Hit(dep, method=method)))
        for pattern, dep in self.clients:
            for m in pattern.finditer(src.code, span[0], span[1]):
                if inside(m.start()):
                    tail = src.code[m.start():_simple_end(src.code, m.start(), span[1], src.language)]
                    found.append((m.start(), Hit(dep, method="POST" if _SDK_WRITE.search(tail) else "GET")))
        for at, target in self.index.calls(func, span):
            if inside(at):
                found += [(at, h) for h in self.function(target)]
        found.sort(key=lambda f: f[0])
        out: list[Hit] = []
        for _, hit in found:
            same = next((h for h in out if h.dep == hit.dep), None)
            if same is None:
                out.append(Hit(hit.dep, hit.method, hit.tool))
            elif hit.method not in (None, "GET", "HEAD") or same.method is None:
                same.method = hit.method   # reads and writes the same service: it writes (D25's rule)
        return out

    def function(self, func: Func) -> list[Hit]:
        if func.key in self._memo:
            return self._memo[func.key]
        self._memo[func.key] = []
        hits = self.statement(func, func.body)
        self._memo[func.key] = hits
        return hits


def _method(text: str) -> str | None:
    if m := _FETCH_METHOD.search(text):
        return m.group(1).upper()
    if m := _HTTP_METHOD.search(text):
        return m.group(1).upper()
    return "GET" if "fetch(" in text else None


@dataclass
class Part:
    """What one statement is, beyond `Stmt`: its spans, its block and the declaration it makes."""

    span: tuple[int, int]
    block: int                      # the start of the block it sits in
    keyword: str | None = None      # final, var, const, let
    typed: bool = False             # a declared type (Dart `final Trip? trip`, TS `const a: T`)
    cond: tuple[int, int] | None = None


def _ends_line(code: str, i: int, language: str) -> bool:
    """JS without `;`: does the line break at `i` end the statement?"""
    if language == "dart":
        return False
    before = code[:i].rstrip()
    after = code[i:].lstrip()
    if not before or before[-1] in "=+-*/%&|^,(.[{?:<>!":
        return False
    return not (after[:1] and after[0] in ".?:+-*/%&|^,)]}=" or re.match(r"(else|catch|finally)\b", after))


def _simple_end(code: str, i: int, end: int, language: str) -> int:
    """The end of a simple statement starting at `i`: after its `;`, at a line break that ends it (JS), or before the
    `}` that closes the block."""
    depth = 0
    j = i
    while j < end:
        c = code[j]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return j
            depth -= 1
            if depth == 0 and c == "}":
                nxt = _skip(code, j + 1, end)
                goes_on = code[nxt] in ".,;)]?:+-*/%&|^=" or _CONTINUES.match(code, nxt)
                if nxt >= end or (not goes_on and "\n" in code[j:nxt]):
                    return j + 1
        elif c == ";" and depth == 0:
            return j + 1
        elif c == "\n" and depth == 0 and j > i and _ends_line(code, j, language):
            return j
        j += 1
    return end


class _Reader:
    """One function's statements in order (D25's `Body`), from its masked code."""

    def __init__(self, func: Func, index: Index, reach: Reach):
        self.func, self.index, self.reach = func, index, reach
        self.src = index.files[func.path]
        self.code = self.src.code
        self.body = Body(func)   # type: ignore[arg-type]
        self.parts: dict[int, Part] = {}

    def add(self, span: tuple[int, int], ifs: list[tuple[int, str]], loop: bool, block: int, *, is_if: bool = False,
            hit_span: tuple[int, int] | None = None, header: str | None = None) -> Stmt:
        a, b = span
        text = self.code[a:b]
        reads = {n for n in _NAME.findall(text) if n not in KEYWORDS}
        writes: set[str] = set()
        keyword, typed = None, False
        if not is_if:
            if m := _DECL.match(text):
                keyword, typed = m.group(1), bool(m.group(3)) or self.src.language == "dart" and \
                    bool(re.match(rf"\s*(?:late\s+)?(?:final|var|const)\s+[\w$<>?,\[\]. ]+?\s+{_IDENT}\s*=", text))
                writes.add(m.group(2))
            if m := _DESTRUCT.match(text):
                writes |= {n for n in re.findall(_IDENT, m.group(1)) if n not in KEYWORDS}
            if m := _TYPED.match(text):
                writes.add(m.group(2))
            if m := _ASSIGN.match(text):
                writes.add(m.group(1))
            writes |= {n for n in _MUTATE.findall(text)}
            writes |= {x or y for x, y in _INCREMENT.findall(text)}
        if header == "for":
            writes |= set(_FOR_IN.findall(text))
        reads -= writes if keyword else set()
        for _, target in self.index.calls(self.func, span):   # what the repo functions it calls read and write
            r, w = self.index.effects(target)
            reads |= r
            writes |= w
        stripped = text.lstrip()
        s = Stmt(idx=len(self.body.stmts), node=None, line=self.src.line(a + len(text) - len(stripped)), reads=reads,
                 writes=writes, hits=self.reach.statement(self.func, hit_span or span) if hit_span != (0, 0) else [],
                 ifs=list(ifs), loop=loop, returns=bool(re.match(r"(return|throw|rethrow)\b", stripped)),
                 gathered=bool(_GATHER.search(text)), is_if=is_if)
        self.body.stmts.append(s)
        self.parts[s.idx] = Part(span=span, block=block, keyword=keyword, typed=typed)
        return s

    def extent(self, i: int, end: int) -> int:
        """Where the statement starting at `i` ends, with its blocks, `else` and `catch` included."""
        code = self.code
        if code.startswith("{", i):
            return _match(code, i) + 1
        word = _word(code, i)
        if word in ("if", "for", "while", "switch") and code.startswith("(", _skip(code, i + len(word), end)):
            p = _skip(code, i + len(word), end)
            j = self.extent(_skip(code, _match(code, p) + 1, end), end)
            if word == "if":
                k = _skip(code, j, end)
                if _word(code, k) == "else":
                    j = self.extent(_skip(code, k + 4, end), end)
            return j
        if word == "do":
            j = self.extent(_skip(code, i + 2, end), end)
            return _simple_end(code, _skip(code, j, end), end, self.src.language)
        if word == "try":
            j = self.extent(_skip(code, i + 3, end), end)
            while True:
                k = _skip(code, j, end)
                w = _word(code, k)
                if w == "catch" or w == "finally" or w == "on":
                    brace = code.find("{", k, end)
                    if brace < 0:
                        return j
                    j = _match(code, brace) + 1
                else:
                    return j
        return _simple_end(code, i, end, self.src.language)

    def walk(self, a: int, b: int, ifs: list[tuple[int, str]], loop: bool) -> None:
        code = self.code
        i = a
        while True:
            i = _skip(code, i, b)
            while i < b and code[i] == ";":
                i = _skip(code, i + 1, b)
            if i >= b:
                return
            word = _word(code, i)
            if code.startswith("{", i):
                close = _match(code, i)
                self.walk(i + 1, close, ifs, loop)
                i = close + 1
            elif word == "if" and code.startswith("(", _skip(code, i + 2, b)):
                i = self._if(i, b, ifs, loop)
            elif word in ("for", "while") and code.startswith("(", _skip(code, i + len(word), b)):
                p = _skip(code, i + len(word), b)
                q = _match(code, p)
                self.add((p + 1, q), ifs, loop, a, header="for" if word == "for" else None)
                body_start = _skip(code, q + 1, b)
                end = self.extent(body_start, b)
                self._branch(body_start, end, ifs, True)
                i = end
            elif word == "do":
                body_start = _skip(code, i + 2, b)
                end = self.extent(body_start, b)
                self._branch(body_start, end, ifs, True)
                tail = _skip(code, end, b)
                close = _simple_end(code, tail, b, self.src.language)
                self.add((tail, close), ifs, loop, a)
                i = close
            elif word == "try":
                end = self.extent(i, b)
                j = _skip(code, i + 3, b)
                while j < end:
                    brace = code.find("{", j, end)
                    if brace < 0:
                        break
                    close = _match(code, brace)
                    self.walk(brace + 1, close, ifs, loop)
                    j = close + 1
                i = end
            else:
                end = self.extent(i, b)
                self.add((i, end), ifs, loop, a)
                i = end

    def _branch(self, start: int, end: int, ifs: list[tuple[int, str]], loop: bool) -> None:
        if self.code.startswith("{", start):
            self.walk(start + 1, end - 1, ifs, loop)
        else:
            self.walk(start, end, ifs, loop)

    def _if(self, i: int, b: int, ifs: list[tuple[int, str]], loop: bool) -> int:
        code = self.code
        p = _skip(code, i + 2, b)
        q = _match(code, p)
        test = self.add((p + 1, q), ifs, loop, i, is_if=True)
        self.parts[test.idx].cond = (p + 1, q)
        first = len(self.body.stmts)
        body_start = _skip(code, q + 1, b)
        body_end = self.extent(body_start, b)
        self._branch(body_start, body_end, [*ifs, (test.idx, "yes")], loop)
        after_body = len(self.body.stmts)
        end = body_end
        k = _skip(code, body_end, b)
        if _word(code, k) == "else":
            else_start = _skip(code, k + 4, b)
            end = self.extent(else_start, b)
            self._branch(else_start, end, [*ifs, (test.idx, "no")], loop)
        test.block_end = len(self.body.stmts) - 1
        yes = next((s for s in self.body.stmts[first:after_body] if s.returns and not s.loop), None)
        no = next((s for s in self.body.stmts[after_body:] if s.returns and not s.loop), None)
        if yes and not no:
            test.stops, test.stop_line = "yes", yes.line
        elif no and not yes:
            test.stops, test.stop_line = "no", no.line
        return end


def read(func: Func, index: Index, reach: Reach) -> tuple[Body, dict[int, Part]]:
    reader = _Reader(func, index, reach)
    a, b = func.body
    if index.files[func.path].code[a - 2:a] == "=>" or not index.files[func.path].code[a - 1:a] == "{":
        reader.add((a, b), [], False, a)   # an arrow's expression is one statement
    else:
        reader.walk(a, b, [], False)
    return reader.body, reader.parts


def entries(index: Index, reach: Reach) -> list[Func]:
    """Functions that reach a dependency and that nothing in the repo calls, in file and line order."""
    callers = index.callers()
    found = [f for f in index.funcs.values() if reach.function(f) and not callers[f.key]]
    return sorted(found, key=lambda f: (f.path, f.line))


class Lang:
    """What the shared flow builder asks of a Dart/JS/TS function (D32)."""

    name = "curly"

    def __init__(self, index: Index):
        self.index = index
        self.parts: dict[str, dict[int, Part]] = {}   # func key -> statement index -> Part
        self.bodies: dict[str, Body] = {}

    def read(self, func: Func, reach: Reach) -> Body:
        if func.key not in self.bodies:
            self.bodies[func.key], self.parts[func.key] = read(func, self.index, reach)
        return self.bodies[func.key]

    def start_line(self, func: Func) -> int:
        return func.line

    @staticmethod
    def gather(func: Func) -> str:
        return "a record's .wait" if func.language == "dart" else "Promise.all"

    def change(self, calls: list[Call]) -> Change | None:
        return change(calls, self)

    def is_async(self, func: Func) -> bool:
        return func.is_async

    def _part(self, func: Func, s: Stmt) -> Part:
        return self.parts[func.key][s.idx]

    def text(self, func: Func, s: Stmt, *, raw: bool = False) -> str:
        p = self._part(func, s)
        src = self.index.files[func.path]
        a, b = p.cond or p.span
        return (src.text if raw else src.code)[a:b]

    def end_line(self, func: Func, s: Stmt) -> int:
        p = self._part(func, s)
        return self.index.files[func.path].line(max(p.span[0], p.span[1] - 1))

    def awaited(self, func: Func, s: Stmt) -> bool:
        return bool(_AWAIT.search(self.text(func, s)))

    def label(self, func: Func, s: Stmt) -> str:
        """A string with spaces it passes, without a trailing note in brackets; else the repo function it calls."""
        raw = self.text(func, s, raw=True)
        for m in _STRING.finditer(raw):
            value = m.group(2).strip()
            if " " in value and "$" not in value and "http" not in value:
                return re.sub(r"\s*\([^)]*\)\s*$", "", value)[:120]
        p = self._part(func, s)
        calls = self.index.calls(func, p.span)
        return words(calls[0][1].short) if calls else ""

    def condition(self, func: Func, s: Stmt) -> str:
        return re.sub(r"\s+", " ", self.text(func, s, raw=True)).strip()

    def keep_decision(self, func: Func, body: Body, s: Stmt) -> bool:
        """A check that only stops on UI state (`!mounted || request != _request`) isn't the app's flow (D33): keep a
        decision that guards a call, or whose condition reads a call's result or an input."""
        if any(t.hits for t in body.stmts[s.idx + 1: s.block_end + 1]):
            return True
        from_calls = set().union(*(t.writes for t in body.stmts[: s.idx] if t.hits))
        return bool(s.reads & (from_calls | func.params))

    def question(self, func: Func, body: Body, s: Stmt) -> str:
        cond = re.sub(r"\s+", " ", self.text(func, s)).strip()
        name, failed = None, False
        if m := re.fullmatch(rf"({_IDENT})\s*(==|===|!=|!==)\s*(null|undefined)", cond):
            name, failed = m.group(1), m.group(2).startswith("=")
        elif m := re.fullmatch(rf"!\s*({_IDENT})(?:\.ok)?", cond):
            name, failed = m.group(1), True
        elif m := re.fullmatch(rf"({_IDENT})\.(isEmpty|isNotEmpty|ok)", cond):
            name, failed = m.group(1), m.group(2) == "isEmpty"
        elif m := re.fullmatch(_IDENT, cond):
            name = cond
        if name is None:
            return f"Is {self.condition(func, s)} true?"
        writer = next((t for t in reversed(body.stmts[: s.idx]) if name in t.writes and t.hits), None)
        if writer is not None and (said := self.label(func, writer)):
            return f'Did "{said}" {"fail" if failed else "work"}?'
        said = words(name)
        if name in func.params:
            return f"No {said} given?" if failed else f"Was a {said} given?"
        return f"No {said}?" if failed else f"Has a {said}?"


_DECL_AWAIT = re.compile(rf"^(final|var|const|let)\s+(?:([\w$<>?,\[\]. ]+?)\s+)?({_IDENT})\s*(?::\s*([^=]+?))?\s*="
                         r"\s*await\s+(.+?)\s*(;?)\s*$", re.DOTALL)
_ASSIGN_AWAIT = re.compile(rf"^({_IDENT})\s*=\s*await\s+(.+?)\s*(;?)\s*$", re.DOTALL)
_BARE_AWAIT = re.compile(r"^await\s+(.+?)\s*(;?)\s*$", re.DOTALL)


def _one_line(expr: str) -> str:
    """A call chain written over several lines, on one: `supabaseClient\n  .from('x')` → `supabaseClient.from('x')`."""
    return re.sub(r"\s+", " ", re.sub(r"\s*\n\s*(?=\.)", "", expr))


def _plain(raw: str) -> tuple[str | None, str | None, str | None, str, bool, str | None] | None:
    """`final x = await e;` → (keyword, dart type, name, e, semicolon, ts type); `x = await e;` → (None, None, x, …);
    `await e;` → (None, None, None, e, …). Anything else → None."""
    raw = raw.strip()
    if m := _DECL_AWAIT.match(raw):
        keyword, dart_type, name, ts_type, expr, semi = m.groups()
        return keyword, dart_type, name, _one_line(expr), bool(semi), ts_type
    if m := _ASSIGN_AWAIT.match(raw):
        return None, None, m.group(1), _one_line(m.group(2)), bool(m.group(3)), None
    if m := _BARE_AWAIT.match(raw):
        return None, None, None, _one_line(m.group(1)), bool(m.group(2)), None
    return None


def change(calls: list[Call], lang: Lang) -> Change | None:
    """The calls written to run together (D27, D32): Dart's record `.wait`, JS/TS `Promise.all`, when one block of one
    async function holds them as plain `x = await …` with nothing between using a result or changing an input."""
    func: Func = calls[0].func
    if not func.is_async or any(c.func is not func for c in calls):
        return None
    parts = lang.parts[func.key]
    src = lang.index.files[func.path]
    blocks: dict[int, list[Call]] = {}
    for c in calls:
        blocks.setdefault(parts[c.stmt.idx].block, []).append(c)
    chosen = max(blocks.values(), key=lambda g: (len(g), -g[0].line))
    plain = [(c, p) for c in chosen if (p := _plain(lang.text(func, c.stmt, raw=True)))
             and not (func.language == "typescript" and p[5])]
    if len(plain) < 2:
        return None
    plain.sort(key=lambda cp: cp[0].stmt.idx)
    members = {c.stmt.idx for c, _ in plain}
    first, last = plain[0][0].stmt.idx, plain[-1][0].stmt.idx
    targets = set().union(*(c.stmt.writes for c, _ in plain))
    reads = set().union(*(c.stmt.reads for c, _ in plain))
    for s in lang.bodies[func.key].stmts[first + 1:last]:
        if s.idx not in members and (s.reads & targets or s.writes & reads):
            return None   # code between them uses a result, or changes what a call reads
    names = [p[2] or "_" for _, p in plain]
    exprs = [p[3] for _, p in plain]
    keywords = {p[0] for _, p in plain if p[0]}
    if keywords and len(keywords) != 1 and not keywords <= {"final", "var", "const", "let"}:
        return None
    if any(p[0] is None and p[2] for _, p in plain) and keywords:
        return None   # a declaration beside a plain assignment: by hand
    first_line = plain[0][0].line
    last_line = lang.end_line(func, plain[-1][0].stmt)
    lines = src.text.splitlines()
    indent = re.match(r"\s*", lines[first_line - 1]).group(0)
    semi = ";" if func.language == "dart" or all(p[4] for _, p in plain) else ""
    if func.language == "dart":
        kw = "var" if "var" in keywords else "final" if keywords else ""
        typed = [f"{p[1]} {p[2]}" if p[1] else (p[2] or "_") for _, p in plain]
        lhs = f"{kw + ' ' if kw else ''}({', '.join(typed)}) = " if any(n != "_" for n in names) else ""
        line = f"{indent}{lhs}await ({', '.join(exprs)}).wait{semi}"
        has_async = re.search(r"""^\s*import\s+['"]dart:async['"]""", src.text, re.MULTILINE)
        import_text = None if has_async else "import 'dart:async';"
    else:
        kw = "let" if keywords & {"let", "var"} else "const" if keywords else ""
        lhs = f"{kw + ' ' if kw else ''}[{', '.join('' if n == '_' else n for n in names)}] = " \
            if any(n != "_" for n in names) else ""
        line = f"{indent}{lhs}await Promise.all([{', '.join(exprs)}]){semi}"
        import_text = None
    spans = [(c.line, lang.end_line(func, c.stmt)) for c, _ in plain]
    after: list[str] = []
    for n in range(first_line, last_line + 1):
        if n == spans[0][0]:
            after.append(line)
        elif not any(a <= n <= b for a, b in spans):
            after.append(lines[n - 1])
    weights = [c.weight for c, _ in plain]
    left = [c for c in calls if c.stmt.idx not in members]
    return Change(path=func.path, first_line=first_line,
                  before=[redact_code(x) for x in lines[first_line - 1:last_line]],
                  after=[redact_code(x) for x in after], saved_ms=round(sum(weights) - max(weights), 1),
                  by_hand=[f'"{c.words}" ({c.ref}): in another block' for c in sorted(left, key=lambda c: c.line)],
                  import_text=import_text)

