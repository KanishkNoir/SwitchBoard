"""Backend optimization contracts: timing headers, generation cache, bounded queries."""
import os

from fastapi.testclient import TestClient

import switchboard.app as app_module
from switchboard.domain import QuestionRequest
from switchboard.persistence import Store, reset_sqlite_stats, sqlite_stats
from switchboard.service import SwitchboardService

DIRS = [
    {"edge": "left", "label": "Cheaper", "expected_effect": "Lower cost first"},
    {"edge": "right", "label": "More comfort", "expected_effect": "Comfort first"},
]


def make():
    svc = SwitchboardService(Store(":memory:"))
    reg = svc.register_agent("perf")
    return svc, svc.authenticate(reg["api_key"])


def test_journal_mode_env_gate(tmp_path):
    db = str(tmp_path / "j.db")
    os.environ["SWITCHBOARD_JOURNAL_MODE"] = "delete"
    try:
        mode = Store(db).conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "delete"
    finally:
        del os.environ["SWITCHBOARD_JOURNAL_MODE"]
    assert Store(str(tmp_path / "j2.db")).conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_write_seq_bumps_only_on_real_writes():
    svc, agent = make()
    seq0 = svc.store.write_seq
    svc.ask(agent, QuestionRequest(request_id="r1", question="May I buy this?",
                                  category="purchase", reversibility="reversible"))
    assert svc.store.write_seq > seq0
    seq1 = svc.store.write_seq
    svc.inbox()
    svc.list_steering()
    svc.debrief()
    svc.taste_profile()
    assert svc.store.write_seq == seq1  # reads never bump the generation
    svc.passport("purchase")  # audit-only write: must not invalidate the cache
    assert svc.store.write_seq == seq1


def test_bounded_queries_for_lists():
    svc, agent = make()
    for i in range(20):
        svc.ask(agent, QuestionRequest(
            request_id=f"q{i}", question=f"May I buy item {i}?",
            category="purchase", reversibility="reversible"))
        s = svc.submit_proposal(agent, f"Prop {i}", f"Body {i}", "purchase", DIRS)
        svc.steer(s["id"], "left")
    reset_sqlite_stats(svc.store)
    svc.inbox()
    _, nq = sqlite_stats(svc.store)
    assert nq <= 3, f"inbox took {nq} queries"
    reset_sqlite_stats(svc.store)
    svc.list_steering()
    _, nq = sqlite_stats(svc.store)
    assert nq <= 5, f"list_steering took {nq} queries"


def test_server_timing_and_cache_headers():
    app_module.UI_TOKEN = ""
    app_module.store = Store(":memory:")
    app_module.svc = SwitchboardService(app_module.store)
    app_module._read_cache.clear()
    client = TestClient(app_module.app)
    r1 = client.get("/inbox")
    assert r1.status_code == 200
    assert "sqlite" in r1.headers.get("Server-Timing", "")
    assert r1.headers.get("X-Cache") == "MISS"
    etag = r1.headers.get("ETag")
    assert etag
    r2 = client.get("/inbox")
    assert r2.headers.get("X-Cache") == "HIT"  # only the lightweight generation check
    r3 = client.get("/inbox", headers={"If-None-Match": etag})
    assert r3.status_code == 304
    assert r3.content == b""  # 304 must not send JSON null over a real HTTP connection.
    assert "content-type" not in r3.headers
    # A write must invalidate: fresh data, never a stale HIT.
    reg = client.post("/api/agents/register", json={"name": "w", "kind": "cli"}).json()
    client.post("/api/ask", headers={"x-agent-key": reg["api_key"]},
                json={"request_id": "w1", "question": "May I buy this?",
                      "category": "purchase", "reversibility": "reversible"})
    r4 = client.get("/inbox", headers={"If-None-Match": etag})
    assert r4.status_code == 200 and r4.headers.get("X-Cache") == "MISS"
    assert len(r4.json()) == 1


def test_cache_detects_commits_from_another_connection(tmp_path, monkeypatch):
    path = str(tmp_path / "shared.db")
    reader = Store(path)
    writer = Store(path)
    service = SwitchboardService(writer)
    agent = service.authenticate(service.register_agent("stdio-writer")["api_key"])
    monkeypatch.setattr(app_module, "store", reader)
    monkeypatch.setattr(app_module, "_read_cache", {})
    reader_service = SwitchboardService(reader)
    before, _, hit = app_module.cached_read("inbox", "", reader_service.inbox)
    assert before == [] and hit is False
    assert app_module.cached_read("inbox", "", reader_service.inbox)[2] is True

    result = service.ask(agent, QuestionRequest(request_id="external", question="Pick an editor", category="coding"))

    after, _, hit = app_module.cached_read("inbox", "", reader_service.inbox)
    assert hit is False
    assert [item["question_id"] for item in after] == [result["question_id"]]
    assert app_module.cached_read("inbox", "", reader_service.inbox)[2] is True
    reader.close()
    writer.close()


def test_store_replacement_cannot_reuse_old_cache(monkeypatch):
    first, second = Store(":memory:"), Store(":memory:")
    monkeypatch.setattr(app_module, "_read_cache", {})
    monkeypatch.setattr(app_module, "store", first)
    assert app_module.cached_read("test", "", lambda: "first")[0] == "first"
    monkeypatch.setattr(app_module, "store", second)
    assert app_module.cached_read("test", "", lambda: "second")[0] == "second"
    first.close()
    second.close()


def test_external_commit_during_compute_is_not_cached(tmp_path, monkeypatch):
    path = str(tmp_path / "compute-race.db")
    reader, writer = Store(path), Store(path)
    monkeypatch.setattr(app_module, "store", reader)
    monkeypatch.setattr(app_module, "_read_cache", {})

    def compute():
        value = reader.query_one("SELECT COUNT(*) n FROM events")["n"]
        writer.emit("test", "writer", "changed", "test", "one")
        return value

    assert app_module.cached_read("events", "", compute)[0] == 0
    value, _, hit = app_module.cached_read(
        "events", "", lambda: reader.query_one("SELECT COUNT(*) n FROM events")["n"])
    assert value == 1 and hit is False
    reader.close()
    writer.close()


def test_stream_announces_ledger_changes_without_http_notifications(tmp_path, monkeypatch):
    # These coroutine bodies do no I/O; drive them directly to avoid requiring
    # a network socket merely to test the SSE heartbeat's change detection.
    def immediate(coro):
        try:
            coro.send(None)
        except StopIteration as done:
            return done.value
        raise AssertionError("unexpected asynchronous wait")

    path = str(tmp_path / "stream.db")
    reader, writer = Store(path), Store(path)
    monkeypatch.setattr(app_module, "store", reader)
    monkeypatch.setattr(app_module, "_subscribers", [])

    async def to_thread(fn):
        return fn()

    async def timeout(awaitable, timeout):
        awaitable.close()
        writer.emit("test", "stdio", "external.write", "test", "one")
        raise TimeoutError

    class Request:
        async def is_disconnected(self):
            return False

    monkeypatch.setattr(app_module.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(app_module.asyncio, "wait_for", timeout)
    response = immediate(app_module.stream(Request()))
    try:
        event = immediate(response.body_iterator.__anext__())
        assert '"event": "ledger"' in event
    finally:
        immediate(response.body_iterator.aclose())
        assert app_module._subscribers == []
        reader.close()
        writer.close()
