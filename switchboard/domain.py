import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field

LOCKED_RISK = "locked"
REVERSIBILITY = ("reversible", "partially_reversible", "irreversible", "unknown")
INTENT_TYPES = ("preference", "permission", "disambiguation", "action_review", "unknown")


def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s or "")).strip()


def tokens(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", normalize_text(s).lower()))


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@dataclass
class QuestionRequest:
    request_id: str
    question: str
    category: str
    risk_hint: str | None = None
    reversibility: str = "unknown"
    deadline_at: str | None = None
    options: list = field(default_factory=list)
    context: dict = field(default_factory=dict)
    intent_type: str = "unknown"
    action: dict | None = None
    parent_receipts: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def canonical_payload(self) -> dict:
        return {
            "request_id": self.request_id,
            "question": normalize_text(self.question),
            "category": self.category,
            "reversibility": self.reversibility if self.reversibility in REVERSIBILITY else "unknown",
            "deadline_at": self.deadline_at,
            "options": sorted(
                [{"id": str(o.get("id", "")), "label": normalize_text(str(o.get("label", "")))} for o in self.options],
                key=lambda o: o["id"]),
            "context": self.context or {},
            "intent_type": self.intent_type if self.intent_type in INTENT_TYPES else "unknown",
            "action": self.action,
            "parent_receipts": sorted(self.parent_receipts or []),
        }

    def canonical_hash(self) -> str:
        return sha256_hex(canonical_json(self.canonical_payload()))


def evaluate_scope(scope: dict, context: dict) -> dict:
    """Mandatory predicates: failure -> invalid; missing context -> unknown (never true)."""
    mandatory = (scope or {}).get("mandatory", {})
    details, unknown = {}, False
    for key, expected in mandatory.items():
        if key not in context:
            details[key] = "unknown"
            unknown = True
            continue
        actual = context[key]
        ok = actual in expected if isinstance(expected, list) else actual == expected
        details[key] = "pass" if ok else "fail"
        if not ok:
            return {"valid": False, "result": "fail", "details": details}
    if unknown:
        return {"valid": False, "result": "unknown", "details": details}
    return {"valid": True, "result": "pass", "details": details}


def classify_risk(q: QuestionRequest, settings) -> dict:
    """Conservative: agent risk_hint can raise, never lower, our classification."""
    reasons = []
    ctx = q.context or {}
    if q.category in settings.locked_categories:
        reasons.append(f"category_locked:{q.category}")
    for flag in settings.locked_context_flags:
        if ctx.get(flag) is True:
            reasons.append(f"context_flag:{flag}")
    if q.intent_type == "action_review" and q.reversibility in ("irreversible", "unknown"):
        reasons.append("action_review_irreversible_or_unknown")
    if q.action and q.action.get("type") in ("payment", "delete", "send_message", "purchase"):
        reasons.append(f"action_type:{q.action.get('type')}")
    locked = bool(reasons)
    return {"risk_class": LOCKED_RISK if locked else "standard", "is_locked": locked, "reasons": reasons}
