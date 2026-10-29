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
def register_agent(body: dict):
    # Local-only bootstrap: registration is a human local action.
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


# ---- human (local PWA) routes ----
@app.get("/inbox")
def inbox():
    return svc.inbox()


@app.post("/inbox/{item_id}/answer")
def inbox_answer(item_id: str, body: dict):
    try:
        out = svc.answer_inbox(item_id, body.get("answer"), save_rule=body.get("save_rule"))
        _notify("inbox")
        return out
    except SwitchboardError as e:
        return err(e)


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
def passport(category: str):
    return svc.passport(category)


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
