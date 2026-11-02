import asyncio
import json
import os
import re

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
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

_LOGIN_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>Sign in to Switchboard</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #f4f4f1; --card: #fff; --ink: #20211f; --muted: #676963;
      --line: #e7e8e2; --accent: #256b56; --accent-ink: #fff; --soft: #edf5f0;
      --shadow: 0 28px 72px rgba(37, 45, 37, .10);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    @media (prefers-color-scheme: dark) {
      :root { --bg: #111412; --card: #1c211e; --ink: #f3f5f1; --muted: #b5bcb6;
        --line: #303832; --accent: #8bd0ad; --accent-ink: #112117; --soft: #26352d; --shadow: 0 28px 72px rgba(0,0,0,.32); }
    }
    * { box-sizing: border-box; }
    body { min-height: 100vh; margin: 0; display: grid; place-items: center; padding: 28px;
      color: var(--ink); background: radial-gradient(ellipse at 76% 15%, rgba(120,177,142,.16), transparent 34%), var(--bg); }
    .card { width: min(900px, 100%); min-height: 480px; display: grid; grid-template-columns: 1.12fr .88fr;
      overflow: hidden; border: 1px solid var(--line); border-radius: 28px; background: var(--card); box-shadow: var(--shadow);
      animation: arrive .45s cubic-bezier(.2,.75,.25,1) both; }
    .copy { display: flex; flex-direction: column; align-items: flex-start; padding: clamp(30px, 6vw, 58px); }
    .brand { display: flex; align-items: center; gap: 11px; font-weight: 720; letter-spacing: -.035em; font-size: 19px; }
    .mark { width: 30px; height: 30px; display: grid; grid-template: 1fr 1fr / 1fr 1fr; gap: 3px; padding: 5px;
      border-radius: 9px; background: #202b25; transform: rotate(-4deg); }
    .mark i { border-radius: 3px; background: #a9d8b8; }
    .mark i:nth-child(2) { background: #f0b45f; } .mark i:nth-child(3) { background: #d98979; } .mark i:nth-child(4) { background: #83b6d4; }
    .eyebrow { margin: auto 0 14px; color: var(--accent); font-size: 11px; font-weight: 750; letter-spacing: .14em; text-transform: uppercase; }
    h1 { max-width: 440px; margin: 0; font-size: clamp(34px, 5vw, 49px); line-height: 1.05; letter-spacing: -.055em; font-weight: 680; }
    .body { max-width: 405px; margin: 19px 0 0; color: var(--muted); font-size: 16px; line-height: 1.65; }
    .signin { width: 100%; margin-top: 24px; }
    .signin label { display: block; margin-bottom: 8px; color: var(--ink); font-size: 13px; font-weight: 680; }
    .entry { display: flex; gap: 8px; }
    .entry input { flex: 1; min-width: 0; padding: 12px 13px; border: 1px solid var(--line); border-radius: 11px;
      outline: none; color: var(--ink); background: var(--bg); font: inherit; font-size: 13px; }
    .entry input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent); }
    .entry button { flex: none; padding: 0 15px; border: 0; border-radius: 11px; color: var(--accent-ink); background: var(--accent);
      font: inherit; font-size: 13px; font-weight: 700; cursor: pointer; transition: transform .18s ease, filter .18s ease; }
    .entry button:hover { filter: brightness(1.06); transform: translateY(-1px); }
    .entry button:focus-visible { outline: 3px solid color-mix(in srgb, var(--accent) 45%, transparent); outline-offset: 2px; }
    .entry-note { margin: 8px 1px 0; color: var(--muted); font-size: 12px; line-height: 1.5; }
    .error { margin: 10px 0 0; padding: 10px 12px; border: 1px solid color-mix(in srgb, #d86b60 42%, var(--line));
      border-radius: 10px; color: var(--ink); background: color-mix(in srgb, #d86b60 10%, var(--card)); font-size: 13px; }
    .hint { width: 100%; margin-top: 34px; padding: 15px 16px; border: 1px solid var(--line); border-radius: 14px;
      color: var(--muted); font-size: 13px; line-height: 1.55; }
    .hint strong { display: block; margin-bottom: 3px; color: var(--ink); font-size: 13px; }
    .visual { position: relative; display: grid; place-items: center; min-height: 320px; overflow: hidden;
      background: linear-gradient(145deg, #e5efe7, #d7e5dc 55%, #cedfd3); }
    @media (prefers-color-scheme: dark) { .visual { background: linear-gradient(145deg, #25352d, #1e2c25 55%, #19231e); } }
    .visual::before, .visual::after { content: ""; position: absolute; width: 280px; height: 280px; border: 1px solid rgba(49,101,72,.13); border-radius: 50%; }
    .visual::after { width: 390px; height: 390px; }
    .board { position: relative; width: min(290px, 78%); padding: 23px; border: 1px solid rgba(42,83,59,.17); border-radius: 23px;
      background: rgba(255,255,255,.58); box-shadow: 0 18px 50px rgba(37,75,52,.12); backdrop-filter: blur(14px); }
    @media (prefers-color-scheme: dark) { .board { background: rgba(18,28,22,.55); border-color: rgba(191,225,199,.14); } }
    .board-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 23px; color: var(--muted); font-size: 11px; font-weight: 650; letter-spacing: .08em; text-transform: uppercase; }
    .live { display: flex; align-items: center; gap: 6px; color: var(--accent); letter-spacing: 0; text-transform: none; }
    .live i { width: 7px; height: 7px; border-radius: 50%; background: #62ae7c; box-shadow: 0 0 0 4px rgba(98,174,124,.14); }
    .lane { position: relative; height: 39px; display: flex; align-items: center; gap: 11px; }
    .lane + .lane { margin-top: 10px; }
    .lane::before { content: ""; position: absolute; left: 8px; right: 8px; top: 19px; height: 1px; background: rgba(62,102,76,.22); }
    .node { position: relative; z-index: 1; width: 16px; height: 16px; border: 4px solid rgba(255,255,255,.84); border-radius: 50%; background: #83b6d4; box-shadow: 0 0 0 1px rgba(43,82,57,.16); }
    .node.gold { margin-left: auto; background: #e8b564; } .node.rose { background: #d98979; }
    .node.green { margin-left: auto; background: #80b791; animation: signal 2.4s ease-in-out infinite; }
    .lane-label { position: absolute; z-index: 2; left: 38px; padding: 2px 7px; border-radius: 6px; color: #425247; background: rgba(244,249,244,.94); font-size: 10px; font-weight: 650; }
    @media (prefers-color-scheme: dark) { .lane-label { color: #d4e4d8; background: #26352d; } }
    .foot { margin-top: auto; padding-top: 26px; color: var(--muted); font-size: 12px; }
    @keyframes arrive { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
    @keyframes signal { 50% { box-shadow: 0 0 0 7px rgba(98,174,124,.10); } }
    @media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; scroll-behavior: auto !important; } }
    @media (max-width: 820px) {
      body { padding: 14px; }
      .card { grid-template-columns: 1fr; min-height: 0; max-width: 640px; margin: 0 auto; border-radius: 22px; }
      .copy { min-height: 430px; padding: clamp(28px, 6vw, 42px); }
      .eyebrow { margin-top: auto; }
      h1 { font-size: clamp(34px, 7vw, 44px); }
      .visual { min-height: 210px; }
      .board { width: min(280px, 78%); padding: 16px 19px; }
      .foot { padding-top: 22px; }
    }
  </style>
</head>
<body>
  <main class="card" aria-labelledby="title">
    <section class="copy">
      <div class="brand"><span class="mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span>Switchboard</div>
      <p class="eyebrow">Private operator access</p>
      <h1 id="title">Welcome back to your Switchboard.</h1>
      <p class="body">Sign in once on this browser. We’ll keep you signed in for 30 days.</p>
      <form class="signin" method="post" action="/login">
        <label for="operator-credential">Operator login link or access key</label>
        <div class="entry">
          <input id="operator-credential" name="credential" type="password" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="Paste your link or key" required>
          <button type="submit">Sign in <span aria-hidden="true">→</span></button>
        </div>
        <p class="entry-note">Your key is checked securely and never added to the address bar.</p>
        <!--AUTH_ERROR-->
      </form>
      <aside class="hint"><strong>Need your access key?</strong>Use the value set as <code>SWITCHBOARD_UI_TOKEN</code> for this deployment. Treat it like a password.</aside>
      <p class="foot">One calm place to guide work across your agents.</p>
    </section>
    <div class="visual" aria-hidden="true">
      <div class="board">
        <div class="board-top"><span>Agent channels</span><span class="live"><i></i> Connected</span></div>
        <div class="lane"><i class="node"></i><span class="lane-label">Research</span><i class="node gold"></i></div>
        <div class="lane"><i class="node rose"></i><span class="lane-label">Build</span><i class="node green"></i></div>
        <div class="lane"><i class="node"></i><span class="lane-label">Review</span><i class="node gold"></i></div>
      </div>
    </div>
  </main>
</body>
</html>"""


def _login_response(status_code: int = 401, *, invalid_credential: bool = False) -> HTMLResponse:
    error = ('<p class="error" role="alert">That link or token didn’t match. Check it and try again.</p>'
             if invalid_credential else "")
    return HTMLResponse(
        _LOGIN_PAGE.replace("<!--AUTH_ERROR-->", error),
        status_code=status_code,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@app.middleware("http")
async def ui_auth(request: Request, call_next):
    """Human web UI gate. Open locally when no token configured; required for tunnel use."""
    if not UI_TOKEN or request.url.path.startswith(_EXEMPT_PREFIXES):
        return await call_next(request)
    if request.url.path == "/login":
        credential = request.query_params.get("token", "")
        is_invalid_submission = request.method == "POST"
        if request.method == "POST":
            # Keep the existing shared UI token as the sole credential. The
            # form is just a safer, easier transport than putting it in the URL.
            from urllib.parse import parse_qs, urlsplit
            form = parse_qs((await request.body()).decode("utf-8", errors="replace"))
            credential = form.get("credential", [""])[0].strip()
            if credential.startswith(("https://", "http://")):
                credential = parse_qs(urlsplit(credential).query).get("token", [""])[0]
        if credential and credential == UI_TOKEN:
            from fastapi.responses import RedirectResponse
            resp = RedirectResponse(url="/", status_code=303 if request.method == "POST" else 302)
            forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
            is_https = request.url.scheme == "https" or forwarded_proto == "https"
            resp.set_cookie("sb_token", UI_TOKEN, httponly=True, samesite="lax", secure=is_https,
                            path="/", max_age=60 * 60 * 24 * 30)
            return resp
        return _login_response(invalid_credential=is_invalid_submission or bool(request.query_params.get("token")))
    token = request.cookies.get("sb_token") or request.headers.get("x-ui-token")
    if token != UI_TOKEN:
        # Direct browser visits should get a deliberate sign-in screen. Keep
        # API/fetch failures machine-readable so clients don't receive HTML
        # where they expect JSON.
        accepts_html = "text/html" in request.headers.get("accept", "").lower()
        is_document = request.headers.get("sec-fetch-dest", "").lower() == "document"
        if request.method == "GET" and (accepts_html or is_document):
            return _login_response()
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


# Capability handshake: the UI checks this list, not just reachability, so a
# stale server can never pose as a compatible one. Add a name here whenever a
# UI surface depends on a new backend route.
API_CAPABILITIES = ["inbox", "steering", "debrief", "onboarding", "taste",
                    "simulation", "passport", "notices", "resolve", "action_gate",
                    "steering_suggestions", "steering_summary",
                    "steering_written_requests", "simulation_semantic_steering"]


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0", "t3_enabled": svc.ladder.t3 is not None,
            "risk_gate_mode": getattr(settings, "risk_gate_mode", "shadow"),
            "capabilities": API_CAPABILITIES}


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


@app.get("/api/action-requests/{question_id}")
def action_request_status(question_id: str, x_agent_key: str | None = Header(default=None)):
    agent = agent_from(x_agent_key)
    try:
        return svc.action_request_status(agent, question_id)
    except SwitchboardError as e:
        return err(e)


@app.get("/api/questions/{question_id}/answer")
def question_answer_status(question_id: str, x_agent_key: str | None = Header(default=None)):
    agent = agent_from(x_agent_key)
    try:
        return svc.action_request_status(agent, question_id, expected_intent=None)
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


@app.post("/steering/{session_id}/suggestions")
def steering_suggestions(session_id: str):
    """Generate optional, proposal-specific change requests with the configured model.

    This is on-demand: the UI calls it only after the user chooses model suggestions.
    Suggestions are inert text until the user selects one and sends it to the agent.
    """
    try:
        session = svc.steering_session(session_id)
        if session["status"] != "open":
            return JSONResponse(status_code=409, content={"error": "SESSION_CLOSED"})
        if session["locked"]:
            return JSONResponse(status_code=409, content={"error": "LOCKED_CATEGORY"})
        if session["pending_steer"]:
            return JSONResponse(status_code=409, content={"error": "STEER_PENDING"})
        adapter = svc.ladder.t3
        if adapter is None:
            return JSONResponse(status_code=503, content={"error": "MODEL_DISABLED"})

        context = {
            "title": session["title"],
            "category": session["category"],
            "project": session.get("project"),
            "current_draft": session["proposal_text"][:4000],
            "agent_offered_changes": [
                {"label": d["label"], "expected_effect": d["expected_effect"]}
                for d in session["directions"]
            ],
        }
        result = adapter.generate(
            json.dumps(context, ensure_ascii=False),
            system=(
                "You help a person think of optional edits to an AI agent's draft. "
                "Return JSON only: {\"suggestions\":[{\"text\":\"...\",\"why\":\"...\"}]}. "
                "Give 2 or 3 short, distinct requests in plain language, different from the listed "
                "agent_offered_changes. Use only facts in the draft. Do not invent options, prices, "
                "availability, or evidence. Phrase each as a request to revise a draft; never approve, "
                "purchase, send, delete, deploy, or execute anything."
            ),
        )
        if not result or not result.get("text"):
            return JSONResponse(status_code=502, content={"error": "MODEL_UNAVAILABLE"})
        raw = str(result["text"]).strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines and lines[0].strip().casefold() in ("```", "```json"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return JSONResponse(status_code=502, content={"error": "MODEL_INVALID_OUTPUT"})

        raw_suggestions = parsed.get("suggestions") if isinstance(parsed, dict) else None
        if not isinstance(raw_suggestions, list) or not 2 <= len(raw_suggestions) <= 3:
            return JSONResponse(status_code=502, content={"error": "MODEL_INVALID_OUTPUT"})
        suggestions, seen = [], set()
        for item in raw_suggestions:
            if not isinstance(item, dict):
                return JSONResponse(status_code=502, content={"error": "MODEL_INVALID_OUTPUT"})
            text = str(item.get("text", "")).strip()
            why = str(item.get("why", "")).strip()
            key = text.casefold()
            if not text or len(text) > 240 or key in seen or len(why) > 180:
                return JSONResponse(status_code=502, content={"error": "MODEL_INVALID_OUTPUT"})
            seen.add(key)
            suggestions.append({"text": text, "why": why})
        return {"suggestions": suggestions, "model": result.get("model")}
    except SwitchboardError as e:
        return err(e)


@app.post("/steering/{session_id}/steer")
def steering_steer(session_id: str, body: dict):
    try:
        request_text = body.get("request_text")
        out = svc.steer(session_id, body.get("edge"), body.get("magnitude", 1),
                        request_text=request_text)
        _demo_revise_if_demo(session_id, body.get("edge"), request_text)
        _sim_revise_if_sim(session_id, body.get("edge"), request_text)
        _notify("steering")
        return out
    except SwitchboardError as e:
        return err(e)


@app.post("/steering/{session_id}/summary")
def steering_summary(session_id: str):
    """On demand, explain the difference between the previous and current draft."""
    try:
        session = svc.steering_session(session_id)
        if session["status"] != "open":
            return JSONResponse(status_code=409, content={"error": "SESSION_CLOSED"})
        if len(session["revisions"]) < 2:
            return JSONResponse(status_code=409, content={"error": "NO_REVISION"})
        adapter = svc.ladder.t3
        if adapter is None:
            return JSONResponse(status_code=503, content={"error": "MODEL_DISABLED"})

        previous = session["revisions"][-2]["proposal_text"]
        current = session["revisions"][-1]["proposal_text"]
        applied = next((event for event in reversed(session["trajectory"])
                        if event["event"] == "steering.applied"), {})
        context = {
            "title": session["title"],
            "category": session["category"],
            "change_requested": applied.get("request_text") or applied.get("label"),
            "previous_draft": previous[:3000],
            "current_draft": current[:3000],
        }
        result = adapter.generate(
            json.dumps(context, ensure_ascii=False),
            system=(
                "Explain the actual differences between two versions of an agent's draft to a nontechnical user. "
                "Return plain text only, at most two short sentences and 240 characters. Use only facts visible in "
                "the drafts and the change request. Do not imply a requested change was completed unless the current "
                "draft shows it. If the drafts are effectively the same, say that plainly. Do not mention version IDs, "
                "approve, or authorize anything."
            ),
        )
        if not result or not result.get("text"):
            return JSONResponse(status_code=502, content={"error": "MODEL_UNAVAILABLE"})
        summary = str(result["text"]).strip()
        if summary.startswith("```"):
            lines = summary.splitlines()
            if lines and lines[0].strip().casefold() in ("```", "```text"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            summary = "\n".join(lines).strip()
        if summary.casefold().startswith("summary:"):
            summary = summary.split(":", 1)[1].strip()
        summary = " ".join(summary.split())
        if not summary:
            return JSONResponse(status_code=502, content={"error": "MODEL_INVALID_OUTPUT"})
        if len(summary) > 240:
            summary = summary[:237].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
        return {"summary": summary, "model": result.get("model")}
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


def _sample_base_proposal(session_id, current_text):
    first = svc.store.query_one(
        "SELECT proposal_text FROM steering_revisions WHERE session_id=? ORDER BY version LIMIT 1",
        (session_id,))
    return first["proposal_text"] if first else current_text


def _sample_label_from_request(request_text):
    value = str(request_text or "").casefold()
    if any(word in value for word in ("cheap", "budget", "cost", "under $", "lower price", "afford")):
        return "Cheaper"
    if "comfort" in value or "comfortable" in value:
        return "More comfort"
    if any(word in value for word in ("explore", "novel", "unusual", "different", "less obvious", "alternative")):
        return "Explore"
    if any(word in value for word in ("simpl", "easy", "easiest", "straightforward")):
        return "Simplify"
    return None


def _rank_sample_proposal(base_text, label):
    lines = str(base_text).splitlines()
    item_indexes = [i for i, line in enumerate(lines)
                    if line.strip().startswith(("·", "•", "-", "*"))
                    or re.match(r"^\s*\d+[.)]\s+", line)]
    if len(item_indexes) != 3:
        order = _DEMO_RANK.get(label, [0, 1, 2])
        if len(DEMO_LAPTOPS) != 3:
            return base_text
        return "\n".join(
            f"{i + 1}. {DEMO_LAPTOPS[j][0]} — ${DEMO_LAPTOPS[j][1]} ({DEMO_LAPTOPS[j][2]})"
            for i, j in enumerate(order))
    prefix = lines[:item_indexes[0]]
    if prefix and prefix[-1].strip().casefold() == "three laptops, first pass:":
        prefix[-1] = "Available options:"
    items = [re.sub(r"^\s*(?:[·•*-]|\d+[.)])\s*", "", lines[i]).strip()
             for i in item_indexes]
    order = _DEMO_RANK.get(label, [0, 1, 2])
    ranked = [f"{i + 1}. {items[j]}" for i, j in enumerate(order)]
    return "\n".join([*prefix, *ranked]).strip()


def _demo_revise_if_demo(session_id, edge, request_text=None):
    """The demo agent answers a steer immediately, on the real rails."""
    s = svc.store.query_one("SELECT * FROM steering_sessions WHERE id=?", (session_id,))
    if not s:
        return
    agent = svc.store.query_one("SELECT * FROM agents WHERE id=?", (s["agent_id"],))
    if not agent or agent["name"] != "switchboard_demo":
        return
    label = (_sample_label_from_request(request_text) if request_text else
             next((d["label"] for d in DEMO_STEER_DIRECTIONS if d["edge"] == edge), "Cheaper"))
    base = _sample_base_proposal(session_id, s["proposal_text"])
    if not label:
        svc.revise_proposal(
            agent, session_id, base,
            note="Sample agent: this preview only demonstrates the four listed choices; the original draft is unchanged.")
        return
    text = _rank_sample_proposal(base, label)
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


def _sim_revise_if_sim(session_id, edge, request_text=None):
    """Simulated agents answer a steer immediately, on the real rails."""
    s = svc.store.query_one("SELECT * FROM steering_sessions WHERE id=?", (session_id,))
    if not s:
        return
    agent = svc.store.query_one("SELECT * FROM agents WHERE id=?", (s["agent_id"],))
    if not agent or not str(agent["name"]).startswith("sim-"):
        return
    import json as _json
    dirs = {d["edge"]: d for d in _json.loads(s["directions_json"])}
    label = _sample_label_from_request(request_text) if request_text else (dirs.get(edge) or {}).get("label")
    base = _sample_base_proposal(session_id, s["proposal_text"])
    if not label:
        svc.revise_proposal(
            agent, session_id, base,
            note="Sample agent: this preview only demonstrates the four listed choices; the original draft is unchanged.")
        return
    text = _rank_sample_proposal(base, label)
    svc.revise_proposal(agent, session_id, text, note=f"simulation agent revised: {label}")


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
    except (ValueError, KeyError, TypeError) as e:
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
