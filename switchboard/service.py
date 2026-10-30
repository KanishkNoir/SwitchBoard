import hashlib
import json
import secrets
from datetime import datetime, timezone

from .config import settings as default_settings
from .domain import QuestionRequest, canonical_json, classify_risk, evaluate_scope, normalize_text, sha256_hex
from .matching import MatcherLadder
from .persistence import Store, new_id, now_iso

EVIDENCE_ELIGIBLE = {"human_confirmed": True, "human_corrected": True,
                     "tool_verified": False, "agent_asserted": False,
                     "model_inferred": False, "synthetic": False}


class SwitchboardError(Exception):
    def __init__(self, code, message=""):
        super().__init__(message or code)
        self.code = code


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class SwitchboardService:
    def __init__(self, store: Store, cfg=None, ladder: MatcherLadder | None = None):
        self.store = store
        self.cfg = cfg or default_settings
        if ladder is None:
            t3 = None
            if getattr(self.cfg, "enable_t3", False):
                from .adapters import reasoning_adapter
                t3 = reasoning_adapter(self.cfg)
            ladder = MatcherLadder(self.cfg.t1_threshold, t3_adapter=t3)
        self.ladder = ladder

    # ---------- agents / auth ----------
    def register_agent(self, name, kind="cli", scopes=None):
        key = "sb_" + secrets.token_urlsafe(24)
        aid = new_id()
        self.store.execute(
            "INSERT INTO agents(id,name,kind,key_hash,scopes_json,enabled,created_at) VALUES(?,?,?,?,?,1,?)",
            (aid, name, kind, _hash_key(key), json.dumps(scopes or ["ask", "get_rules", "report_outcome"]), now_iso()))
        self.store.emit("human", "local_user", "agent.registered", "agent", aid, {"name": name})
        return {"agent_id": aid, "api_key": key}  # key shown once at registration

    def authenticate(self, api_key: str):
        if not api_key:
            raise SwitchboardError("UNAUTHENTICATED")
        row = self.store.query_one("SELECT * FROM agents WHERE key_hash=? AND enabled=1", (_hash_key(api_key),))
        if not row:
            raise SwitchboardError("UNAUTHENTICATED")
        return row

    def list_agents(self):
        return self.store.query(
            "SELECT id,name,kind,scopes_json,enabled,created_at FROM agents ORDER BY created_at")

    def list_rules_human(self, category=None):
        sql = ("SELECT r.id as rule_id, r.category, r.status, rv.id as version_id, rv.version_number,"
               " rv.predicate_json, rv.answer_json, rv.scope_json, rv.source_type,"
               " rv.confirmed_by_human, rv.created_at FROM rules r"
               " JOIN rule_versions rv ON rv.id=r.active_version_id")
        params = ()
        if category:
            sql += " WHERE r.category=?"
            params = (category,)
        return self.store.query(sql + " ORDER BY r.created_at", params)

    def rule_versions(self, rule_id):
        if not self.store.query_one("SELECT id FROM rules WHERE id=?", (rule_id,)):
            raise SwitchboardError("NOT_FOUND", "rule")
        return self.store.query(
            "SELECT id,version_number,predicate_json,answer_json,scope_json,source_type,"
            "confirmed_by_human,valid_from,valid_until,supersedes_version_id,created_at"
            " FROM rule_versions WHERE rule_id=? ORDER BY version_number", (rule_id,))

    def revalidate_decision(self, decision_id, agent=None):
        dec = self.store.query_one("SELECT * FROM decisions WHERE id=?", (decision_id,))
        if not dec:
            raise SwitchboardError("NOT_FOUND", "decision")
        q = self.store.query_one("SELECT * FROM questions WHERE id=?", (dec["question_id"],))
        agent_row = agent or self.store.query_one("SELECT * FROM agents WHERE id=?", (q["agent_id"],))
        req = QuestionRequest(
            request_id=f"reval-{decision_id[:8]}-{new_id()[:8]}", question=q["question_text"],
            category=q["category"], intent_type=q["intent_type"], reversibility=q["reversibility"],
            deadline_at=q["deadline_at"], options=json.loads(q["options_json"] or "[]"),
            context=json.loads(q["context_json"] or "{}"))
        self.store.emit("human", "local_user", "decision.revalidation_queued", "decision", decision_id, {})
        resp = self.ask(agent_row, req)
        self.store.emit("system", "switchboard", "decision.revalidated", "decision", decision_id,
                        {"new_decision": resp.get("decision_id")})
        return resp

    # ---------- category settings ----------
    def category(self, category: str) -> dict:
        row = self.store.query_one("SELECT * FROM category_settings WHERE category=?", (category,))
        if not row:
            locked = 1 if category in self.cfg.locked_categories else 0
            self.store.execute(
                "INSERT INTO category_settings(category,stage,risk_target,locked,policy_version,"
                "min_evidence_state,active_preference_epoch,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (category, "shadow", 0.02, locked, self.cfg.policy_version, "ok", "epoch-1", now_iso()))
            row = self.store.query_one("SELECT * FROM category_settings WHERE category=?", (category,))
        return row

    def set_stage(self, category, stage, reason="manual"):
        if stage not in ("shadow", "suggest", "warn", "auto"):
            raise SwitchboardError("INVALID_SCHEMA", "bad stage")
        self.category(category)
        self.store.execute("UPDATE category_settings SET stage=?,updated_at=? WHERE category=?",
                           (stage, now_iso(), category))
        ev = "category.promoted" if stage == "auto" else "category.demoted" if stage == "shadow" else "category.promoted"
        self.store.emit("human", "local_user", ev, "category", category, {"stage": stage, "reason": reason})
        return self.category(category)

    # ---------- rules ----------
    def create_rule(self, category, predicate, answer, scope=None, source_type="explicit_edit",
                    confirmed_by_human=True, actor="local_user"):
        rid = new_id()
        vid = new_id()
        ts = now_iso()
        self.store.execute("INSERT INTO rules(id,category,created_at,created_by,active_version_id,status)"
                           " VALUES(?,?,?,?,?,'active')", (rid, category, ts, actor, vid))
        self.store.execute(
            "INSERT INTO rule_versions(id,rule_id,version_number,predicate_json,answer_json,scope_json,"
            "source_type,evidence_ids_json,confirmed_by_human,valid_from,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (vid, rid, 1, json.dumps(predicate), json.dumps(answer), json.dumps(scope or {}),
             source_type, "[]", 1 if confirmed_by_human else 0, ts, ts))
        self.category(category)
        self.store.emit("human", actor, "rule.confirmed" if confirmed_by_human else "rule.proposed",
                        "rule", rid, {"version_id": vid, "category": category})
        return {"rule_id": rid, "version_id": vid, "version_number": 1}

    def supersede_rule(self, rule_id, new_answer=None, new_scope=None, new_predicate=None, actor="local_user"):
        rule = self.store.query_one("SELECT * FROM rules WHERE id=?", (rule_id,))
        if not rule:
            raise SwitchboardError("NOT_FOUND", "rule")
        old = self.store.query_one("SELECT * FROM rule_versions WHERE id=?", (rule["active_version_id"],))
        vid = new_id()
        ts = now_iso()
        num = (old["version_number"] + 1) if old else 1
        self.store.execute(
            "INSERT INTO rule_versions(id,rule_id,version_number,predicate_json,answer_json,scope_json,"
            "source_type,evidence_ids_json,confirmed_by_human,valid_from,supersedes_version_id,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,1,?,?,?)",
            (vid, rule_id, num,
             json.dumps(new_predicate if new_predicate is not None else json.loads(old["predicate_json"])),
             json.dumps(new_answer if new_answer is not None else json.loads(old["answer_json"])),
             json.dumps(new_scope if new_scope is not None else json.loads(old["scope_json"])),
             "explicit_edit", "[]", ts, old["id"] if old else None, ts))
        if old:
            self.store.execute("UPDATE rule_versions SET valid_until=? WHERE id=?", (ts, old["id"]))
        self.store.execute("UPDATE rules SET active_version_id=? WHERE id=?", (vid, rule_id))
        # Preference epoch bump + V1 sliced recalibration hold (research 2026-10):
        # hold ONLY the flipped rule's slice, never the whole category.
        cat = self.category(rule["category"])
        epoch_num = int(cat["active_preference_epoch"].split("-")[-1]) + 1
        self.store.execute(
            "UPDATE category_settings SET active_preference_epoch=?, updated_at=? WHERE category=?",
            (f"epoch-{epoch_num}", ts, rule["category"]))
        scope_for_hold = new_scope if new_scope is not None else json.loads(old["scope_json"])
        fingerprint = sha256_hex(canonical_json(scope_for_hold.get("mandatory", {})))
        pred_for_hold = new_predicate if new_predicate is not None else json.loads(old["predicate_json"])
        # T0 (keyword/exact, human-supplied flip) needs 1 more distinct context; semantic needs 3.
        required_m = 1 if (pred_for_hold.get("keywords") or pred_for_hold.get("exact_question")) else 3
        self.store.execute(
            "INSERT INTO recalibration_holds(id,category,rule_id,new_version_id,scope_fingerprint,"
            "preference_epoch,required_m,fresh_count,seen_contexts_json,status,created_at)"
            " VALUES(?,?,?,?,?,?,?,0,'[]','held',?)",
            (new_id(), rule["category"], rule_id, vid, fingerprint, f"epoch-{epoch_num}", required_m, ts))
        self.store.emit("human", actor, "rule.superseded", "rule", rule_id,
                        {"old_version": old["id"] if old else None, "new_version": vid,
                         "preference_epoch": f"epoch-{epoch_num}"})
        blast = self.blast_radius(rule_id)
        return {"rule_id": rule_id, "version_id": vid, "version_number": num, "blast_radius": blast}

    # ---------- V1 sliced recalibration holds ----------
    def held_rule_ids(self, category):
        rows = self.store.query(
            "SELECT rule_id FROM recalibration_holds WHERE category=? AND status='held'", (category,))
        return {r["rule_id"] for r in rows}

    def list_holds(self, category=None):
        if category:
            return self.store.query("SELECT * FROM recalibration_holds WHERE category=? ORDER BY created_at",
                                    (category,))
        return self.store.query("SELECT * FROM recalibration_holds ORDER BY created_at")

    def clear_holds(self, category, actor="local_user"):
        """Human (or B1-style immediate resume) clears all held slices in a category."""
        self.store.execute(
            "UPDATE recalibration_holds SET status='released', released_at=? WHERE category=? AND status='held'",
            (now_iso(), category))
        self.store.emit("human", actor, "calibration.epoch_started", "category", category,
                        {"action": "holds_cleared_manually"})
        return {"category": category, "cleared": True}

    def _record_fresh_evidence(self, category, context: dict, source: str):
        """Count one distinct human-confirmed context toward held slices in this category.

        Only called from human evidence paths. Agent/model labels never reach here (B3).
        Duplicated contexts do not farm m.
        """
        holds = self.store.query(
            "SELECT * FROM recalibration_holds WHERE category=? AND status='held'", (category,))
        if not holds:
            return
        ctx_hash = sha256_hex(canonical_json(context or {}))
        for hold in holds:
            seen = json.loads(hold["seen_contexts_json"])
            if ctx_hash in seen:
                continue
            seen.append(ctx_hash)
            fresh = hold["fresh_count"] + 1
            if fresh >= hold["required_m"]:
                self.store.execute(
                    "UPDATE recalibration_holds SET fresh_count=?, seen_contexts_json=?, status='released',"
                    " released_at=? WHERE id=?", (fresh, json.dumps(seen), now_iso(), hold["id"]))
                self.store.emit("system", "switchboard", "calibration.epoch_started", "rule", hold["rule_id"],
                                {"action": "hold_released", "fresh_distinct": fresh, "source": source})
            else:
                self.store.execute(
                    "UPDATE recalibration_holds SET fresh_count=?, seen_contexts_json=? WHERE id=?",
                    (fresh, json.dumps(seen), hold["id"]))

    def active_rule_versions(self, category):
        rows = self.store.query(
            "SELECT rv.* FROM rule_versions rv JOIN rules r ON r.id=rv.rule_id"
            " WHERE r.category=? AND r.active_version_id=rv.id AND rv.confirmed_by_human=1", (category,))
        for r in rows:
            r["_predicate"] = json.loads(r["predicate_json"])
            r["_answer"] = json.loads(r["answer_json"])
            r["_scope"] = json.loads(r["scope_json"])
        return rows

    def get_rules(self, agent, category=None):
        scopes = json.loads(agent["scopes_json"])
        if "get_rules" not in scopes:
            raise SwitchboardError("FORBIDDEN_SCOPE")
        sql = ("SELECT r.id as rule_id, r.category, rv.id as version_id, rv.version_number,"
               " rv.predicate_json, rv.answer_json, rv.scope_json FROM rules r"
               " JOIN rule_versions rv ON rv.id=r.active_version_id")
        params = ()
        if category:
            sql += " WHERE r.category=?"
            params = (category,)
        return self.store.query(sql, params)

    # ---------- ask ----------
    def ask(self, agent, req: QuestionRequest) -> dict:
        if not req.request_id or not req.question or not req.category:
            raise SwitchboardError("INVALID_SCHEMA", "request_id, question, category required")
        if len(req.question) > 4000:
            raise SwitchboardError("INVALID_SCHEMA", "question too long")
        chash = req.canonical_hash()
        prior_q = self.store.query_one(
            "SELECT * FROM questions WHERE agent_id=? AND request_id=?", (agent["id"], req.request_id))
        if prior_q:
            if prior_q["canonical_hash"] != chash:
                raise SwitchboardError("IDEMPOTENCY_CONFLICT")
            dec = self.store.query_one("SELECT * FROM decisions WHERE question_id=? ORDER BY created_at DESC",
                                       (prior_q["id"],))
            rec = self.store.query_one("SELECT * FROM receipts WHERE decision_id=?", (dec["id"],))
            return self._response(dec, rec, prior_q)
        cat = self.category(req.category)
        risk = classify_risk(req, self.cfg)
        qid = new_id()
        self.store.execute(
            "INSERT INTO questions(id,request_id,agent_id,canonical_hash,question_text,category,intent_type,"
            "risk_class,reversibility,deadline_at,options_json,context_json,status,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (qid, req.request_id, agent["id"], chash, normalize_text(req.question), req.category,
             req.intent_type, risk["risk_class"], req.reversibility, req.deadline_at,
             json.dumps(req.options), json.dumps(req.context), "received", now_iso()))
        self.store.emit("agent", agent["id"], "question.received", "question", qid,
                        {"category": req.category}, correlation_id=req.request_id)
        if risk["is_locked"] or cat["locked"]:
            return self._persist_decision(qid, req, cat, mode="deferred", reason="locked",
                                          tier="none", candidate=None, human=True)
        self._register_attention(qid, req, risk)
        # Candidate matching with hard scope validation before any stage decision.
        versions = self.active_rule_versions(req.category)
        candidate = self.ladder.resolve(normalize_text(req.question), req.category, req.intent_type, versions)
        scope_result = None
        if candidate:
            scope_result = evaluate_scope(candidate["rule_version"]["_scope"], req.context or {})
            if not scope_result["valid"]:
                self.store.emit("system", "switchboard", "decision.deferred", "question", qid,
                                {"reason": "out_of_scope", "scope": scope_result})
                candidate = None
        if cat["min_evidence_state"] == "quarantined":
            return self._persist_decision(qid, req, cat, "deferred", "feedback_integrity_hold", "none", None, True)
        stage = cat["stage"]
        # V1: only the flipped rule's slice is held; other slices proceed (B1 speed).
        if candidate and candidate["rule_version"]["rule_id"] in self.held_rule_ids(req.category):
            return self._persist_decision(qid, req, cat, "deferred", "recalibration_pending",
                                          candidate["tier"] if candidate else "none", candidate, True, scope_result)
        if self._away_grant_active(req.category, req.intent_type) and candidate:
            stage = "auto"  # scoped grant upgrades suggest, never overrides locks/shadow logging below
        if stage == "shadow":
            return self._persist_decision(qid, req, cat, "shadow", "shadow",
                                          candidate["tier"] if candidate else "none", candidate, True, scope_result)
        if stage == "suggest":
            return self._persist_decision(qid, req, cat, "suggested", "suggest",
                                          candidate["tier"] if candidate else "none", candidate, True, scope_result)
        if stage == "warn" and candidate:
            # V2 warning stage: answer is given, but flagged and the human is
            # notified with a veto — graduation step between suggest and auto.
            return self._persist_decision(qid, req, cat, "warn", "warn_stage",
                                          candidate["tier"], candidate, False, scope_result)
        if stage == "auto" and candidate:
            return self._persist_decision(qid, req, cat, "auto", "matched_rule", candidate["tier"],
                                          candidate, False, scope_result)
        return self._persist_decision(qid, req, cat, "deferred", "below_policy",
                                      candidate["tier"] if candidate else "none", candidate, True, scope_result)

    def _persist_decision(self, qid, req, cat, mode, reason, tier, candidate, human, scope_result=None):
        # Atomicity guard: re-check the candidate version is still active at persistence time.
        if candidate:
            active = self.store.query_one("SELECT active_version_id FROM rules WHERE id=?",
                                          (candidate["rule_version"]["rule_id"],))
            if not active or active["active_version_id"] != candidate["rule_version"]["id"]:
                mode, reason, candidate = "deferred", "stale_rule_version", None
        did = new_id()
        answer = candidate["rule_version"]["_answer"] if (candidate and mode in ("auto", "warn")) else None
        self.store.execute(
            "INSERT INTO decisions(id,question_id,mode,answer_json,reason_code,matcher_tier,score,score_kind,"
            "category_stage,policy_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (did, qid, mode, json.dumps(answer) if answer else None, reason, tier,
             candidate["score"] if candidate else None, candidate["score_kind"] if candidate else None,
             cat["stage"], self.cfg.policy_version, now_iso()))
        if candidate:
            self.store.execute(
                "INSERT OR IGNORE INTO decision_rule_uses(decision_id,rule_version_id,match_type,scope_result_json)"
                " VALUES(?,?,?,?)", (did, candidate["rule_version"]["id"], candidate["match_type"],
                                     json.dumps(scope_result or {"result": "pass"})))
        if mode == "warn":
            # The answer stands unless vetoed: surface it as a notice, not a question.
            self.store.execute(
                "UPDATE attention_items SET status='notified',updated_at=? WHERE question_id=? AND status='queued'",
                (now_iso(), qid))
        rid = new_id()
        receipt_type = "answer" if mode in ("auto", "warn") else "defer"
        self.store.execute(
            "INSERT INTO receipts(id,decision_id,receipt_type,why_text,evidence_ids_json,issued_at)"
            " VALUES(?,?,?,?,?,?)", (rid, did, receipt_type, reason, "[]", now_iso()))
        event = {"auto": "decision.auto_answered", "shadow": "decision.shadow_logged",
                 "suggested": "decision.suggested", "warn": "decision.warn_answered"}.get(mode, "decision.deferred")
        self.store.emit("system", "switchboard", event, "decision", did, {"reason": reason, "tier": tier})
        if mode == "auto":
            gate = self.risk_estimate(cat["category"])
            if gate["would_block"]:
                # Shadow gate: flag loudly, block nothing (research verdict).
                self.store.emit("system", "switchboard", "decision.risk_gate_shadow_block",
                                "decision", did, gate)
        dec = self.store.query_one("SELECT * FROM decisions WHERE id=?", (did,))
        rec = self.store.query_one("SELECT * FROM receipts WHERE id=?", (rid,))
        q = self.store.query_one("SELECT * FROM questions WHERE id=?", (qid,))
        return self._response(dec, rec, q)

    def _response(self, dec, rec, q):
        uses = self.store.query("SELECT rule_version_id FROM decision_rule_uses WHERE decision_id=?", (dec["id"],))
        decision = {"auto": "answer", "warn": "answer"}.get(dec["mode"], "defer")
        resp = {
            "decision": decision,
            "answer": json.loads(dec["answer_json"]) if dec["answer_json"] else None,
            "reason_code": dec["reason_code"],
            "receipt_id": rec["id"] if rec else None,
            "question_id": q["id"],
            "decision_id": dec["id"],
            "rule_versions": [u["rule_version_id"] for u in uses],
            "matcher_tier": dec["matcher_tier"],
            "score": dec["score"],
            "score_kind": dec["score_kind"],
            "stage": dec["category_stage"],
            "requires_human": dec["mode"] not in ("auto", "warn"),
            "warning": ("warn_stage: answered under the warning stage; the human has been "
                        "notified and can veto" if dec["mode"] == "warn" else None),
            "risk_gate": (self.risk_estimate(q["category"])
                          if dec["mode"] in ("auto", "warn") else None),
            "explanation": f"{dec['reason_code']} via {dec['matcher_tier']}",
        }
        return resp

    def inbox_detail(self, item_id):
        """Provenance for one inbox item: why it is here and what stands behind it."""
        item = self.store.query_one("SELECT * FROM attention_items WHERE id=?", (item_id,))
        if not item:
            raise SwitchboardError("NOT_FOUND", "attention item")
        q = self.store.query_one("SELECT * FROM questions WHERE id=?", (item["question_id"],))
        agent = self.store.query_one("SELECT id,name,kind FROM agents WHERE id=?", (q["agent_id"],))
        decisions = self.store.query(
            "SELECT d.*, (SELECT GROUP_CONCAT(dru.rule_version_id) FROM decision_rule_uses dru"
            " WHERE dru.decision_id=d.id) AS rule_version_ids FROM decisions d"
            " WHERE d.question_id=? ORDER BY d.created_at DESC LIMIT 5", (q["id"],))
        receipts = self.store.query(
            "SELECT r.* FROM receipts r JOIN decisions d ON d.id=r.decision_id"
            " WHERE d.question_id=? ORDER BY r.issued_at DESC LIMIT 5", (q["id"],))
        events = self.store.query(
            "SELECT event_type, actor_type, occurred_at FROM events"
            " WHERE object_type='question' AND object_id=? ORDER BY occurred_at DESC LIMIT 10",
            (q["id"],))
        return {"item": item, "question": q, "agent": agent,
                "eligibility": self.swipe_eligibility(q, item),
                "decisions": decisions, "receipts": receipts, "events": events}

    _DEBRIEF_REASONS = {
        "locked": "Locked class — only you can answer this.",
        "quarantine": "A rule tried to answer outside its scope, so it was paused and the question came to you.",
        "recalibration_pending": "This category is recalibrating after a correction, so the rule is paused.",
        "shadow": "Shadow stage: the rule would have answered, but this category only watches for now.",
        "suggest": "Suggest stage: Switchboard proposed an answer and waited for your tap.",
        "warn_stage": "Warning stage: Switchboard answered and left you a veto.",
        "rule_match": "A standing rule inside its scope answered this.",
        "governor_budget": "The attention budget for this batch was reached, so this waited.",
        "semantic_ambiguous": "The matching rule's evidence was ambiguous, so it asked instead of guessing.",
        "no_match": "No standing rule covered this, so it asked you.",
    }

    def debrief(self, limit: int = 30) -> list:
        """Recent decisions in priority order, each with its reason in plain words."""
        rows = self.store.query(
            "SELECT d.*, q.question_text, q.category, q.agent_id,"
            " (SELECT r.id FROM receipts r WHERE r.decision_id=d.id ORDER BY r.issued_at DESC LIMIT 1) AS receipt_id,"
            " (SELECT e.payload_json FROM events e WHERE e.object_type='question' AND e.object_id=d.question_id"
            "  AND e.event_type='attention.item_resolved' ORDER BY e.occurred_at DESC LIMIT 1) AS resolved_json"
            " FROM decisions d JOIN questions q ON q.id=d.question_id"
            " ORDER BY d.created_at DESC, d.rowid DESC LIMIT ?", (limit,))
        out = []
        for d in rows:
            answer = json.loads(d["answer_json"] or "null")
            origin = None
            dwell = None
            if d["resolved_json"]:
                try:
                    payload = json.loads(d["resolved_json"])
                    origin, dwell = payload.get("origin"), payload.get("dwell_ms")
                except ValueError:
                    pass
            value = answer.get("value") if isinstance(answer, dict) else answer
            if d["mode"] == "human":
                bucket = "denied_by_you" if str(value).lower() in ("deny", "denied", "no") else "answered_by_you"
            elif d["mode"] in ("auto", "warn"):
                bucket = "auto_answered"
            elif d["mode"] == "suggested":
                bucket = "answered_by_you"
            else:
                bucket = "still_waiting"
            out.append({
                "decision_id": d["id"], "question_text": d["question_text"],
                "category": d["category"], "mode": d["mode"], "bucket": bucket,
                "answer": answer, "reason_code": d["reason_code"],
                "reason_plain": self._DEBRIEF_REASONS.get(
                    d["reason_code"], f"Decided by {d['reason_code']} (see ledger event)."),
                "receipt_id": d["receipt_id"], "origin": origin, "dwell_ms": dwell,
                "stage": d["category_stage"], "created_at": d["created_at"],
            })
        return out

    # ---------- first-run onboarding (§6.1) ----------
    def onboarding_state(self) -> dict:
        done = self.store.query_one(
            "SELECT id FROM events WHERE event_type='onboarding.completed' LIMIT 1")
        cats = self.store.query(
            "SELECT category, stage, locked, risk_target FROM category_settings ORDER BY category")
        return {"completed": bool(done),
                "locked_categories": list(self.cfg.locked_categories),
                "categories": cats,
                "t3_enabled": self.ladder.t3 is not None}

    def complete_onboarding(self, model_calls: bool = False, risk_choice: str = "balanced",
                            actor="local_user") -> dict:
        targets = {"careful": 0.01, "balanced": 0.02, "relaxed": 0.05}
        if risk_choice not in targets:
            raise SwitchboardError("INVALID_SCHEMA", "risk_choice must be careful|balanced|relaxed")
        for cat in self.store.query("SELECT category FROM category_settings"):
            self.store.execute(
                "UPDATE category_settings SET risk_target=?, updated_at=? WHERE category=?",
                (targets[risk_choice], now_iso(), cat["category"]))
        self.store.emit("human", actor, "onboarding.completed", "system", "onboarding",
                        {"model_calls": bool(model_calls), "risk_choice": risk_choice,
                         "risk_target": targets[risk_choice]},
                        evidence_class="human_confirmed")
        return self.onboarding_state()

    # ---------- V2 warning-stage notices ----------
    def notices(self):
        return self.store.query(
            "SELECT ai.*, q.question_text, q.category, q.agent_id,"
            " (SELECT d.id FROM decisions d WHERE d.question_id=q.id ORDER BY d.created_at DESC LIMIT 1) AS decision_id,"
            " (SELECT d.answer_json FROM decisions d WHERE d.question_id=q.id ORDER BY d.created_at DESC LIMIT 1) AS answer_json"
            " FROM attention_items ai JOIN questions q ON q.id=ai.question_id"
            " WHERE ai.status='notified' ORDER BY ai.created_at DESC")

    def dismiss_notice(self, item_id, actor="local_user"):
        """Accept a warn-stage answer silently: clear the notice, record nothing."""
        item = self.store.query_one("SELECT * FROM attention_items WHERE id=? AND status='notified'",
                                    (item_id,))
        if not item:
            raise SwitchboardError("NOT_FOUND", "notice")
        self.store.execute("UPDATE attention_items SET status='resolved',updated_at=? WHERE id=?",
                           (now_iso(), item_id))
        self.store.emit("human", actor, "attention.notice_accepted", "question", item["question_id"], {})
        return {"item_id": item_id, "dismissed": True}

    def veto_notice(self, item_id, actor="local_user"):
        """Veto a warn-stage answer: clear the notice and record a human negative."""
        item = self.store.query_one("SELECT * FROM attention_items WHERE id=? AND status='notified'",
                                    (item_id,))
        if not item:
            raise SwitchboardError("NOT_FOUND", "notice")
        self.store.execute("UPDATE attention_items SET status='resolved',updated_at=? WHERE id=?",
                           (now_iso(), item_id))
        dec = self.store.query_one(
            "SELECT id FROM decisions WHERE question_id=? ORDER BY created_at DESC LIMIT 1",
            (item["question_id"],))
        if dec:
            self.confirm_feedback(dec["id"], "incorrect", actor=actor)
        self.store.emit("human", actor, "attention.notice_vetoed", "question", item["question_id"],
                        {"decision_id": dec["id"] if dec else None}, evidence_class="human_confirmed")
        return {"item_id": item_id, "vetoed": True,
                "decision_id": dec["id"] if dec else None}

    # ---------- attention ----------
    def _register_attention(self, qid, req, risk):
        # Merge only on strict compatibility: same category, same option IDs, same normalized decision key.
        opt_ids = sorted(o.get("id", "") for o in req.options)
        decision_key = sha256_hex(f"{req.category}|{','.join(opt_ids)}|"
                                  f"{' '.join(sorted(__import__('switchboard.domain', fromlist=['tokens']).tokens(req.question)))}")
        batch_id = None
        existing = self.store.query_one(
            "SELECT * FROM attention_batches WHERE decision_key=? AND status='open'", (decision_key,))
        if existing and opt_ids:
            batch_id = existing["id"]
        elif opt_ids:
            batch_id = new_id()
            self.store.execute(
                "INSERT INTO attention_batches(id,decision_key,status,created_at,merge_reason,compatibility_json)"
                " VALUES(?,?, 'open',?,?,?)", (batch_id, decision_key, now_iso(),
                                               "same_category_options_decision_key", json.dumps({"options": opt_ids})))
            self.store.emit("system", "switchboard", "attention.items_clustered", "batch", batch_id, {})
        priority = 50.0
        if req.deadline_at:
            priority += 30.0
        if risk["risk_class"] == "locked":
            priority = 100.0
        self.store.execute(
            "INSERT INTO attention_items(id,question_id,priority_score,urgency_class,deadline_at,status,batch_id,"
            "created_at,updated_at) VALUES(?,?,?,?,?,'queued',?,?,?)",
            (new_id(), qid, priority, "critical" if priority >= 80 else "normal",
             req.deadline_at, batch_id, now_iso(), now_iso()))
        return batch_id

    def swipe_eligibility(self, q, item=None) -> dict:
        """Server-computed from stored question data — never from client claims.

        A swipe is a shortcut, not an authorization: only verified reversible,
        low-consequence, single, non-batched questions may be swiped at all.
        Unknown reversibility fails closed.
        """
        cat = self.category(q["category"])
        reasons = []
        if cat["locked"] or q["risk_class"] == "locked":
            reasons.append("locked")
        if q["reversibility"] != "reversible":
            reasons.append(f"reversibility_{q['reversibility']}")
        if q["intent_type"] == "action_review":
            reasons.append("action_review")
        if item is not None and item.get("batch_id"):
            reasons.append("batched")
        options = json.loads(q["options_json"] or "[]")
        if options:
            reasons.append("has_options")
        return {"swipe_eligible": not reasons, "is_locked": bool(cat["locked"] or q["risk_class"] == "locked"),
                "requires_confirmation": bool(reasons), "eligibility_reasons": reasons}

    def inbox(self):
        rows = self.store.query(
            "SELECT ai.*, q.question_text, q.category, q.agent_id, q.options_json,"
            " q.reversibility, q.intent_type, q.risk_class, a.name AS agent_name"
            " FROM attention_items ai JOIN questions q ON q.id=ai.question_id"
            " LEFT JOIN agents a ON a.id=q.agent_id WHERE ai.status='queued'"
            " ORDER BY ai.priority_score DESC, ai.created_at ASC")
        for r in rows:
            q = self.store.query_one("SELECT * FROM questions WHERE id=?", (r["question_id"],))
            r.update(self.swipe_eligibility(q, r))
        return rows

    # Rubber-stamp signals are advisory only: they never block an answer.
    _APPROVAL_VALUES = {"allow", "yes", "approve", "approved", "true", "ok"}

    def _is_approval(self, answer_obj) -> bool:
        if isinstance(answer_obj, dict):
            if answer_obj.get("allow") is True or answer_obj.get("approved") is True:
                return True
            val = answer_obj.get("value", answer_obj.get("decision", ""))
        else:
            val = answer_obj
        return str(val).strip().lower() in self._APPROVAL_VALUES

    def attention_health(self, window: int = 50) -> dict:
        """Detect rubber-stamping: approving everything, in bursts, without reading.

        Signals over the most recent human answers: approval share, longest
        approval streak, fastest 10-minute burst, and median dwell time the
        question was on screen (reported by the UI; None when unmeasured).
        Advisory only — high risk suggests a nudge, never a block.
        """
        rows = self.store.query(
            "SELECT d.answer_json, d.created_at FROM decisions d WHERE d.mode='human'"
            " ORDER BY d.created_at DESC LIMIT ?", (window,))
        total = len(rows)
        if total == 0:
            return {"total_answers": 0, "approval_share": None, "approval_streak": 0,
                    "burst_per_10min": 0, "median_dwell_ms": None, "risk": "unknown",
                    "signals": []}
        approvals = [self._is_approval(json.loads(r["answer_json"] or "{}")) for r in rows]
        streak = best = 0
        for a in approvals:
            streak = streak + 1 if a else 0
            best = max(best, streak)
        times = sorted(r["created_at"] for r in rows)
        burst = 1
        left = 0
        from datetime import datetime, timedelta
        parsed = [datetime.fromisoformat(t) for t in times]
        for i, t in enumerate(parsed):
            while t - parsed[left] > timedelta(minutes=10):
                left += 1
            burst = max(burst, i - left + 1)
        dwell_rows = self.store.query(
            "SELECT payload_json FROM events WHERE event_type='attention.item_resolved'"
            " ORDER BY occurred_at DESC LIMIT ?", (window,))
        dwells = []
        for r in dwell_rows:
            try:
                d = json.loads(r["payload_json"] or "{}").get("dwell_ms")
            except (ValueError, AttributeError):
                d = None
            if isinstance(d, (int, float)) and d >= 0:
                dwells.append(d)
        dwells.sort()
        median_dwell = dwells[len(dwells) // 2] if dwells else None
        share = sum(approvals) / total
        signals = []
        if total >= 10 and share >= 0.9:
            signals.append(f"approval_share {share:.0%} over last {total} answers")
        if best >= 8:
            signals.append(f"{best} approvals in a row")
        if burst >= 8:
            signals.append(f"{burst} answers within 10 minutes")
        if median_dwell is not None and median_dwell < 3000 and total >= 10:
            signals.append(f"median on-screen time {int(median_dwell)}ms before answering")
        risk = "elevated" if len(signals) >= 2 else ("watch" if signals else "ok")
        return {"total_answers": total, "approval_share": round(share, 3),
                "approval_streak": best, "burst_per_10min": burst,
                "median_dwell_ms": median_dwell, "risk": risk, "signals": signals}

    def answer_inbox(self, item_id, answer, actor="local_user", save_rule=None, dwell_ms=None,
                     origin="tap"):
        item = self.store.query_one("SELECT * FROM attention_items WHERE id=?", (item_id,))
        if not item:
            raise SwitchboardError("NOT_FOUND", "attention item")
        if item["status"] != "queued":
            raise SwitchboardError("CONFLICT", "attention item already resolved")
        q = self.store.query_one("SELECT * FROM questions WHERE id=?", (item["question_id"],))
        # --- origin gate: a swipe is a shortcut, never an authorization ---
        if origin not in ("tap", "swipe", "rule_sheet"):
            raise SwitchboardError("INVALID_SCHEMA", "bad answer origin")
        elig = self.swipe_eligibility(q, item)
        if origin == "swipe" and not elig["swipe_eligible"]:
            raise SwitchboardError(
                "CONFIRMATION_REQUIRED",
                f"swipe not allowed here ({', '.join(elig['eligibility_reasons'])}); deliberate tap required")
        if save_rule:
            if origin != "rule_sheet":
                raise SwitchboardError(
                    "CONFIRMATION_REQUIRED", "rules are created from the rule sheet, not a quick answer")
            if elig["is_locked"]:
                raise SwitchboardError("RULE_NOT_ALLOWED_LOCKED",
                                       "locked categories cannot get standing rules")
            scope = save_rule.get("scope") or {}
            if not (scope.get("mandatory") or {}):
                raise SwitchboardError(
                    "RULE_SCOPE_REQUIRED", "a standing rule needs a non-empty scope; broad rules are not created silently")
        self.store.execute("UPDATE attention_items SET status='resolved',updated_at=? WHERE id=?",
                           (now_iso(), item_id))
        if item["batch_id"]:
            self.store.execute(
                "UPDATE attention_items SET status='resolved',updated_at=? WHERE batch_id=? AND status='queued'",
                (now_iso(), item["batch_id"]))
        ev = self.add_evidence("human_confirmed", "human", actor, payload_excerpt=str(answer)[:200])
        # Record a human decision + receipt so the answer is traceable and reusable.
        cat = self.category(q["category"])
        did = new_id()
        answer_obj = answer if isinstance(answer, dict) else {"value": str(answer)}
        self.store.execute(
            "INSERT INTO decisions(id,question_id,mode,answer_json,reason_code,matcher_tier,score,score_kind,"
            "category_stage,policy_version,created_at) VALUES(?,?, 'human',?,'human_answered','none',NULL,NULL,?,?,?)",
            (did, q["id"], json.dumps(answer_obj), cat["stage"], self.cfg.policy_version, now_iso()))
        rid = new_id()
        self.store.execute(
            "INSERT INTO receipts(id,decision_id,receipt_type,why_text,evidence_ids_json,issued_at)"
            " VALUES(?,?,'answer','human_answered',?,?)", (rid, did, json.dumps([ev]), now_iso()))
        self.store.emit("human", actor, "attention.item_resolved", "question", item["question_id"],
                        {"answer": answer_obj, "decision_id": did, "dwell_ms": dwell_ms,
                         "origin": origin},
                        evidence_class="human_confirmed")
        self._record_fresh_evidence(q["category"], json.loads(q["context_json"] or "{}"), "answer_inbox")
        result = {"item_id": item_id, "evidence_id": ev, "decision_id": did, "receipt_id": rid,
                  "batch_propagated": bool(item["batch_id"]), "rule": None}
        if save_rule:
            keywords = [k.strip() for k in (save_rule.get("keywords") or []) if str(k).strip()]
            if keywords:
                predicate = {"keywords": keywords, "example_question": q["question_text"]}
                scope = save_rule.get("scope") or {}
                # Supersede an existing rule with identical keywords in this category, else create.
                existing = None
                for row in self.list_rules_human(q["category"]):
                    if json.loads(row["predicate_json"]).get("keywords") == keywords:
                        existing = row["rule_id"]
                        break
                if existing:
                    out = self.supersede_rule(existing, new_answer=answer_obj,
                                              new_scope=scope, new_predicate=predicate, actor=actor)
                    result["rule"] = {"rule_id": existing, "version_id": out["version_id"],
                                      "action": "superseded"}
                else:
                    created = self.create_rule(q["category"], predicate, answer_obj, scope=scope,
                                               source_type="explicit_edit", actor=actor)
                    result["rule"] = {**created, "action": "created"}
        return result

    # ---------- V3/V4 risk gate (shadow mode) ----------
    # Per the research verdict, tiny per-user label counts cannot certify an
    # error-rate target, so the gate never blocks yet: it estimates the error
    # rate from human-confirmed labels only, flags would-block answers, and
    # reports how much evidence enforcement would still need.
    RISK_MIN_GOLD = 30

    def risk_estimate(self, category: str) -> dict:
        import math
        cat = self.category(category)
        rows = self.store.query(
            "SELECT fl.label_value FROM feedback_labels fl"
            " JOIN decisions d ON d.id=fl.decision_id JOIN questions q ON q.id=d.question_id"
            " WHERE q.category=? AND fl.eligible_for_calibration=1 AND d.mode IN ('auto','warn')"
            " ORDER BY fl.created_at DESC LIMIT 200", (category,))
        n = len(rows)
        errors = sum(1 for r in rows
                     if str(r["label_value"]).strip().lower() in self._NEGATIVE_OUTCOMES)
        target = cat["risk_target"]
        if n == 0:
            return {"category": category, "gold_sample": 0, "errors": 0, "error_rate": None,
                    "wilson_upper": None, "risk_target": target,
                    "gate_state": "insufficient_evidence", "would_block": False, "enforced": False}
        p = errors / n
        z = 1.96
        denom = 1 + z * z / n
        centre = p + z * z / (2 * n)
        margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
        upper = min(1.0, (centre + margin) / denom)
        if n < self.RISK_MIN_GOLD:
            state = "insufficient_evidence"
        elif upper > target:
            state = "would_block"
        else:
            state = "within_target"
        return {"category": category, "gold_sample": n, "errors": errors,
                "error_rate": round(p, 4), "wilson_upper": round(upper, 4),
                "risk_target": target, "gate_state": state,
                "would_block": state == "would_block", "enforced": False}

    def gate_readiness(self, category: str) -> dict:
        est = self.risk_estimate(category)
        needed = max(0, self.RISK_MIN_GOLD - est["gold_sample"])
        return {**est, "labels_needed": needed,
                "can_enforce": needed == 0 and est["gate_state"] != "insufficient_evidence",
                "note": ("Shadow mode: the gate measures and flags only. Enforcement is a "
                         "separate human promotion decision once enough human-confirmed "
                         "labels exist; agent labels never count.")}

    # ---------- V5 silent drift detection ----------
    # The world changed but the rule didn't: question text still matches, so
    # only outcome evidence can reveal it. Human-confirmed negatives are the
    # strong signal; agent-asserted negatives alone need volume + no positives.
    _NEGATIVE_OUTCOMES = {"failure", "failed", "error", "incorrect", "wrong", "bad", "regression"}
    _POSITIVE_OUTCOMES = {"success", "ok", "correct", "worked", "good", "done"}

    def _drift_for_rule(self, rule_id, version_id, scope_json, predicate_json, category):
        rows = self.store.query(
            "SELECT fl.label_value, fl.eligible_for_calibration FROM feedback_labels fl"
            " JOIN decision_rule_uses dru ON dru.decision_id=fl.decision_id"
            " WHERE dru.rule_version_id=? ORDER BY fl.created_at DESC LIMIT 20", (version_id,))
        neg = pos = human_neg = 0
        for r in rows:
            v = str(r["label_value"]).strip().lower()
            if v in self._NEGATIVE_OUTCOMES:
                neg += 1
                if r["eligible_for_calibration"]:
                    human_neg += 1
            elif v in self._POSITIVE_OUTCOMES:
                pos += 1
        status = "ok"
        if human_neg >= 2 or (neg >= 3 and pos == 0):
            status = "drift_suspected"
        elif neg >= 1:
            status = "watch"
        hold_created = False
        if status == "drift_suspected":
            held = self.store.query_one(
                "SELECT id FROM recalibration_holds WHERE rule_id=? AND status='held'", (rule_id,))
            if not held:
                scope = json.loads(scope_json or "{}")
                pred = json.loads(predicate_json or "{}")
                required_m = 1 if (pred.get("keywords") or pred.get("exact_question")) else 3
                self.store.execute(
                    "INSERT INTO recalibration_holds(id,category,rule_id,new_version_id,scope_fingerprint,"
                    "preference_epoch,required_m,fresh_count,seen_contexts_json,status,created_at)"
                    " VALUES(?,?,?,?,?,?,?,0,'[]','held',?)",
                    (new_id(), category, rule_id, version_id,
                     sha256_hex(canonical_json(scope.get("mandatory", {}))),
                     self.category(category)["active_preference_epoch"], required_m, now_iso()))
                self.store.emit("system", "switchboard", "drift.suspected", "rule", rule_id,
                                {"version_id": version_id, "negatives": neg, "positives": pos,
                                 "human_negatives": human_neg})
                hold_created = True
        return {"rule_id": rule_id, "category": category, "version_id": version_id,
                "labelled": len(rows), "positives": pos, "negatives": neg,
                "human_negatives": human_neg, "status": status, "hold_created": hold_created}

    def detect_drift(self, rule_id: str | None = None) -> list:
        """Scan active rule versions for silent drift; place a hold on suspects."""
        q = ("SELECT r.id AS rule_id, r.category, rv.id AS version_id, rv.scope_json, rv.predicate_json"
             " FROM rules r JOIN rule_versions rv ON rv.id=r.active_version_id"
             " WHERE r.status='active'")
        args = []
        if rule_id:
            q += " AND r.id=?"
            args.append(rule_id)
        return [self._drift_for_rule(r["rule_id"], r["version_id"], r["scope_json"],
                                     r["predicate_json"], r["category"])
                for r in self.store.query(q, args)]

    def _drift_check_for_decision(self, decision_id):
        rows = self.store.query(
            "SELECT DISTINCT dru.rule_version_id FROM decision_rule_uses dru WHERE dru.decision_id=?",
            (decision_id,))
        for r in rows:
            ver = self.store.query_one(
                "SELECT rv.*, ru.category, ru.id AS rule_id FROM rule_versions rv"
                " JOIN rules ru ON ru.id=rv.rule_id WHERE rv.id=?", (r["rule_version_id"],))
            if ver:
                self._drift_for_rule(ver["rule_id"], ver["id"], ver["scope_json"],
                                     ver["predicate_json"], ver["category"])

    # ---------- evidence / outcomes ----------
    def add_evidence(self, evidence_class, actor_type, actor_id, source_ref=None, payload_excerpt=None):
        eid = new_id()
        self.store.execute(
            "INSERT INTO evidence_items(id,evidence_class,source_actor_type,source_actor_id,source_ref,"
            "payload_hash,payload_excerpt,quality_status,created_at) VALUES(?,?,?,?,?,?,?,'unreviewed',?)",
            (eid, evidence_class, actor_type, actor_id, source_ref,
             sha256_hex(payload_excerpt or ""), payload_excerpt, now_iso()))
        return eid

    def report_outcome(self, agent, decision_id, outcome, detail=None):
        dec = self.store.query_one("SELECT * FROM decisions WHERE id=?", (decision_id,))
        if not dec:
            raise SwitchboardError("NOT_FOUND", "decision")
        eid = self.add_evidence("agent_asserted", "agent", agent["id"], payload_excerpt=(detail or outcome)[:200])
        lid = new_id()
        self.store.execute(
            "INSERT INTO feedback_labels(id,decision_id,label_type,label_value,evidence_id,"
            "eligible_for_calibration,quarantine_reason,created_at) VALUES(?,?,?,?,?,0,?,?)",
            (lid, decision_id, "outcome", outcome, eid, "agent_asserted_not_gold", now_iso()))
        self.store.emit("agent", agent["id"], "feedback.received", "decision", decision_id,
                        {"outcome": outcome}, evidence_class="agent_asserted")
        self._drift_check_for_decision(decision_id)
        return {"evidence_id": eid, "label_id": lid, "eligible_for_calibration": False}

    def confirm_feedback(self, decision_id, label_value, actor="local_user"):
        eid = self.add_evidence("human_confirmed", "human", actor, payload_excerpt=str(label_value)[:200])
        lid = new_id()
        self.store.execute(
            "INSERT INTO feedback_labels(id,decision_id,label_type,label_value,evidence_id,"
            "eligible_for_calibration,created_at) VALUES(?,?,?,?,?,1,?)",
            (lid, decision_id, "correctness", label_value, eid, now_iso()))
        self.store.emit("human", actor, "feedback.admitted_to_calibration", "decision", decision_id,
                        {}, evidence_class="human_confirmed")
        dec_q = self.store.query_one(
            "SELECT q.category, q.context_json FROM decisions d JOIN questions q ON q.id=d.question_id"
            " WHERE d.id=?", (decision_id,))
        if dec_q:
            self._record_fresh_evidence(dec_q["category"], json.loads(dec_q["context_json"] or "{}"),
                                        "confirm_feedback")
        self._drift_check_for_decision(decision_id)
        return {"evidence_id": eid, "label_id": lid, "eligible_for_calibration": True}

    # ---------- dependencies / blast radius ----------
    def record_use(self, agent, receipt_id, dependent_type, dependent_id, relationship, status="pending"):
        rec = self.store.query_one("SELECT * FROM receipts WHERE id=?", (receipt_id,))
        if not rec:
            raise SwitchboardError("NOT_FOUND", "receipt")
        did = new_id()
        self.store.execute(
            "INSERT OR IGNORE INTO decision_dependencies(id,source_receipt_id,dependent_type,dependent_id,"
            "relationship,observed_by,evidence_class,created_at,status) VALUES(?,?,?,?,?,'agent','agent_asserted',?,?)",
            (did, receipt_id, dependent_type, dependent_id, relationship, now_iso(), status))
        self.store.emit("agent", agent["id"], "decision.dependency_recorded", "receipt", receipt_id,
                        {"dependent_id": dependent_id}, evidence_class="agent_asserted")
        return {"dependency_id": did, "coverage": "partial_agent_reported"}

    def blast_radius(self, rule_id):
        versions = [v["id"] for v in self.store.query("SELECT id FROM rule_versions WHERE rule_id=?", (rule_id,))]
        if not versions:
            raise SwitchboardError("NOT_FOUND", "rule")
        ph = ",".join("?" * len(versions))
        uses = self.store.query(
            f"SELECT DISTINCT d.id as decision_id, d.mode, d.created_at FROM decision_rule_uses dru"
            f" JOIN decisions d ON d.id=dru.decision_id WHERE dru.rule_version_id IN ({ph})", versions)
        items = []
        for u in uses:
            rec = self.store.query_one("SELECT id FROM receipts WHERE decision_id=?", (u["decision_id"],))
            deps = self.store.query("SELECT * FROM decision_dependencies WHERE source_receipt_id=?",
                                    (rec["id"],)) if rec else []
            if deps:
                for dep in deps:
                    status = ("revalidate" if dep["status"] == "pending"
                              else "review_completed" if dep["status"] == "completed" else "unaffected")
                    items.append({"decision_id": u["decision_id"], "dependent_id": dep["dependent_id"],
                                  "dependent_type": dep["dependent_type"], "proposed_status": status})
            else:
                items.append({"decision_id": u["decision_id"], "dependent_id": None,
                              "proposed_status": "unknown_dependency_coverage"})
        return {"rule_id": rule_id, "affected": items,
                "coverage_caveat": "Bounded by recorded dependency edges; absence of an edge is not proof of no impact."}

    # ---------- away grants ----------
    def create_away_grant(self, categories, allowed_intents, expires_at, actor="local_user"):
        gid = new_id()
        self.store.execute(
            "INSERT INTO away_grants(id,created_by,starts_at,expires_at,categories_json,allowed_intents_json,"
            "locked_classes_excluded,status,policy_version) VALUES(?,?,?,?,?,?,1,'active',?)",
            (gid, actor, now_iso(), expires_at, json.dumps(categories), json.dumps(allowed_intents),
             self.cfg.policy_version))
        self.store.emit("human", actor, "away.grant_created", "away_grant", gid, {"expires_at": expires_at})
        return {"grant_id": gid, "expires_at": expires_at}

    def revoke_away_grant(self, grant_id, actor="local_user"):
        self.store.execute("UPDATE away_grants SET revoked_at=?,status='revoked' WHERE id=?", (now_iso(), grant_id))
        self.store.emit("human", actor, "away.grant_revoked", "away_grant", grant_id, {})
        return {"grant_id": grant_id, "status": "revoked"}

    def _away_grant_active(self, category, intent_type):
        now = now_iso()
        for g in self.store.query("SELECT * FROM away_grants WHERE status='active' AND revoked_at IS NULL"):
            if g["expires_at"] > now and category in json.loads(g["categories_json"]):
                intents = json.loads(g["allowed_intents_json"])
                if not intents or intent_type in intents:
                    return True
        return False

    # ---------- passport / canary ----------
    def passport(self, category):
        cat = self.category(category)
        labels = self.store.query(
            "SELECT COUNT(*) n FROM feedback_labels fl JOIN decisions d ON d.id=fl.decision_id"
            " JOIN questions q ON q.id=d.question_id WHERE q.category=? AND fl.eligible_for_calibration=1", (category,))
        sample = labels[0]["n"] if labels else 0
        holds = self.list_holds(category)
        held = [h for h in holds if h["status"] == "held"]
        data = {"category": category, "stage": cat["stage"], "locked": bool(cat["locked"]),
                "risk_target": cat["risk_target"], "preference_epoch": cat["active_preference_epoch"],
                "evidence_state": "recalibration_pending" if held else cat["min_evidence_state"],
                "held_slices": len(held),
                "holds": [{"rule_id": h["rule_id"], "required_m": h["required_m"],
                           "fresh_count": h["fresh_count"], "status": h["status"]} for h in holds],
                "hold_note": "Sliced smoke-test hold: catches gross non-generalisation; certifies no risk target.",
                "gold_sample_count": sample,
                "taste": next((t["leans"] for t in self.taste_profile(category) if t["category"] == category), []),
                "risk_gate": self.gate_readiness(category),
                "limitations": ["Sample metrics are historical measurements, not guarantees about the next decision.",
                                "Dependency coverage is bounded by agent-reported record_use edges."],
                "policy_version": cat["policy_version"]}
        self.store.execute(
            "INSERT INTO autonomy_passports(id,category,stage,evidence_summary_json,limitations_json,reason,created_at)"
            " VALUES(?,?,?,?,?,?,?)", (new_id(), category, cat["stage"], json.dumps(data),
                                       json.dumps(data["limitations"]), cat["min_evidence_state"], now_iso()))
        return data

    def run_canary(self, category, case_id, expected, observed, run_type="shadow"):
        passed = 1 if expected == observed else 0
        self.store.execute(
            "INSERT INTO canary_runs(id,run_type,case_id,category,expected_behavior,observed_behavior,passed,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)", (new_id(), run_type, case_id, category, expected, observed, passed, now_iso()))
        if not passed:
            self.category(category)
            self.store.execute("UPDATE category_settings SET min_evidence_state='quarantined',stage='shadow',"
                               "updated_at=? WHERE category=?", (now_iso(), category))
            self.store.emit("system", "switchboard", "category.frozen", "category", category,
                            {"case_id": case_id})
        return {"passed": bool(passed), "category_stage": self.category(category)["stage"]}

    # ---------- steering: the centrepiece ----------
    # Agents submit proposals with declared directions; humans steer. Steering
    # NEVER accepts or authorizes: acceptance is a separate deliberate action,
    # and locked categories cannot be steered at all (nothing to authorize by
    # nudge). The agent owns revisions; Switchboard owns the surface, the
    # ledger, and the learned taste.
    STEER_EDGES = ("top", "left", "right", "bottom")

    def _validate_directions(self, directions):
        if not isinstance(directions, list) or not (2 <= len(directions) <= 4):
            raise SwitchboardError("INVALID_SCHEMA", "a steerable proposal needs 2-4 directions")
        seen = set()
        out = []
        for d in directions:
            if not isinstance(d, dict):
                raise SwitchboardError("INVALID_SCHEMA", "each direction must be an object")
            edge = str(d.get("edge", ""))
            label = str(d.get("label", "")).strip()
            effect = str(d.get("expected_effect", "")).strip()
            if edge not in self.STEER_EDGES:
                raise SwitchboardError("INVALID_SCHEMA", f"unknown edge: {edge or '(missing)'}")
            if edge in seen:
                raise SwitchboardError("INVALID_SCHEMA", f"duplicate edge: {edge}")
            if not label or not effect:
                raise SwitchboardError("INVALID_SCHEMA", "each direction needs a label and an expected_effect")
            seen.add(edge)
            out.append({"edge": edge, "label": label[:80], "expected_effect": effect[:200]})
        return out

    def submit_proposal(self, agent, title, proposal_text, category, directions) -> dict:
        title = str(title or "").strip()
        proposal_text = str(proposal_text or "").strip()
        if not title or not proposal_text or not category:
            raise SwitchboardError("INVALID_SCHEMA", "title, proposal_text and category required")
        if len(proposal_text) > 8000:
            raise SwitchboardError("INVALID_SCHEMA", "proposal too long")
        cat = self.category(category)
        if cat["locked"]:
            raise SwitchboardError("LOCKED_CATEGORY",
                                   "locked categories always need a deliberate answer; they cannot be steered")
        dirs = self._validate_directions(directions)
        sid = new_id()
        ts = now_iso()
        self.store.execute(
            "INSERT INTO steering_sessions(id,agent_id,category,title,proposal_text,directions_json,"
            "version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,1,'open',?,?)",
            (sid, agent["id"], category, title[:200], proposal_text, json.dumps(dirs), ts, ts))
        self.store.execute(
            "INSERT INTO steering_revisions(id,session_id,version,proposal_text,note,created_at)"
            " VALUES(?,?,1,?,NULL,?)", (new_id(), sid, proposal_text, ts))
        self.store.emit("agent", agent["id"], "steering.proposal_submitted", "steering_session", sid,
                        {"category": category, "version": 1})
        return self.steering_session(sid)

    def steering_session(self, session_id, agent=None) -> dict:
        s = self.store.query_one("SELECT * FROM steering_sessions WHERE id=?", (session_id,))
        if not s:
            raise SwitchboardError("NOT_FOUND", "steering session")
        if agent is not None and s["agent_id"] != agent["id"]:
            raise SwitchboardError("NOT_FOUND", "steering session")
        agent_row = self.store.query_one("SELECT id,name,kind FROM agents WHERE id=?", (s["agent_id"],))
        revisions = self.store.query(
            "SELECT version,proposal_text,note,created_at FROM steering_revisions"
            " WHERE session_id=? ORDER BY version", (session_id,))
        events = self.store.query(
            "SELECT event_type,actor_type,payload_json,occurred_at FROM events"
            " WHERE object_type='steering_session' AND object_id=? ORDER BY occurred_at, rowid",
            (session_id,))
        trajectory = []
        for e in events:
            try:
                payload = json.loads(e["payload_json"] or "{}")
            except ValueError:
                payload = {}
            trajectory.append({"event": e["event_type"], "actor": e["actor_type"],
                               "at": e["occurred_at"], **payload})
        pending = None
        for t in reversed(trajectory):
            if t["event"] == "steering.applied":
                pending = t
                break
            if t["event"] in ("steering.proposal_revised", "steering.accepted", "steering.rejected"):
                break
        return {"id": s["id"], "agent": agent_row, "category": s["category"], "title": s["title"],
                "proposal_text": s["proposal_text"], "directions": json.loads(s["directions_json"]),
                "version": s["version"], "status": s["status"],
                "pending_steer": pending, "revisions": revisions, "trajectory": trajectory,
                "created_at": s["created_at"], "updated_at": s["updated_at"]}

    def list_steering(self, status="open") -> list:
        rows = self.store.query(
            "SELECT id FROM steering_sessions WHERE status=? ORDER BY updated_at DESC", (status,))
        return [self.steering_session(r["id"]) for r in rows]

    def steer(self, session_id, edge, magnitude=1, actor="local_user") -> dict:
        """Record one nudge. Never resolves the session: no acceptance by gesture."""
        s = self.store.query_one("SELECT * FROM steering_sessions WHERE id=?", (session_id,))
        if not s:
            raise SwitchboardError("NOT_FOUND", "steering session")
        if s["status"] != "open":
            raise SwitchboardError("CONFLICT", "session is closed")
        dirs = {d["edge"]: d for d in json.loads(s["directions_json"])}
        if edge not in dirs:
            raise SwitchboardError("INVALID_SCHEMA", f"edge {edge} was not declared by the agent")
        try:
            mag = float(magnitude)
        except (TypeError, ValueError):
            raise SwitchboardError("INVALID_SCHEMA", "magnitude must be a number")
        mag = max(0.25, min(2.0, mag))
        d = dirs[edge]
        instruction = {"type": "steer", "edge": edge, "label": d["label"],
                       "expected_effect": d["expected_effect"], "magnitude": mag,
                       "session_id": session_id, "base_version": s["version"]}
        self.store.execute("UPDATE steering_sessions SET updated_at=? WHERE id=?",
                           (now_iso(), session_id))
        self.store.emit("human", actor, "steering.applied", "steering_session", session_id,
                        instruction, evidence_class="human_confirmed")
        return {"instruction": instruction, "session": self.steering_session(session_id)}

    def revise_proposal(self, agent, session_id, proposal_text, note=None) -> dict:
        """Agent answers a steer with a new version. Only the owning agent."""
        s = self.store.query_one("SELECT * FROM steering_sessions WHERE id=? AND agent_id=?",
                                 (session_id, agent["id"]))
        if not s:
            raise SwitchboardError("NOT_FOUND", "steering session")
        if s["status"] != "open":
            raise SwitchboardError("CONFLICT", "session is closed")
        proposal_text = str(proposal_text or "").strip()
        if not proposal_text or len(proposal_text) > 8000:
            raise SwitchboardError("INVALID_SCHEMA", "proposal_text required (max 8000 chars)")
        version = s["version"] + 1
        self.store.execute(
            "UPDATE steering_sessions SET proposal_text=?,version=?,updated_at=? WHERE id=?",
            (proposal_text, version, now_iso(), session_id))
        self.store.execute(
            "INSERT INTO steering_revisions(id,session_id,version,proposal_text,note,created_at)"
            " VALUES(?,?,?,?,?,?)", (new_id(), session_id, version, proposal_text,
                                    str(note)[:300] if note else None, now_iso()))
        self.store.emit("agent", agent["id"], "steering.proposal_revised", "steering_session",
                        session_id, {"version": version})
        return self.steering_session(session_id)

    def resolve_steering(self, session_id, outcome, actor="local_user") -> dict:
        """The deliberate close: accept or reject. Deliberately separate from steer()."""
        if outcome not in ("accepted", "rejected"):
            raise SwitchboardError("INVALID_SCHEMA", "outcome must be accepted|rejected")
        s = self.store.query_one("SELECT * FROM steering_sessions WHERE id=?", (session_id,))
        if not s:
            raise SwitchboardError("NOT_FOUND", "steering session")
        if s["status"] != "open":
            raise SwitchboardError("CONFLICT", "session is closed")
        self.store.execute("UPDATE steering_sessions SET status=?,updated_at=? WHERE id=?",
                           (outcome, now_iso(), session_id))
        self.store.emit("human", actor, f"steering.{outcome}", "steering_session", session_id,
                        {"version": s["version"]}, evidence_class="human_confirmed")
        return self.steering_session(session_id)

    def pending_steer(self, agent, session_id) -> dict:
        """What the agent polls: the latest unconsumed steer, or acceptance."""
        s = self.steering_session(session_id, agent=agent)
        if s["status"] in ("accepted", "rejected"):
            return {"status": s["status"], "instruction": None, "session": s}
        return {"status": s["status"], "instruction": s["pending_steer"], "session": s}

    def taste_profile(self, category=None) -> list:
        """Which way this human leans, per category — from steering alone.

        Descriptive only: counts of human steers by direction label. It is a
        mirror for the Passport, never a rule and never gold evidence.
        """
        sql = ("SELECT ss.category, e.payload_json FROM events e"
               " JOIN steering_sessions ss ON ss.id=e.object_id"
               " WHERE e.event_type='steering.applied'")
        params = ()
        if category:
            sql += " AND ss.category=?"
            params = (category,)
        counts: dict = {}
        for r in self.store.query(sql, params):
            try:
                label = json.loads(r["payload_json"] or "{}").get("label", "?")
            except ValueError:
                label = "?"
            counts.setdefault(r["category"], {}).setdefault(label, 0)
            counts[r["category"]][label] += 1
        return [{"category": c, "leans": [[k, n] for k, n in sorted(v.items(), key=lambda kv: -kv[1])]}
                for c, v in sorted(counts.items())]

    # ---------- sandbox action review ----------
    def request_action_review(self, agent, action: dict, expires_at=None):
        canonical = canonical_json(action)
        ahash = sha256_hex(canonical)
        aid = new_id()
        self.store.execute(
            "INSERT INTO action_reviews(id,receipt_id,canonical_action_json,action_hash,status,requested_by,expires_at)"
            " VALUES(?,?,?,?, 'held',?,?)", (aid, None, canonical, ahash, agent["id"], expires_at))
        self.store.emit("agent", agent["id"], "action.review_requested", "action_review", aid, {"hash": ahash})
        return {"review_id": aid, "action_hash": ahash, "status": "held"}

    def approve_action(self, review_id, actor="local_user"):
        self.store.execute("UPDATE action_reviews SET status='approved',approved_by=?,approved_at=? WHERE id=?",
                           (actor, now_iso(), review_id))
        self.store.emit("human", actor, "action.approved", "action_review", review_id, {})
        return self.store.query_one("SELECT * FROM action_reviews WHERE id=?", (review_id,))

    def verify_action_execution(self, review_id, actual_action: dict):
        row = self.store.query_one("SELECT * FROM action_reviews WHERE id=?", (review_id,))
        if not row:
            raise SwitchboardError("NOT_FOUND", "action review")
        actual_hash = sha256_hex(canonical_json(actual_action))
        if row["status"] != "approved":
            raise SwitchboardError("LOCKED_ACTION", "not approved")
        if actual_hash != row["action_hash"]:
            self.store.emit("system", "switchboard", "action.hash_mismatch", "action_review", review_id, {})
            raise SwitchboardError("ACTION_HASH_MISMATCH")
        if row["executed_at"]:
            raise SwitchboardError("LOCKED_ACTION", "already executed (one-use)")
        if row["expires_at"] and row["expires_at"] < now_iso():
            raise SwitchboardError("GRANT_EXPIRED")
        self.store.execute("UPDATE action_reviews SET executed_at=?,status='executed' WHERE id=?",
                           (now_iso(), review_id))
        return {"executed": True, "action_hash": actual_hash}
