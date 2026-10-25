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
from flowforge.security.finders import SpotHit, literal_at, spots_in
from flowforge.security.keystore import NAME, KeyStore, _write_private

DEFINES = ".flowforge/dart-defines.json"
DEFINE_ARG = f"--dart-define-from-file={DEFINES}"
UNKNOWN = "?"
CANT_TELL = ("This app loads a key file FlowForge can't tell from the code, so nothing is written there. Save keeps "
             "the key in the Vault, and your agent's run_app passes it.")
NO_FILE = ("This app can't take keys from a file: it doesn't load .env. Save keeps the key in the Vault, and your "
           "agent's run_app passes it.")
_CODE = ("python", "dart", "javascript", "typescript")
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
    sink: str | None     # dart-defines, or the env file: .env, .env.local, flutter_dotenv's; None: the app reads none
    why_not: str | None
    check: str           # the line as the page saw it (a hash): a changed line is refused

    @property
    def ref(self) -> str:
        return f"{self.path}:{self.line}"

    def public(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "ref": self.ref, "sink": self.sink, "why_not": self.why_not,
                "check": self.check, "where": _WHERE.get(self.sink or "", self.sink)}


_WHERE = {"dart-defines": "your Run config"}   # any other sink is the file's own name


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
    python_env: str | None   # the dotenv file Python loads; UNKNOWN when FlowForge can't tell; None: none
    node_env: str | None
    vite: bool
    dart_dotenv: str | None = None   # the file flutter_dotenv loads, when the code loads one listed in the assets
    dart_dotenv_why: str | None = None


_DOTENV_LOAD = re.compile(r"\bdotenv\s*\.\s*load\s*\(")
_FILE_NAME = re.compile(r"""\bfileName\s*:\s*(['"])([^'"\n]+)\1""")


def _dart_dotenv(root: Path, texts: dict[str, str]) -> tuple[str | None, str | None]:
    """(the file flutter_dotenv loads, why there is none): a real `dotenv.load(…)` call in the code (default `.env`,
    or its `fileName:`), and that file listed in pubspec.yaml's assets, where flutter_dotenv reads it from (Codex
    review)."""
    from flowforge.flow.curly import mask

    loaded = None
    for rel, text in texts.items():
        if language(rel) != "dart":
            continue
        code = mask(text, "dart")
        for m in _DOTENV_LOAD.finditer(code):
            args = text[m.end():m.end() + 200].split(")", 1)[0]
            named = _FILE_NAME.search(args)
            loaded = named.group(2) if named else ".env"
            break
        if loaded:
            break
    if loaded is None:
        return None, "This app reads dotenv.env but never calls dotenv.load(), so no key file is read."
    assets = re.findall(r"^\s*-\s*['\"]?([^'\"\n#]+?)['\"]?\s*$", _read(root / "pubspec.yaml"), re.MULTILINE)
    if loaded.strip("/") not in {a.strip().strip("/") for a in assets}:
        return None, f"{loaded} isn't in pubspec.yaml's assets, so flutter_dotenv can't load it. Add it there first."
    return loaded, None


def _relative(path: str) -> str:
    """A loader's path, as a path inside the repo, or UNKNOWN (absolute, or climbing out)."""
    clean = path.strip().removeprefix("./")
    return UNKNOWN if not clean or clean.startswith("/") or ".." in Path(clean).parts or ":" in clean else clean


def _py_env_file(text: str) -> str | None:
    """The dotenv file the code loads: load_dotenv() / dotenv_values() (default `.env`, or their path), a settings
    class's env_file. Only a real call counts, not a comment or docstring; a path built at run time is UNKNOWN
    (Codex review)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None

    def name_of(f: ast.AST) -> str:
        return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""

    def path_of(arg: ast.AST | None) -> str:
        if arg is None:
            return ".env"
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return _relative(arg.value)
        if isinstance(arg, ast.Call) and name_of(arg.func) == "find_dotenv":   # searches upward for the name
            return path_of(arg.args[0]) if arg.args else ".env"
        return UNKNOWN

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if name_of(node.func) in ("load_dotenv", "dotenv_values"):
                given = node.args[0] if node.args else next(
                    (k.value for k in node.keywords if k.arg == "dotenv_path"), None)
                found.add(path_of(given))
            for k in node.keywords:
                if k.arg == "env_file":
                    found.add(path_of(k.value))
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "env_file" for t in node.targets):
            found.add(path_of(node.value))
    return _one(found)


def _one(found: set[str]) -> str | None:
    """The one file every loader names; UNKNOWN when they disagree or one can't be told; None with no loader."""
    if not found:
        return None
    return found.pop() if len(found) == 1 else UNKNOWN


_JS_SOURCE = re.compile(r"""\brequire\s*\(\s*(?=['"])|\bimport\s+(?=['"])|\bfrom\s+(?=['"])""")
_QUOTED_AT = re.compile(r"""(['"])([^'"\n]*)\1""")


_CONFIG_CALL = re.compile(r"\bdotenv\s*\.\s*config\s*\(|\)\s*\.\s*config\s*\(|(?<![\w.])config\s*\(")
_PATH_OPTION = re.compile(r"""\bpath\s*:\s*(['"])([^'"\n]+)\1""")


def _js_env_file(text: str, lang: str) -> str | None:
    """The dotenv file the code loads: `import 'dotenv/config'` (`.env`), or `dotenv.config()` / `config()` imported
    from 'dotenv', with its `path:` when given. Read from the code with comments and strings blanked, so a word in
    either doesn't count; a path that isn't a plain string is UNKNOWN (Codex review)."""
    from flowforge.flow.curly import mask

    code = mask(text, lang)   # same length; comments and string contents blanked, quotes kept
    modules = []
    for m in _JS_SOURCE.finditer(code):
        quoted = _QUOTED_AT.match(text, m.end())
        if quoted:
            modules.append(quoted.group(2))
    found: set[str] = set()
    if "dotenv/config" in modules:
        found.add(".env")
    if "dotenv" in modules:
        for m in _CONFIG_CALL.finditer(code):
            args = text[m.end():m.end() + 300].split(")", 1)[0]
            named = _PATH_OPTION.search(args)
            found.add(_relative(named.group(2)) if named else UNKNOWN if re.search(r"\bpath\b", args) else ".env")
    return _one(found)


_ENV_FILE_FLAG = re.compile(r"--env-file[= ](\S+)")


def _node_env_file(deps: dict[str, Any], scripts: str, texts: dict[str, str]) -> str | None:
    found = {_relative(m.group(1).strip("'\"")) for m in _ENV_FILE_FLAG.finditer(scripts)}
    if "dotenv/config" in scripts or "next" in deps:
        found.add(".env")
    found |= {f for p, t in texts.items() if language(p) in ("javascript", "typescript")
              and (f := _js_env_file(t, language(p) or ""))}
    return _one(found)


def _facts(root: Path, texts: dict[str, str]) -> _Facts:
    package = _read(root / "package.json")
    try:
        pkg = json.loads(package) if package else {}
    except ValueError:
        pkg = {}
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})} if isinstance(pkg, dict) else {}
    scripts = " ".join(map(str, (pkg.get("scripts") or {}).values())) if isinstance(pkg, dict) else ""
    return _Facts(
        python_env=_one({f for p, t in texts.items() if language(p) == "python" and (f := _py_env_file(t))}),
        # loaded, not just listed (Codex review): a call in the code, a start script, or Next.js, which loads .env
        node_env=_node_env_file(deps, scripts, texts),
        vite="vite" in deps or any((root / f"vite.config.{e}").exists() for e in ("js", "ts", "mjs", "mts")),
        **dict(zip(("dart_dotenv", "dart_dotenv_why"), _dart_dotenv(root, texts), strict=True)),
    )


def _loaded(name: str, env_file: str | None) -> tuple[str, str | None, str | None]:
    if env_file is None:
        return name, None, NO_FILE
    if env_file == UNKNOWN:
        return name, None, CANT_TELL
    return name, env_file, None


def _place(hit: SpotHit, lang: str, text: str, facts: _Facts) -> tuple[str, str | None, str | None]:
    """(the name the app reads, the file the key goes to, why there is none)."""
    if lang == "dart":
        if hit.reader == "dart-dotenv":
            return hit.name, facts.dart_dotenv, facts.dart_dotenv_why
        return hit.name, "dart-defines", None
    if lang == "python":
        return _loaded(hit.name, facts.python_env)
    from flowforge.security.fixes import _runs_on_node

    if hit.reader == "vite":   # the code's own name: its envPrefix may not be VITE_ (Codex review)
        return hit.name, ".env.local", None
    if hit.kind != "reads" and facts.vite and not _runs_on_node(text, lang):
        return (hit.name if hit.name.startswith("VITE_") else f"VITE_{hit.name}"), ".env.local", None
    return _loaded(hit.name, facts.node_env)


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
    services = {_service(s.name) for s in out if s.kind != "setting"} - {""}
    return [s for s in out if s.kind != "setting" or _service(s.name) in services]   # a key's settings only (D45)


_PREFIXES = ("VITE_", "NEXT_PUBLIC_", "EXPO_PUBLIC_", "REACT_APP_", "PUBLIC_")
_NOT_A_SERVICE = {"api", "app", "my", "the", "default", "base", "public", "env", "secret", "key", "token", "auth"}


def _service(name: str) -> str:
    """The service a name is for: its first word after a framework prefix (SUPABASE_URL → supabase)."""
    for prefix in _PREFIXES:
        name = name.removeprefix(prefix)
    first = name.split("_", 1)[0].lower()
    return "" if first in _NOT_A_SERVICE else first


_URL_NAME = re.compile(r"_(?:URL|URI|ENDPOINT|HOST_URL)$")


def setting_problem(name: str, value: str) -> str | None:
    """Why a value can't go into a setting (D45), or None. A setting is never a key: it would sit outside the Vault
    and the app would get its key in the wrong place. A URL setting takes an http(s) address. Found on Vishwa's app,
    where the anon key went into the SUPABASE_URL box."""
    from flowforge.security.finders import KEY_SHAPES, looks_secret

    v = value.strip()
    if any(p.search(v) for _, p in KEY_SHAPES) or looks_secret(v):
        return f"This looks like a key, not {name}. Paste the key in its own box above; {name} is an address."
    if _URL_NAME.search(name) and _bare_url(v) is None:
        return f"{name} takes an address that starts with https://."
    return None


def suggest(name: str, saved: dict[str, str]) -> str | None:
    """A setting's likely value, from what is saved: Supabase's old JWT anon key names its project, so its URL is
    https://<project>.supabase.co (D45). Only the URL leaves this function, never the key."""
    if _service(name) != "supabase" or not name.endswith("_URL"):
        return None
    import base64

    for key_name, value in saved.items():
        if _service(key_name) != "supabase" or value.count(".") != 2:
            continue
        try:
            claims = json.loads(base64.urlsafe_b64decode(value.split(".")[1] + "=="))
        except ValueError:
            continue
        ref = claims.get("ref") if isinstance(claims, dict) else None
        if isinstance(ref, str) and re.fullmatch(r"[a-z0-9]{6,40}", ref):
            return f"https://{ref}.supabase.co"
    return None


def app_settings(root: Path) -> dict[str, str]:
    """The URL settings the app is given (`dart-defines.json`, `.env`, `.env.local`), for a health check's address
    (D45). A key-like name is never read here."""
    from dotenv import dotenv_values

    from flowforge.security.finders import is_secret_name

    found: dict[str, str] = {}
    try:
        defines = json.loads(_read(root / DEFINES) or "{}")
    except ValueError:
        defines = {}
    if isinstance(defines, dict):
        found.update({k: v for k, v in defines.items() if isinstance(v, str)})
    for env in (".env", ".env.local"):
        if (root / env).is_file():
            found.update({k: v for k, v in dotenv_values(root / env).items() if v})
    return {k: clean for k, v in found.items() if not is_secret_name(k) and (clean := _bare_url(v))}


def _bare_url(value: str) -> str | None:
    """scheme://host[:port]/path of an http(s) URL: no user, password, query or fragment, which a check never sends
    (D24; Codex review)."""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:   # a port that isn't a number
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname or re.search(r"\s", value.strip()):
        return None   # the whole URL, not just how it starts (Codex review)
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"{parts.scheme}://{host}{f':{port}' if port else ''}{parts.path}"


# the writes, prepared in memory first

def _ignored_by_project(root: Path, rel: str) -> bool:
    """A `.gitignore` inside the project hides `rel`, so every clone hides it. A rule only in this machine's global
    ignore or `.git/info/exclude` doesn't count (Codex review, P1)."""
    try:
        done = subprocess.run(["git", "check-ignore", "-v", "--no-index", rel], cwd=root, capture_output=True,
                              text=True)
    except OSError:
        return False
    if done.returncode != 0:
        return False
    source = done.stdout.split(":", 1)[0]
    if not source or source.startswith(".git/"):
        return False
    where = (root / source).resolve()
    return where.name == ".gitignore" and where.is_relative_to(root)


def _tracked(root: Path, rel: str) -> bool:
    try:
        done = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=root, capture_output=True)
    except OSError:
        return False
    return done.returncode == 0


def _dotenv_line(name: str, value: str) -> str:
    """One `.env` line every loader reads back exactly. A `$` is refused: python-dotenv expands `${X}` whatever the
    quotes, with no escape, so the app would get a different key (Codex review)."""
    if "$" in value or "\n" in value:
        raise CantAdd("This key has a $ or a line break, which .env loaders change. It's saved in the Vault only; "
                      "your agent's run_app passes it as it is.")
    if _PLAIN_VALUE.fullmatch(value):
        return f"{name}={value}"
    if "'" not in value:
        return f"{name}='{value}'"
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


def _check_destination(root: Path, path: Path) -> None:
    """A write stays inside the folder and never goes through a link: a project can't send the key elsewhere."""
    rel = path.relative_to(root)
    at = root
    for part in rel.parts:
        at = at / part
        if at.is_symlink():
            raise CantAdd(f"{at.relative_to(root).as_posix()} is a link, so FlowForge won't write the key through it.")
    if not path.parent.resolve().is_relative_to(root):
        raise CantAdd(f"{rel.as_posix()} is outside this folder.")


def _save(root: Path, name: str, value: str) -> None:
    try:
        KeyStore(root).add(name, value)
    except Exception as e:   # a locked keychain, a wrong master key: nothing else is touched
        raise CantAdd(f"The Vault couldn't save the key ({type(e).__name__}), so nothing was changed.") from None


def _hide_only(root: Path, spot: Spot, hit: SpotHit, text: str, target: Path, value: str) -> dict[str, Any]:
    """A key written in the code of an app that loads no key file: the line reads it, the value goes to the Vault
    (Codex review: getting it out of the code comes first)."""
    _check_destination(root, target)
    _save(root, spot.name, value)   # the Vault first: if it fails, the key stays in the code
    mode = target.stat().st_mode & 0o777
    _write_private(target, _rewrite(text, spot, hit).encode("utf-8"), mode)
    return {"name": spot.name, "ref": spot.ref, "changed": [spot.ref, "Vault"],
            "note": "This app loads no key file, so your agent's run_app passes the key when it starts the app."}


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
    if spot.kind == "open":   # the clicked literal itself, even with two keys on the line (Codex review)
        found = literal_at(text, lang, line, hit.start or 0, hit.end or 0)
        if found is None:
            raise CantAdd(f"The key at {ref} isn't a whole string FlowForge can move. Send it to your agent.")
        value = found
    value = (value or "").strip()
    if not value or "\x00" in value:
        raise CantAdd("Paste the key first.")
    if not NAME.fullmatch(spot.name):
        raise CantAdd(f"{spot.name} isn't a name an app can read.")
    if spot.kind == "setting" and (problem := setting_problem(spot.name, value)):
        raise CantAdd(problem)
    if spot.sink is None:
        if spot.kind != "open":
            raise CantAdd(spot.why_not or NO_FILE)
        return _hide_only(root, spot, hit, text, target, value)   # out of the code first, even with no file to fill
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
        try:
            writes[sink_path] = (_merge_dotenv(_read(sink_path), spot.name, value), True)
        except CantAdd:   # a value .env would change: kept in the Vault, as the message says (Codex review)
            if spot.kind != "setting":
                _save(root, spot.name, value)
            raise
    changed.insert(0, sink_rel)
    if spot.kind in ("placeholder", "open"):
        writes[target] = (_rewrite(text, spot, hit), False)
        changed.insert(0, ref)
    entry = _ignore_entry(spot.sink)
    if not _ignored_by_project(root, sink_rel):
        ignore = root / ".gitignore"
        old = _read(ignore)
        if entry not in old.splitlines():
            writes[ignore] = (old + ("" if not old or old.endswith("\n") else "\n") + entry + "\n", False)
            changed.append(".gitignore")
    deny = _deny(root, spot.sink)
    if deny:
        writes[deny[0]] = (deny[1], False)
        changed.append("Claude Code told not to read it")
    for file in writes:
        _check_destination(root, file)   # every write checked before the first (Codex review, P1)
    secret = spot.kind != "setting"   # decided by the spot, never the caller (D45)
    if secret:
        _save(root, spot.name, value)   # the Vault before any file: an open key is never lost (Codex review)
    for file, (new, private) in sorted(writes.items(), key=lambda w: w[0] != sink_path):   # the key's file first
        mode = 0o600 if private else (file.stat().st_mode & 0o777 if file.exists() else 0o644)
        _write_private(file, new.encode("utf-8"), mode)
    if secret:
        changed.append("Vault")
    out: dict[str, Any] = {"name": spot.name, "ref": ref, "changed": changed}
    if spot.sink == "dart-defines":
        out["run_config"] = _has_run_config(root)   # Run passes the key; else the one command that does
        out["terminal"] = f"flutter run {DEFINE_ARG}"
    return out
