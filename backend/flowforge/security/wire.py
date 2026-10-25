""""Add to code" (D44): the key box puts the key into the app with one click.

`key_spots` lists where each key goes (`finders.spots_in` over the repo's code) and the file the app reads it from:
`.flowforge/dart-defines.json` for Dart's build-time `String.fromEnvironment`, `.env` for apps that load it, and
`.env.local` for Vite. `add_to_code` checks everything first, then writes that file, rewrites a placeholder or an open
key so the code reads the key, adds `--dart-define-from-file` to the Flutter Run configs, keeps the file git-ignored,
tells Claude Code not to read it, and saves the key in the Vault. Directly in the working files: nothing is committed.
The value never goes into a code file, an answer or a log.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flowforge.scan.files import language, list_files
from flowforge.security.finders import SpotHit, key_span, spots_in
from flowforge.security.keystore import NAME, KeyStore, _write_private

DEFINES = ".flowforge/dart-defines.json"
DEFINE_ARG = f"--dart-define-from-file={DEFINES}"
NO_FILE = ("This app can't take keys from a file: it doesn't load .env. The key is saved in the Vault, and your "
           "agent's run_app passes it to the app.")
_CODE = ("python", "dart", "javascript", "typescript")
_PY_LOADS_ENV = re.compile(r"\bload_dotenv\s*\(|\bdotenv_values\s*\(|\bfind_dotenv\s*\(|env_file\s*=\s*['\"]\.env")
_JS_LOADS_ENV = re.compile(r"""\brequire\(\s*['"]dotenv['"]\s*\)|['"]dotenv/config['"]|\bdotenv\.config\(""")
_PLAIN_VALUE = re.compile(r"[A-Za-z0-9_\-.+/=:@]+")


class CantAdd(Exception):
    """Why the key can't be added now, in one sentence for the Keys page."""


@dataclass(frozen=True)
class Spot:
    name: str
    kind: str            # reads | placeholder | open
    path: str
    line: int
    lang: str
    reader: str
    sink: str | None     # dart-defines | .env | .env.local; None: the app reads no file
    why_not: str | None
    check: str           # the line as the page saw it (a hash): a changed line is refused

    @property
    def ref(self) -> str:
        return f"{self.path}:{self.line}"

    def public(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "ref": self.ref, "sink": self.sink, "why_not": self.why_not,
                "check": self.check, "where": _WHERE.get(self.sink or "", None)}


_WHERE = {"dart-defines": "your Run config", ".env": ".env", ".env.local": ".env.local"}


def _check(line: str) -> str:
    return hashlib.sha256(line.encode()).hexdigest()[:16]


def _read(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


@dataclass
class _Facts:
    """What the repo uses to load keys."""
    python_env: bool
    node_env: bool
    vite: bool


def _facts(root: Path, texts: dict[str, str]) -> _Facts:
    package = _read(root / "package.json")
    try:
        pkg = json.loads(package) if package else {}
    except ValueError:
        pkg = {}
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})} if isinstance(pkg, dict) else {}
    scripts = " ".join(map(str, (pkg.get("scripts") or {}).values())) if isinstance(pkg, dict) else ""
    return _Facts(
        python_env=any(_PY_LOADS_ENV.search(t) for p, t in texts.items() if language(p) == "python"),
        # loaded, not just listed (Codex review): a call in the code, a start script, or Next.js, which loads .env
        node_env="next" in deps or "--env-file" in scripts or "dotenv/config" in scripts
        or any(_JS_LOADS_ENV.search(t) for p, t in texts.items() if language(p) in ("javascript", "typescript")),
        vite="vite" in deps or any((root / f"vite.config.{e}").exists() for e in ("js", "ts", "mjs", "mts")),
    )


def _place(hit: SpotHit, lang: str, text: str, facts: _Facts) -> tuple[str, str | None, str | None]:
    """(the name the app reads, the file the key goes to, why there is none)."""
    if lang == "dart":
        return hit.name, ".env" if hit.reader == "dart-dotenv" else "dart-defines", None
    if lang == "python":
        return (hit.name, ".env", None) if facts.python_env else (hit.name, None, NO_FILE)
    from flowforge.security.fixes import _runs_on_node

    if hit.reader == "vite":   # the code's own name: its envPrefix may not be VITE_ (Codex review)
        return hit.name, ".env.local", None
    if hit.kind != "reads" and facts.vite and not _runs_on_node(text, lang):
        return (hit.name if hit.name.startswith("VITE_") else f"VITE_{hit.name}"), ".env.local", None
    return (hit.name, ".env", None) if facts.node_env else (hit.name, None, NO_FILE)


def _code_texts(root: Path) -> dict[str, str]:
    return {rel: _read(root / rel) for rel in list_files(root).files if language(rel) in _CODE}


def key_spots(root: Path) -> list[Spot]:
    """Every spot in the repo's code where a key goes, with the file the app would read it from (D44)."""
    root = root.resolve()
    texts = _code_texts(root)
    facts = _facts(root, texts)
    out = []
    for rel, text in sorted(texts.items()):
        lang = language(rel) or ""
        lines = text.splitlines()
        for hit in spots_in(text, lang):
            name, sink, why = _place(hit, lang, text, facts)
            out.append(Spot(name, hit.kind, rel, hit.line, lang, hit.reader, sink, why, _check(lines[hit.line - 1])))
    return out


# the writes, prepared in memory first

def _gitignored(root: Path, rel: str) -> bool | None:
    """True or False in a git repo; None outside one (or without git)."""
    try:
        done = subprocess.run(["git", "check-ignore", "-q", rel], cwd=root, capture_output=True)
    except OSError:
        return None
    return {0: True, 1: False}.get(done.returncode)


def _tracked(root: Path, rel: str) -> bool:
    try:
        done = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=root, capture_output=True)
    except OSError:
        return False
    return done.returncode == 0


def _dotenv_line(name: str, value: str) -> str:
    if _PLAIN_VALUE.fullmatch(value):
        return f"{name}={value}"
    return f'{name}="' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _merge_dotenv(old: str, name: str, value: str) -> str:
    line = _dotenv_line(name, value)
    newline = "\r\n" if "\r\n" in old else "\n"
    pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(name)}\s*=")
    rows = old.splitlines()
    if any(pattern.match(r) for r in rows):
        rows = [line if pattern.match(r) else r for r in rows]
    else:
        rows.append(line)
    return newline.join(rows) + newline


def _rewrite(text: str, spot: Spot, hit: SpotHit) -> str:
    """The code with the placeholder or key on the spot's line swapped for the read of `spot.name`."""
    lines = text.splitlines(keepends=True)
    source = lines[spot.line - 1]
    assert hit.start is not None and hit.end is not None
    if spot.lang == "dart":
        const = re.search(r"\bconst\b", source[:hit.start]) is not None
        read = ("" if const else "const ") + f"String.fromEnvironment('{spot.name}')"
    elif spot.lang == "python":
        read = f'os.environ["{spot.name}"]'
    elif spot.sink == ".env.local":
        read = f"import.meta.env.{spot.name}"
    else:
        read = f"process.env.{spot.name}"
    lines[spot.line - 1] = source[:hit.start] + read + source[hit.end:]
    if spot.lang == "python":
        from flowforge.security.fixes import _import_at, _imports_os, _newline

        tree = ast.parse(text)
        if not _imports_os(tree):
            lines.insert(_import_at(tree, lines), "import os" + _newline(text))
    return "".join(lines)


_NEW_RUN_CONFIG = """<component name="ProjectRunConfigurationManager">
  <configuration default="false" name="main.dart (keys from FlowForge)" type="FlutterRunConfigurationType" \
factoryName="Flutter">
    <option name="additionalArgs" value="{arg}" />
    <option name="filePath" value="$PROJECT_DIR$/lib/main.dart" />
    <method />
  </configuration>
</component>
"""


def _has_run_config(root: Path) -> bool:
    """A Flutter Run config already passes the defines file."""
    files = [*(root / ".idea" / "runConfigurations").glob("*.xml"), root / ".vscode" / "launch.json"]
    return any(DEFINE_ARG in _read(f) for f in files if f.is_file())


def _flutter_configs(root: Path) -> dict[Path, str]:
    """Flutter Run configs that gain `--dart-define-from-file` (IntelliJ / Android Studio, VS Code): path → new text.
    An IntelliJ project with none of its own gets one for lib/main.dart (Codex review: else Run wouldn't pass it)."""
    out: dict[Path, str] = {}
    configs = root / ".idea" / "runConfigurations"
    has_flutter = any("FlutterRunConfigurationType" in _read(f) for f in configs.glob("*.xml"))
    if (root / ".idea").is_dir() and not has_flutter and (root / "lib" / "main.dart").is_file():
        out[configs / "main_dart_flowforge.xml"] = _NEW_RUN_CONFIG.format(arg=DEFINE_ARG)
    for path in sorted((root / ".idea" / "runConfigurations").glob("*.xml")):
        try:
            tree = ET.parse(path)
        except ET.ParseError:
            continue
        changed = False
        for conf in tree.getroot().iter("configuration"):
            if conf.get("type") != "FlutterRunConfigurationType":
                continue
            opt = next((o for o in conf.iter("option") if o.get("name") == "additionalArgs"), None)
            if opt is None:
                opt = ET.Element("option", {"name": "additionalArgs", "value": ""})
                conf.insert(0, opt)
            if DEFINE_ARG not in (opt.get("value") or ""):
                opt.set("value", f"{opt.get('value') or ''} {DEFINE_ARG}".strip())
                changed = True
        if changed:
            ET.indent(tree)
            out[path] = ET.tostring(tree.getroot(), encoding="unicode") + "\n"
    launch = root / ".vscode" / "launch.json"
    if launch.is_file():
        try:
            data = json.loads(_read(launch))
        except ValueError:   # comments: left as it is (the Keys page says so)
            data = None
        if isinstance(data, dict):
            changed = False
            for conf in data.get("configurations") or []:
                if isinstance(conf, dict) and conf.get("type") == "dart":
                    args = conf.setdefault("toolArgs", [])
                    if DEFINE_ARG not in args:
                        args.append(DEFINE_ARG)
                        changed = True
            if changed:
                out[launch] = json.dumps(data, indent=2) + "\n"
    return out


def _ignore_entry(sink: str) -> str:
    return ".flowforge/" if sink == "dart-defines" else sink


def _deny(root: Path, sink: str) -> tuple[Path, str] | None:
    """`.claude/settings.local.json` with a rule that keeps Claude Code from reading the key's file."""
    path = root / ".claude" / "settings.local.json"
    rule = "Read(./.flowforge/**)" if sink == "dart-defines" else f"Read(./{sink})"
    try:
        data = json.loads(_read(path)) if path.is_file() else {}
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    deny = data.setdefault("permissions", {}).setdefault("deny", [])
    if rule in deny:
        return None
    deny.append(rule)
    return path, json.dumps(data, indent=2) + "\n"


def add_to_code(root: Path, name: str, ref: str, check: str, value: str | None) -> dict[str, Any]:
    """Put one key into the app (D44). `value` is what the user typed; None for a key written in the open, whose value
    is taken from the code. Raises CantAdd, having written nothing."""
    root = root.resolve()
    path, _, line_s = ref.rpartition(":")
    target = (root / path).resolve()
    if not path or not line_s.isdigit() or not target.is_relative_to(root) or language(path) not in _CODE:
        raise CantAdd("That spot isn't in this folder's code. Re-scan.")
    texts = _code_texts(root)
    text = texts.get(path, _read(target))
    lines = text.splitlines()
    line = int(line_s)
    if not 0 < line <= len(lines) or _check(lines[line - 1]) != check:
        raise CantAdd(f"{ref} changed since this page showed it. Re-scan, then try again.")
    lang = language(path) or ""
    facts = _facts(root, texts)
    spot, hit = None, None
    for h in spots_in(text, lang):
        if h.line != line:
            continue
        n, sink, why = _place(h, lang, text, facts)
        if n == name:
            spot, hit = Spot(n, h.kind, path, line, lang, h.reader, sink, why, check), h
    if spot is None or hit is None:
        raise CantAdd(f"{name} isn't at {ref} any more. Re-scan.")
    if spot.kind == "open":
        found = key_span(text, lang, line)
        if found is None:
            raise CantAdd(f"The key at {ref} isn't a whole string FlowForge can move. Send it to your agent.")
        value = found[2]
    value = (value or "").strip()
    if not value or "\x00" in value:
        raise CantAdd("Paste the key first.")
    if not NAME.fullmatch(spot.name):
        raise CantAdd(f"{spot.name} isn't a name an app can read.")
    if spot.sink is None:
        raise CantAdd(spot.why_not or NO_FILE)
    sink_rel = DEFINES if spot.sink == "dart-defines" else spot.sink
    if _tracked(root, sink_rel):
        raise CantAdd(f"git tracks {sink_rel}, so the key would be committed. Remove it from git first "
                      f"(git rm --cached {sink_rel}).")

    writes: dict[Path, tuple[str, bool]] = {}   # path → (new text, private 0600)
    changed: list[str] = []
    sink_path = root / sink_rel
    if spot.sink == "dart-defines":
        try:
            defines = json.loads(_read(sink_path)) if sink_path.is_file() else {}
        except ValueError:
            raise CantAdd(f"{DEFINES} isn't valid JSON: fix or delete it, then try again.") from None
        writes[sink_path] = (json.dumps({**(defines if isinstance(defines, dict) else {}), spot.name: value},
                                        indent=2) + "\n", True)
        for conf, new in _flutter_configs(root).items():
            writes[conf] = (new, False)
            changed.append(f"Run config ({conf.name})")
    else:
        writes[sink_path] = (_merge_dotenv(_read(sink_path), spot.name, value), True)
    changed.insert(0, sink_rel)
    if spot.kind in ("placeholder", "open"):
        writes[target] = (_rewrite(text, spot, hit), False)
        changed.insert(0, ref)
    entry = _ignore_entry(spot.sink)
    if _gitignored(root, sink_rel) is not True:
        ignore = root / ".gitignore"
        old = _read(ignore)
        if entry not in old.splitlines():
            writes[ignore] = (old + ("" if not old or old.endswith("\n") else "\n") + entry + "\n", False)
            changed.append(".gitignore")
    deny = _deny(root, spot.sink)
    if deny:
        writes[deny[0]] = (deny[1], False)
        changed.append("Claude Code told not to read it")
    for file, (new, private) in sorted(writes.items(), key=lambda w: w[0] != sink_path):   # the key's file first
        if private:
            _write_private(file, new.encode("utf-8"))
        else:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(new.encode("utf-8"))
    KeyStore(root).add(spot.name, value)
    changed.append("Vault")
    out: dict[str, Any] = {"name": spot.name, "ref": ref, "changed": changed}
    if spot.sink == "dart-defines":
        out["run_config"] = _has_run_config(root)   # Run passes the key; else the one command that does
        out["terminal"] = f"flutter run {DEFINE_ARG}"
    return out
