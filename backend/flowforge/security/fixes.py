"""Fixes you click (D37): for a key written in the code, the change plain code can make with no LLM.

The value goes to the key store (D36) and the literal becomes an env lookup, which `flowforge run` fills in. A key in
`.mcp.json` goes to the agent instead: the coding tool would read `${NAME}` from its own environment, and handing it
the key would hand it to the agent (Codex review). `preview` shows that change with the key
masked; `apply_fix` makes it on a new branch, in a temporary `git worktree`, committed as you, so the branch you work
on and your files are never touched (§9.3). Everything else goes to your coding agent.
"""

from __future__ import annotations

import ast
import difflib
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flowforge.scan.files import language
from flowforge.scan.models import Finding
from flowforge.security.finders import find_keys, key_span
from flowforge.security.findings import env_name
from flowforge.security.keystore import KeyStore
from flowforge.security.logfilter import REDACTED, redact_code

_FIXABLE_CODE = ("python", "javascript", "typescript")
# JS/TS that shows it runs on Node, where `process.env` exists; anything that may run in a browser goes to the agent.
# Read from code only: comments and string contents are blanked first (Codex review).
_NODE_CODE = re.compile(r"\brequire\s*\(|\bprocess\.env\b")
_IMPORT_FROM = re.compile(r"""\bfrom\s+(?=['"])""")
_NODE_MODULE = re.compile(r"node:.*|fs|path|os|http|https|crypto|child_process|express|fastify|koa|@nestjs/[\w-]+")
_BROWSER = re.compile(r"\b(?:window|document|localStorage|navigator)\.|\bimport\.meta\.env\b")
_QUOTED = re.compile(r"""(['"])([^'"\n]*)\1""")


def _runs_on_node(text: str, lang: str) -> bool:
    """The file's code shows it runs on Node and nothing in it says browser (Codex review: a browser has no
    `process`, and a key bundled into a web page is public anyway)."""
    from flowforge.flow.curly import mask

    code = mask(text, lang)   # same length: comments and string contents blanked, quotes kept
    if _BROWSER.search(code):
        return False
    if _NODE_CODE.search(code):
        return True
    for m in _IMPORT_FROM.finditer(code):
        source = _QUOTED.match(text, m.end())
        if source and _NODE_MODULE.fullmatch(source.group(2)):
            return True
    return False


class CantFix(Exception):
    """Why this fix can't be made now, in one sentence for the Issues page."""


@dataclass
class _Change:
    path: str       # relative to the repo, as in the finding
    old: str
    new: str
    name: str       # the env var the value moves to
    value: str      # never shown, stored or logged: it goes to the key store only


def _where(f: Finding) -> tuple[str, int]:
    path, line = f.ref.rsplit(":", 1)
    return path, int(line)


def _read(root: Path, path: str) -> str:
    """The file as it is, line endings included (a fix must not rewrite every line on Windows)."""
    try:
        return (root / path).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise CantFix(f"{path} can't be read. Re-scan.") from None


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _imports_os(tree: ast.Module) -> bool:
    return any(isinstance(n, ast.Import) and any(a.name == "os" and a.asname is None for a in n.names)
               for n in tree.body)


def _import_at(tree: ast.Module) -> int:
    """The line index where `import os` goes: after the module docstring and any `from __future__` imports."""
    at = 0
    for i, node in enumerate(tree.body):
        doc = i == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
            and isinstance(node.value.value, str)
        if doc or (isinstance(node, ast.ImportFrom) and node.module == "__future__"):
            at = node.end_lineno or at
        else:
            break
    return at


def _code_change(root: Path, f: Finding) -> _Change:
    path, line = _where(f)
    lang = language(path)
    text = _read(root, path)
    span = key_span(text, lang, line)
    hit = next((h for h in find_keys(text, lang) if h.line == line), None)
    if span is None or hit is None:
        raise CantFix(f"The key is no longer on {path}:{line}. Re-scan.")
    start, end, value = span
    name = env_name(hit.name, "API_KEY" if hit.label == "secret" else hit.label)
    lookup = f'os.environ["{name}"]' if lang == "python" else f"process.env.{name}"
    lines = text.splitlines(keepends=True)
    lines[line - 1] = lines[line - 1][:start] + lookup + lines[line - 1][end:]
    if lang == "python":
        tree = ast.parse(text)
        if not _imports_os(tree):
            lines.insert(_import_at(tree), "import os" + _newline(text))
    return _Change(path, text, "".join(lines), name, value)


def _change(root: Path, f: Finding) -> _Change:
    if f.kind == "key_in_code":
        return _code_change(root, f)
    raise CantFix("FlowForge doesn't fix this kind itself: send it to your agent.")


def fixable(root: Path, f: Finding) -> bool:
    """Can plain code make this change safely? A key that is a whole string literal in Python, or in JS or TS that
    runs on Node."""
    if f.kind != "key_in_code":
        return False
    path, line = _where(f)
    lang = language(path)
    try:
        text = _read(root, path)
    except CantFix:
        return False
    if lang not in _FIXABLE_CODE or (lang != "python" and not _runs_on_node(text, lang)):
        return False
    return key_span(text, lang, line) is not None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "key"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def _branch_for(root: Path, name: str) -> str:
    base = f"flowforge/fix-{_slug(name)}"
    branch, n = base, 2
    while _git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0:
        branch, n = f"{base}-{n}", n + 1
    return branch


def _not_ready(root: Path, path: str) -> str | None:
    """Why FlowForge can't make a branch for this file now, or None."""
    if shutil.which("git") is None or _git(root, "rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
        return "This folder isn't a git repo: FlowForge only changes code on a new git branch. Send it to your agent."
    if _git(root, "rev-parse", "--verify", "--quiet", "HEAD").returncode != 0:
        return "This repo has no commits yet: commit once, then fix."
    if _git(root, "status", "--porcelain", "--", path).stdout.strip():
        return f"{path} has uncommitted changes: commit or stash them first, so the fix starts from your code."
    return None


def _last_line(done: subprocess.CompletedProcess[str], value: str) -> str:
    """git's last line of output, masked (a hook may print what it read)."""
    last = (done.stderr or done.stdout).strip().splitlines()[-1:] or ["unknown error"]
    return redact_code(last[0].replace(value, REDACTED))


def _lines(change: _Change) -> list[dict[str, Any]]:
    """The change as diff lines (one line of context), every line masked and the key's value replaced."""
    def mask(s: str) -> str:
        return redact_code(s.replace(change.value, REDACTED))

    out: list[dict[str, Any]] = []
    old, new = change.old.splitlines(), change.new.splitlines()
    for group in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_grouped_opcodes(1):
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                out += [{"kind": "ctx", "n": j + 1, "text": mask(new[j])} for j in range(j1, j2)]
                continue
            out += [{"kind": "del", "n": i + 1, "text": mask(old[i])} for i in range(i1, i2)]
            out += [{"kind": "add", "n": j + 1, "text": mask(new[j])} for j in range(j1, j2)]
    return out


def preview(root: Path, f: Finding) -> dict[str, Any]:
    """What Fix will change, masked: the diff, the env name, the branch, and whether it can be made now."""
    change = _change(root, f)
    why = _not_ready(root, change.path)
    return {"id": f.id, "file": change.path, "name": change.name, "lines": _lines(change),
            "branch": _branch_for(root, change.name) if why is None or "uncommitted" in why else None,
            "can_apply": why is None, "why_not": why}


def apply_fix(root: Path, f: Finding) -> dict[str, Any]:
    """Save the key, then make the change on a new branch in a temporary worktree and commit it as you. Your branch,
    your files and your index are left as they were. Raises CantFix with the reason."""
    change = _change(root, f)
    why = _not_ready(root, change.path)
    if why:
        raise CantFix(why)
    top = Path(_git(root, "rev-parse", "--show-toplevel").stdout.strip())
    rel = (root.resolve() / change.path).relative_to(top.resolve()).as_posix()
    KeyStore(root).add(change.name, change.value)
    branch = _branch_for(root, change.name)
    temp = Path(tempfile.mkdtemp(prefix="flowforge-fix-"))
    tree = temp / "tree"
    made = _git(root, "worktree", "add", "-q", "-b", branch, str(tree), "HEAD")
    if made.returncode != 0:
        shutil.rmtree(temp, ignore_errors=True)
        raise CantFix("git couldn't make the branch: " + _last_line(made, change.value))
    try:
        (tree / rel).write_bytes(change.new.encode("utf-8"))
        message = (f"Read {change.name} from the environment instead of the code\n\n"
                   f"Made by FlowForge (D37). The key is saved in FlowForge; replace it with the provider, because "
                   f"older commits still hold it.")
        added = _git(tree, "add", "--", rel)
        committed = _git(tree, "commit", "-q", "-m", message) if added.returncode == 0 else added
        if committed.returncode != 0:
            raise CantFix("git couldn't commit the fix: " + _last_line(committed, change.value))
        sha = _git(tree, "rev-parse", "HEAD").stdout.strip()
    except CantFix:
        _git(root, "worktree", "remove", "--force", str(tree))
        _git(root, "branch", "-D", branch)   # no half-made branch left behind
        raise
    finally:
        _git(root, "worktree", "remove", "--force", str(tree))
        _git(root, "worktree", "prune")
        shutil.rmtree(temp, ignore_errors=True)
    return {"id": f.id, "branch": branch, "commit": sha, "file": change.path, "name": change.name}
