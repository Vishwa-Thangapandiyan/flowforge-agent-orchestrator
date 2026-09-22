import pytest

from flowforge.templating import TemplateError, referenced_steps, resolve

OUT = {"fetch": {"status": 200, "body": "hello", "items": [{"name": "x"}]}, "n": 3}


def test_referenced_steps_nested():
    params = {"a": "{{steps.fetch.output.body}}", "b": ["{{ steps.n.output }}", 1], "c": {"d": "plain"}}
    assert referenced_steps(params) == {"fetch", "n"}


def test_whole_template_keeps_raw_type():
    assert resolve("{{steps.fetch.output}}", OUT) == OUT["fetch"]
    assert resolve("{{steps.n.output}}", OUT) == 3


def test_interpolation_and_paths():
    assert resolve("got {{steps.fetch.output.body}} ({{steps.fetch.output.status}})", OUT) == "got hello (200)"
    assert resolve("{{steps.fetch.output.items.0.name}}", OUT) == "x"


def test_resolve_recurses():
    assert resolve({"k": ["{{steps.n.output}}"]}, OUT) == {"k": [3]}


@pytest.mark.parametrize("tmpl", ["{{steps.fetch.output.nope}}", "{{steps.missing.output}}"])
def test_bad_references_raise(tmpl):
    with pytest.raises(TemplateError):
        resolve(tmpl, OUT)
