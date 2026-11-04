"""Disposable public playground. Never mount this inside the private hub.

Every opaque browser cookie selects a separate in-memory service AND web route
instance. The deployment has no volume, hub credentials, model keys or MCP.
"""
import asyncio
import importlib.util
import json
import os
import re
import secrets
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from pathlib import Path
from types import ModuleType
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse

from .benchmark import isolated_service
from .domain import QuestionRequest
from .service import SwitchboardError

COOKIE = "sb_sandbox"
CONTEXT = {"project": "Photo workshop", "environment": "draft", "audience": "public"}
QUESTION = "What workshop session time should I use?"
CAST = ["Muse Code", "Claude Desktop", "Codex", "Claude Code", "OpenCode", "Hermes", "ChatGPT", "Claude"]
ROOT = Path(__file__).resolve().parents[1]
CAPABILITIES = ["inbox", "steering", "debrief", "onboarding", "taste", "simulation", "passport",
                "notices", "resolve", "action_gate", "steering_written_requests", "simulation_semantic_steering",
                "rule_scope_contracts", "rule_correction_preview", "rule_hold_review", "public_sandbox"]
READ = re.compile(r"^/(?:inbox(?:/[^/]+/detail)?|human/(?:agents|rules(?:/[^/]+/versions)?|attention-health)|"
                  r"steering(?:/[^/]+)?|taste|onboarding|debrief|passport/[^/]+|risk/[^/]+|notices|drift|"
                  r"settings/[^/]+/scope-contract|rules/[^/]+/blast-radius|sandbox/status|evaluation/suite)$")
WRITE = re.compile(r"^/(?:inbox/[^/]+/answer|steering/[^/]+/(?:steer|resolve)|"
                   r"rules(?:/[^/]+/(?:supersede|preview|review-hold))?|decisions/[^/]+/revalidate|"
                   r"notices/[^/]+/(?:dismiss|veto)|demo/(?:steering-proposal|simulation|tradeoff|steer)|"
                   r"sandbox/(?:reuse|preview|correct|reset))$")
SETTINGS = re.compile(r"^/settings/[a-zA-Z0-9_-]{1,64}(?:/scope-contract)?$")


def _web_module(service):
    """Reuse real UI routes without sharing their module-level mutable state."""
    name = f"switchboard._sandbox_web_{secrets.token_hex(12)}"
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("app.py"))
    module = importlib.util.module_from_spec(spec)
    module._provided_service = service
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        module.settings = service.cfg
        module.UI_TOKEN = ""
        # Reconnect periodically so a visitor cannot pin an expired workspace.
        module.app.router.routes = [r for r in module.app.router.routes if getattr(r, "path", None) != "/stream"]

        @module.app.get("/stream")
        async def bounded_stream(request: Request):
            async def events():
                generation = service.store.cache_generation()
                yield ": sandbox stream\n\n"
                for _ in range(25):
                    await asyncio.sleep(1)
                    if await request.is_disconnected():
                        break
                    current = service.store.cache_generation()
                    if current != generation:
                        generation = current
                        yield 'data: {"event":"ledger"}\n\n'
                    else:
                        yield ": keep-alive\n\n"
            return StreamingResponse(events(), media_type="text/event-stream")
        return module
    except BaseException:
        sys.modules.pop(name, None)
        raise


@dataclass
class Workspace:
    service: object
    web: ModuleType
    agents: dict
    rule_id: str
    touched: float
    active: int = 0
    streams: int = 0
    retired: bool = False
    calls: deque = field(default_factory=deque)
    reuse_count: int = 0

    def close(self):
        self.service.store.close()
        sys.modules.pop(self.web.__name__, None)


def new_workspace(now):
    service = isolated_service()
    web = None
    try:
        agents = {}
        for name in CAST:
            registered = service.register_agent(name + " · sample", "sandbox_sample")
            agents[name] = service.authenticate(registered["api_key"])
        # This is fictional initial policy, not collected human calibration.
        made = service.create_rule("event_schedule", {"keywords": ["workshop", "session", "time"], "intent_type": "preference"},
                                   {"value": "Saturday at 10 AM"}, scope={"mandatory": CONTEXT},
                                   source_type="synthetic", actor="sandbox_fixture")
        service.set_stage("event_schedule", "auto", reason="fictional example configuration; not earned promotion")
        for name, work, status in [("Muse Code", "signup-page", "pending"),
                                   ("Claude Desktop", "invitation-draft", "completed")]:
            decision = service.ask(agents[name], QuestionRequest(request_id=work, question=QUESTION,
                category="event_schedule", intent_type="preference", reversibility="reversible", context=CONTEXT))
            service.record_use(agents[name], decision["receipt_id"], "draft", work, "used_answer", status)
        service.set_scope_contract("event_schedule", ["project", "environment", "audience"])
        service.ask(agents["Muse Code"], QuestionRequest(request_id="contact-details",
            question="Should the workshop signup draft include a phone number?", category="contact_display",
            intent_type="preference", reversibility="reversible", context=CONTEXT,
            options=[{"id": "email", "label": "Use email only"}, {"id": "phone", "label": "Include a phone number"}]))
        service.ask(agents["Hermes"], QuestionRequest(request_id="venue-payment",
            question="May I pay the workshop venue $140? (Sample only; no payment will happen.)",
            category="payments", intent_type="permission", reversibility="irreversible", context=CONTEXT))
        # Skip setup only in the disposable example. Do not manufacture labels.
        service.store.emit("system", "sandbox_fixture", "onboarding.completed", "system", "sandbox",
                           {"is_synthetic": True}, evidence_class="synthetic")
        # All preloaded events are synthetic, even those emitted by normal
        # rule setup paths. No fixture evidence enters calibration_examples.
        service.store.execute("UPDATE events SET source_evidence_class='synthetic'")
        web = _web_module(service)
        service.submit_proposal(web._demo_agent(), "Pick a venue for the photography workshop",
            "Three example venues, first pass:\n· Community Studio — $80 (simplest, tables included)\n"
            "· Garden Room — $160 (more comfortable, outdoor space)\n· Rooftop Loft — $240 (most unusual view)",
            "venue_choice", web.DEMO_STEER_DIRECTIONS, project="Photo workshop")
        service.store.execute("UPDATE events SET source_evidence_class='synthetic'")
        return Workspace(service, web, agents, made["rule_id"], now)
    except BaseException:
        if web:
            sys.modules.pop(web.__name__, None)
        service.store.close()
        raise


class PublicSandbox:
    def __init__(self, *, max_sessions=64, ttl=1800, clock=time.monotonic):
        self.sessions = {}
        self.max_sessions, self.ttl, self.clock = max_sessions, ttl, clock
        self.lock = threading.RLock()
        self.creations = deque()

    def _retire(self, key, workspace):
        self.sessions.pop(key, None)
        workspace.retired = True
        if workspace.active == 0:
            workspace.close()

    def close(self):
        with self.lock:
            for key, workspace in list(self.sessions.items()):
                self._retire(key, workspace)

    def _select(self, cookie, create, reset=False):
        now = self.clock()
        with self.lock:
            for key, workspace in list(self.sessions.items()):
                if now - workspace.touched >= self.ttl:
                    self._retire(key, workspace)
            workspace = self.sessions.get(cookie)
            if workspace and not reset:
                return cookie, workspace, False
            if not create:
                return None, None, False
            while self.creations and now - self.creations[0] >= 60:
                self.creations.popleft()
            if len(self.creations) >= 60 or len(self.sessions) >= self.max_sessions and not workspace:
                return None, None, False
            replacement = new_workspace(now)
            if workspace:
                self._retire(cookie, workspace)
            key = secrets.token_urlsafe(32)
            self.sessions[key] = replacement
            self.creations.append(now)
            return key, replacement, True

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    self.close()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return
        request = Request(scope, receive)
        path, method = request.url.path, request.method

        async def reply(data, status=200):
            await JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store"})(scope, receive, send)

        if path == "/health" and method == "GET":
            await reply({"status": "ok", "version": "0.2.0", "build_id": os.environ.get("SWITCHBOARD_BUILD_ID", "development"),
                         "t3_enabled": False, "sandbox": True, "capabilities": CAPABILITIES})
            return
        if path.startswith("/assets/") and method == "GET":
            directory = (ROOT / "frontend/dist/assets").resolve()
            target = (directory / path.removeprefix("/assets/")).resolve()
            if not target.is_relative_to(directory) or not target.is_file():
                await reply({"error": "NOT_FOUND"}, 404)
            else:
                await FileResponse(target)(scope, receive, send)
            return
        if not ((method == "GET" and (path in ("/", "/stream") or READ.fullmatch(path)))
                or (method == "POST" and WRITE.fullmatch(path))
                or (method == "PUT" and SETTINGS.fullmatch(path))):
            await reply({"error": "SANDBOX_ONLY", "detail": "This playground supports sample decisions only. External agents and model calls are disabled."}, 403)
            return
        if method in ("POST", "PUT"):
            origin = request.headers.get("origin")
            if (request.headers.get("sec-fetch-site") == "cross-site" or
                    origin and (urlsplit(origin).netloc != request.headers.get("host") or urlsplit(origin).scheme not in ("http", "https"))):
                await reply({"error": "CROSS_SITE_REQUEST"}, 403)
                return
            if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                await reply({"error": "JSON_REQUIRED"}, 415)
                return
        # Bound actual streamed input too, rather than trusting Content-Length.
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 16384:
                await reply({"error": "SANDBOX_REQUEST_TOO_LARGE"}, 413)
                return
            if not message.get("more_body", False):
                break
        sent_body = False

        async def replay_receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        cookies = SimpleCookie()
        try:
            cookies.load(request.headers.get("cookie", ""))
        except Exception:
            pass
        cookie = cookies[COOKIE].value if COOKIE in cookies else None
        reset = path == "/sandbox/reset" and method == "POST"
        key, workspace, fresh = self._select(cookie, create=path == "/" or reset, reset=reset)
        if workspace is None:
            await reply({"error": "SANDBOX_BUSY" if path == "/" or reset else "SANDBOX_EXPIRED",
                         "detail": "The playground is full. Try again shortly." if path == "/" or reset else "Reload this page to start a fresh sample workspace."},
                        503 if path == "/" or reset else 409)
            return
        with self.lock:
            now = self.clock()
            while workspace.calls and now - workspace.calls[0] >= 60:
                workspace.calls.popleft()
            limited = (workspace.active >= 10 or len(workspace.calls) >= 180
                       or path == "/stream" and workspace.streams >= 2)
            if not limited:
                workspace.calls.append(now)
                workspace.active += 1
                workspace.streams += int(path == "/stream")
                workspace.touched = now
        if limited:
            await reply({"error": "SANDBOX_RATE_LIMIT", "detail": "Please pause briefly, then retry."}, 429)
            return

        async def sandbox_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
                                (b"referrer-policy", b"no-referrer")])
                if fresh:
                    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
                    value = f"{COOKIE}={key}; HttpOnly; SameSite=Lax; Path=/; Max-Age={self.ttl}" + ("; Secure" if secure else "")
                    headers.append((b"set-cookie", value.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            if method != "GET" and workspace.service.store.query_one("PRAGMA page_count")["page_count"] > 1024:
                await JSONResponse({"error": "SANDBOX_FULL", "detail": "Reset the example workspace to keep exploring."}, status_code=429)(scope, replay_receive, sandbox_send)
            elif path.startswith("/sandbox/"):
                try:
                    data = json.loads(body or b"{}")
                    if not isinstance(data, dict):
                        raise ValueError("Object required")
                    result = self._action(workspace, path, data)
                    await JSONResponse(result)(scope, replay_receive, sandbox_send)
                except (ValueError, TypeError, SwitchboardError) as exc:
                    await JSONResponse({"error": getattr(exc, "code", "INVALID_SCHEMA"), "detail": str(exc)}, status_code=400)(scope, replay_receive, sandbox_send)
            else:
                await workspace.web.app(scope, replay_receive, sandbox_send)
        finally:
            with self.lock:
                workspace.active -= 1
                workspace.streams -= int(path == "/stream")
                if workspace.retired and workspace.active == 0:
                    workspace.close()

    def _action(self, workspace, path, body):
        service = workspace.service
        if path in ("/sandbox/status", "/sandbox/reset"):
            return {"sandbox": True, "expires_after_idle_seconds": self.ttl, "sample_agents": CAST,
                    "rule_id": workspace.rule_id, "is_synthetic": True}
        if path == "/sandbox/reuse":
            workspace.reuse_count += 1
            name = CAST[(workspace.reuse_count + 1) % len(CAST)]
            context = {**CONTEXT, **({"project": "Another project"} if body.get("different_project") is True else {})}
            result = service.ask(workspace.agents[name], QuestionRequest(
                request_id=f"try-{workspace.reuse_count}", question=QUESTION, category="event_schedule",
                intent_type="preference", reversibility="reversible", context=context))
            if result["decision"] == "answer":
                service.record_use(workspace.agents[name], result["receipt_id"], "draft", f"sample-draft-{workspace.reuse_count}", "used_answer")
            workspace.web._notify("inbox")
            return {"agent": name + " · sample", "context": context, **result, "is_synthetic": True}
        if path in ("/sandbox/preview", "/sandbox/correct"):
            if path == "/sandbox/preview":
                return service.preview_rule_update(workspace.rule_id, new_answer={"value": "Sunday at 11 AM"})
            expected = body.get("expected_version_id")
            if not isinstance(expected, str) or not expected:
                raise SwitchboardError("CONFIRMATION_REQUIRED", "Preview the current example rule first.")
            result = service.supersede_rule(workspace.rule_id, new_answer={"value": "Sunday at 11 AM"}, expected_version_id=expected)
            workspace.web._notify("inbox")
            return result
        raise ValueError("Unknown sample action")


app = PublicSandbox()
