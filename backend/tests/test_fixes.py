"""Fixes you click (D37): the exact characters of a key, the change FlowForge makes for it (shown masked), and that
change made on a new branch in a temporary worktree, never on the branch you work on. Fake keys only (§6.6)."""

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from flowforge.scan import scan
from flowforge.security.finders import key_span
from flowforge.security.fixes import CantFix, apply_fix, fixable, preview
from flowforge.security.keystore import KeyStore

FAKE = "sk_test_FAKEFAKE12345678"
GOOGLE = "AIzaFAKEFAKEFAKEFAKEFAKE1234"


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return root


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def as_someone(monkeypatch):
    for k, v in {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.test", "GIT_COMMITTER_NAME": "Test",
                 "GIT_COMMITTER_EMAIL": "t@example.test", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}.items():
        monkeypatch.setenv(k, v)


def repo_with(tmp_path: Path, files: dict[str, str]) -> Path:
    root = write(tmp_path / "app", files)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "first")
    return root


def finding(root: Path, kind: str = "key_in_code"):
    return next(f for f in scan(root).findings if f.kind == kind)


# key_span: the literal that is the key, and nothing else

def test_key_span_finds_a_python_literal_that_is_the_key():
    line = f'STRIPE_KEY = "{FAKE}"  # test mode'
    start, end, value = key_span(line + "\n", "python", 1)
    assert line[start:end] == f'"{FAKE}"' and value == FAKE


def test_key_span_finds_a_js_literal_in_an_object():
    line = f"const cfg = {{ apiKey: '{GOOGLE}', region: 'eu' }};"
    start, end, value = key_span(line, "javascript", 1)
    assert line[start:end] == f"'{GOOGLE}'" and value == GOOGLE


@pytest.mark.parametrize("line", [
    f'headers = {{"Authorization": "Bearer {FAKE}"}}',   # more than the key: changing it would change the meaning
    f"# old key: {FAKE}",                               # a comment
    f'KEY = f"{FAKE}{{suffix}}"',                       # an f-string
])
def test_key_span_refuses_what_isnt_only_the_key(line):
    assert key_span(line, "python", 1) is None


# fixable: which issues get Fix, which go to the agent

def test_a_python_key_is_fixable_and_http_goes_to_the_agent(tmp_path, as_someone):
    root = repo_with(tmp_path, {"pay.py": f"""
        import httpx

        STRIPE_KEY = "{FAKE}"

        def pay():
            return httpx.post("http://api.stripe.com/v1/charges", headers={{"Authorization": STRIPE_KEY}})
    """})
    found = {f.kind: f for f in scan(root).findings}
    assert fixable(root, found["key_in_code"]) is True
    assert fixable(root, found["plain_http"]) is False


def test_a_dart_key_goes_to_the_agent(tmp_path, as_someone):
    root = repo_with(tmp_path, {"lib/keys.dart": f"const stripeKey = '{FAKE}';\n"})
    assert fixable(root, finding(root)) is False


# preview: the change, with the key masked

def test_the_preview_shows_the_change_with_the_key_masked_and_adds_import_os(tmp_path, as_someone):
    root = repo_with(tmp_path, {"config.py": f'''
        """Settings."""

        from __future__ import annotations

        import httpx

        GOOGLE_STATIC_MAPS_KEY = "{GOOGLE}"
    '''})
    got = preview(root, finding(root))
    text = json.dumps(got)
    assert GOOGLE not in text
    assert got["name"] == "GOOGLE_STATIC_MAPS_KEY" and got["file"] == "config.py"
    removed = [ln["text"] for ln in got["lines"] if ln["kind"] == "del"]
    added = [ln["text"] for ln in got["lines"] if ln["kind"] == "add"]
    assert removed == ['GOOGLE_STATIC_MAPS_KEY = "[REDACTED]"']
    assert added == ["import os", 'GOOGLE_STATIC_MAPS_KEY = os.environ["GOOGLE_STATIC_MAPS_KEY"]']
    assert got["branch"] == "flowforge/fix-google-static-maps-key"


def test_import_os_goes_after_the_future_import(tmp_path, as_someone):
    root = repo_with(tmp_path, {"config.py": f'from __future__ import annotations\n\nKEY = "{FAKE}"\n'})
    apply_fix(root, finding(root))
    text = git(root, "show", "flowforge/fix-key:config.py")
    assert text.splitlines()[:2] == ["from __future__ import annotations", "import os"]
    compile(text, "config.py", "exec")   # still valid Python


def test_an_existing_import_os_is_kept(tmp_path, as_someone):
    root = repo_with(tmp_path, {"config.py": f'import os\n\nKEY = "{FAKE}"\n'})
    got = preview(root, finding(root))
    assert [ln["text"] for ln in got["lines"] if ln["kind"] == "add"] == ['KEY = os.environ["KEY"]']


def test_a_js_key_becomes_process_env(tmp_path, as_someone):
    root = repo_with(tmp_path, {"src/pay.js": f"const stripe = require('stripe')('{FAKE}');\n"})
    got = preview(root, finding(root))
    assert [ln["text"] for ln in got["lines"] if ln["kind"] == "add"] == [
        "const stripe = require('stripe')(process.env.STRIPE_KEY);"]


# apply: a new branch, your branch untouched, the key saved and in no commit

def test_fix_makes_a_branch_saves_the_key_and_leaves_your_branch_alone(tmp_path, as_someone):
    root = repo_with(tmp_path, {"config.py": f'import os\n\nSTRIPE_SECRET_KEY = "{FAKE}"\n'})
    before = (root / "config.py").read_text()
    head = git(root, "rev-parse", "HEAD")
    done = apply_fix(root, finding(root))
    assert done["branch"] == "flowforge/fix-stripe-secret-key"
    assert (root / "config.py").read_text() == before                    # your files: untouched
    assert git(root, "rev-parse", "HEAD") == head                         # your branch: untouched
    assert git(root, "branch", "--show-current").strip() == "main"
    assert 'os.environ["STRIPE_SECRET_KEY"]' in git(root, "show", f"{done['branch']}:config.py")
    assert FAKE not in git(root, "show", f"{done['branch']}:config.py")   # the fixed file holds no key
    assert FAKE not in git(root, "log", "-1", "--format=%B", done["branch"])
    assert git(root, "worktree", "list").count("\n") == 1                 # the temporary worktree is gone
    assert KeyStore(root).env() == {"STRIPE_SECRET_KEY": FAKE}


def test_a_second_fix_of_the_same_name_gets_its_own_branch(tmp_path, as_someone):
    root = repo_with(tmp_path, {"config.py": f'import os\n\nKEY = "{FAKE}"\n'})
    assert apply_fix(root, finding(root))["branch"] == "flowforge/fix-key"
    assert apply_fix(root, finding(root))["branch"] == "flowforge/fix-key-2"


def test_fix_refuses_a_file_with_changes_you_havent_committed(tmp_path, as_someone):
    root = repo_with(tmp_path, {"config.py": f'KEY = "{FAKE}"\n'})
    (root / "config.py").write_text(f'KEY = "{FAKE}"\nMORE = 1\n')
    with pytest.raises(CantFix, match="uncommitted"):
        apply_fix(root, finding(root))
    assert KeyStore(root).names() == []


def test_fix_refuses_a_folder_that_isnt_a_git_repo(tmp_path):
    root = write(tmp_path / "plain", {"config.py": f'KEY = "{FAKE}"\n'})
    assert fixable(root, finding(root)) is True     # the change is clear
    with pytest.raises(CantFix, match="git"):
        apply_fix(root, finding(root))              # but FlowForge only changes code on a branch


def test_fix_refuses_when_the_code_moved_since_the_scan(tmp_path, as_someone):
    root = repo_with(tmp_path, {"config.py": f'KEY = "{FAKE}"\n'})
    old = finding(root)
    (root / "config.py").write_text(f'\n\nKEY = "{FAKE}"\n')
    git(root, "commit", "-qam", "moved")
    with pytest.raises(CantFix, match="Re-scan"):
        preview(root, old)


# .mcp.json: to the agent. The coding tool would read ${NAME} from its own environment, which FlowForge must not fill:
# that would hand the key to the agent (Codex review).

def test_a_key_in_an_mcp_config_goes_to_the_agent(tmp_path, as_someone):
    root = repo_with(tmp_path, {"main.py": "print('hi')\n", ".mcp.json": json.dumps({"mcpServers": {"search": {
        "command": "npx", "args": ["-y", "brave-search-mcp@1.0.0"], "env": {"BRAVE_API_KEY": FAKE}}}}, indent=2)})
    f = finding(root, "key_in_config")
    assert fixable(root, f) is False
    with pytest.raises(CantFix):
        apply_fix(root, f)
    assert KeyStore(root).names() == []
