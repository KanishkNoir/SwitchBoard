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
        if stage not in ("shadow", "suggest", "auto"):
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
        answer = candidate["rule_version"]["_answer"] if (candidate and mode == "auto") else None
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
        rid = new_id()
        receipt_type = "answer" if mode == "auto" else "defer"
        self.store.execute(
            "INSERT INTO receipts(id,decision_id,receipt_type,why_text,evidence_ids_json,issued_at)"
            " VALUES(?,?,?,?,?,?)", (rid, did, receipt_type, reason, "[]", now_iso()))
        event = {"auto": "decision.auto_answered", "shadow": "decision.shadow_logged",
                 "suggested": "decision.suggested"}.get(mode, "decision.deferred")
        self.store.emit("system", "switchboard", event, "decision", did, {"reason": reason, "tier": tier})
        dec = self.store.query_one("SELECT * FROM decisions WHERE id=?", (did,))
        rec = self.store.query_one("SELECT * FROM receipts WHERE id=?", (rid,))
        q = self.store.query_one("SELECT * FROM questions WHERE id=?", (qid,))
        return self._response(dec, rec, q)

    def _response(self, dec, rec, q):
        uses = self.store.query("SELECT rule_version_id FROM decision_rule_uses WHERE decision_id=?", (dec["id"],))
        decision = {"auto": "answer"}.get(dec["mode"], "defer")
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
            "requires_human": dec["mode"] != "auto",
            "explanation": f"{dec['reason_code']} via {dec['matcher_tier']}",
        }
        return resp

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

    def inbox(self):
        return self.store.query(
            "SELECT ai.*, q.question_text, q.category, q.agent_id FROM attention_items ai"
            " JOIN questions q ON q.id=ai.question_id WHERE ai.status='queued'"
            " ORDER BY ai.priority_score DESC, ai.created_at ASC")

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

    def answer_inbox(self, item_id, answer, actor="local_user", save_rule=None, dwell_ms=None):
        item = self.store.query_one("SELECT * FROM attention_items WHERE id=?", (item_id,))
        if not item:
            raise SwitchboardError("NOT_FOUND", "attention item")
        q = self.store.query_one("SELECT * FROM questions WHERE id=?", (item["question_id"],))
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
                        {"answer": answer_obj, "decision_id": did, "dwell_ms": dwell_ms},
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
