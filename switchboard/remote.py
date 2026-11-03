"""Hub client for device-agnostic mode.

When SWITCHBOARD_REMOTE_URL is set, agent calls go to that Switchboard web
API (the Modal hub) with the agent key, so every device shares one ledger.
Fails closed: an unreachable hub defers, never guesses.
"""
import httpx


class HubUnavailableError(RuntimeError):
    """No remote answer was obtained; never misrepresent this as no rules."""


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
                "risk_hint": req.risk_hint,
                "reversibility": req.reversibility, "context": req.context or {},
                "options": req.options or [], "action": req.action,
                "parent_receipts": req.parent_receipts or []})
        except Exception:
            return {"decision": "defer", "answer": None,
                    "reason_code": "hub_unreachable", "receipt_id": None,
                    "question_id": None, "decision_id": None, "rule_versions": []}

    def action_request_status(self, question_id: str) -> dict:
        try:
            response = self._client.get(f"/api/action-requests/{question_id}")
            response.raise_for_status()
            return response.json()
        except Exception:
            return {"status": "unavailable", "question_id": question_id,
                    "reason_code": "hub_unreachable"}

    def get_rules(self, category=None) -> list:
        try:
            resp = self._client.get("/api/rules", params={"category": category} if category else {})
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise ValueError("invalid rule response")
            return data
        except Exception:
            raise HubUnavailableError("Switchboard hub rule lookup failed; check connection status") from None

    def connection_status(self) -> dict:
        try:
            health = self._client.get("/health")
            health.raise_for_status()
            identity = self._client.get("/api/identity")
            identity.raise_for_status()
            state, agent = health.json(), identity.json()
            if (state.get("status") != "ok" or not isinstance(agent.get("id"), str)
                    or not isinstance(agent.get("name"), str) or not isinstance(agent.get("scopes"), list)):
                return {"connected": False, "backend": "hub", "reason_code": "incompatible_hub"}
            return {"connected": True, "backend": "hub", "agent": agent,
                    "version": state.get("version"), "build_id": state.get("build_id"),
                    "capabilities": state.get("capabilities", [])}
        except httpx.HTTPStatusError as exc:
            return {"connected": False, "backend": "hub", "reason_code": "hub_http_error",
                    "http_status": exc.response.status_code}
        except Exception:
            return {"connected": False, "backend": "hub", "reason_code": "hub_unreachable"}

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

    # Steering fails closed too: no hub, no proposal — never a local guess.
    def submit_proposal(self, title, proposal_text, category, directions, project=None) -> dict:
        try:
            return self._post("/api/steering/submit", {
                "title": title, "proposal_text": proposal_text,
                "category": category, "directions": directions, "project": project})
        except Exception:
            return {"status": "deferred", "reason_code": "hub_unreachable", "id": None}

    def revise_proposal(self, session_id, proposal_text, note=None) -> dict:
        try:
            return self._post("/api/steering/revise", {
                "session_id": session_id, "proposal_text": proposal_text, "note": note})
        except Exception:
            return {"status": "deferred", "reason_code": "hub_unreachable", "id": session_id}

    def pending_steer(self, session_id) -> dict:
        try:
            resp = self._client.get(f"/api/steering/pending/{session_id}")
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {"status": "unknown", "reason_code": "hub_unreachable", "instruction": None}
