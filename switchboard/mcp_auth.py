"""OAuth bridge for remote MCP clients.

Agents authenticate with their existing Switchboard API key on a hosted consent
page. The key is checked once and is never returned to the MCP client; OAuth
tokens carry the enabled Switchboard agent id and can be revoked independently.
"""
from __future__ import annotations

import hashlib
import html
import json
import secrets
import time
from urllib.parse import parse_qs, urlencode

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SwitchboardOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """Persist OAuth state in Switchboard's existing SQLite ledger."""

    access_lifetime = 3600
    refresh_lifetime = 60 * 60 * 24 * 30

    def __init__(self, store, public_url: str, authenticate_key):
        self.store = store
        self.public_url = public_url.rstrip("/")
        self.authenticate_key = authenticate_key
        with self.store._lock:
            self.store.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mcp_oauth_clients(
                  client_id TEXT PRIMARY KEY, client_json TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS mcp_oauth_transactions(
                  session_hash TEXT PRIMARY KEY, transaction_json TEXT NOT NULL, expires_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS mcp_oauth_codes(
                  code_hash TEXT PRIMARY KEY, code_json TEXT NOT NULL, expires_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS mcp_oauth_tokens(
                  token_hash TEXT PRIMARY KEY, token_json TEXT NOT NULL, token_type TEXT NOT NULL,
                  family_id TEXT NOT NULL, expires_at REAL NOT NULL, revoked_at REAL);
                CREATE INDEX IF NOT EXISTS mcp_oauth_tokens_family_idx
                  ON mcp_oauth_tokens(family_id);
                """
            )
            self.store.conn.commit()

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        row = self.store.query_one(
            "SELECT client_json FROM mcp_oauth_clients WHERE client_id=?", (client_id,)
        )
        return OAuthClientInformationFull.model_validate_json(row["client_json"]) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self.store.execute(
            "INSERT OR REPLACE INTO mcp_oauth_clients(client_id,client_json,created_at) VALUES(?,?,?)",
            (client_info.client_id, client_info.model_dump_json(), time.time()),
        )

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        session = secrets.token_urlsafe(32)
        data = {
            "client_id": client.client_id,
            "params": params.model_dump(mode="json"),
            "client_name": client.client_name or "MCP client",
        }
        self.store.execute(
            "INSERT INTO mcp_oauth_transactions(session_hash,transaction_json,expires_at) VALUES(?,?,?)",
            (_hash(session), json.dumps(data), time.time() + 600),
        )
        return f"{self.public_url}/oauth/consent?session={session}"

    async def consent_page(self, request: Request):
        form = {}
        if request.method == "POST":
            form_data = parse_qs((await request.body()).decode("utf-8", errors="replace"), keep_blank_values=True)
            form = {key: values[-1] for key, values in form_data.items() if values}
        session = request.query_params.get("session", "") or str(form.get("session", ""))
        row = self.store.query_one(
            "SELECT transaction_json,expires_at FROM mcp_oauth_transactions WHERE session_hash=?",
            (_hash(session),),
        ) if session else None
        if not row or row["expires_at"] < time.time():
            return HTMLResponse("Authorization request expired. Return to Claude and try again.", status_code=400)
        data = json.loads(row["transaction_json"])
        client_name = html.escape(data["client_name"])
        client = await self.get_client(data["client_id"])
        client_home = html.escape(str(client.client_uri)) if client and client.client_uri else "Not provided"
        if request.method == "GET":
            return HTMLResponse(
                "<!doctype html><meta name='viewport' content='width=device-width'>"
                "<meta name='referrer' content='no-referrer'>"
                "<title>Connect Switchboard</title>"
                "<h1>Connect Switchboard</h1>"
                f"<p><b>{client_name}</b> ({client_home}) wants to use a Switchboard agent.</p>"
                "<p>Only continue for a client you trust. Enter that agent's Switchboard key; Switchboard checks it and does not share it with the client.</p>"
                f"<form method='post' action='{self.public_url}/oauth/consent'>"
                f"<input type='hidden' name='session' value='{html.escape(session, quote=True)}'>"
                "<label>Agent key <input type='password' name='agent_key' required autocomplete='off'></label>"
                "<button type='submit' name='decision' value='allow'>Connect</button>"
                "<button type='submit' name='decision' value='deny'>Cancel</button>"
                "</form>",
                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
            )
        if form.get("decision") != "allow":
            self.store.execute("DELETE FROM mcp_oauth_transactions WHERE session_hash=?", (_hash(session),))
            params = AuthorizationParams.model_validate(data["params"])
            query = {"error": "access_denied"}
            if params.state:
                query["state"] = params.state
            redirect_uri = str(params.redirect_uri)
            separator = "&" if "?" in redirect_uri else "?"
            return RedirectResponse(f"{redirect_uri}{separator}{urlencode(query)}", status_code=302,
                                    headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        agent_key = str(form.get("agent_key", ""))
        try:
            agent = self.authenticate_key(agent_key)
        except Exception:
            return HTMLResponse(
                "That Switchboard key was not accepted. Return to Claude and try again.",
                status_code=401,
                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
            )
        self.store.execute("DELETE FROM mcp_oauth_transactions WHERE session_hash=?", (_hash(session),))
        params = AuthorizationParams.model_validate(data["params"])
        code = secrets.token_urlsafe(32)
        auth_code = AuthorizationCode(
            code=code,
            scopes=params.scopes or ["switchboard:access"],
            expires_at=time.time() + 300,
            client_id=data["client_id"],
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
            subject=agent["id"],
        )
        code_data = auth_code.model_dump()
        code_data["code"] = ""
        self.store.execute(
            "INSERT INTO mcp_oauth_codes(code_hash,code_json,expires_at) VALUES(?,?,?)",
            (_hash(code), json.dumps(code_data, default=str), auth_code.expires_at),
        )
        query = {"code": code}
        if params.state:
            query["state"] = params.state
        redirect_uri = str(params.redirect_uri)
        separator = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(f"{redirect_uri}{separator}{urlencode(query)}", status_code=302,
                                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> AuthorizationCode | None:
        row = self.store.query_one(
            "SELECT code_json,expires_at FROM mcp_oauth_codes WHERE code_hash=?", (_hash(authorization_code),)
        )
        if not row or row["expires_at"] < time.time():
            return None
        code_data = json.loads(row["code_json"])
        code_data["code"] = authorization_code
        code = AuthorizationCode.model_validate(code_data)
        return code if code.client_id == client.client_id else None

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        with self.store._lock:
            row = self.store.conn.execute(
                "DELETE FROM mcp_oauth_codes WHERE code_hash=? AND expires_at>? RETURNING code_json",
                (_hash(authorization_code.code), time.time()),
            ).fetchone()
            if row:
                self.store.conn.commit()
                self.store.write_seq += 1
        if not row or authorization_code.client_id != client.client_id:
            raise ValueError("authorization code is expired or already used")
        code_data = json.loads(row["code_json"])
        code_data["code"] = authorization_code.code
        code = AuthorizationCode.model_validate(code_data)
        if not code.subject or code.client_id != client.client_id:
            raise ValueError("authorization code has no Switchboard agent")
        return self._issue_tokens(client.client_id, code.subject, code.scopes, code.resource)

    async def load_refresh_token(self, client: OAuthClientInformationFull,
                                 refresh_token: str) -> RefreshToken | None:
        row = self.store.query_one(
            "SELECT token_json,expires_at,revoked_at,token_type FROM mcp_oauth_tokens WHERE token_hash=?",
            (_hash(refresh_token),),
        )
        if not row or row["token_type"] != "refresh" or row["revoked_at"] is not None or row["expires_at"] < time.time():
            return None
        token_data = json.loads(row["token_json"])
        token_data["token"] = refresh_token
        token = RefreshToken.model_validate(token_data)
        return token if token.client_id == client.client_id else None

    async def exchange_refresh_token(self, client: OAuthClientInformationFull,
                                     refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        if refresh_token.client_id != client.client_id or not refresh_token.subject:
            raise ValueError("refresh token does not belong to this client")
        allowed = set(refresh_token.scopes)
        requested = set(scopes or refresh_token.scopes)
        if not requested.issubset(allowed):
            raise ValueError("requested scope exceeds the original grant")
        with self.store._lock:
            row = self.store.conn.execute(
                "SELECT family_id,revoked_at,expires_at FROM mcp_oauth_tokens WHERE token_hash=?",
                (_hash(refresh_token.token),),
            ).fetchone()
            if not row or row["revoked_at"] is not None or row["expires_at"] < time.time():
                raise ValueError("refresh token is expired or revoked")
            family_id = row["family_id"]
            self.store.conn.execute(
                "UPDATE mcp_oauth_tokens SET revoked_at=? WHERE token_hash=?", (time.time(), _hash(refresh_token.token))
            )
            self.store.conn.execute(
                "UPDATE mcp_oauth_tokens SET revoked_at=? WHERE family_id=? AND token_type='access'",
                (time.time(), family_id),
            )
            self.store.conn.commit()
            self.store.write_seq += 1
        return self._issue_tokens(client.client_id, refresh_token.subject or "", list(requested),
                                  refresh_token.resource, family_id=family_id)

    async def load_access_token(self, token: str) -> AccessToken | None:
        row = self.store.query_one(
            "SELECT token_json,expires_at,revoked_at,token_type FROM mcp_oauth_tokens WHERE token_hash=?",
            (_hash(token),),
        )
        if not row or row["token_type"] != "access" or row["revoked_at"] is not None or row["expires_at"] < time.time():
            return None
        access_data = json.loads(row["token_json"])
        access_data["token"] = token
        access = AccessToken.model_validate(access_data)
        if not access.subject:
            return None
        try:
            if not self.store.query_one("SELECT id FROM agents WHERE id=? AND enabled=1", (access.subject,)):
                return None
        except Exception:
            return None
        return access

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        with self.store._lock:
            row = self.store.conn.execute(
                "SELECT family_id FROM mcp_oauth_tokens WHERE token_hash=?", (_hash(token.token),)
            ).fetchone()
            if row:
                self.store.conn.execute(
                    "UPDATE mcp_oauth_tokens SET revoked_at=? WHERE family_id=?",
                    (time.time(), row["family_id"]),
                )
                self.store.conn.commit()
                self.store.write_seq += 1

    def _issue_tokens(self, client_id: str, agent_id: str, scopes: list[str], resource: str | None,
                      family_id: str | None = None) -> OAuthToken:
        family_id = family_id or secrets.token_urlsafe(24)
        access_raw = secrets.token_urlsafe(32)
        refresh_raw = secrets.token_urlsafe(48)
        now = time.time()
        access = AccessToken(token=access_raw, client_id=client_id, scopes=scopes,
                             expires_at=int(now + self.access_lifetime), resource=resource, subject=agent_id)
        refresh = RefreshToken(token=refresh_raw, client_id=client_id, scopes=scopes,
                               expires_at=int(now + self.refresh_lifetime), resource=resource, subject=agent_id)
        for raw, token, token_type in ((access_raw, access, "access"), (refresh_raw, refresh, "refresh")):
            token_data = token.model_dump()
            token_data["token"] = ""
            self.store.execute(
                "INSERT INTO mcp_oauth_tokens(token_hash,token_json,token_type,family_id,expires_at) VALUES(?,?,?,?,?)",
                (_hash(raw), json.dumps(token_data, default=str), token_type, family_id,
                 token.expires_at or now + self.access_lifetime),
            )
        return OAuthToken(access_token=access_raw, refresh_token=refresh_raw,
                          expires_in=self.access_lifetime, scope=" ".join(scopes))
