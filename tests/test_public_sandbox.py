"""Public boundaries and real decision/correction behavior, not a UI mock."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import switchboard.app as private_web
from switchboard.sandbox import COOKIE, PublicSandbox


@pytest.fixture
def playground():
    app = PublicSandbox()
    yield app
    app.close()


def visitor(app):
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert COOKIE in client.cookies
    return client


def test_no_private_store_or_model_access(playground, monkeypatch):
    before_service, before_store = private_web.svc, private_web.store
    monkeypatch.setattr(private_web, "UI_TOKEN", "private-fixture")
    a, b = visitor(playground), visitor(playground)
    assert len(playground.sessions) == 2
    assert private_web.svc is before_service and private_web.store is before_store
    assert private_web.UI_TOKEN == "private-fixture"
    assert a.get("/health").json()["sandbox"]
    assert not a.get("/health").json()["t3_enabled"]
    for workspace in playground.sessions.values():
        assert workspace.service.ladder.t3 is None
        assert not workspace.service.cfg.baseten_api_key
        assert not workspace.service.cfg.meta_api_key
        assert workspace.service.store.query_one("PRAGMA database_list")["file"] == ""
        assert workspace.service.store.query_one("SELECT count(*) AS n FROM calibration_examples")["n"] == 0
        assert workspace.service.store.query_one("SELECT count(*) AS n FROM events WHERE source_evidence_class!='synthetic'")["n"] == 0
    a_ids = {i["id"] for i in a.get("/inbox").json()}
    b_ids = {i["id"] for i in b.get("/inbox").json()}
    assert a_ids.isdisjoint(b_ids)
    foreign = a.post(f"/inbox/{next(iter(b_ids))}/answer", json={"answer": {"value": "allow"}})
    assert foreign.status_code == 400
    assert len(b.get("/inbox").json()) == 2
    for path in ("/mcp", "/api/agents/register", "/api/ask", "/login", "/demo/visual/generate", "/evaluation/replay"):
        assert a.post(path, json={}).status_code == 403
    assert a.get("/openapi.json").status_code == 403
    assert TestClient(private_web.app).get("/inbox").status_code == 401


def test_reuse_scope_and_correction_use_actual_service(playground):
    a, b = visitor(playground), visitor(playground)
    rule_id = a.get("/sandbox/status").json()["rule_id"]
    reused = a.post("/sandbox/reuse", json={}).json()
    assert reused["decision"] == "answer" and reused["answer"]["value"] == "Saturday at 10 AM"
    different = a.post("/sandbox/reuse", json={"different_project": True}).json()
    assert different["decision"] == "defer"
    assert len(a.get("/inbox").json()) == 3
    preview = a.post("/sandbox/preview", json={}).json()
    assert {i["proposed_status"] for i in preview["blast_radius"]["affected"]} == {"revalidate", "review_completed"}
    assert a.get("/human/rules").json()[0]["version_number"] == 1
    corrected = a.post("/sandbox/correct", json={"expected_version_id": preview["current_version_id"]})
    assert corrected.status_code == 200 and corrected.json()["required_confirmations"] == 1
    assert a.post("/sandbox/correct", json={"expected_version_id": preview["current_version_id"]}).json()["error"] == "CONFLICT"
    assert a.post("/sandbox/reuse", json={}).json()["decision"] == "defer"
    assert b.get("/human/rules").json()[0]["version_number"] == 1
    assert b.post("/sandbox/reuse", json={}).json()["decision"] == "answer"
    rules = a.get("/human/rules").json()
    assert rules[0]["rule_id"] == rule_id and rules[0]["recalibration"]


def test_answer_and_reset_are_personal(playground):
    a, b = visitor(playground), visitor(playground)
    old_cookie = a.cookies[COOKIE]
    contact = next(i for i in a.get("/inbox").json() if i["category"] == "contact_display")
    assert a.post(f"/inbox/{contact['id']}/answer", json={"answer": {"value": "Use email only"}, "origin": "tap"}).status_code == 200
    assert len(a.get("/inbox").json()) == 1
    assert len(b.get("/inbox").json()) == 2
    assert a.post("/sandbox/reset", json={}).status_code == 200
    assert a.cookies[COOKIE] != old_cookie
    assert old_cookie not in playground.sessions
    assert len(a.get("/inbox").json()) == len(b.get("/inbox").json()) == 2
    assert len(playground.sessions) == 2


def test_parallel_visitors_have_separate_caches(playground):
    a, b = visitor(playground), visitor(playground)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(a.post, "/sandbox/correct", json={"expected_version_id": a.post("/sandbox/preview", json={}).json()["current_version_id"]})
        second = pool.submit(b.post, "/sandbox/reuse", json={})
        assert first.result().json()["version_number"] == 2
        assert second.result().json()["answer"]["value"] == "Saturday at 10 AM"
    a_read, b_read = a.get("/inbox"), b.get("/inbox")
    assert a.get("/inbox", headers={"If-None-Match": b_read.headers["etag"]}).status_code == 200
    unchanged = a.get("/inbox", headers={"If-None-Match": a_read.headers["etag"]})
    assert unchanged.status_code == 304 and unchanged.content == b""


def test_cookie_csrf_body_limits_and_capacity(playground):
    client = visitor(playground)
    # Fresh HTTPS visitors get a secure, opaque cookie, never an agent key.
    secure = TestClient(playground, base_url="https://testserver")
    header = secure.get("/").headers["set-cookie"]
    assert "HttpOnly" in header and "Secure" in header and "SameSite=Lax" in header
    assert client.post("/sandbox/reset", json={}, headers={"Origin": "https://other.example"}).status_code == 403
    assert client.post("/sandbox/reset", content="{}", headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.post("/rules", content=b"x" * 16385, headers={"Content-Type": "application/json"}).status_code == 413
    assert client.post("/sandbox/reuse", json=[]).status_code == 400
    small = PublicSandbox(max_sessions=1)
    try:
        first = visitor(small)
        assert TestClient(small).get("/").status_code == 503
        assert first.post("/sandbox/reset", json={}).status_code == 200
    finally:
        small.close()


def test_health_and_unknown_cookies_do_not_allocate_workspaces(playground):
    client = TestClient(playground)
    assert client.get("/health").status_code == 200
    client.cookies.set(COOKIE, "made-up-browser-cookie")
    assert client.get("/inbox").status_code == 409
    assert not playground.sessions
    assert client.post("/sandbox/reset", json={}).status_code == 200
    assert len(playground.sessions) == 1


def test_request_budget_and_database_budget_allow_reset(playground):
    client = visitor(playground)
    workspace = playground.sessions[client.cookies[COOKIE]]
    workspace.calls.extend([playground.clock()] * 180)
    assert client.get("/inbox").status_code == 429
    workspace.calls.clear()
    workspace.service.store.execute("CREATE TABLE payload(value BLOB)")
    workspace.service.store.execute("INSERT INTO payload VALUES(zeroblob(4500000))")
    assert client.post("/sandbox/reuse", json={}).status_code == 429
    assert client.post("/sandbox/reset", json={}).status_code == 200
    assert len(client.get("/inbox").json()) == 2


def test_expiry_does_not_close_inflight_workspace():
    now = [0.0]
    app = PublicSandbox(ttl=5, clock=lambda: now[0])
    try:
        client = visitor(app)
        original = app.sessions[client.cookies[COOKIE]]
        original.active = 1  # A bounded event stream is still reading it.
        now[0] = 6.0
        assert client.get("/inbox").status_code == 409
        assert original.retired
        assert original.service.store.query_one("SELECT 1 AS n")["n"] == 1
        original.active = 0
        original.close()
        assert client.get("/").status_code == 200
    finally:
        app.close()
