"""Example-data mode (D16): offline, separate database, genuine runs through the executor."""

import socket
import time

import pytest
from fastapi.testclient import TestClient

from flowforge import cli, main
from flowforge.example_data import CONNECTORS, SEED_RUNS, ExampleNode


def wait_for_seed(client, timeout_s=60):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        runs = client.get("/runs").json()
        if len(runs) >= len(SEED_RUNS) and all(r["status"] != "running" for r in runs):
            return runs
        time.sleep(0.1)
    raise AssertionError("example history was not seeded")


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture
def offline(monkeypatch):
    """Any connection that would leave this machine fails the test. (asyncio's own loopback
    socket pair on Windows is allowed.)"""
    real_connect, real_create = socket.socket.connect, socket.create_connection

    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in LOOPBACK:
            raise AssertionError(f"example mode tried to use the network: {address}")
        return real_connect(sock, address)

    def create_connection(address, *args, **kwargs):
        if address[0] not in LOOPBACK:
            raise AssertionError(f"example mode tried to use the network: {address}")
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", create_connection)


@pytest.fixture
def client(tmp_path, monkeypatch, offline):
    monkeypatch.setenv("FLOWFORGE_EXAMPLE", "1")
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "example.db"))
    for name in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "RAZORPAY_KEY"):
        monkeypatch.delenv(name, raising=False)
    with TestClient(main.app) as c:
        yield c


def test_meta_and_connectors(client):
    assert client.get("/meta").json()["example"] is True
    assert client.get("/meta").json()["project"] == "Baby-care shop"
    ids = {c["id"] for c in client.get("/connectors").json()}
    assert {c.id for c in CONNECTORS} | {"nim", "fetch"} <= ids
    assert client.get("/connectors/gemini").json()["secret"] == {"ref": "env:GEMINI_API_KEY", "status": "example"}
    assert all(isinstance(main.state.nodes[c.id], ExampleNode) for c in CONNECTORS)
    assert isinstance(main.state.nodes["llm"], ExampleNode) and isinstance(main.state.nodes["mcp"], ExampleNode)


def test_history_is_seeded_offline_with_real_runs(client):
    runs = wait_for_seed(client)
    assert sorted(r["plan"] for r in runs) == sorted(
        {"nightly_finance_check": "Nightly finance check", "payment_risk_check": "Payment risk check",
         "security_scan": "Security scan", "swap_razorpay_to_stripe": "Swap Razorpay to Stripe"}[name]
        for name, _ in SEED_RUNS)
    failed = [r for r in runs if r["status"] == "failed"]
    assert len(failed) == 1 and "could not start its MCP server" in failed[0]["failure_reason"]
    assert "3 steps after it were skipped" in failed[0]["failure_reason"]
    finance = [r for r in runs if r["plan"] == "Nightly finance check"]
    assert all(r["cache_hits"] >= 1 and r["tokens"] > 0 for r in finance)
    assert runs == sorted(runs, key=lambda r: r["started_at"], reverse=True)
    savings = client.get("/stats/savings").json()
    assert savings["runs"] == len(SEED_RUNS) and savings["time_saved_ms"] > 0 and savings["calls_skipped"] >= 2
    health = {h["id"]: h for h in client.get("/health/tools").json()}
    assert health["razorpay"]["status"] == "ok" and health["fetch"]["status"] == "failing"


def test_seeding_happens_once(tmp_path, monkeypatch, offline):
    monkeypatch.setenv("FLOWFORGE_EXAMPLE", "1")
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "once.db"))
    with TestClient(main.app) as first:
        wait_for_seed(first)
    with TestClient(main.app) as second:
        time.sleep(0.5)
        assert len(second.get("/runs").json()) == len(SEED_RUNS)


def test_demo_run_from_the_workflow_list(client):
    wait_for_seed(client)
    assert "nightly_finance_check" in client.get("/workflows").json()
    wf = client.get("/workflows/security_scan").json()
    run_id = client.post("/runs", json=wf).json()["run_id"]
    deadline = time.monotonic() + 30
    while client.get(f"/runs/{run_id}").json()["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.1)
    assert client.get(f"/runs/{run_id}").json()["status"] == "succeeded"


def test_example_mode_defaults_to_its_own_database(tmp_path, monkeypatch, offline):
    monkeypatch.setenv("FLOWFORGE_EXAMPLE", "1")
    monkeypatch.delenv("FLOWFORGE_DB", raising=False)
    with TestClient(main.app) as client:
        wait_for_seed(client)
    from flowforge.home import flowforge_home
    assert (flowforge_home() / "example.db").exists()


def test_cli_example_flag(monkeypatch):
    import os

    from flowforge.home import flowforge_home

    calls = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.update(app=app, **kw))
    saved = os.environ.copy()  # cli.main sets variables itself; put everything back afterwards
    try:
        os.environ.pop("FLOWFORGE_EXAMPLE", None)
        os.environ.pop("FLOWFORGE_DB", None)
        cli.main(["--example", "--no-open", "--port", "8123"])
        assert calls["app"] == "flowforge.main:app" and calls["port"] == 8123 and calls["host"] == "127.0.0.1"
        assert os.environ["FLOWFORGE_EXAMPLE"] == "1"
        assert os.environ["FLOWFORGE_DB"] == str(flowforge_home() / "example.db")
    finally:
        os.environ.clear()
        os.environ.update(saved)
