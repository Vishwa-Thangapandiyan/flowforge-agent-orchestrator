import pytest


@pytest.fixture(autouse=True)
def isolated_flowforge_home(tmp_path_factory, monkeypatch):
    """No test reads or writes the real ~/.flowforge (connectors.json, artifacts)."""
    monkeypatch.setenv("FLOWFORGE_HOME", str(tmp_path_factory.mktemp("flowforge_home")))
