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
    assert r2.headers.get("X-Cache") == "HIT"  # same generation: zero SQLite
    r3 = client.get("/inbox", headers={"If-None-Match": etag})
    assert r3.status_code == 304
    # A write must invalidate: fresh data, never a stale HIT.
    reg = client.post("/api/agents/register", json={"name": "w", "kind": "cli"}).json()
    client.post("/api/ask", headers={"x-agent-key": reg["api_key"]},
                json={"request_id": "w1", "question": "May I buy this?",
                      "category": "purchase", "reversibility": "reversible"})
    r4 = client.get("/inbox", headers={"If-None-Match": etag})
    assert r4.status_code == 200 and r4.headers.get("X-Cache") == "MISS"
    assert len(r4.json()) == 1
