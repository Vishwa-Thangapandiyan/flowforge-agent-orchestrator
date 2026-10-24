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

from flowforge.security.logfilter import KEY_PATTERNS

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
    if language not in ("javascript", "typescript"):
        return None
    for m in _LITERAL.finditer(source):
        before = source[:m.start()]
        if "//" in before or "/*" in before or (m.group(1) == "`" and "${" in m.group(2)):
            continue
        if _only_key(m.group(2)):
            return m.start(), m.end(), m.group(2)
    return None
