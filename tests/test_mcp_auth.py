from urllib.parse import parse_qs, urlparse

from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from starlette.requests import Request

from switchboard.mcp_auth import SwitchboardOAuthProvider
from switchboard.persistence import Store
from switchboard.service import SwitchboardService


def _run_immediate(coro):
    """Run these I/O-free async provider methods without opening an event loop."""
    while True:
        try:
            yielded = coro.send(None)
        except StopIteration as done:
            return done.value
        if yielded is not None:
            raise AssertionError(f"unexpected async wait in unit test: {yielded!r}")


def _request(method, session, body=b""):
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "https", "path": "/oauth/consent",
        "raw_path": b"/oauth/consent", "query_string": b"",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
        "client": ("127.0.0.1", 1), "server": ("example.test", 443),
    }
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def test_oauth_key_consent_and_token_rotation():
    async def run():
        store = Store(":memory:")
        service = SwitchboardService(store)
        registered = service.register_agent("claude-mobile", "assistant")
        provider = SwitchboardOAuthProvider(store, "https://mcp.example.test", service.authenticate)
        client = OAuthClientInformationFull(
            client_id="claude-client", client_name="Claude", redirect_uris=["https://client.example/callback"])
        await provider.register_client(client)
        params = AuthorizationParams(
            state="state-123", scopes=["switchboard:access"], code_challenge="pkce-challenge",
            redirect_uri="https://client.example/callback", redirect_uri_provided_explicitly=True,
            resource="https://mcp.example.test/mcp")
        consent_url = await provider.authorize(client, params)
        session = parse_qs(urlparse(consent_url).query)["session"][0]
        posted = _request("POST", session,
                          f"session={session}&decision=allow&agent_key={registered['api_key']}".encode())
        response = await provider.consent_page(posted)
        redirect = urlparse(response.headers["location"])
        assert redirect.netloc == "client.example"
        assert parse_qs(redirect.query)["state"] == ["state-123"]
        code_raw = parse_qs(redirect.query)["code"][0]

        code = await provider.load_authorization_code(client, code_raw)
        assert code is not None and code.subject == registered["agent_id"]
        issued = await provider.exchange_authorization_code(client, code)
        access = await provider.load_access_token(issued.access_token)
        assert access is not None and access.subject == registered["agent_id"]
        assert issued.access_token not in store.query_one(
            "SELECT token_json FROM mcp_oauth_tokens WHERE token_type='access'")["token_json"]
        assert registered["api_key"] not in store.query_one(
            "SELECT token_json FROM mcp_oauth_tokens WHERE token_type='access'")["token_json"]

        refresh = await provider.load_refresh_token(client, issued.refresh_token)
        assert refresh is not None
        rotated = await provider.exchange_refresh_token(client, refresh, refresh.scopes)
        assert await provider.load_access_token(issued.access_token) is None
        assert await provider.load_access_token(rotated.access_token) is not None
        with store._lock:
            store.conn.execute("UPDATE agents SET enabled=0 WHERE id=?", (registered["agent_id"],))
            store.conn.commit()
        assert await provider.load_access_token(rotated.access_token) is None
        with store._lock:
            store.conn.execute("UPDATE agents SET enabled=1 WHERE id=?", (registered["agent_id"],))
            store.conn.commit()
        assert await provider.load_access_token(rotated.access_token) is not None
        next_refresh = await provider.load_refresh_token(client, rotated.refresh_token)
        assert next_refresh is not None
        await provider.revoke_token(next_refresh)
        assert await provider.load_access_token(rotated.access_token) is None

    _run_immediate(run())


def test_oauth_consent_rejects_invalid_agent_key():
    async def run():
        store = Store(":memory:")
        service = SwitchboardService(store)
        provider = SwitchboardOAuthProvider(store, "https://mcp.example.test", service.authenticate)
        client = OAuthClientInformationFull(
            client_id="claude-client", client_name="Claude", redirect_uris=["https://client.example/callback"])
        await provider.register_client(client)
        params = AuthorizationParams(
            state="s", scopes=["switchboard:access"], code_challenge="c",
            redirect_uri="https://client.example/callback", redirect_uri_provided_explicitly=True)
        consent_url = await provider.authorize(client, params)
        session = parse_qs(urlparse(consent_url).query)["session"][0]
        response = await provider.consent_page(
            _request("POST", session, f"session={session}&decision=allow&agent_key=sb_invalid".encode()))
        assert response.status_code == 401
        assert store.query_one("SELECT session_hash FROM mcp_oauth_transactions") is not None

    _run_immediate(run())
