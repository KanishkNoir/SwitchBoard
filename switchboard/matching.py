from .domain import tokens


def token_cosine(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / (len(ta) ** 0.5 * len(tb) ** 0.5)


class T0Matcher:
    """Exact typed rules: category + predicate keywords/intent."""

    tier = "T0"

    def match(self, question_text, category, intent_type, rule_versions):
        for rv in rule_versions:
            pred = rv["_predicate"]
            if pred.get("category") and pred["category"] != category:
                continue
            if pred.get("intent_type") and pred["intent_type"] != intent_type:
                continue
            kws = [k.lower() for k in pred.get("keywords", [])]
            text = question_text.lower()
            if kws and not all(k in text for k in kws):
                continue
            if not kws and pred.get("exact_question") and pred["exact_question"].lower() != text.strip().lower():
                continue
            return {"rule_version": rv, "score": 1.0, "score_kind": "similarity", "match_type": "exact"}
        return None


class T1Matcher:
    """Local token-cosine encoder stand-in (no external egress). Scores are similarity, not probabilities."""

    tier = "T1"

    def __init__(self, threshold: float = 0.35):
        self.threshold = threshold

    def match(self, question_text, category, intent_type, rule_versions):
        best = None
        for rv in rule_versions:
            example = rv["_predicate"].get("example_question") or rv["_predicate"].get("exact_question") or ""
            if not example:
                continue
            score = token_cosine(question_text, example)
            if score >= self.threshold and (best is None or score > best["score"]):
                best = {"rule_version": rv, "score": round(score, 4),
                        "score_kind": "similarity", "match_type": "semantic"}
        return best


class MatcherLadder:
    def __init__(self, t1_threshold: float = 0.35, t3_adapter=None):
        self.t0 = T0Matcher()
        self.t1 = T1Matcher(t1_threshold)
        self.t3 = t3_adapter  # optional Baseten adapter; failure -> None (defer upstream)

    def resolve(self, question_text, category, intent_type, rule_versions):
        hit = self.t0.match(question_text, category, intent_type, rule_versions)
        if hit:
            return {**hit, "tier": "T0"}
        hit = self.t1.match(question_text, category, intent_type, rule_versions)
        if hit:
            return {**hit, "tier": "T1"}
        if self.t3 is not None:
            try:
                hit = self.t3.match(question_text, category, rule_versions)
            except Exception:
                hit = None
            if hit:
                return {**hit, "tier": "T3"}
        return None
