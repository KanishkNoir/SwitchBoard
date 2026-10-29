"""Hub client for device-agnostic mode.

When SWITCHBOARD_REMOTE_URL is set, agent calls go to that Switchboard web
API (the Modal hub) with the agent key, so every device shares one ledger.
Fails closed: an unreachable hub defers, never guesses.
"""
import httpx


class HubClient:
    def __init__(self, base_url: str, api_key: str, transport=None, timeout: float = 20.0):
        self._client = httpx.Client(base_url=base_url.rstrip("/"),
                                    headers={"x-agent-key": api_key},
                                    timeout=timeout, transport=transport)

    def _post(self, path, payload):
        resp = self._client.post(path, json=payload)
        resp.raise_for_status()
        return resp.json()

    def ask(self, req) -> dict:
        try:
            return self._post("/api/ask", {
                "request_id": req.request_id, "question": req.question,
                "category": req.category, "intent_type": req.intent_type,
                "reversibility": req.reversibility, "context": req.context or {},
                "options": req.options or []})
        except Exception:
            return {"decision": "defer", "answer": None,
                    "reason_code": "hub_unreachable", "receipt_id": None,
                    "question_id": None, "decision_id": None, "rule_versions": []}

    def get_rules(self, category=None) -> list:
        try:
            resp = self._client.get("/api/rules", params={"category": category} if category else {})
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return []

    def report_outcome(self, decision_id, outcome, detail="") -> dict:
        try:
            return self._post("/api/report_outcome",
                              {"decision_id": decision_id, "outcome": outcome, "detail": detail})
        except Exception:
            return {"recorded": False, "reason_code": "hub_unreachable"}

    def record_use(self, receipt_id, dependent_type, dependent_id,
                   relationship="used_answer", status="pending") -> dict:
        try:
            return self._post("/api/record_use", {
                "receipt_id": receipt_id, "dependent_type": dependent_type,
                "dependent_id": dependent_id, "relationship": relationship, "status": status})
        except Exception:
            return {"recorded": False, "reason_code": "hub_unreachable"}
