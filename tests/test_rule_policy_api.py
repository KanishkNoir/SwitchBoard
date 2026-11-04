import pytest
from fastapi.testclient import TestClient

import switchboard.app as app_module
from switchboard.benchmark import isolated_service


@pytest.fixture
def client(monkeypatch):
    service = isolated_service()
    monkeypatch.setattr(app_module, "svc", service)
    monkeypatch.setattr(app_module, "store", service.store)
    monkeypatch.setattr(app_module, "UI_TOKEN", "")
    try:
        yield TestClient(app_module.app)
    finally:
        service.store.close()


def test_contract_and_preview_routes_report_validation_without_500(client):
    response = client.put("/settings/reports/scope-contract", json={"required_fields": ["project"]})
    assert response.status_code == 200 and response.json()["configured"]
    body = {"category": "reports", "predicate": {"keywords": ["report"]}, "answer": {"value": "markdown"}}
    bad = client.post("/rules", json={**body, "scope": {"mandatory": {"workspace": "drafts"}}})
    assert bad.status_code == 400 and bad.json()["error"] == "RULE_SCOPE_REQUIRED"
    made = client.post("/rules", json={**body, "scope": {"mandatory": {"project": "atlas"}}}).json()
    request = {"answer": {"value": "pdf"}, "expected_version_id": made["version_id"]}
    preview = client.post(f"/rules/{made['rule_id']}/preview", json=request)
    assert preview.status_code == 200 and preview.json()["required_confirmations"] == 1
    assert client.post(f"/rules/{made['rule_id']}/supersede", json=request).status_code == 200
    assert client.post(f"/rules/{made['rule_id']}/supersede", json=request).json()["error"] == "CONFLICT"


def test_contract_updates_and_previews_require_operator_auth(client, monkeypatch):
    monkeypatch.setattr(app_module, "UI_TOKEN", "operator-fixture")
    for method, path, body in (("get", "/settings/reports/scope-contract", None),
                               ("put", "/settings/reports/scope-contract", {"required_fields": ["project"]}),
                               ("post", "/rules/not-a-rule/preview", {}),
                               ("post", "/rules/not-a-rule/review-hold", {"confirmed": True})):
        kwargs = {"json": body} if body is not None else {}
        response = client.request(method, path, **kwargs)
        assert response.status_code == 401
    assert client.get("/settings/reports/scope-contract", headers={"x-ui-token": "operator-fixture"}).status_code == 200
