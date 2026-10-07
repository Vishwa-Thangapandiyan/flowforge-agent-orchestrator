"""The local command step (D13): no shell, folder restriction, explicit env, timeout, output cap."""

import asyncio
import json
import os
import sys

import pytest

from flowforge.connectors.models import parse_connector
from flowforge.nodes import NodeError, TransientNodeError
from flowforge.nodes.local_node import LocalNode
from flowforge.schema import Workflow
from flowforge.scheduler.executor import StepState, run_workflow

FAKE_SECRET = "sk_test_FAKEFAKE12345678"


def node(tmp_path, **conn):
    return LocalNode.from_connector(parse_connector({
        "id": "py", "type": "local", "name": "Python",
        "connection": {"command": [sys.executable], "cwd": str(tmp_path), **conn}}))


def py(code, *extra):
    return {"args": ["-c", code, *extra]}


async def test_runs_and_captures_output(tmp_path):
    out = await node(tmp_path).run(py("import sys; print('hi'); print('warn', file=sys.stderr)"))
    assert out["kind"] == "text" and out["exit_code"] == 0
    assert out["stdout"].strip() == "hi" and out["stderr"].strip() == "warn"


async def test_shell_metacharacters_are_plain_arguments(tmp_path):
    hostile = "x; echo pwned && del /q * | rm -rf / $(whoami) `id` > out.txt"
    out = await node(tmp_path).run(py("import sys, json; print(json.dumps(sys.argv[1:]))", hostile))
    assert json.loads(out["stdout"]) == [hostile]
    assert not (tmp_path / "out.txt").exists()


async def test_args_must_be_strings(tmp_path):
    with pytest.raises(NodeError, match="args"):
        await node(tmp_path).run({"args": ["-c", 1]})


async def test_stdin_is_passed(tmp_path):
    out = await node(tmp_path).run({**py("import sys; print(sys.stdin.read().upper())"), "stdin": "abc"})
    assert out["stdout"].strip() == "ABC"


# --- folder restriction ------------------------------------------------------------------------

async def test_runs_in_cwd_and_allowed_subdir(tmp_path):
    (tmp_path / "sub").mkdir()
    out = await node(tmp_path).run(py("import os; print(os.getcwd())"))
    assert os.path.samefile(out["stdout"].strip(), tmp_path)
    out = await node(tmp_path).run({**py("import os; print(os.getcwd())"), "subdir": "sub"})
    assert os.path.samefile(out["stdout"].strip(), tmp_path / "sub")


@pytest.mark.parametrize("subdir", ["..", "../..", "sub/../../x", "/", "C:\\"])
async def test_subdir_cannot_escape(tmp_path, subdir):
    (tmp_path / "sub").mkdir()
    with pytest.raises(NodeError, match="outside"):
        await node(tmp_path).run({**py("print(1)"), "subdir": subdir})


async def test_symlink_cannot_escape(tmp_path):
    outside = tmp_path / "outside"
    root = tmp_path / "root"
    outside.mkdir()
    root.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need extra privileges on this system")
    with pytest.raises(NodeError, match="outside"):
        await node(root).run({**py("print(1)"), "subdir": "link"})


async def test_missing_cwd_is_permanent(tmp_path):
    with pytest.raises(NodeError, match="does not exist") as exc:
        await node(tmp_path / "nope").run(py("print(1)"))
    assert not isinstance(exc.value, TransientNodeError)


# --- environment -------------------------------------------------------------------------------

async def test_only_the_explicit_environment_is_visible(tmp_path, monkeypatch):
    monkeypatch.setenv("PARENT_SECRET", FAKE_SECRET)
    monkeypatch.setenv("SCRIPT_TOKEN", "tok-FAKE")
    n = node(tmp_path, env={"MODE": "test"}, env_refs={"API_TOKEN": "env:SCRIPT_TOKEN"})
    out = await n.run(py("import os, json; print(json.dumps(dict(os.environ)))"))
    env = json.loads(out["stdout"])
    assert env["MODE"] == "test" and env["API_TOKEN"] == "tok-FAKE"
    assert "PARENT_SECRET" not in env and FAKE_SECRET not in out["stdout"]
    allowed = {"MODE", "API_TOKEN", "PATH", "SYSTEMROOT", "TEMP", "TMP"}
    # Windows may add a few process-start variables itself; nothing from our environment leaks
    leaked = {k for k in env if k.upper() not in allowed} & {k for k in os.environ if k.upper() not in allowed}
    assert not leaked


async def test_missing_secret_ref_is_permanent(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRIPT_TOKEN", raising=False)
    with pytest.raises(NodeError, match="SCRIPT_TOKEN is not set"):
        await node(tmp_path, env_refs={"API_TOKEN": "env:SCRIPT_TOKEN"}).run(py("print(1)"))


# --- program checks ----------------------------------------------------------------------------

@pytest.mark.parametrize("script", ["run.bat", "run.cmd", "RUN.CMD"])
async def test_batch_files_are_refused(tmp_path, script):
    (tmp_path / script).write_text("echo hi")
    n = LocalNode.from_connector(parse_connector({
        "id": "b", "type": "local", "name": "Batch",
        "connection": {"command": [str(tmp_path / script)], "cwd": str(tmp_path)}}))
    with pytest.raises(NodeError, match="cmd.exe"):
        await n.run({})


async def test_unknown_program_is_permanent(tmp_path):
    n = LocalNode.from_connector(parse_connector({
        "id": "x", "type": "local", "name": "X",
        "connection": {"command": ["flowforge-no-such-program"], "cwd": str(tmp_path)}}))
    with pytest.raises(NodeError, match="not found"):
        await n.run({})


# --- exit codes and output cap -----------------------------------------------------------------

async def test_nonzero_exit_is_permanent_with_stderr_tail(tmp_path):
    with pytest.raises(NodeError, match="exit code 3.*boom") as exc:
        await node(tmp_path).run(py("import sys; print('boom', file=sys.stderr); sys.exit(3)"))
    assert not isinstance(exc.value, TransientNodeError)


async def test_ok_exit_codes(tmp_path):
    out = await node(tmp_path).run({**py("import sys; sys.exit(1)"), "ok_exit_codes": [0, 1]})
    assert out["exit_code"] == 1


async def test_output_is_capped(tmp_path):
    out = await node(tmp_path, max_output_bytes=1000).run(py("print('x' * 50000)"))
    assert out["stdout"].startswith("x" * 1000) and "truncated" in out["stdout"]
    assert len(out["stdout"]) < 1100


# --- timeout kills the process ------------------------------------------------------------------

async def test_timeout_kills_the_process(tmp_path):
    marker = tmp_path / "survived.txt"
    code = f"import time, pathlib; time.sleep(2); pathlib.Path({str(marker)!r}).write_text('alive')"
    wf = Workflow.model_validate({"id": "t", "steps": [
        {"id": "slow", "type": "local", "connector": "py", "timeout_s": 0.5, "retries": 0, "params": py(code)}]})
    result = await run_workflow(wf, {"py": node(tmp_path)})
    assert result.steps["slow"].state == StepState.FAILED
    await asyncio.sleep(3)
    assert not marker.exists()


def test_not_cached_across_runs_and_namespaced(tmp_path):
    n = node(tmp_path)
    assert not n.cacheable_across_runs({"args": []})
    assert (n.connector_id, n.cache_namespace, n.rate_limit_key) == ("py", "local:py", "py")
