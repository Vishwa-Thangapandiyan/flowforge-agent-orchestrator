"""Key finders (D31, CLAUDE.md §6.4 step 1, §6.6): golden snippets, each key found on its exact line, by name only."""

import textwrap

from flowforge.security.finders import KEY_SHAPES, entropy, find_keys, is_placeholder
from flowforge.security.logfilter import KEY_PATTERNS

FAKE = "sk_test_FAKEFAKE12345678"
GOOGLE = "AIzaFAKEFAKEFAKEFAKEFAKE1234"
RANDOM = "Zq8Wm3Xr7Tn2Yp5Lk9Jh4Gf6"   # no known shape: only its entropy and its name give it away


def lines_of(text: str, language: str) -> dict[int, tuple[str, str | None]]:
    return {h.line: (h.label, h.name) for h in find_keys(textwrap.dedent(text).lstrip("\n"), language)}


def test_every_known_key_shape_has_a_name():
    assert len(KEY_SHAPES) == len(KEY_PATTERNS)
    assert all(label for label, _ in KEY_SHAPES)


def test_python_keys_in_every_place_they_hide():
    got = lines_of(f'''
        import os
        stripe.api_key = "{FAKE}"
        client = Client(token="{RANDOM}")
        CONFIG = {{"api_key": "{RANDOM}"}}
        def outer():
            def inner():
                return call(secret="{RANDOM}")
        # the old one: {GOOGLE}
        url = f"https://x.test/v1?key={FAKE}"
        password = os.getenv("PASSWORD")
        api_key = "your-api-key-here"
        token = "<TOKEN>"
        primary_key = "id"
        session_token = ""
    ''', "python")
    assert got == {
        2: ("Stripe key", "api_key"),
        3: ("secret", "token"),
        4: ("secret", "api_key"),
        7: ("secret", "secret"),
        8: ("Google API key", None),
        9: ("Stripe key", "url"),
    }


def test_js_and_ts_keys_in_calls_objects_template_literals_and_comments():
    got = lines_of(f'''
        const stripe = new Stripe("{FAKE}");
        const config = {{ apiKey: "{RANDOM}" }};
        const header = `Bearer {FAKE}`;
        // {GOOGLE}
        const key = process.env.API_KEY;
        const secret = "changeme";
        const keyboard = "qwertyuiopasdfgh";
    ''', "typescript")
    assert got == {1: ("Stripe key", None), 2: ("secret", "apiKey"), 3: ("Stripe key", "header"),
                   4: ("Google API key", None)}


def test_dart_keys():
    got = lines_of(f'''
        const apiKey = '{RANDOM}';
        final String mapsKey = "{GOOGLE}";
        final anon = String.fromEnvironment('SUPABASE_KEY');
    ''', "dart")
    assert got == {1: ("secret", "apiKey"), 2: ("Google API key", "mapsKey")}


def test_references_patterns_and_env_names_are_not_keys():
    got = lines_of('''
        PRESET = {"secret_ref": "env:NVIDIA_API_KEY", "token_env": "GITHUB_PERSONAL_TOKEN"}
        SECRET_REF_PATTERN = r"^(env|vault):[A-Z_][A-Z0-9_]*$"
        api_key = "{{steps.auth.output.key}}"
    ''', "python")
    assert got == {}


def test_a_private_key_block_is_found_at_its_first_line():
    got = lines_of('''
        PEM = """
        -----BEGIN RSA PRIVATE KEY-----
        FAKEFAKEFAKE
        -----END RSA PRIVATE KEY-----
        """
    ''', "python")
    assert got == {2: ("private key", None)}


def test_a_hit_never_carries_the_value():
    hits = find_keys(f'API_KEY = "{FAKE}"\n', "python")
    assert hits and all(FAKE not in repr(h) for h in hits)


def test_entropy_and_placeholders():
    assert entropy(RANDOM) > 3.5 > entropy("aaaaaaaabbbbbbbb")
    for value in ("your-api-key-here", "<TOKEN>", "xxxxxxxxxxxxxxxx", "changeme", "${API_KEY}", "REPLACE_ME", "example-key"):
        assert is_placeholder(value), value
    assert not is_placeholder(RANDOM)
