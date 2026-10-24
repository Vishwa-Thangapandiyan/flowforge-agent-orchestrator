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
