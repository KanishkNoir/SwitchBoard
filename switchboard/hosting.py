"""Compose the operator web app and OAuth MCP app without sharing auth gates."""
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

from starlette.requests import Request


def combined_app(web_app, mcp_app, session_manager):
    web_lifespan = web_app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with web_lifespan(application):
            async with session_manager.run():
                yield

    web_app.router.lifespan_context = lifespan

    class CombinedASGI:
        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                path = scope.get("path", "")
                if path == "/revoke" and scope.get("method") == "POST":
                    # MCP 2.3's revocation model accidentally requires the
                    # optional client_secret field. Public PKCE clients omit
                    # it correctly. Supplying an empty field preserves the
                    # SDK's client authentication, including secret checks for
                    # confidential clients, while accepting public clients.
                    request = Request(scope, receive)
                    if request.headers.get("content-type", "").split(";", 1)[0] == "application/x-www-form-urlencoded":
                        body = await request.body()
                        if "client_secret" not in parse_qs(body.decode("utf-8"), keep_blank_values=True):
                            body += b"&client_secret="
                        scope = {**scope, "headers": [(k, v) for k, v in scope["headers"]
                                 if k.lower() != b"content-length"] + [(b"content-length", str(len(body)).encode())]}
                        original_receive = receive
                        sent = False

                        async def receive():
                            nonlocal sent
                            if not sent:
                                sent = True
                                return {"type": "http.request", "body": body, "more_body": False}
                            return await original_receive()
                if (path in {"/mcp", "/authorize", "/token", "/register", "/revoke", "/oauth/consent"}
                        or path.startswith("/.well-known/")):
                    return await mcp_app(scope, receive, send)
            return await web_app(scope, receive, send)

    return CombinedASGI()
