"""A map made by an older FlowForge is read again on start (D35); a current one is left alone."""

from pathlib import Path

from flowforge.flowmap.models import Override
from flowforge.flowmap.planner import READER, CodeFlowPlanner, ScanPlanner
from flowforge.flowmap.service import FlowService
from flowforge.storage import Storage

TRIP_PLANNER = Path(__file__).resolve().parents[2] / "examples" / "trip-planner"


def service(storage: Storage, map_id: str) -> FlowService:
    return FlowService(storage.flows(map_id), dict, None)


def test_an_older_readers_map_is_read_again_and_a_current_one_is_kept(tmp_path):
    storage = Storage(tmp_path / "ff.db")
    for map_id, planner in (("deps", ScanPlanner(TRIP_PLANNER)), ("flow", CodeFlowPlanner(TRIP_PLANNER))):
        old = planner.analyze(0)
        old.flow.reader = 0   # as saved by FlowForge before D35
        storage.flows(map_id).add_flow_version("accepted", old.flow.model_dump(mode="json"), None,
                                               old.analysis.model_dump(mode="json"), old.fact_sheet_hash)
        maps = service(storage, map_id)
        assert maps.map_folder(planner, fresh=False) == 2   # read again: a new version
        assert storage.flows(map_id).latest_flow_version("accepted")["flow"]["reader"] == READER
        assert storage.flows(map_id).count_flow_versions() == 2   # the old version stays listed
        assert service(storage, map_id).map_folder(planner, fresh=False) is None   # current: left alone
        assert storage.flows(map_id).count_flow_versions() == 2


def test_your_edits_survive_the_reread(tmp_path):
    storage = Storage(tmp_path / "ff.db")
    planner = ScanPlanner(TRIP_PLANNER)
    old = planner.analyze(0)
    old.flow.reader = 0
    store = storage.flows("deps")
    store.add_flow_version("accepted", old.flow.model_dump(mode="json"), None, old.analysis.model_dump(mode="json"),
                           old.fact_sheet_hash)
    maps = service(storage, "deps")
    maps.planner = planner
    maps.add_override(Override(op="hide", node="api-wikipedia"))
    service(storage, "deps").map_folder(planner, fresh=False)
    assert all(n["id"] != "api-wikipedia" for n in service(storage, "deps").current()["nodes"])


def test_accepting_a_rescan_keeps_what_the_map_is(tmp_path):
    from flowforge.flowmap.diff import apply_choices, diff

    new = CodeFlowPlanner(TRIP_PLANNER).analyze(0).flow
    old = new.model_copy(deep=True)
    old.nodes = [n for n in old.nodes if n.id != "local-packing-list-1"]
    old.edges = [e for e in old.edges if "local-packing-list-1" not in (e.source, e.target)]
    accepted, _ = apply_choices(old, new, diff(old, new, [], {}), {})
    assert accepted.source == "code" and accepted.reader == READER
    assert accepted.actions and accepted.written_ms == new.written_ms and accepted.patterns == new.patterns
    assert all(all(i in {n.id for n in accepted.nodes} for i in a.nodes) for a in accepted.advice)


def test_a_rescan_waiting_for_review_is_discarded_when_the_map_is_read_again(tmp_path):
    storage = Storage(tmp_path / "ff.db")
    planner = ScanPlanner(TRIP_PLANNER)
    old = planner.analyze(0)
    old.flow.reader = 0
    store = storage.flows("deps")
    for status in ("accepted", "pending"):
        store.add_flow_version(status, old.flow.model_dump(mode="json"), None, old.analysis.model_dump(mode="json"),
                               old.fact_sheet_hash)
    service(storage, "deps").map_folder(planner, fresh=False)
    assert store.latest_flow_version("pending") is None
    assert store.flow_version(2)["status"] == "discarded"
