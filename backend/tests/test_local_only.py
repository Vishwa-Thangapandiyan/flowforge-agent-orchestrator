"""The whole API answers only to this machine (D47): a page reached through DNS rebinding (its own Host) and another
site's form (its own Origin) get 403, everywhere, not only on the key routes."""

import pytest
from fastapi.testclient import TestClient

from flowforge import main


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOWFORGE_EXAMPLE", "1")
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "example.db"))
    return lambda host="http://127.0.0.1:8000": TestClient(main.app, base_url=host)


@pytest.mark.parametrize("path", ["/meta", "/flow", "/keys", "/projects", "/"])
def test_a_page_reached_by_dns_rebinding_gets_nothing(api, path):
    with api() as c:
        r = c.get(path, headers={"host": "evil.test"})
    assert r.status_code == 403 and "this machine" in r.text


@pytest.mark.parametrize("method, path", [("post", "/scan"), ("post", "/checks"), ("delete", "/connectors/nim"),
                                          ("put", "/flow/positions"), ("post", "/projects")])
def test_another_sites_form_cant_change_anything(api, method, path):
    with api() as c:
        r = getattr(c, method)(path, headers={"origin": "https://evil.test"})
    assert r.status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:5173", "[::1]:8000", "localhost"])
def test_this_machine_and_the_dev_server_work(api, host):
    with api() as c:
        assert c.get("/meta", headers={"host": host}).status_code == 200
        assert c.get("/meta", headers={"host": host, "origin": "http://localhost:5173"}).status_code == 200


def test_a_change_from_this_machines_page_or_a_command_line_works(api):
    with api() as c:
        page = c.put("/flow/positions", json={"positions": {}}, headers={"origin": "http://127.0.0.1:8000"})
        cli = c.put("/flow/positions", json={"positions": {}})   # no Origin: curl, scripts
    assert page.status_code != 403 and cli.status_code != 403


@pytest.mark.parametrize("peer", ["192.168.1.50", "10.0.0.7", "2001:db8::1"])
def test_another_computer_is_refused_whatever_host_it_claims(tmp_path, monkeypatch, peer):
    """Codex review (P1): on a 0.0.0.0 bind, another machine could send `Host: localhost`. The connection's own
    address decides; a header can be forged."""
    monkeypatch.setenv("FLOWFORGE_EXAMPLE", "1")
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "example.db"))
    monkeypatch.setenv("FLOWFORGE_HOST", "0.0.0.0")
    with TestClient(main.app, base_url="http://localhost:8000", client=(peer, 40000)) as c:
        assert c.get("/meta").status_code == 403
        assert c.post("/scan", json={"path": "/tmp"}).status_code == 403


@pytest.mark.parametrize("peer", ["127.0.0.1", "127.0.1.1", "::1", "::ffff:127.0.0.1"])
def test_this_computer_is_let_in_by_its_loopback_address(tmp_path, monkeypatch, peer):
    monkeypatch.setenv("FLOWFORGE_EXAMPLE", "1")
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "example.db"))
    with TestClient(main.app, base_url="http://localhost:8000", client=(peer, 40000)) as c:
        assert c.get("/meta").status_code == 200


def test_a_null_origin_cant_change_anything(api):
    with api() as c:
        assert c.post("/scan", json={"path": "/tmp"}, headers={"origin": "null"}).status_code == 403
