from fastapi.testclient import TestClient

import switchboard.app as app_module
from switchboard.app import app

# The operator's .env may set a UI token; these API tests run tokenless.
app_module.UI_TOKEN = ""
client = TestClient(app)


def test_health_and_demo_flow():
    assert client.get("/health").status_code == 200
    p = client.post("/demo/tradeoff", json={"options": [
        {"id": "a", "price": 900, "comfort": 9, "complexity": 3},
        {"id": "b", "price": 300, "comfort": 5, "complexity": 1}]})
    assert p.status_code == 200
    payload = p.json()
    assert {a["edge"] for a in payload["actions"]} == {"top", "left", "right", "bottom"}
    s = client.post("/demo/steer", json={"payload": payload, "action_id": "cheaper"})
    assert s.status_code == 200 and s.json()["status"] == "steered"


def test_demo_steer_malformed_is_400_not_500():
    # A null/mismatched payload must fail loudly as a 400, never a 500 —
    # and the UI surfaces the failure instead of swallowing the tap.
    assert client.post("/demo/steer", json={"payload": None, "action_id": "cheaper"}).status_code == 400
    assert client.post("/demo/steer", json={"payload": {"actions": []}, "action_id": "nope"}).status_code == 400


def test_api_ask_requires_agent_key():
    r = client.post("/api/ask", json={"request_id": "x", "question": "hi?", "category": "purchase"})
    assert r.status_code == 401


def test_ui_served():
    r = client.get("/")
    assert r.status_code == 200 and "Switchboard" in r.text


def test_health_advertises_capabilities():
    # The UI's compatibility handshake depends on this list: every surface
    # the frontend renders from a backend route must be named here.
    h = client.get("/health").json()
    for cap in ["inbox", "steering", "debrief", "onboarding", "simulation",
                "taste", "passport", "notices", "resolve"]:
        assert cap in h["capabilities"], f"missing capability: {cap}"
