import asyncio
import json
import os

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from .agents import apply_steering, tradeoff_planner_question, validate_decision_payload, visual_scout_question
from .config import settings
from .domain import QuestionRequest
from .persistence import Store
from .service import SwitchboardError, SwitchboardService

UI_DIR = os.path.join(os.path.dirname(__file__), "ui")
store = Store(settings.db_path if settings.db_path != ":memory:" else "switchboard.db")
svc = SwitchboardService(store)
app = FastAPI(title="Switchboard", version="0.2.0")
_subscribers: list[asyncio.Queue] = []

UI_TOKEN = settings.ui_token
_EXEMPT_PREFIXES = ("/api/", "/health")  # agent API uses its own key auth


@app.middleware("http")
async def ui_auth(request: Request, call_next):
    """Human web UI gate. Open locally when no token configured; required for tunnel use."""
    if not UI_TOKEN or request.url.path.startswith(_EXEMPT_PREFIXES):
        return await call_next(request)
    if request.url.path == "/login":
        if request.query_params.get("token") == UI_TOKEN:
            from fastapi.responses import RedirectResponse
            resp = RedirectResponse(url="/", status_code=302)
            resp.set_cookie("sb_token", UI_TOKEN, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
            return resp
        return JSONResponse(status_code=401, content={"error": "UNAUTHORIZED"})
    token = request.cookies.get("sb_token") or request.headers.get("x-ui-token")
    if token != UI_TOKEN:
        return JSONResponse(status_code=401,
                            content={"error": "UNAUTHORIZED",
                                     "detail": "Open the login link from your Switchboard operator."})
    return await call_next(request)


def _notify(event: str):
    for q in list(_subscribers):
        q.put_nowait(event)


@app.middleware("http")
async def server_timing(request: Request, call_next):
    """Phase 0 observability: split every response into app time vs SQLite time."""
    import time as _time
    from .persistence import reset_sqlite_stats, sqlite_stats
    reset_sqlite_stats(store)
    t0 = _time.perf_counter()
    try:
        resp = await call_next(request)
    except Exception:
        raise
    total_ms = (_time.perf_counter() - t0) * 1000.0
    sql_ms, nq = sqlite_stats(store)
    resp.headers["Server-Timing"] = (
        f"app;dur={total_ms:.1f}, sqlite;dur={sql_ms:.1f}, queries;count={nq}")
    return resp


# Phase 2 read cache (Snowflake-style persisted results): hot reads are keyed
# on (endpoint, params, write_seq) and served without touching SQLite while
# nothing has changed. Any write bumps write_seq inside the same commit, so a
# cached read can never follow a write it doesn't include.
_read_cache: dict = {}


def cached_read(key: str, params: str, compute):
    gen = store.write_seq
    ckey = (key, params, gen)
    if ckey in _read_cache:
        body, etag = _read_cache[ckey]
        return body, etag, True
    body = compute()
    etag = f'"{abs(hash(json.dumps(body, sort_keys=True, default=str))) % 10**12}"'
    for k in [k for k in _read_cache if k[2] != gen]:
        del _read_cache[k]  # only the current generation is ever servable
    _read_cache[ckey] = (body, etag)
    return body, etag, False


def cached_response(request: Request, key: str, params: str, compute):
    body, etag, hit = cached_read(key, params, compute)
    if request.headers.get("if-none-match") == etag:
        return JSONResponse(status_code=304, content=None, headers={"ETag": etag})
    return JSONResponse(content=body, headers={"ETag": etag, "X-Cache": "HIT" if hit else "MISS"})


def err(e: SwitchboardError):
    return JSONResponse(status_code=400, content={"error": e.code, "detail": str(e)})


def agent_from(header_key: str | None):
    try:
        return svc.authenticate(header_key or "")
    except SwitchboardError as e:
        raise HTTPException(status_code=401, detail=e.code)


class AskIn(BaseModel):
    request_id: str
    question: str
    category: str
    risk_hint: str | None = None
    reversibility: str = "unknown"
    deadline_at: str | None = None
    options: list = []
    context: dict = {}
    intent_type: str = "unknown"
    action: dict | None = None
    parent_receipts: list = []


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0", "t3_enabled": svc.ladder.t3 is not None}


@app.post("/api/agents/register")
def register_agent(body: dict, request: Request):
    # Bootstrap is a human action: on a token-protected deployment (the hub)
    # registration requires the UI token, so strangers cannot mint agents.
    if UI_TOKEN:
        token = request.cookies.get("sb_token") or request.headers.get("x-ui-token")
        if token != UI_TOKEN:
            return JSONResponse(status_code=401, content={"error": "UNAUTHORIZED"})
    return svc.register_agent(body.get("name", "agent"), body.get("kind", "cli"), body.get("scopes"))


@app.post("/api/ask")
def ask(body: AskIn, x_agent_key: str | None = Header(default=None)):
    agent = agent_from(x_agent_key)
    try:
        resp = svc.ask(agent, QuestionRequest(**body.model_dump()))
        _notify("question")
        return resp
    except SwitchboardError as e:
        return err(e)


@app.get("/api/rules")
def rules(x_agent_key: str | None = Header(default=None), category: str | None = None):
    agent = agent_from(x_agent_key)
    try:
        return svc.get_rules(agent, category)
    except SwitchboardError as e:
        return err(e)


@app.post("/api/report_outcome")
def report_outcome(body: dict, x_agent_key: str | None = Header(default=None)):
    agent = agent_from(x_agent_key)
    try:
        return svc.report_outcome(agent, body["decision_id"], body["outcome"], body.get("detail"))
    except SwitchboardError as e:
        return err(e)
    except KeyError:
        return JSONResponse(status_code=400, content={"error": "INVALID_SCHEMA"})


@app.post("/api/record_use")
def record_use(body: dict, x_agent_key: str | None = Header(default=None)):
    agent = agent_from(x_agent_key)
    try:
        return svc.record_use(agent, body["receipt_id"], body["dependent_type"], body["dependent_id"],
                              body.get("relationship", "used_answer"), body.get("status", "pending"))
    except SwitchboardError as e:
        return err(e)
    except KeyError:
        return JSONResponse(status_code=400, content={"error": "INVALID_SCHEMA"})


# ---- steering (agent-facing) ----
@app.post("/api/steering/submit")
def steering_submit(body: dict, x_agent_key: str | None = Header(default=None)):
    agent = agent_from(x_agent_key)
    try:
        return svc.submit_proposal(agent, body.get("title"), body.get("proposal_text"),
                                   body.get("category"), body.get("directions"),
                                   project=body.get("project"))
    except SwitchboardError as e:
        return err(e)


@app.post("/api/steering/revise")
def steering_revise(body: dict, x_agent_key: str | None = Header(default=None)):
    agent = agent_from(x_agent_key)
    try:
        out = svc.revise_proposal(agent, body["session_id"], body.get("proposal_text"),
                                  body.get("note"))
        _notify("steering")
        return out
    except SwitchboardError as e:
        return err(e)
    except KeyError:
        return JSONResponse(status_code=400, content={"error": "INVALID_SCHEMA"})


@app.get("/api/steering/pending/{session_id}")
def steering_pending(session_id: str, x_agent_key: str | None = Header(default=None)):
    agent = agent_from(x_agent_key)
    try:
        return svc.pending_steer(agent, session_id)
    except SwitchboardError as e:
        return err(e)


# ---- human (local PWA) routes ----
@app.get("/steering")
def steering_list(request: Request):
    return cached_response(request, "steering", "", svc.list_steering)


@app.get("/steering/{session_id}")
def steering_get(session_id: str):
    try:
        return svc.steering_session(session_id)
    except SwitchboardError as e:
        return err(e)


@app.post("/steering/{session_id}/steer")
def steering_steer(session_id: str, body: dict):
    try:
        out = svc.steer(session_id, body.get("edge"), body.get("magnitude", 1))
        _demo_revise_if_demo(session_id, body.get("edge"))
        _sim_revise_if_sim(session_id, body.get("edge"))
        _notify("steering")
        return out
    except SwitchboardError as e:
        return err(e)


@app.post("/steering/{session_id}/resolve")
def steering_resolve(session_id: str, body: dict):
    try:
        out = svc.resolve_steering(session_id, body.get("outcome"))
        _notify("steering")
        return out
    except SwitchboardError as e:
        return err(e)


@app.get("/taste")
def taste(request: Request):
    return cached_response(request, "taste", "", svc.taste_profile)
@app.get("/inbox")
def inbox(request: Request):
    return cached_response(request, "inbox", "", svc.inbox)


@app.post("/inbox/{item_id}/answer")
def inbox_answer(item_id: str, body: dict):
    try:
        out = svc.answer_inbox(item_id, body.get("answer"), save_rule=body.get("save_rule"),
                               dwell_ms=body.get("dwell_ms"), origin=body.get("origin", "tap"))
        _notify("inbox")
        return out
    except SwitchboardError as e:
        return err(e)


@app.get("/human/attention-health")
def attention_health():
    return svc.attention_health()


@app.get("/risk/{category}")
def risk(category: str):
    return svc.gate_readiness(category)


@app.get("/debrief")
def debrief(request: Request, limit: int = 30):
    return cached_response(request, "debrief", str(limit), lambda: svc.debrief(limit))


@app.get("/onboarding")
def onboarding():
    return svc.onboarding_state()


@app.post("/onboarding/complete")
def onboarding_complete(body: dict):
    try:
        return svc.complete_onboarding(bool(body.get("model_calls", False)),
                                       body.get("risk_choice", "balanced"))
    except SwitchboardError as e:
        return err(e)


@app.get("/inbox/{item_id}/detail")
def inbox_detail(item_id: str):
    try:
        return svc.inbox_detail(item_id)
    except SwitchboardError as e:
        return err(e)


@app.get("/notices")
def notices():
    return svc.notices()


@app.post("/notices/{item_id}/dismiss")
def dismiss_notice(item_id: str):
    try:
        out = svc.dismiss_notice(item_id)
        _notify("inbox")
        return out
    except SwitchboardError as e:
        return err(e)


@app.post("/notices/{item_id}/veto")
def veto_notice(item_id: str):
    try:
        out = svc.veto_notice(item_id)
        _notify("inbox")
        return out
    except SwitchboardError as e:
        return err(e)


@app.get("/drift")
def drift_report():
    return svc.detect_drift()


@app.post("/drift/scan")
def drift_scan():
    return svc.detect_drift()


@app.get("/human/agents")
def human_agents():
    return svc.list_agents()


@app.get("/human/rules")
def human_rules(category: str | None = None):
    return svc.list_rules_human(category)


@app.get("/human/rules/{rule_id}/versions")
def human_rule_versions(rule_id: str):
    try:
        return svc.rule_versions(rule_id)
    except SwitchboardError as e:
        return err(e)


@app.post("/decisions/{decision_id}/revalidate")
def revalidate(decision_id: str):
    try:
        out = svc.revalidate_decision(decision_id)
        _notify("inbox")
        return out
    except SwitchboardError as e:
        return err(e)


@app.post("/rules")
def create_rule(body: dict):
    return svc.create_rule(body["category"], body.get("predicate", {}), body.get("answer", {}),
                           scope=body.get("scope"), source_type=body.get("source_type", "explicit_edit"))


@app.post("/rules/{rule_id}/supersede")
def supersede(rule_id: str, body: dict):
    try:
        return svc.supersede_rule(rule_id, new_answer=body.get("answer"),
                                  new_scope=body.get("scope"), new_predicate=body.get("predicate"))
    except SwitchboardError as e:
        return err(e)


@app.get("/rules/{rule_id}/blast-radius")
def blast(rule_id: str):
    try:
        return svc.blast_radius(rule_id)
    except SwitchboardError as e:
        return err(e)


@app.put("/settings/{category}")
def set_category(category: str, body: dict):
    try:
        return svc.set_stage(category, body["stage"], body.get("reason", "manual"))
    except SwitchboardError as e:
        return err(e)
    except KeyError:
        return JSONResponse(status_code=400, content={"error": "INVALID_SCHEMA"})


@app.get("/passport/{category}")
def passport(request: Request, category: str):
    return cached_response(request, "passport", category, lambda: svc.passport(category))


@app.post("/away/grants")
def away_create(body: dict):
    return svc.create_away_grant(body.get("categories", []), body.get("allowed_intents", []), body["expires_at"])


@app.post("/away/grants/{grant_id}/revoke")
def away_revoke(grant_id: str):
    return svc.revoke_away_grant(grant_id)


@app.post("/canary")
def canary(body: dict):
    return svc.run_canary(body["category"], body["case_id"], body["expected"], body["observed"])


@app.get("/evaluation/suite")
def evaluation_suite():
    from .evaluation import default_suite
    return {"cases": default_suite(), "is_synthetic": True}


@app.post("/evaluation/replay")
def evaluation_replay(body: dict | None = None):
    from .evaluation import run_comparison
    cases = (body or {}).get("cases")
    return run_comparison(cases)


DEMO_STEER_DIRECTIONS = [
    {"edge": "left", "label": "Cheaper", "expected_effect": "Rank lower-cost options first"},
    {"edge": "right", "label": "More comfort", "expected_effect": "Rank higher-comfort options first"},
    {"edge": "top", "label": "Explore", "expected_effect": "Surface less obvious options"},
    {"edge": "bottom", "label": "Simplify", "expected_effect": "Prefer the simplest option"},
]
DEMO_LAPTOPS = [
    ("Eco Air 14", 899, "comfort 6/10, simplest to own"),
    ("Framework 13", 1599, "comfort 9/10, repairable"),
    ("Titan 16", 2499, "comfort 8/10, most powerful and novel"),
]


def _demo_agent():
    row = svc.store.query_one("SELECT * FROM agents WHERE name='switchboard_demo'")
    if row:
        return row
    reg = svc.register_agent("switchboard_demo", kind="demo")
    return svc.store.query_one("SELECT * FROM agents WHERE id=?", (reg["agent_id"],))


@app.post("/demo/steering-proposal")
def demo_steering_proposal():
    """One-click live loop: a demo agent submits a real steerable proposal."""
    agent = _demo_agent()
    text = "Three laptops, first pass:\n" + "\n".join(
        f"· {n} — ${p} ({d})" for n, p, d in DEMO_LAPTOPS)
    try:
        return svc.submit_proposal(agent, "Which laptop should we pick?", text,
                                   "purchase", DEMO_STEER_DIRECTIONS)
    except SwitchboardError as e:
        return err(e)


_DEMO_RANK = {"Cheaper": [0, 1, 2], "More comfort": [1, 2, 0],
              "Explore": [2, 1, 0], "Simplify": [0, 1, 2]}


def _demo_revise_if_demo(session_id, edge):
    """The demo agent answers a steer immediately, on the real rails."""
    s = svc.store.query_one("SELECT * FROM steering_sessions WHERE id=?", (session_id,))
    if not s:
        return
    agent = svc.store.query_one("SELECT * FROM agents WHERE id=?", (s["agent_id"],))
    if not agent or agent["name"] != "switchboard_demo":
        return
    label = next((d["label"] for d in DEMO_STEER_DIRECTIONS if d["edge"] == edge), "Cheaper")
    order = _DEMO_RANK.get(label, [0, 1, 2])
    text = f"Revised after your steer ({label.lower()} first):\n" + "\n".join(
        f"{i + 1}. {DEMO_LAPTOPS[j][0]} — ${DEMO_LAPTOPS[j][1]} ({DEMO_LAPTOPS[j][2]})"
        for i, j in enumerate(order))
    svc.revise_proposal(agent, session_id, text, note=f"demo agent re-ranked: {label}")


def _sim_agent(name):
    row = svc.store.query_one("SELECT * FROM agents WHERE name=?", (name,))
    if row:
        return row
    reg = svc.register_agent(name, kind="simulation")
    return svc.store.query_one("SELECT * FROM agents WHERE id=?", (reg["agent_id"],))


SIM_CAST = [
    ("sim-opencode", "web-app"),
    ("sim-claude-code", "api-refactor"),
    ("sim-hermes", "work-trip"),
]


@app.post("/demo/simulation")
def demo_simulation():
    """Multi-agent simulation: three agents, three projects, overlapping categories.

    Labelled simulation, real rails: every question and proposal goes through
    the same service paths a live harness uses, onto the same ledger.
    Beats: (1) same-category questions from different agents, (2) steerable
    proposals in one shared category, (3) a locked-category attempt.
    """
    import uuid as _uuid
    run = _uuid.uuid4().hex[:8]
    agents = {name: _sim_agent(name) for name, _ in SIM_CAST}
    questions = []

    def ask(agent_name, question, category, project, reversibility="reversible"):
        req = QuestionRequest(
            request_id=f"sim-{run}-{len(questions)}", question=question, category=category,
            reversibility=reversibility, intent_type="simulation",
            context={"project": project})
        out = svc.ask(agents[agent_name], req)
        questions.append({"agent": agent_name, "project": project, "category": category,
                          "question": question, "decision": out.get("decision"),
                          "question_id": out.get("question_id")})
        return out

    ask("sim-opencode", "May I buy the domain switchboard-demo.com for $12 for the web app?",
        "purchase", "web-app")
    ask("sim-claude-code", "May I upgrade CI minutes for $20/month for the API refactor?",
        "purchase", "api-refactor")
    ask("sim-opencode", "May I deploy the web app to staging?", "deploy", "web-app",
        reversibility="costly")
    ask("sim-claude-code", "May I push the database migration to staging for the API refactor?",
        "deploy", "api-refactor", reversibility="costly")
    ask("sim-hermes", "May I pay the airport hotel $140 now?", "payments", "work-trip",
        reversibility="costly")

    proposals = []
    p1 = svc.submit_proposal(
        agents["sim-opencode"], "Pick a laptop for the design contractor",
        "For the web-app project:\n· Eco Air 14 — $899 (simplest to own)\n"
        "· Framework 13 — $1599 (most comfortable, repairable)\n· Titan 16 — $2499 (most novel)",
        "purchase", DEMO_STEER_DIRECTIONS, project="web-app")
    proposals.append({"agent": "sim-opencode", "project": "web-app", "id": p1["id"]})
    p2 = svc.submit_proposal(
        agents["sim-hermes"], "Pick a hotel for the offsite",
        "For the work-trip project:\n· City Inn — $110/night (simplest, near the venue)\n"
        "· Grand Central Hotel — $210/night (most comfortable)\n· Skyline Lofts — $320/night (most novel)",
        "purchase", DEMO_STEER_DIRECTIONS, project="work-trip")
    proposals.append({"agent": "sim-hermes", "project": "work-trip", "id": p2["id"]})
    _notify("simulation")
    return {"run": run, "kind": "simulation",
            "agents": [{"name": n, "project": p} for n, p in SIM_CAST],
            "questions": questions, "proposals": proposals,
            "beats": [
                "Answer one purchase question with Always (scope: under $50) — the other agent's purchase question inherits it.",
                "Steer one proposal 'Cheaper' twice — the Passport taste for purchase updates for every agent.",
                "Correct the purchase rule — blast radius spans both projects.",
                "The payments question ignores all of it: locked, deliberate tap only.",
            ]}


def _sim_revise_if_sim(session_id, edge):
    """Simulated agents answer a steer immediately, on the real rails."""
    s = svc.store.query_one("SELECT * FROM steering_sessions WHERE id=?", (session_id,))
    if not s:
        return
    agent = svc.store.query_one("SELECT * FROM agents WHERE id=?", (s["agent_id"],))
    if not agent or not str(agent["name"]).startswith("sim-"):
        return
    import json as _json
    dirs = {d["edge"]: d for d in _json.loads(s["directions_json"])}
    d = dirs.get(edge)
    if not d:
        return
    text = (f"Revised after your steer ({d['label'].lower()}): {d['expected_effect'].lower()} "
            f"now leads this proposal.\n\n{s['proposal_text']}")
    svc.revise_proposal(agent, session_id, text, note=f"simulation agent revised: {d['label']}")


@app.post("/demo/tradeoff")
def demo_tradeoff(body: dict):
    payload = tradeoff_planner_question(body.get("task_id", "task-1"), body.get("options", []))
    validate_decision_payload(payload)
    return payload


@app.post("/demo/visual")
def demo_visual(body: dict):
    payload = visual_scout_question(body.get("task_id", "task-1"), body.get("goal", "improve this space"),
                                    body.get("objects"))
    validate_decision_payload(payload)
    return payload


@app.post("/demo/visual/segment")
def demo_segment(body: dict):
    from .adapters import MetaSegmentationAdapter
    adapter = MetaSegmentationAdapter(settings)
    if not adapter.enabled:
        return JSONResponse(status_code=503, content={"error": "SEGMENTATION_UNAVAILABLE"})
    out = adapter.segment(body.get("image_b64", ""), body.get("phrase", ""), body.get("mime", "image/webp"))
    if out is None:
        return JSONResponse(status_code=502, content={"error": "MODEL_UNAVAILABLE"})
    return out


@app.post("/demo/visual/generate")
def demo_generate(body: dict):
    from .adapters import MetaImageAdapter
    adapter = MetaImageAdapter(settings)
    if not adapter.enabled:
        return JSONResponse(status_code=503, content={"error": "IMAGE_UNAVAILABLE"})
    out = adapter.generate_or_edit(body.get("prompt", ""))
    if out is None:
        return JSONResponse(status_code=502, content={"error": "MODEL_UNAVAILABLE"})
    return out


@app.post("/demo/visual/scout")
def demo_scout(body: dict):
    from .adapters import MetaImageAdapter, MetaSegmentationAdapter
    from .agents import run_visual_scout
    payload, evidence = run_visual_scout(
        body.get("task_id", "task-1"), body.get("goal", "improve this space"),
        image_b64=body.get("image_b64"), phrases=body.get("phrases", []),
        mime=body.get("mime", "image/webp"),
        seg_adapter=MetaSegmentationAdapter(settings),
        image_prompt=body.get("image_prompt"), image_adapter=MetaImageAdapter(settings))
    return {"payload": payload, "evidence": evidence}


STEER_EDIT_PROMPTS = {
    "lower_cost": "Same room, same layout, but simpler and cheaper furniture and fixtures. Photorealistic.",
    "comfort": "Same room, same layout, but noticeably more comfortable and ergonomic. Photorealistic.",
    "bolder": "Same room, bolder redesign: stronger colors and more ambitious styling. Photorealistic.",
    "keep": "Same room, tidier and calmer, keep the existing layout and furniture. Photorealistic.",
}


@app.post("/demo/visual/steer-edit")
def demo_steer_edit(body: dict):
    from .adapters import MetaImageAdapter
    adapter = MetaImageAdapter(settings)
    if not adapter.enabled:
        return JSONResponse(status_code=503, content={"error": "IMAGE_UNAVAILABLE"})
    prompt = body.get("prompt") or STEER_EDIT_PROMPTS.get(body.get("action_id", ""), "")
    if not prompt:
        return JSONResponse(status_code=400, content={"error": "INVALID_SCHEMA", "detail": "unknown action_id"})
    out = adapter.edit(prompt, body.get("image_b64", ""), body.get("mime", "image/webp"))
    if out is None:
        return JSONResponse(status_code=502, content={"error": "MODEL_UNAVAILABLE"})
    return {**out, "prompt_used": prompt}


@app.post("/demo/steer")
def demo_steer(body: dict):
    try:
        return apply_steering(body["payload"], body["action_id"])
    except (ValueError, KeyError) as e:
        return JSONResponse(status_code=400, content={"error": "INVALID_SCHEMA", "detail": str(e)})


@app.get("/stream")
async def stream(request: Request):
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers.append(queue)

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps({'event': event})}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            _subscribers.remove(queue)

    return StreamingResponse(gen(), media_type="text/event-stream")


_DIST_CANDIDATES = [
    os.path.join(os.getcwd(), "frontend", "dist"),
    os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"),
]
FRONTEND_DIST = next((p for p in _DIST_CANDIDATES if os.path.isfile(os.path.join(p, "index.html"))),
                     _DIST_CANDIDATES[0])


@app.get("/assets/{asset_path:path}")
def frontend_asset(asset_path: str):
    target = os.path.normpath(os.path.join(FRONTEND_DIST, "assets", asset_path))
    if not target.startswith(os.path.normpath(FRONTEND_DIST)) or not os.path.isfile(target):
        return JSONResponse(status_code=404, content={"error": "NOT_FOUND"})
    return FileResponse(target)


@app.get("/")
def index():
    # Prefer the React build (frontend/dist); fall back to the legacy static page.
    react_index = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.isfile(react_index):
        return FileResponse(react_index)
    return FileResponse(os.path.join(UI_DIR, "index.html"))


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
