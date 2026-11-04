"""Local, deterministic rule boundaries and correction planning.

No model can declare a boundary complete or turn a proposal into confirmation.
Category contracts are operator-authored; unknown categories keep legacy scope
semantics until a contract is configured.
"""
import math

from .domain import canonical_json, normalize_text


# Stable decision dimensions, not agent-generated request/task IDs or clocks.
# Operators can narrow this list or declare additional fields in a contract.
DEFAULT_EVIDENCE_FIELDS = (
    "account", "branch", "env", "environment", "project", "recipient",
    "region", "repo", "repository", "team", "workspace",
)


def validate_scope(scope):
    if not isinstance(scope, dict):
        raise ValueError("scope must be an object")
    if set(scope) - {"mandatory", "global"}:
        raise ValueError("scope supports mandatory fields and an explicit global flag")
    mandatory = scope.get("mandatory", {})
    if not isinstance(mandatory, dict):
        raise ValueError("scope.mandatory must be an object")
    if "global" in scope and not isinstance(scope["global"], bool):
        raise ValueError("scope.global must be a boolean")
    if scope.get("global") and mandatory:
        raise ValueError("a global rule cannot also have mandatory boundaries")
    for key, value in mandatory.items():
        if not isinstance(key, str) or not key.strip() or key != key.strip() or len(key) > 64:
            raise ValueError("scope fields need nonempty names, up to 64 characters")
        values = value if isinstance(value, list) else [value]
        if not values or any(v is None or isinstance(v, (dict, list))
                             or not isinstance(v, (str, int, float, bool))
                             or (isinstance(v, float) and not math.isfinite(v))
                             or (isinstance(v, str) and not v.strip()) for v in values):
            raise ValueError("scope values must be nonempty scalars or nonempty lists of scalars")


def scope_contract_result(scope, contract):
    """A missing contract is explicit legacy compatibility, not inferred consent."""
    try:
        validate_scope(scope)
    except ValueError as exc:
        return {"valid": False, "reason": "invalid_scope", "message": str(exc), "missing_fields": []}
    if scope.get("global"):
        valid = contract["configured"] and contract["allow_global"]
        return {"valid": valid, "reason": "global_confirmed" if valid else "global_not_allowed",
                "missing_fields": []}
    missing = sorted(set(contract["required_fields"]) - set(scope.get("mandatory", {})))
    valid = not missing and (not contract["configured"] or bool(scope.get("mandatory")))
    return {"valid": valid, "reason": "complete" if valid else "scope_contract_incomplete",
            "missing_fields": missing}


def _values(value):
    return {canonical_json(v) for v in (value if isinstance(value, list) else [value])}


def scope_implies(narrow, broad):
    """Set containment, not number-of-fields or string-length heuristics."""
    nm, bm = narrow.get("mandatory", {}), broad.get("mandatory", {})
    return all(key in nm and _values(nm[key]) <= _values(value) for key, value in bm.items())


def scope_relation(old, new):
    new_in_old, old_in_new = scope_implies(new, old), scope_implies(old, new)
    if new_in_old and old_in_new:
        return "equal"
    if new_in_old:
        return "narrowed"
    if old_in_new:
        return "widened"
    return "changed"


def normalized_predicate(predicate):
    if not isinstance(predicate, dict):
        raise ValueError("predicate must be an object")
    result = dict(predicate)
    if "keywords" in result:
        if not isinstance(result["keywords"], list) or any(not isinstance(k, str) for k in result["keywords"]):
            raise ValueError("predicate keywords must be a list of strings")
        result["keywords"] = sorted({normalize_text(k).lower() for k in result["keywords"] if k.strip()})
    for field in ("example_question", "exact_question"):
        if field in result:
            if not isinstance(result[field], str):
                raise ValueError(f"{field} must be a string")
            result[field] = normalize_text(result[field]).lower()
    return result


def predicate_implies(narrow, broad):
    """Conservative implication for exact rules; examples cannot prove it."""
    n, b = normalized_predicate(narrow), normalized_predicate(broad)
    for field in ("category", "intent_type"):
        if b.get(field) and n.get(field) != b[field]:
            return False
    if b.get("exact_question"):
        return n.get("exact_question") == b["exact_question"]
    if n.get("exact_question"):
        return all(word in n["exact_question"] for word in b.get("keywords", []))
    return set(b.get("keywords", [])) <= set(n.get("keywords", []))


def more_specific(narrow, broad):
    ns, bs = narrow["_scope"], broad["_scope"]
    np, bp = narrow["_predicate"], broad["_predicate"]
    forward = scope_implies(ns, bs) and predicate_implies(np, bp)
    backward = scope_implies(bs, ns) and predicate_implies(bp, np)
    return forward and not backward


def correction_plan(old_predicate, old_answer, old_scope, predicate, answer, scope, held_required=0):
    op, np = normalized_predicate(old_predicate), normalized_predicate(predicate)
    relation = scope_relation(old_scope, scope)
    same_answer = canonical_json(old_answer) == canonical_json(answer)
    same_predicate = canonical_json(op) == canonical_json(np)
    # Scope metadata changes (e.g. explicit global confirmation) still create a version.
    same_scope = relation == "equal" and bool(old_scope.get("global")) == bool(scope.get("global"))
    if same_answer and same_predicate and same_scope:
        return {"changed": False, "change_kind": "unchanged", "scope_relation": relation,
                "required_confirmations": held_required, "preserves_hold": bool(held_required)}
    if same_answer and same_predicate and relation == "narrowed" and not held_required:
        return {"changed": True, "change_kind": "scope_narrowed", "scope_relation": relation,
                "required_confirmations": 0, "preserves_hold": False}
    exact = bool(np.get("keywords") or np.get("exact_question"))
    base = 1 if exact else 3
    broader = relation in ("widened", "changed") or not same_predicate
    return {"changed": True, "change_kind": "scope_widened" if relation == "widened" else
            "scope_changed" if relation == "changed" else "predicate_changed" if not same_predicate else
            "answer_changed" if not same_answer else "scope_narrowed",
            "scope_relation": relation, "required_confirmations": max(base, 3 if broader else 0, held_required),
            "preserves_hold": False}


def fresh_context_key(context, scope, contract):
    # Scope dimensions always matter. A configured contract may restrict the
    # remaining dimensions; arbitrary extra agent metadata never adds evidence.
    extras = contract["evidence_fields"] if contract["configured"] else DEFAULT_EVIDENCE_FIELDS
    fields = sorted(set(extras) | set(contract["required_fields"]) | set(scope.get("mandatory", {})))
    relevant = {}
    for key in fields:
        value = context.get(key)
        if isinstance(value, str):
            value = normalize_text(value)
            if value:
                relevant[key] = value
        elif isinstance(value, (bool, int)) or isinstance(value, float) and math.isfinite(value):
            relevant[key] = value
        # Nested tool metadata and absent/empty identities cannot manufacture
        # independently confirmed decision contexts.
    # Including the basis prevents hashes from mixing different definitions.
    return canonical_json({"fields": fields, "context": relevant})
