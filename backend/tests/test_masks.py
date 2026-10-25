"""Masked keys (D43): the agent writes ffkey://NAME, plain code fills it with the saved value as the app starts. Fake
keys only."""

import pytest

from flowforge.security.masks import MissingKeys, fill, mask, masks_in

FAKE = "sk_test_FAKEFAKE12345678"
OTHER = "rzp_test_FAKE1234567"
VALUES = {"STRIPE_SECRET_KEY": FAKE, "RAZORPAY_KEY": OTHER}


def test_a_mask_names_its_key():
    assert mask("STRIPE_SECRET_KEY") == "ffkey://STRIPE_SECRET_KEY"


def test_masks_in_a_command_and_env_are_found():
    argv = ["flutter", "run", "--dart-define=STRIPE_SECRET_KEY=ffkey://STRIPE_SECRET_KEY"]
    env = {"PAY": "ffkey://RAZORPAY_KEY", "HOME": "/home/me"}
    assert masks_in(argv, env) == {"STRIPE_SECRET_KEY", "RAZORPAY_KEY"}


def test_fill_puts_the_values_in_the_command_and_env_and_adds_every_saved_key():
    argv, env = fill(["flutter", "run", "--dart-define=STRIPE_SECRET_KEY=ffkey://STRIPE_SECRET_KEY"],
                     {"PAY": "Bearer ffkey://RAZORPAY_KEY", "HOME": "/home/me"}, VALUES)
    assert argv == ["flutter", "run", f"--dart-define=STRIPE_SECRET_KEY={FAKE}"]
    assert env["PAY"] == f"Bearer {OTHER}" and env["HOME"] == "/home/me"
    assert env["STRIPE_SECRET_KEY"] == FAKE and env["RAZORPAY_KEY"] == OTHER   # code reading the env var gets it


def test_the_callers_lists_are_not_changed():
    argv, env = ["echo", "ffkey://RAZORPAY_KEY"], {"X": "ffkey://RAZORPAY_KEY"}
    fill(argv, env, VALUES)
    assert argv == ["echo", "ffkey://RAZORPAY_KEY"] and env == {"X": "ffkey://RAZORPAY_KEY"}


def test_a_mask_for_a_key_that_isnt_saved_stops_everything():
    with pytest.raises(MissingKeys) as e:
        fill(["app", "--key=ffkey://NOT_SAVED", "ffkey://ALSO_MISSING"], {}, VALUES)
    assert e.value.names == ["ALSO_MISSING", "NOT_SAVED"]
    assert FAKE not in str(e.value) and OTHER not in str(e.value)


@pytest.mark.parametrize("text", ["ffkey://", "ffkey://1BAD", "ffkey:/NAME", "FFKEY://NAME"])
def test_only_well_formed_masks_count(text):
    assert masks_in([text], {}) == set()
