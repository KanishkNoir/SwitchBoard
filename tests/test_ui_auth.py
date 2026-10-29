from fastapi.testclient import TestClient

import switchboard.app as app_module


def test_ui_open_when_no_token(monkeypatch):
    monkeypatch.setattr(app_module, "UI_TOKEN", "")
    client = TestClient(app_module.app)
    assert client.get("/health").status_code == 200
    assert client.get("/inbox").status_code == 200


def test_ui_requires_token_cookie_or_header(monkeypatch):
    monkeypatch.setattr(app_module, "UI_TOKEN", "test-token-123")
    client = TestClient(app_module.app, follow_redirects=False)
    assert client.get("/inbox").status_code == 401
    assert client.get("/login?token=wrong").status_code == 401
    r = client.get("/login?token=test-token-123")
    assert r.status_code == 302 and "sb_token" in r.headers.get("set-cookie", "")
    assert client.get("/inbox").status_code == 200  # cookie persisted by client
    assert client.get("/inbox", headers={"x-ui-token": "test-token-123"}).status_code == 200
    # Agent API stays on its own key auth, not the UI token.
    assert client.post("/api/ask", json={"request_id": "x", "question": "hi?", "category": "c"}).status_code == 401
