"""The runner (D43): the app starts with its keys filled in, as you would start it by hand, and its output comes back
masked. Plain code: a list, never a shell. Fake keys only."""

import sys
import time

import pytest

from flowforge.apps import Runs
from flowforge.security.logfilter import Redactor
from flowforge.security.masks import MissingKeys

FAKE = "sk_test_FAKEFAKE12345678"
PLAIN = "plainvalue-FAKE-0000-1111"   # no known key shape: only the redactor's memory masks it


def until(check, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def runs():
    r = Runs()
    yield r
    r.stop_all()


def redactor_for(*values):
    red = Redactor()
    red.learn(values)
    return red.redact_text


def test_the_app_gets_its_keys_and_its_output_comes_back_masked(runs, tmp_path):
    code = "import os, sys; print('key', os.environ['STRIPE_SECRET_KEY']); print('arg', sys.argv[1])"
    run = runs.start("shop", [sys.executable, "-c", code, "ffkey://PLAIN_TOKEN"], tmp_path,
                     {"STRIPE_SECRET_KEY": FAKE, "PLAIN_TOKEN": PLAIN}, redactor_for(FAKE, PLAIN))
    assert until(lambda: runs.get(run.id).status == "exited")
    lines = [line for _, line in runs.get(run.id).output()]
    assert lines == ["key [REDACTED]", "arg [REDACTED]"]
    assert run.code == 0 and run.argv[-1] == "ffkey://PLAIN_TOKEN"   # shown as the agent wrote it
    assert run.keys == ["PLAIN_TOKEN", "STRIPE_SECRET_KEY"]


def test_a_missing_key_starts_nothing(runs, tmp_path):
    marker = tmp_path / "ran"
    with pytest.raises(MissingKeys):
        runs.start("shop", [sys.executable, "-c", f"open({str(marker)!r}, 'w')", "ffkey://NOT_SAVED"], tmp_path,
                   {}, redactor_for())
    time.sleep(0.3)
    assert not marker.exists() and runs.list("shop") == []


def test_no_shell_ever(runs, tmp_path):
    marker = tmp_path / "shell-ran"
    run = runs.start("shop", [sys.executable, "-c", "pass", f"; touch {marker}"], tmp_path, {}, redactor_for())
    assert until(lambda: runs.get(run.id).status == "exited")
    assert not marker.exists()


def test_stop_ends_a_long_running_app(runs, tmp_path):
    run = runs.start("shop", [sys.executable, "-c", "import time; print('up', flush=True); time.sleep(60)"],
                     tmp_path, {}, redactor_for())
    assert until(lambda: runs.get(run.id).output())
    assert runs.stop(run.id) is True
    assert until(lambda: runs.get(run.id).status == "stopped")


def test_output_since_a_point_and_runs_per_project(runs, tmp_path):
    run = runs.start("shop", [sys.executable, "-c", "print('a'); print('b'); print('c')"], tmp_path, {}, redactor_for())
    assert until(lambda: runs.get(run.id).status == "exited")
    first = runs.get(run.id).output()
    assert [line for _, line in runs.get(run.id).output(since=first[0][0])] == ["b", "c"]
    assert [r.id for r in runs.list("shop")] == [run.id] and runs.list("blog") == []


def test_a_program_that_doesnt_exist_fails_plainly(runs, tmp_path):
    run = runs.start("shop", ["no-such-program-ffx"], tmp_path, {}, redactor_for())
    assert run.status == "failed" and "not found" in run.output()[0][1]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups; Windows ends the tree with taskkill /T")
def test_stop_ends_the_apps_children_too(runs, tmp_path):
    """Codex review: `npm run dev` starts children; Stop must end them, not only the process FlowForge started."""
    import os

    pid_file = tmp_path / "child.pid"
    code = ("import subprocess, sys, time; "
            "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            f"open({str(pid_file)!r}, 'w').write(str(c.pid)); print('up', flush=True); time.sleep(60)")
    run = runs.start("shop", [sys.executable, "-c", code], tmp_path, {}, redactor_for())
    assert until(lambda: pid_file.exists() and pid_file.read_text())
    child = int(pid_file.read_text())
    assert runs.stop(run.id) is True

    def gone() -> bool:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            return True
        return False

    assert until(gone)
