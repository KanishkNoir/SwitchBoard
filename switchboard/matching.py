from .domain import canonical_json, evaluate_scope, normalize_text, tokens
from .rule_policy import more_specific, validate_scope


def token_cosine(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / (len(ta) ** 0.5 * len(tb) ** 0.5)


class T0Matcher:
    """Exact typed rules: category + predicate keywords/intent."""

    tier = "T0"

    def match(self, question_text, category, intent_type, rule_versions):
        hits = []
        for rv in rule_versions:
            pred = rv["_predicate"]
            if pred.get("category") and pred["category"] != category:
                continue
            if pred.get("intent_type") and pred["intent_type"] != intent_type:
                continue
            kws = [normalize_text(k).lower() for k in pred.get("keywords", []) if isinstance(k, str) and k.strip()]
            text = normalize_text(question_text).lower()
            # Examples belong to T1. An empty/semantic-only predicate must
            # never become an unconditional exact match.
            if not kws and not pred.get("exact_question"):
                continue
            if kws and not all(k in text for k in kws):
                continue
            if pred.get("exact_question") and normalize_text(pred["exact_question"]).lower() != text:
                continue
            hits.append(rv)
        if not hits:
            return None
        winners = [rv for rv in hits if not any(more_specific(other, rv) for other in hits)]
        if len({canonical_json(rv["_answer"]) for rv in winners}) > 1:
            return {"ambiguous": True, "reason": "conflicting_rules", "score": 1.0,
                    "score_kind": "similarity", "match_type": "exact",
                    "candidate_rule_ids": sorted(rv["id"] for rv in winners)}
        # Equivalent answers need no extra review; choose a stable receipt source.
        winner = min(winners, key=lambda rv: rv["id"])
        return {"rule_version": winner, "score": 1.0, "score_kind": "similarity", "match_type": "exact"}


class T1Matcher:
    """Local token-cosine encoder stand-in (no external egress). Scores are similarity, not probabilities."""

    tier = "T1"

    def __init__(self, threshold: float = 0.35):
        self.threshold = threshold
        self.ambiguity_margin = 0.08

    def match(self, question_text, category, intent_type, rule_versions):
        ranked = []
        for rv in rule_versions:
            predicate = rv["_predicate"]
            if predicate.get("category") and predicate["category"] != category:
                continue
            if predicate.get("intent_type") and predicate["intent_type"] != intent_type:
                continue
            example = predicate.get("example_question") or predicate.get("exact_question") or ""
            if not example:
                continue
            score = token_cosine(question_text, example)
            if score >= self.threshold:
                ranked.append((score, rv))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        if not ranked:
            return None
        if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < self.ambiguity_margin:
            return {"ambiguous": True, "score": round(ranked[0][0], 4),
                    "score_kind": "similarity", "match_type": "semantic",
                    "candidate_rule_ids": [ranked[0][1]["id"], ranked[1][1]["id"]]}
        return {"rule_version": ranked[0][1], "score": round(ranked[0][0], 4),
                "score_kind": "similarity", "match_type": "semantic"}


class MatcherLadder:
    def __init__(self, t1_threshold: float = 0.35, t3_adapter=None):
        self.t0 = T0Matcher()
        self.t1 = T1Matcher(t1_threshold)
        self.t3 = t3_adapter  # optional Baseten adapter; failure -> None (defer upstream)

    def _unknown_override(self, hit, unknown, question_text, category, intent_type):
        if hit.get("ambiguous"):
            return None
        for rv, result in unknown:
            relevant = self.t0.match(question_text, category, intent_type, [rv])
            if not relevant and hit.get("match_type") != "exact":
                relevant = self.t1.match(question_text, category, intent_type, [rv])
            if (relevant and not more_specific(hit["rule_version"], rv)
                    and canonical_json(rv["_answer"]) != canonical_json(hit["rule_version"]["_answer"])):
                return {"blocked_by_scope": True, "scope_result": result}
        return None

    def resolve(self, question_text, category, intent_type, rule_versions, context=None):
        """Match only rules whose structured intent and hard scope are eligible."""
        eligible, scope_results, unknown, rejected = [], {}, [], []
        for rv in rule_versions:
            predicate = rv["_predicate"]
            if predicate.get("category") and predicate["category"] != category:
                continue
            if predicate.get("intent_type") and predicate["intent_type"] != intent_type:
                continue
            try:
                validate_scope(rv["_scope"])
                result = evaluate_scope(rv["_scope"], context or {})
            except ValueError:
                result = {"valid": False, "result": "invalid", "details": {}}
            if not result["valid"]:
                rejected.append(result)
                if result["result"] == "unknown":
                    unknown.append((rv, result))
                continue
            eligible.append(rv)
            scope_results[rv["id"]] = result

        if not eligible:
            if rejected:
                return {"blocked_by_scope": True, "scope_result": rejected[0]}
            return None
        hit = self.t0.match(question_text, category, intent_type, eligible)
        if hit:
            blocked = self._unknown_override(hit, unknown, question_text, category, intent_type)
            if blocked:
                return blocked
            if hit.get("ambiguous"):
                return {**hit, "tier": "T0"}
            return {**hit, "tier": "T0", "scope_result": scope_results[hit["rule_version"]["id"]]}
        hit = self.t1.match(question_text, category, intent_type, eligible)
        if hit:
            blocked = self._unknown_override(hit, unknown, question_text, category, intent_type)
            if blocked:
                return blocked
            if hit.get("ambiguous"):
                return {**hit, "tier": "T1"}
            return {**hit, "tier": "T1", "scope_result": scope_results[hit["rule_version"]["id"]]}
        if self.t3 is not None:
            try:
                hit = self.t3.match(question_text, category, eligible)
            except Exception:
                hit = None
            if hit:
                blocked = self._unknown_override(hit, unknown, question_text, category, intent_type)
                if blocked:
                    return blocked
                return {**hit, "tier": "T3", "scope_result": scope_results[hit["rule_version"]["id"]]}
        return None
