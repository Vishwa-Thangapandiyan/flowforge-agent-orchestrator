"""Key finders (D31, CLAUDE.md §6.4 step 1): pure functions over one file's text, no I/O.

Two ways a key shows: a known shape (`KEY_PATTERNS`, on any line, comments included), or a high-entropy string given
to a key-like name (Python by the AST, JS/TS and Dart by patterns). A hit holds the line, what kind of key it is and
the name it is given to, never the value. Pattern-based: known key formats and these shapes, not everything.
"""

from __future__ import annotations

import ast
import math
import re
from collections import Counter
from dataclasses import dataclass

from flowforge.security.logfilter import KEY_PATTERNS, REDACTED, Redactor, redact_code

# Names for KEY_PATTERNS, in the same order
KEY_SHAPES = list(zip(
    ("private key", "Stripe key", "Razorpay key", "Google API key", "NVIDIA key", "Anthropic key", "OpenAI-style key",
     "token (JWT)"),
    KEY_PATTERNS, strict=True))
PEM_START = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
SECRET_PARTS = frozenset({"key", "apikey", "token", "secret", "password", "passwd", "pwd", "credential", "credentials"})
MIN_LENGTH = 16
MIN_ENTROPY = 3.5   # bits per character
_PLACEHOLDER = re.compile(r"your|example|sample|placeholder|changeme|change_me|replace|dummy|todo|<[^>]*>|\$\{|^\$|"
                          r"^(.)\1+$|x{4,}|\*{3,}|\.\.\.", re.IGNORECASE)
_KEY_CHARS = re.compile(r"^[A-Za-z0-9_\-+=]+$")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_WORDS = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
# JS/TS/Dart: a name, then `=` or `:`, then a quoted string on the same line
_GIVEN = re.compile(r"""\b([A-Za-z_$][\w$]*)["']?\s*(?::\s*[\w<>?, ]+\s*)?[:=]\s*(['"`])((?:(?!\2).)*)\2""")


@dataclass(frozen=True)
class KeyHit:
    line: int
    label: str              # "Google API key", or "secret" when only entropy and the name tell
    name: str | None = None  # the variable, key or argument it is given to


def entropy(value: str) -> float:
    counts = Counter(value)
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())


def is_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER.search(value))


def is_secret_name(name: str) -> bool:
    """`apiKey`, `api_key`, `SUPABASE_KEY`, `accessToken`: a part of the name is a key word; `keyboard` is not."""
    parts = [p.lower() for p in _WORDS.findall(name)]
    return any(p in SECRET_PARTS for p in parts) or name.lower() in SECRET_PARTS


def looks_secret(value: str) -> bool:
    """Long, random-looking, one run of key characters: not a sentence, URL, path, reference (`env:NAME`), pattern,
    template, env var name (`GITHUB_TOKEN`) or placeholder."""
    if len(value) < MIN_LENGTH or not _KEY_CHARS.match(value) or _ENV_NAME.match(value) or is_placeholder(value):
        return False
    classes = sum(bool(re.search(p, value)) for p in (r"[a-z]", r"[A-Z]", r"\d"))
    return classes >= 2 and entropy(value) >= MIN_ENTROPY


def _shape(text: str) -> str | None:
    if PEM_START.search(text):
        return "private key"
    return next((label for label, pattern in KEY_SHAPES if pattern.search(text)), None)


def _python_names(text: str) -> dict[int, list[tuple[str, str]]]:
    """line -> (name, value) for each string given to a name: assignments, keywords, dict keys. Values stay here."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    out: dict[int, list[tuple[str, str]]] = {}

    def strings(node: ast.AST) -> list[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.JoinedStr):
            return [v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
        return []

    def target_name(t: ast.AST) -> str | None:
        return t.id if isinstance(t, ast.Name) else t.attr if isinstance(t, ast.Attribute) else None

    for node in ast.walk(tree):
        pairs: list[tuple[str | None, ast.AST]] = []
        if isinstance(node, ast.Assign):
            pairs = [(target_name(t), node.value) for t in node.targets]
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            pairs = [(target_name(node.target), node.value)]
        elif isinstance(node, ast.keyword) and node.arg:
            pairs = [(node.arg, node.value)]
        elif isinstance(node, ast.Dict):
            pairs = [(k.value, v) for k, v in zip(node.keys, node.values, strict=True)
                     if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        for name, value in pairs:
            if name:
                for s in strings(value):
                    out.setdefault(value.lineno, []).append((name, s))
    return out


def _given(line: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(3)) for m in _GIVEN.finditer(line)]


def find_keys(text: str, language: str | None) -> list[KeyHit]:
    """Every line that holds a key, once, in line order."""
    python = _python_names(text) if language == "python" else {}
    hits: list[KeyHit] = []
    for n, line in enumerate(text.splitlines(), 1):
        given = python.get(n, []) if language == "python" else _given(line) if language else []
        label = _shape(line)
        if label is not None:
            name = next((name for name, value in given if _shape(value) is not None), None)
            hits.append(KeyHit(n, label, name))
            continue
        name = next((name for name, value in given if is_secret_name(name) and looks_secret(value)), None)
        if name is not None:
            hits.append(KeyHit(n, "secret", name))
    return hits


_LITERAL = re.compile(r"""(['"`])((?:\\.|(?!\1).)*)\1""")


def _only_key(value: str) -> bool:
    """The whole string is one key: a known shape from start to end, or one random-looking value."""
    return any(p.fullmatch(value) for _, p in KEY_SHAPES) or looks_secret(value)


def key_span(text: str, language: str | None, line: int) -> tuple[int, int, str] | None:
    """(start, end, value) of the string literal on `line` (1-based) that is exactly a key, quotes included, so a fix
    can swap it for an env lookup (D37). None when the key is only part of a string ("Bearer …"), in an f-string or
    template, in a comment, or the language isn't Python, JS or TS. The only finder that returns a value: for the fix
    and the locked key view, never for display or storage."""
    lines = text.splitlines()
    if not 0 < line <= len(lines):
        return None
    source = lines[line - 1]
    if language == "python":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return None
        inside_f = {id(v) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for v in node.values}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in inside_f
                    and node.lineno == line == node.end_lineno and _only_key(node.value)):
                raw = source.encode()   # AST columns count UTF-8 bytes
                start = len(raw[:node.col_offset].decode(errors="replace"))
                end = len(raw[:node.end_col_offset].decode(errors="replace"))
                return start, end, node.value
        return None
    if language not in ("javascript", "typescript", "dart"):
        return None
    for m in _LITERAL.finditer(source):
        before = source[:m.start()]
        if "//" in before or "/*" in before or (m.group(1) == "`" and "${" in m.group(2)):
            continue
        if _only_key(m.group(2)):
            return m.start(), m.end(), m.group(2)
    return None


# Masked lines: a file safe to cut excerpts from. A key split over lines ("sk_…" "…" or a private-key block) is found
# by the finders but slips past a line-by-line mask, so every line such a key touches is masked first (Codex review).

_BASE64_LINE = re.compile(r"^\s*[A-Za-z0-9+/=]{16,}\s*$")
_GLUE_AFTER = re.compile(r"""(?:\+|['"`])\s*$""")    # a line that goes on: ends with `+` or a string (Dart's 'a' 'b')
_GLUE_BEFORE = re.compile(r"""^\s*(?:\+\s*)?['"`]""")   # a line that carries on one: starts with `+ "…` or a string


def _secret_value(value: str) -> bool:
    return any(p.search(value) for p in KEY_PATTERNS) or bool(PEM_START.search(value)) or _only_key(value)


def _python_spans(text: str) -> list[tuple[int, int, int, int]]:
    """(first line, first column, last line, last column) of each string over several lines that holds a key: an
    implicit or `+` concatenation, or a triple-quoted block. Columns count characters; lines are 1-based."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()

    def chars(line: int, col: int) -> int:   # AST columns count UTF-8 bytes
        return len(lines[line - 1].encode()[:col].decode(errors="replace")) if 0 < line <= len(lines) else col

    def joined(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = joined(node.left), joined(node.right)
            return None if left is None or right is None else left + right
        return None

    spans = []
    for node in ast.walk(tree):
        value = joined(node)
        end = getattr(node, "end_lineno", None)
        if value is not None and end is not None and end > node.lineno and _secret_value(value):
            spans.append((node.lineno, chars(node.lineno, node.col_offset), end, chars(end, node.end_col_offset or 0)))
    return spans


def _wipe_strings(line: str) -> str:
    return _LITERAL.sub(lambda m: f"{m.group(1)}{REDACTED}{m.group(1)}", line)


def masked_lines(text: str, language: str | None, redactor: Redactor | None = None) -> list[str]:
    """`text`'s lines, one for one, with every key masked, a key split over lines included: safe to store, show or
    hand to an agent. Pattern-based like the finders: known key formats and these shapes, not everything."""
    lines = text.splitlines()
    out = list(lines)
    if language == "python":
        for first, start, last, end in _python_spans(text):
            for n in range(first, last + 1):
                raw = lines[n - 1]
                lead = raw[:len(raw) - len(raw.lstrip())]
                head = raw[:start] if n == first else lead
                tail = raw[end:] if n == last else ""
                out[n - 1] = f"{head}{REDACTED}{tail}"
    in_pem = False
    for n, raw in enumerate(lines):   # a private key's body, in any language
        if PEM_START.search(raw):
            in_pem = True
        elif in_pem and _BASE64_LINE.match(raw):
            out[n] = raw[:len(raw) - len(raw.lstrip())] + REDACTED
        else:
            in_pem = False
    if language in ("javascript", "typescript", "dart"):
        keyed = [n for n, raw in enumerate(lines) if _shape(raw) is not None]
        for n in keyed:   # follow the string a key is part of, down and up
            at = n
            while at + 1 < len(lines) and (_GLUE_AFTER.search(lines[at]) or _GLUE_BEFORE.match(lines[at + 1])) \
                    and _LITERAL.search(lines[at + 1]):
                at += 1
                out[at] = _wipe_strings(out[at])
            at = n
            while at > 0 and (_GLUE_AFTER.search(lines[at - 1]) or _GLUE_BEFORE.match(lines[at])) \
                    and _LITERAL.search(lines[at - 1]):
                at -= 1
                out[at] = _wipe_strings(out[at])
            out[n] = _wipe_strings(out[n])
    return [redact_code(line, redactor) for line in out]


def split_key_in(text: str, language: str | None, first: int, last: int) -> bool:
    """A key split over lines touches lines `first`..`last` (1-based): masking the file differs there from masking
    each line alone. Code built from those lines (a written change) would carry its pieces."""
    whole = masked_lines(text, language)
    raw = text.splitlines()
    return any(whole[n - 1] != redact_code(raw[n - 1]) for n in range(max(1, first), min(len(raw), last) + 1))


# Spots (D44): where a key goes in the code, for "Add to code". A line that already reads the key, a key-like name
# given a placeholder, or a key written in the open. Names and places only: never a value.

@dataclass(frozen=True)
class SpotHit:
    line: int
    kind: str                # "reads" | "placeholder" | "open" | "setting" (not a key: D45)
    name: str                # the env var the app reads: SUPABASE_ANON_KEY, API_KEY
    reader: str              # how the line reads it: env, vite, dart-define, dart-dotenv; "" for a literal
    start: int | None = None  # the literal's span on the line, quotes included (placeholder, open)
    end: int | None = None


_READS = {
    "python": [],   # read by the AST (_python_reads)
    "javascript": [(re.compile(r"""\bprocess\.env\.([A-Za-z_]\w*)"""
                               r"""|\bprocess\.env\[\s*['"]([A-Za-z_]\w*)['"]\s*\]"""), "env"),
                   (re.compile(r"""\bimport\.meta\.env\.([A-Za-z_]\w*)"""), "vite")],
    "dart": [(re.compile(r"""\bString\.fromEnvironment\(\s*['"]([A-Za-z_]\w*)['"]"""), "dart-define"),
             (re.compile(r"""\bdotenv\.(?:env\[|get\(|maybeGet\()\s*['"]([A-Za-z_]\w*)['"]"""), "dart-dotenv")],
}
_READS["typescript"] = _READS["javascript"]
# a value that asks for a key, rather than holding one or being ordinary text
_ASKS = re.compile(r"\b(?:enter|insert|paste|put|add)\b.*\b(?:key|token|secret|here)\b"
                   r"|^\s*(?:tbd|fixme|todo|none|null|n/?a|-+)\s*$", re.IGNORECASE)
# a name ending in one of these describes a key (apiKeyHint, TOKEN_URL); it doesn't hold one
_LABEL_ENDS = frozenset({"hint", "label", "title", "text", "placeholder", "message", "msg", "error", "field", "prompt",
                         "pattern", "regex", "name", "type", "length", "len", "url", "uri", "path", "header", "prefix",
                         "suffix", "id", "count", "min", "max", "format", "controller", "visible", "obscure", "icon",
                         "button", "file", "env", "var"})
_EMPTY_OK = frozenset({"key", "apikey", "token", "secret"})   # "" counts only for these: a form's password = "" doesn't


_BUILT = re.compile(r"\$\{|\$[A-Za-z_]")   # a string built from values: `${x}`, Dart's `$x`


def _asks_for_key(name: str, value: str) -> bool:
    parts = [p.lower() for p in _WORDS.findall(name)]
    if not is_secret_name(name) or (parts and parts[-1] in _LABEL_ENDS) or parts in (["key"], ["keys"]):
        return False   # a bare `key` is a widget's, a map's or a cache's far more often than an API's
    if _BUILT.search(value):
        return False
    if not value.strip():
        return bool(set(parts) & _EMPTY_OK)
    return is_placeholder(value) or bool(_ASKS.search(value))


def _python_literals(text: str) -> list[tuple[int, int, int, str, str]]:
    """(line, start, end, name, value) for each one-line string literal given to a name; columns in characters."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()
    out = []

    def target(t: ast.AST) -> str | None:
        return t.id if isinstance(t, ast.Name) else t.attr if isinstance(t, ast.Attribute) else None

    for node in ast.walk(tree):
        pairs: list[tuple[str | None, ast.AST]] = []
        if isinstance(node, ast.Assign):
            pairs = [(target(t), node.value) for t in node.targets]
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            pairs = [(target(node.target), node.value)]
        elif isinstance(node, ast.keyword) and node.arg:
            pairs = [(node.arg, node.value)]
        elif isinstance(node, ast.Dict):
            pairs = [(k.value, v) for k, v in zip(node.keys, node.values, strict=True)
                     if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        for name, value in pairs:
            if name and isinstance(value, ast.Constant) and isinstance(value.value, str) \
                    and value.lineno == value.end_lineno:
                raw = lines[value.lineno - 1].encode()   # AST columns count UTF-8 bytes
                start = len(raw[:value.col_offset].decode(errors="replace"))
                end = len(raw[:value.end_col_offset].decode(errors="replace"))
                out.append((value.lineno, start, end, name, value.value))
    return out


def _curly_literals(source: str, language: str) -> list[tuple[int, int, str, str]]:
    """(start, end, name, value) for each `name = "…"` / `name: '…'` on one line of JS, TS or Dart."""
    out = []
    for m in _GIVEN.finditer(source):
        if m.group(2) == "`" and "${" in m.group(3):
            continue
        start = m.start(2)
        if language == "dart" and start > 0 and source[start - 1] == "r":   # a raw string: r'…'
            start -= 1
        out.append((start, m.end(), m.group(1), m.group(3)))
    return out


def _python_reads(text: str) -> list[tuple[int, str, bool]]:
    """(line, name, has a default) for os.environ["X"], os.environ.get("X"[, d]), os.getenv("X"[, d]), getenv(…): from
    the AST, so a comment or a string that mentions one isn't a read (Codex review)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    def environ(node: ast.AST) -> bool:
        return isinstance(node, ast.Attribute) and node.attr == "environ" or isinstance(node, ast.Name) \
            and node.id == "environ"

    def name_of(node: ast.AST | None) -> str | None:
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    out = []
    for node in ast.walk(tree):
        name, default = None, False
        if isinstance(node, ast.Subscript) and environ(node.value):
            name = name_of(node.slice)
        elif isinstance(node, ast.Call) and node.args:
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "get" and environ(f.value) \
                    or isinstance(f, ast.Attribute) and f.attr == "getenv" \
                    or isinstance(f, ast.Name) and f.id == "getenv":
                name = name_of(node.args[0])
                default = len(node.args) > 1 or any(k.arg == "default" for k in node.keywords)
        if name and re.fullmatch(r"[A-Za-z_]\w*", name):
            out.append((node.lineno, name, default))
    return out


def _has_default(source: str, at: int, reader: str) -> bool:
    """A read that falls back to a value: Dart's `defaultValue:` / flutter_dotenv's `fallback:`, or `??` / `||` after
    the read in JS/TS and Dart. Such a setting isn't needed (D45)."""
    rest = source[at:]
    if reader in ("dart-define", "dart-dotenv"):
        call = rest.split(")", 1)[0]
        if "defaultValue" in call or "fallback" in call:
            return True
    return re.match(r"\s*\)?\s*\]?\s*(?:\?\?|\|\|)", rest) is not None


def spots_in(text: str, language: str | None) -> list[SpotHit]:
    """Every place in one file where a key goes (D44), in line order: lines that read a key-like env name, key-like
    names given a placeholder, and keys written whole in a string. Comments and string contents never count: Python
    by its AST, JS/TS/Dart by matching only where the code reader's blanked text still has code (Codex review)."""
    if language not in _READS:
        return []
    from flowforge.security.findings import env_name

    lines = text.splitlines()
    found: dict[tuple[int, str], SpotHit] = {}
    literals: list[tuple[int, int, int, str, str]]
    if language == "python":
        for n, name, default in _python_reads(text):
            if is_secret_name(name):
                found.setdefault((n, name), SpotHit(n, "reads", name, "env"))
            elif not default:   # a setting the app needs (D45); wire keeps those that go with a key
                found.setdefault((n, name), SpotHit(n, "setting", name, "env"))
        literals = _python_literals(text)
    else:
        from flowforge.flow.curly import mask

        code_lines = mask(text, language).splitlines()

        def is_code(n: int, at: int) -> bool:
            code = code_lines[n - 1] if n <= len(code_lines) else ""
            return at < len(code) and code[at] == lines[n - 1][at] and not code[at].isspace()

        literals = []
        for n, source in enumerate(lines, 1):
            for pattern, reader in _READS[language]:
                for m in pattern.finditer(source):
                    name = next(g for g in m.groups() if g)
                    if not is_code(n, m.start()):
                        continue
                    if is_secret_name(name):
                        found.setdefault((n, name), SpotHit(n, "reads", name, reader))
                    elif not _has_default(source, m.end(), reader):
                        found.setdefault((n, name), SpotHit(n, "setting", name, reader))
            for start, end, name, value in _curly_literals(source, language):
                quote = start + 1 if source[start] == "r" else start
                at_name = source.rfind(name, 0, start)
                if is_code(n, quote) and at_name >= 0 and is_code(n, at_name):
                    literals.append((n, start, end, name, value))
    open_lines = {hit.line for hit in find_keys(text, language)}
    for line, start, end, name, value in literals:
        env = env_name(name, "API_KEY")
        if line in open_lines and _only_key(value) and key_span(text, language, line) is not None:
            found.setdefault((line, env), SpotHit(line, "open", env, "", start, end))
        elif _asks_for_key(name, value):
            found.setdefault((line, env), SpotHit(line, "placeholder", env, "", start, end))
    return sorted(found.values(), key=lambda h: (h.line, h.name))


def literal_at(text: str, language: str | None, line: int, start: int, end: int) -> str | None:
    """The value of the string literal a spot points at (its exact span), for moving an open key (D44): the one that
    was clicked, even with two on a line (Codex review). Only for the move into the Vault, never for display."""
    if language == "python":
        found = [v for n, s, e, _, v in _python_literals(text) if (n, s, e) == (line, start, end)]
    else:
        lines = text.splitlines()
        source = lines[line - 1] if 0 < line <= len(lines) else ""
        found = [v for s, e, _, v in _curly_literals(source, language or "") if (s, e) == (start, end)]
    return found[0] if found else None
