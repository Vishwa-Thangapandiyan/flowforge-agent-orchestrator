"""The settings a key needs (D45): SUPABASE_URL goes with SUPABASE_ANON_KEY. Found on Vishwa's Flutter app, which
stayed on fake data with its key in place because the URL was never offered. A setting goes into the app like its key,
never into the Vault; a Supabase key suggests its URL; and a health check can use the app's URL setting."""

import base64
import json
import textwrap
from pathlib import Path

import pytest

from flowforge.security.finders import spots_in
from flowforge.security.keystore import KeyStore
from flowforge.security.wire import add_to_code, app_settings, key_spots, suggest

FAKE = "sk_test_FAKEFAKE12345678"
LOCAL = "http://127.0.0.1:8000"
HERE = ("127.0.0.1", 50000)


def fake_supabase_key(ref: str = "abcdefghijklmnopqrst") -> str:
    """A JWT-shaped fake: Supabase's old anon key names its project in `ref`. Signed by nothing."""
    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")   # noqa: E731
    return f"{part({'alg': 'HS256', 'typ': 'JWT'})}.{part({'ref': ref, 'role': 'anon'})}.FAKESIGNATUREFAKE"


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(textwrap.dedent(text), encoding="utf-8")
    return root


@pytest.fixture
def travel(tmp_path):
    """Vishwa's app's shape (lib/dev/app_config.dart)."""
    return write(tmp_path / "travel", {
        "pubspec.yaml": "name: travel\n",
        "lib/main.dart": "void main() {}\n",
        "lib/dev/app_config.dart": """\
            const supabaseUrl = String.fromEnvironment('SUPABASE_URL');
            const supabaseAnonKey = String.fromEnvironment('SUPABASE_ANON_KEY');
            const _forceFakeData = bool.fromEnvironment('USE_FAKE_DATA');
            const tilesUrl = String.fromEnvironment('TILES_URL');
            const region = String.fromEnvironment('SUPABASE_REGION', defaultValue: 'eu');
        """,
    })


def by_name(spots):
    return {s.name: s for s in spots}


def test_a_read_with_no_default_is_a_setting_and_one_with_a_default_isnt():
    dart = ("const u = String.fromEnvironment('SUPABASE_URL');\n"
            "const r = String.fromEnvironment('SUPABASE_REGION', defaultValue: 'eu');\n")
    assert {(s.name, s.kind) for s in spots_in(dart, "dart")} == {("SUPABASE_URL", "setting")}
    py = 'import os\nA = os.environ["DB_HOST"]\nB = os.getenv("DB_PORT", "5432")\nC = os.environ.get("DB_NAME")\n'
    assert {(s.name, s.kind) for s in spots_in(py, "python")} == {("DB_HOST", "setting"), ("DB_NAME", "setting")}
    js = "const a = process.env.API_URL;\nconst b = process.env.API_HOST ?? 'localhost';\nconst c = process.env.X || 1;\n"
    assert {(s.name, s.kind) for s in spots_in(js, "javascript")} == {("API_URL", "setting")}


def test_only_settings_that_go_with_a_key_are_offered(travel):
    spots = by_name(key_spots(travel))
    assert spots["SUPABASE_URL"].kind == "setting" and spots["SUPABASE_URL"].sink == "dart-defines"
    assert "TILES_URL" not in spots          # no TILES key: not a key's setting
    assert "SUPABASE_REGION" not in spots    # it has a default
    assert "USE_FAKE_DATA" not in spots      # a flag, not a String


def test_a_setting_goes_into_the_app_but_never_the_vault(travel):
    s = by_name(key_spots(travel))["SUPABASE_URL"]
    done = add_to_code(travel, s.name, s.ref, s.check, "https://abcdefghijklmnopqrst.supabase.co")
    defines = json.loads((travel / ".flowforge/dart-defines.json").read_text())
    assert defines == {"SUPABASE_URL": "https://abcdefghijklmnopqrst.supabase.co"}
    assert KeyStore(travel).names() == [] and "Vault" not in done["changed"]
    assert "--dart-define-from-file" in done["terminal"]


def test_a_setting_cant_be_sent_as_a_key_by_mistake(travel):
    """The route decides secret from the spot, not the caller: a key spot always goes to the Vault."""
    s = by_name(key_spots(travel))["SUPABASE_ANON_KEY"]
    add_to_code(travel, s.name, s.ref, s.check, FAKE)
    assert KeyStore(travel).names() == ["SUPABASE_ANON_KEY"]


def test_a_supabase_key_suggests_its_url():
    assert suggest("SUPABASE_URL", {"SUPABASE_ANON_KEY": fake_supabase_key("myproject12345")}) == \
        "https://myproject12345.supabase.co"
    assert suggest("SUPABASE_URL", {"SUPABASE_ANON_KEY": "sb_publishable_FAKEFAKE"}) is None   # new keys don't say
    assert suggest("TILES_URL", {"SUPABASE_ANON_KEY": fake_supabase_key()}) is None
    assert suggest("SUPABASE_URL", {"SUPABASE_ANON_KEY": fake_supabase_key("bad/ref")}) is None   # not a project id


def test_app_settings_are_url_settings_only_never_keys(travel):
    (travel / ".flowforge").mkdir()
    (travel / ".flowforge/dart-defines.json").write_text(json.dumps({
        "SUPABASE_URL": "https://p.supabase.co", "SUPABASE_ANON_KEY": fake_supabase_key(), "MODE": "dev"}))
    assert app_settings(travel) == {"SUPABASE_URL": "https://p.supabase.co"}


# through the API and the checks

@pytest.fixture
def served(travel, tmp_path, monkeypatch):
    monkeypatch.delenv("FLOWFORGE_EXAMPLE", raising=False)
    monkeypatch.setenv("FLOWFORGE_DB", str(tmp_path / "flowforge.db"))
    monkeypatch.setenv("FLOWFORGE_REPO", str(travel))
    from fastapi.testclient import TestClient

    from flowforge import main

    return lambda: TestClient(main.app, base_url=LOCAL, client=HERE)


def test_the_keys_page_lists_the_setting_with_its_suggestion(served, travel):
    KeyStore(travel).add("SUPABASE_ANON_KEY", fake_supabase_key("myproject12345"))
    with served() as c:
        got = c.get("/keys").json()
        names = [k["name"] for k in got["keys"]]
        setting = {s["name"]: s for s in got["settings"]}["SUPABASE_URL"]
        assert "SUPABASE_URL" not in names   # a setting isn't a key
        assert setting["suggestion"] == "https://myproject12345.supabase.co" and setting["in_app"] is False
        r = c.post("/keys/SUPABASE_URL/add-to-code", json={"ref": setting["ref"], "check": setting["check"],
                                                           "value": setting["suggestion"]})
        assert r.status_code == 200, r.text and "Vault" not in r.json()["changed"]
        after = {s["name"]: s for s in c.get("/keys").json()["settings"]}["SUPABASE_URL"]
        assert after["in_app"] is True
    assert KeyStore(travel).names() == ["SUPABASE_ANON_KEY"]


def test_a_dependency_with_no_address_in_code_is_checked_at_the_apps_url(travel):
    from flowforge.api.checks import target_for
    from flowforge.scan.models import Dependency, ScanResult

    dep = Dependency(id="api-supabase", kind="api", name="Supabase", catalog="supabase")
    got = target_for(dep, ScanResult(root="travel"), settings={"SUPABASE_URL": "https://p.supabase.co",
                                                                "TILES_URL": "https://tiles.test"})
    assert got.target == "https://p.supabase.co"
    assert target_for(dep, ScanResult(root="travel")).target is None


def test_an_app_url_loses_credentials_and_query_before_a_check(travel):
    """Codex review (P1): D24 sends no key and no query; a setting's userinfo or ?apikey= never reaches a check."""
    (travel / ".flowforge").mkdir()
    (travel / ".flowforge/dart-defines.json").write_text(json.dumps({
        "SUPABASE_URL": "https://user:FAKEPASS1234@p.supabase.co:8443/rest/v1?apikey=sk_test_FAKEFAKE12345678#x"}))
    assert app_settings(travel) == {"SUPABASE_URL": "https://p.supabase.co:8443/rest/v1"}


def test_a_key_pasted_into_a_setting_box_is_refused(travel):
    """Found on Vishwa's app: the anon key went into the SUPABASE_URL box, so it sat outside the Vault and the app
    started with the key as its URL. A setting never takes a key, and a URL setting takes a URL."""
    from flowforge.security.wire import CantAdd

    s = by_name(key_spots(travel))["SUPABASE_URL"]
    for wrong, why in ((fake_supabase_key(), "looks like a key"), (FAKE, "looks like a key"),
                       ("not a url", "https://")):
        with pytest.raises(CantAdd, match=why):
            add_to_code(travel, s.name, s.ref, s.check, wrong)
    assert not (travel / ".flowforge").exists()


def test_a_wrong_value_already_in_the_app_shows_as_missing_with_the_suggestion(served, travel):
    KeyStore(travel).add("SUPABASE_ANON_KEY", fake_supabase_key("myproject12345"))
    (travel / ".flowforge").mkdir()
    (travel / ".flowforge/dart-defines.json").write_text(json.dumps({"SUPABASE_URL": fake_supabase_key("myproject12345")}))
    with served() as c:
        setting = {s["name"]: s for s in c.get("/keys").json()["settings"]}["SUPABASE_URL"]
    assert setting["in_app"] is False and setting["suggestion"] == "https://myproject12345.supabase.co"


@pytest.mark.parametrize("value, ok", [
    ("https://p.supabase.co", True), ("http://localhost:54321", True), ("https://p.supabase.co/rest/v1", True),
    ("https://example.com garbage", False), ("https://host:bad", False), ("https://", False), ("https://:443", False),
    ("ftp://p.supabase.co", False),
])
def test_a_url_setting_must_be_a_whole_url(value, ok):
    """Codex review: the whole URL, host and port included, not just how it starts."""
    from flowforge.security.wire import setting_problem

    assert (setting_problem("SUPABASE_URL", value) is None) is ok
