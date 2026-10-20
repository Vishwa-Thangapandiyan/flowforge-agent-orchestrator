"""Facts from JS/TS and Dart files by patterns, line by line (D21). Less exact than Python's AST, and said so.

A URL counts only when a quote opens right before it (so URLs inside longer strings and bare comment links don't),
and it is confirmed by a call or key on the same line: fetch(, .get(, Uri.parse(, urlTemplate:, baseURL: …
"""

from __future__ import annotations

import re

from flowforge.scan import services
from flowforge.scan.facts import FileFacts, LLMClient, Ref, UrlHit
from flowforge.scan.urls import clean_url

_JS_IMPORT = re.compile(r"""^\s*import\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)"""
                        r"""|import\(\s*['"]([^'"]+)['"]\s*\)""")
_DART_IMPORT = re.compile(r"""^\s*import\s+['"]package:([A-Za-z0-9_]+)/""")
_URL = re.compile(r"""['"`](https?://[^'"`\s]+)""")
_DART_URI = re.compile(r"""Uri\.https?\(\s*['"]([^'"]+)['"]\s*(?:,\s*['"]([^'"]*)['"])?""")
_CONFIRMS = re.compile(r"fetch\(|axios|\.(get|post|put|patch|delete|request)\(|Uri\.(parse|https?)\(|urlTemplate|"
                       r"base_?url|baseURL|endpoint|\burl\s*[:=]|http\.|dio\.", re.IGNORECASE)
_BASE_URL = re.compile(r"base_?url|baseURL", re.IGNORECASE)
_MODEL = re.compile(r"""\bmodel\s*[:=]\s*['"]([^'"]+)['"]""")
_ENV = re.compile(r"""process\.env\.([A-Za-z_][A-Za-z0-9_]*)|process\.env\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""
                  r"""|import\.meta\.env\.([A-Za-z_][A-Za-z0-9_]*)"""
                  r"""|String\.fromEnvironment\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""
                  r"""|Platform\.environment\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""
                  r"""|dotenv\.(?:env\[|get\()\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]""")
_COMMAND = re.compile(r"""\b(?:spawn|spawnSync|execFile|execFileSync|exec|execSync)\(\s*['"]([^'"\s]+)"""
                      r"""|Process\.(?:run|start|runSync)\(\s*['"]([^'"\s]+)['"]""")
_STRING = re.compile(r"""['"]([^'"\n]{1,120})['"]""")


def _package(spec: str) -> str | None:
    """npm package name from an import path; None for relative or built-in imports."""
    if spec.startswith((".", "/", "node:")):
        return None
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") else parts[0]


def extract(path: str, text: str, language: str) -> FileFacts:
    facts = FileFacts(path=path, language=language)
    dart = language == "dart"
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith(("//", "/*", "*")):
            continue
        if dart:
            if m := _DART_IMPORT.match(line):
                facts.imports.append((m.group(1), n))
        else:
            for m in _JS_IMPORT.finditer(line):
                pkg = _package(next(g for g in m.groups() if g))
                if pkg:
                    facts.imports.append((pkg, n))
        confirmed = bool(_CONFIRMS.search(line))
        for m in _URL.finditer(line):
            if url := clean_url(m.group(1)):
                facts.urls.append(UrlHit(line=n, url=url, confirmed=confirmed))
                if _BASE_URL.search(line):
                    facts.clients.append(LLMClient(line=n, sdk="", base_url=Ref(literal=url)))
        for m in _DART_URI.finditer(line):
            if url := clean_url(f"https://{m.group(1)}{m.group(2) or ''}"):
                facts.urls.append(UrlHit(line=n, url=url, confirmed=True))
        if m := _MODEL.search(line):
            facts.models.append((Ref(literal=m.group(1)), n))
        for m in _ENV.finditer(line):
            facts.env.append((next(g for g in m.groups() if g), n))
        for m in _COMMAND.finditer(line):
            facts.commands.append(([next(g for g in m.groups() if g)], n))
        facts.strings.update(_STRING.findall(line))
    # a base URL line is an LLM client only in a file that imports an LLM SDK; it belongs to that SDK
    llm_sdk = next((pkg for pkg, _ in facts.imports if (s := services.by_sdk(pkg)) and s["kind"] == "llm"), None)
    facts.clients = [LLMClient(line=c.line, sdk=llm_sdk, base_url=c.base_url) for c in facts.clients] if llm_sdk else []
    return facts
