"""Keys the coding agent never sees (D36): one store per repo, the OS keychain or an encrypted file, names kept apart
from values, and `.env` read for names only. Fake keys only (CLAUDE.md §6.6); no test touches the real keychain."""

import json
import os
import stat
import sys

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import KeyringError, PasswordDeleteError

from flowforge.security import keystore
from flowforge.security.keystore import BadKey, KeyStore, env_file_names

FAKE = "sk_test_FAKEFAKE12345678"
OTHER = "rzp_test_FAKE1234567"


class MemoryKeyring(KeyringBackend):
    priority = 10

    def __init__(self):
        super().__init__()
        self.items: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        if self.items.pop((service, username), None) is None:
            raise PasswordDeleteError(username)


class BrokenKeyring(MemoryKeyring):
    def set_password(self, service, username, password):
        raise KeyringError("locked")


@pytest.fixture
def memory(monkeypatch):
    backend = MemoryKeyring()
    previous = keyring.get_keyring()
    keyring.set_keyring(backend)
    monkeypatch.setenv("FLOWFORGE_KEYSTORE", "keychain")
    yield backend
    keyring.set_keyring(previous)


def every_byte_under(folder):
    return b"".join(p.read_bytes() for p in folder.rglob("*") if p.is_file())


def test_a_saved_key_comes_back_only_through_env(tmp_path):
    store = KeyStore(tmp_path)
    assert store.add("STRIPE_SECRET_KEY", FAKE) == "file"
    assert store.names() == ["STRIPE_SECRET_KEY"]
    assert store.env() == {"STRIPE_SECRET_KEY": FAKE}
    assert KeyStore(tmp_path).env() == {"STRIPE_SECRET_KEY": FAKE}   # kept between runs


def test_the_file_store_is_encrypted_and_only_yours(tmp_path):
    KeyStore(tmp_path).add("STRIPE_SECRET_KEY", FAKE)
    home = keystore.flowforge_home()
    assert FAKE.encode() not in every_byte_under(home)
    names = json.loads((home / "keys.json").read_text())
    assert names[str(tmp_path.resolve())]["STRIPE_SECRET_KEY"]["store"] == "file"
    if sys.platform != "win32":
        for path in [home / "master.key", home / "keys.json", *(home / "keys").iterdir()]:
            assert stat.S_IMODE(path.stat().st_mode) == 0o600, path


def test_a_master_key_from_the_environment_is_used(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("FLOWFORGE_MASTER_KEY", Fernet.generate_key().decode())
    KeyStore(tmp_path).add("A_TOKEN", FAKE)
    assert not (keystore.flowforge_home() / "master.key").exists()
    assert KeyStore(tmp_path).env() == {"A_TOKEN": FAKE}


def test_keys_belong_to_one_repo(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    KeyStore(tmp_path / "a").add("STRIPE_SECRET_KEY", FAKE)
    KeyStore(tmp_path / "b").add("STRIPE_SECRET_KEY", OTHER)
    assert KeyStore(tmp_path / "a").env() == {"STRIPE_SECRET_KEY": FAKE}
    assert KeyStore(tmp_path / "b").env() == {"STRIPE_SECRET_KEY": OTHER}


def test_remove_forgets_name_and_value(tmp_path):
    store = KeyStore(tmp_path)
    store.add("A_KEY", FAKE)
    store.add("B_KEY", OTHER)
    assert store.remove("A_KEY") is True
    assert store.remove("A_KEY") is False
    assert store.names() == ["B_KEY"] and store.env() == {"B_KEY": OTHER}


def test_saving_again_replaces_the_value(tmp_path):
    store = KeyStore(tmp_path)
    store.add("A_KEY", FAKE)
    store.add("A_KEY", OTHER)
    assert store.env() == {"A_KEY": OTHER}


@pytest.mark.parametrize("name", ["", "1KEY", "A-KEY", "A KEY", "A=B", "KEY\n"])
def test_a_name_must_be_an_env_name(tmp_path, name):
    with pytest.raises(BadKey):
        KeyStore(tmp_path).add(name, FAKE)


@pytest.mark.parametrize("value", ["", "   ", "nul\x00"])
def test_an_empty_value_or_one_an_env_cant_hold_is_refused(tmp_path, value):
    with pytest.raises(BadKey):
        KeyStore(tmp_path).add("A_KEY", value)


def test_the_keychain_holds_the_value_and_the_index_only_the_name(tmp_path, memory):
    store = KeyStore(tmp_path)
    assert store.add("STRIPE_SECRET_KEY", FAKE) == "keychain"
    assert memory.items == {(f"flowforge:{tmp_path.resolve()}", "STRIPE_SECRET_KEY"): FAKE}
    assert FAKE.encode() not in every_byte_under(keystore.flowforge_home())
    assert store.env() == {"STRIPE_SECRET_KEY": FAKE}
    store.remove("STRIPE_SECRET_KEY")
    assert memory.items == {} and store.names() == []


def test_a_keychain_that_refuses_falls_back_to_the_file(tmp_path, monkeypatch):
    previous = keyring.get_keyring()
    keyring.set_keyring(BrokenKeyring())
    monkeypatch.setenv("FLOWFORGE_KEYSTORE", "auto")
    try:
        store = KeyStore(tmp_path)
        assert store.add("A_KEY", FAKE) == "file"
        assert store.env() == {"A_KEY": FAKE}
    finally:
        keyring.set_keyring(previous)


def test_no_keychain_means_the_file(tmp_path, monkeypatch):
    from keyring.backends import fail

    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    monkeypatch.setenv("FLOWFORGE_KEYSTORE", "auto")
    try:
        assert KeyStore(tmp_path).add("A_KEY", FAKE) == "file"
    finally:
        keyring.set_keyring(previous)


def test_env_file_names_never_returns_a_value(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"# a comment\nSTRIPE_SECRET_KEY={FAKE}\nexport OPENAI_API_KEY = '{OTHER}'\n\nnot a line\n"
                   "EMPTY=\n")
    names = env_file_names(env)
    assert names == ["STRIPE_SECRET_KEY", "OPENAI_API_KEY", "EMPTY"]
    assert FAKE not in repr(names) and OTHER not in repr(names)
    assert env_file_names(tmp_path / "missing.env") == []


def test_status_of_the_keys_the_code_reads(tmp_path):
    (tmp_path / ".env").write_text(f"OPENAI_API_KEY={FAKE}\n")
    store = KeyStore(tmp_path)
    store.add("STRIPE_SECRET_KEY", OTHER)
    got = store.status(["STRIPE_SECRET_KEY", "OPENAI_API_KEY", "SUPABASE_KEY"])
    assert got == {"STRIPE_SECRET_KEY": "saved", "OPENAI_API_KEY": "env_file", "SUPABASE_KEY": "missing"}


def test_import_moves_every_value_in_env_into_the_store(tmp_path):
    (tmp_path / ".env").write_text(f"STRIPE_SECRET_KEY={FAKE}\nexport A_TOKEN=\"{OTHER}\"\nOLLAMA_HOST=localhost\n"
                                   "EMPTY=\n")
    store = KeyStore(tmp_path)
    assert store.import_env(tmp_path / ".env") == ["STRIPE_SECRET_KEY", "A_TOKEN", "OLLAMA_HOST"]
    assert store.env() == {"STRIPE_SECRET_KEY": FAKE, "A_TOKEN": OTHER, "OLLAMA_HOST": "localhost"}
    assert (tmp_path / ".env").exists()   # deleting is the user's call


def test_the_store_never_reads_the_real_home(tmp_path):
    assert str(keystore.flowforge_home()) == os.environ["FLOWFORGE_HOME"]


def test_a_key_belongs_to_the_dependency_that_uses_it(tmp_path):
    from flowforge.scan.models import Dependency, EnvName, ScanEvidence, ScanResult
    from flowforge.security.keystore import report

    deps = [Dependency(id="api-stripe", kind="api", name="Stripe", catalog="stripe",
                       evidence=[ScanEvidence(ref="pay.py:9")]),
            Dependency(id="llm-openai", kind="llm", name="OpenAI", env_names=["OPENAI_API_KEY"],
                       evidence=[ScanEvidence(ref="ai.py:4")]),
            Dependency(id="api-weather", kind="api", name="api.weather.test", evidence=[ScanEvidence(ref="w.py:3")])]
    scan = ScanResult(root="shop", dependencies=deps, env_names=[
        EnvName(name="STRIPE_SECRET_KEY", ref="config.py:2"),    # by the service it names
        EnvName(name="OPENAI_API_KEY", ref="ai.py:4"),           # read on the dependency's own line
        EnvName(name="W_TOKEN", ref="w.py:1"),                   # the only dependency in its file
        EnvName(name="LONELY_SECRET", ref="nothing.py:1"),       # nothing to tie it to
        EnvName(name="OLLAMA_HOST", ref="ai.py:2")])             # not a key
    got = {k["name"]: k["deps"] for k in report(KeyStore(tmp_path), scan)}
    assert got == {"STRIPE_SECRET_KEY": ["api-stripe"], "OPENAI_API_KEY": ["llm-openai"],
                   "W_TOKEN": ["api-weather"], "LONELY_SECRET": []}


def test_a_saved_key_that_cant_be_read_back_says_so(tmp_path, memory):
    """Codex review: `saved` only when `flowforge run` could pass it on; a keychain entry gone or locked is not."""
    store = KeyStore(tmp_path)
    store.add("STRIPE_SECRET_KEY", FAKE)
    memory.items.clear()   # removed from the keychain behind FlowForge's back, or the keychain is locked
    assert store.env() == {}
    assert store.status(["STRIPE_SECRET_KEY"]) == {"STRIPE_SECRET_KEY": "unreadable"}
    assert store.status(["STRIPE_SECRET_KEY"], verify=False) == {"STRIPE_SECRET_KEY": "saved"}   # reads nothing


def test_a_damaged_key_file_makes_its_keys_unreadable_not_a_crash(tmp_path):
    store = KeyStore(tmp_path)
    store.add("A_KEY", FAKE)
    store._file_path().write_bytes(b"not a fernet token")
    assert store.env() == {}
    assert store.status(["A_KEY"]) == {"A_KEY": "unreadable"}


def test_an_unreadable_key_offers_to_save_it_again(tmp_path):
    from flowforge.scan.models import EnvName, ScanResult
    from flowforge.security.keystore import report

    store = KeyStore(tmp_path)
    store.add("A_KEY", FAKE)
    store._file_path().write_bytes(b"damaged")
    [got] = report(store, ScanResult(root="x", env_names=[EnvName(name="A_KEY", ref="a.py:1")]))
    assert got["status"] == "unreadable" and "key add A_KEY" in got["command"]
