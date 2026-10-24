import pytest


@pytest.fixture(autouse=True)
def isolated_flowforge_home(tmp_path_factory, monkeypatch):
    """No test reads or writes the real ~/.flowforge (connectors.json, artifacts)."""
    monkeypatch.setenv("FLOWFORGE_HOME", str(tmp_path_factory.mktemp("flowforge_home")))


@pytest.fixture(autouse=True)
def file_keystore(monkeypatch):
    """No test reads or writes the real OS keychain (D36): keys go to the encrypted file in FLOWFORGE_HOME."""
    monkeypatch.setenv("FLOWFORGE_KEYSTORE", "file")
    monkeypatch.delenv("FLOWFORGE_MASTER_KEY", raising=False)


@pytest.fixture(autouse=True)
def no_real_database(tmp_path_factory, monkeypatch):
    """No test opens the checkout's real flowforge.db: the default database is a fresh path. A test that names its own
    (FLOWFORGE_DB) or clears it to test the default still does so."""
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path_factory.mktemp("db") / "flowforge.db"))
