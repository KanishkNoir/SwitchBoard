"""Switchboard-native demo agents (LLD 16). Agents propose; Switchboard policy decides."""
import uuid


def _qid():
    return str(uuid.uuid4())


def tradeoff_planner_question(task_id, options, category="purchase"):
    """Constrained shortlist from caller-provided data. Never fabricates prices/facts."""
    return {
        "question_id": _qid(), "agent_id": "tradeoff_planner", "task_id": task_id,
        "question": "Which option should we pick?",
        "context_summary": f"{len(options)} caller-provided options",
        "evidence": [{"source": "caller_dataset", "options": options}],
        "visual_assets": [],
        "actions": [
            {"action_id": "cheaper", "edge": "left", "label": "Cheaper", "intent": "steer",
             "parameter_delta": {"max_price_weight": 0.8}, "expected_effect": "Rank lower-cost options first",
             "requires_confirmation": False},
            {"action_id": "comfort", "edge": "right", "label": "More comfort", "intent": "steer",
             "parameter_delta": {"comfort_weight": 1.5}, "expected_effect": "Rank higher-comfort options first",
             "requires_confirmation": False},
            {"action_id": "explore", "edge": "top", "label": "Explore", "intent": "steer",
             "parameter_delta": {"novelty_weight": 1.5}, "expected_effect": "Surface less obvious options",
             "requires_confirmation": False},
            {"action_id": "simplify", "edge": "bottom", "label": "Simplify", "intent": "steer",
             "parameter_delta": {"complexity_weight": 0.5}, "expected_effect": "Prefer simplest option",
             "requires_confirmation": False},
        ],
        "deadline": None, "risk_class": "standard", "reversibility": "reversible", "downstream_refs": [],
        "_options": options,
    }


def apply_steering(payload, action_id):
    """Deterministic gesture mapping shared by swipe/click/keyboard. Never authorizes locked actions."""
    action = next((a for a in payload["actions"] if a["action_id"] == action_id), None)
    if action is None:
        raise ValueError(f"unknown action_id: {action_id}")
    if action.get("requires_confirmation"):
        return {"status": "confirmation_required", "action": action}
    weights = dict(payload.get("_weights", {}))
    for k, v in action["parameter_delta"].items():
        weights[k] = weights.get(k, 1.0) * v
    ranked = _rank(payload.get("_options", []), weights)
    return {"status": "steered", "action_id": action_id, "edge": action["edge"],
            "weights": weights, "ranked_option_ids": [o["id"] for o in ranked]}


def _rank(options, weights):
    def score(o):
        s = 0.0
        if "price" in o:
            s -= o["price"] * 0.01 * weights.get("max_price_weight", 1.0)
        s += o.get("comfort", 0) * weights.get("comfort_weight", 1.0)
        s += o.get("novelty", 0) * weights.get("novelty_weight", 1.0)
        s -= o.get("complexity", 0) * weights.get("complexity_weight", 1.0)
        return s
    return sorted(options, key=score, reverse=True)


def visual_scout_question(task_id, goal, segmented_objects=None):
    labels = ", ".join(o["label"] for o in (segmented_objects or [])) or "the scene"
    return {
        "question_id": _qid(), "agent_id": "visual_scout", "task_id": task_id,
        "question": f"What should change in {labels} for: {goal}?",
        "context_summary": goal,
        "evidence": [{"source": "sam_segmentation", "objects": segmented_objects or []}],
        "visual_assets": [],
        "actions": [
            {"action_id": "lower_cost", "edge": "left", "label": "Lower cost", "intent": "steer",
             "parameter_delta": {"budget": 0.8}, "expected_effect": "Cheaper proposal", "requires_confirmation": False},
            {"action_id": "comfort", "edge": "right", "label": "More comfort", "intent": "steer",
             "parameter_delta": {"comfort": 1.5}, "expected_effect": "Comfort-first proposal", "requires_confirmation": False},
            {"action_id": "bolder", "edge": "top", "label": "Bolder redesign", "intent": "steer",
             "parameter_delta": {"boldness": 1.5}, "expected_effect": "More ambitious proposal", "requires_confirmation": False},
            {"action_id": "keep", "edge": "bottom", "label": "Keep more as-is", "intent": "steer",
             "parameter_delta": {"change": 0.5}, "expected_effect": "Minimal-change proposal", "requires_confirmation": False},
        ],
        "deadline": None, "risk_class": "standard", "reversibility": "reversible", "downstream_refs": [],
    }


def run_visual_scout(task_id, goal, image_b64=None, phrases=None, mime="image/webp",
                     seg_adapter=None, image_prompt=None, image_adapter=None):
    """End-to-end Visual Scout: segment named objects, then ask one grounded question.

    Returns (payload, evidence_dict). Adapters fail safe: no segmentation ->
    question still asked with empty evidence, never an invented object.
    """
    objects, generated = [], None
    if image_b64 and seg_adapter is not None:
        for phrase in (phrases or []):
            out = seg_adapter.segment(image_b64, phrase, mime=mime)
            if out:
                objects.extend(out["objects"])
    if image_prompt and image_adapter is not None:
        generated = image_adapter.generate_or_edit(image_prompt)
    payload = visual_scout_question(task_id, goal, segmented_objects=objects)
    if generated:
        payload["visual_assets"].append({"generated_preview": True, "model": generated.get("model")})
    validate_decision_payload(payload)
    return payload, {"objects": objects, "generated_preview": bool(generated)}


def validate_decision_payload(payload):
    edges = {"top", "left", "right", "bottom"}
    ids = set()
    for a in payload.get("actions", []):
        if a["edge"] not in edges:
            raise ValueError(f"unknown edge: {a['edge']}")
        if not a.get("label"):
            raise ValueError("action missing label")
        if a["action_id"] in ids:
            raise ValueError("duplicate action_id")
        ids.add(a["action_id"])
    return True
