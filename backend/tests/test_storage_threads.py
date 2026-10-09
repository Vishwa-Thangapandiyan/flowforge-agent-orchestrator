"""One sqlite3 connection is shared by the event loop and FastAPI's worker threads (sync routes).
Storage serialises every call, so concurrent requests can't interleave on the connection."""

from concurrent.futures import ThreadPoolExecutor

from flowforge.storage import Storage


def test_many_threads_share_one_storage_safely(tmp_path):
    storage = Storage(tmp_path / "threads.db")
    storage.put_connector("a", '{"id": "a"}')

    def work(i: int) -> int:
        if i % 3 == 0:
            storage.add_flow_override({"op": "rename", "node": f"n{i}", "title": "x"})
        rows = storage.connector_rows()
        assert rows == [("a", '{"id": "a"}')]   # never a half-read row
        return len(storage.flow_overrides())

    with ThreadPoolExecutor(max_workers=16) as pool:
        counts = list(pool.map(work, range(600)))
    assert max(counts) == 200 and len(storage.flow_overrides()) == 200
