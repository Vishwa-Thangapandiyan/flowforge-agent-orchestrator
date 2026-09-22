import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from flowforge.schema import Workflow

WORKFLOWS = Path(__file__).parent.parent / "workflows"


def wf(*steps):
    return {"id": "t", "steps": list(steps)}


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.json")), ids=lambda p: p.name)
def test_example_workflows_validate(path):
    Workflow.model_validate(json.loads(path.read_text()))


def test_duplicate_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate step id 'a'"):
        Workflow.model_validate(wf({"id": "a", "type": "mock"}, {"id": "a", "type": "mock"}))


def test_unknown_dependency_rejected():
    with pytest.raises(ValidationError, match="unknown step 'ghost'"):
        Workflow.model_validate(wf({"id": "a", "type": "mock", "depends_on": ["ghost"]}))


def test_self_dependency_rejected():
    with pytest.raises(ValidationError, match="depends on itself"):
        Workflow.model_validate(wf({"id": "a", "type": "mock", "depends_on": ["a"]}))


def test_template_must_reference_a_dependency():
    with pytest.raises(ValidationError, match="'a' is not in its depends_on"):
        Workflow.model_validate(
            wf(
                {"id": "a", "type": "mock"},
                {"id": "b", "type": "mock", "params": {"x": "{{steps.a.output}}"}},
            )
        )


def test_typo_field_rejected():
    with pytest.raises(ValidationError):
        Workflow.model_validate(wf({"id": "a", "type": "mock", "depend_on": []}))


def test_default_timeouts():
    w = Workflow.model_validate(wf({"id": "a", "type": "llm"}, {"id": "b", "type": "http", "timeout_s": 5}))
    assert w.step("a").effective_timeout_s == 60
    assert w.step("b").effective_timeout_s == 5
