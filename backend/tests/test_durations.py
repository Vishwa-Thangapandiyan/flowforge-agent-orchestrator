from flowforge.schema import Workflow
from flowforge.scheduler.durations import estimate_weights, ewma
from flowforge.storage import Storage

WF = Workflow.model_validate(
    {
        "id": "w",
        "steps": [
            {"id": "hist", "type": "llm", "estimated_ms": 999},
            {"id": "est", "type": "llm", "estimated_ms": 1234},
            {"id": "llm_default", "type": "llm"},
            {"id": "http_default", "type": "http"},
            {"id": "mock", "type": "mock", "params": {"duration_ms": 70}},
        ],
    }
)


def test_fallback_chain():
    assert estimate_weights(WF, {"hist": 2500.0}) == {
        "hist": 2500.0,
        "est": 1234,
        "llm_default": 3000,
        "http_default": 300,
        "mock": 70.0,
    }


def test_ewma():
    assert ewma(None, 100) == 100
    assert ewma(100, 200, alpha=0.3) == 0.3 * 200 + 0.7 * 100


def test_storage_accumulates_ewma(tmp_path):
    db = Storage(tmp_path / "t.db")
    db.record_durations("w", {"a": 100})
    db.record_durations("w", {"a": 200})
    assert db.duration_history("w") == {"a": ewma(100, 200)}
    assert db.duration_history("other") == {}
