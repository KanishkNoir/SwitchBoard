"""Generate MCP client configs so a real agent can call Switchboard.

Usage:
  uv run python -m switchboard.onboard --list
  uv run python -m switchboard.onboard --agent codex --api-key sb_... --out integrations/generated
  uv run python -m switchboard.onboard --agent claude-code --api-key sb_... --transport http
"""
import argparse
import json
import os


def _project() -> str:
    # MCP clients spawn servers from the *user's* cwd, not ours: pin the project
    # so `uv run` always resolves Switchboard's own pyproject/.venv.
    return os.environ.get("SWITCHBOARD_HOME") or os.getcwd()


def _stdio(api_key, remote=None):
    # Clients spawn from arbitrary cwd: pin project, the ledger DB, and a writable uv cache.
    # With `remote`, the server proxies to that hub instead of the local ledger
    # (device-agnostic mode); the DB/cache pins stay harmless in that case.
    env = {"SWITCHBOARD_AGENT_KEY": api_key,
           "SWITCHBOARD_DB": os.path.join(_project(), "switchboard.db"),
           "UV_CACHE_DIR": os.path.join(_project(), ".uv-cache")}
    if remote:
        env["SWITCHBOARD_REMOTE_URL"] = remote
    return {"command": "uv",
            "args": ["run", "--project", _project(), "python", "-m", "switchboard.mcp_server"],
            "env": env}


def _http():
    return {"url": "http://127.0.0.1:8766/mcp"}


def _entry(api_key, transport, remote=None):
    return _http() if transport == "http" else _stdio(api_key, remote)


def _mcp_json(api_key, transport, remote=None):
    return json.dumps({"mcpServers": {"switchboard": _entry(api_key, transport, remote)}}, indent=2)


def _muse_json(api_key, transport, remote=None):
    # Muse (verified on 1.4.14) reads MCP servers from the `mcpServers`
    # block of ~/.config/muse/settings.json in the classic command/args/env
    # shape; `muse mcp login` names the same key. Env values are interpolated
    # from the parent environment, so keep them literal here.
    if transport == "http":
        server = {"url": _http()["url"]}
    else:
        server = _stdio(api_key, remote)
    return json.dumps({"schema_version": 1, "mcpServers": {"switchboard": server}}, indent=2)


AGENTS = {
    "muse": {"label": "Muse (Meta)", "filename": "settings.json", "tier": 1,
             "target_hint": "~/.config/muse/settings.json (merge the mcpServers block)",
             "render": _muse_json},
    "claude-code": {"label": "Claude Code", "filename": ".mcp.json", "tier": 1,
                    "target_hint": "workspace root or ~/.claude.json",
                    "render": _mcp_json},
    "codex": {"label": "Codex CLI", "filename": "config.toml", "tier": 1,
              "target_hint": "~/.codex/config.toml (append)",
              "render": lambda k, t, r=None: (
                  '[mcp_servers.switchboard]\n'
                  + (f'url = "{_http()["url"]}"\n' if t == "http" else
                     'command = "uv"\nargs = ["run", "--project", "' + _project().replace("\\", "\\\\") + '", "python", "-m", "switchboard.mcp_server"]\n'
                     f'env = {{ SWITCHBOARD_AGENT_KEY = "{k}", SWITCHBOARD_DB = "' + os.path.join(_project(), "switchboard.db").replace("\\", "\\\\") + '", UV_CACHE_DIR = "' + os.path.join(_project(), ".uv-cache").replace("\\", "\\\\") + '"' + (f', SWITCHBOARD_REMOTE_URL = "{r}"' if r else "") + ' }\n'))},
    "opencode": {"label": "OpenCode", "filename": "opencode.json", "tier": 1,
                 "target_hint": "project root or ~/.config/opencode/",
                 "render": lambda k, t, r=None: json.dumps(
                     {"$schema": "https://opencode.ai/config.json",
                      "mcp": {"switchboard": (
                          {"type": "remote", "url": _http()["url"]} if t == "http" else
                          {"type": "local", "command": ["uv", "run", "--project", _project(), "python", "-m", "switchboard.mcp_server"],
                           "environment": {**{"SWITCHBOARD_AGENT_KEY": k,
                                              "SWITCHBOARD_DB": os.path.join(_project(), "switchboard.db"),
                                              "UV_CACHE_DIR": os.path.join(_project(), ".uv-cache")},
                                           **({"SWITCHBOARD_REMOTE_URL": r} if r else {})}})}}, indent=2)},
    "cursor": {"label": "Cursor", "filename": "mcp.json", "tier": 2,
               "target_hint": ".cursor/mcp.json (project) or ~/.muse/mcp.json",
               "render": _mcp_json},
    "claude-desktop": {"label": "Claude Desktop", "filename": "claude_desktop_config.json", "tier": 2,
                       "target_hint": "%APPDATA%/Claude — Store builds: %LOCALAPPDATA%/Packages/Claude_*/LocalCache/Roaming/Claude (merge mcpServers, keep existing keys)",
                       "render": _mcp_json},
    "hermes": {"label": "Hermes Agent", "filename": "hermes-config.yaml", "tier": 2,
               "target_hint": "~/.hermes/config.yaml (merge mcp_servers)",
               "render": lambda k, t, r=None: (
                   "mcp_servers:\n  switchboard:\n"
                   + (f"    url: {_http()['url']}\n" if t == "http" else
                      f"    command: uv\n    args: [run, --project, {_project()}, python, -m, switchboard.mcp_server]\n"
                      f"    env:\n      SWITCHBOARD_AGENT_KEY: {k}\n"
                      f"      SWITCHBOARD_DB: {os.path.join(_project(), 'switchboard.db')}\n"
                      f"      UV_CACHE_DIR: {os.path.join(_project(), '.uv-cache')}\n"
                      + (f"      SWITCHBOARD_REMOTE_URL: {r}\n" if r else "")))},
    "openclaw": {"label": "OpenClaw", "filename": "openclaw.json", "tier": 2,
                 "target_hint": "~/.openclaw/openclaw.json (merge mcp.servers)",
                 "render": lambda k, t, r=None: json.dumps(
                     {"mcp": {"servers": {"switchboard": _entry(k, t, r)}}}, indent=2)},
}


def render(agent: str, api_key: str, transport: str = "stdio", remote: str | None = None) -> tuple[str, str]:
    spec = AGENTS[agent]
    return spec["filename"], spec["render"](api_key, transport, remote)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate a Switchboard MCP config for a real agent.")
    ap.add_argument("--agent", choices=sorted(AGENTS))
    ap.add_argument("--api-key", default=os.environ.get("SWITCHBOARD_AGENT_KEY", "sb_REPLACE_ME"))
    ap.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    ap.add_argument("--remote", default=None,
                    help="hub base URL (device-agnostic mode): agent calls proxy there")
    ap.add_argument("--out", default="integrations/generated")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)
    if args.list or not args.agent:
        for name, spec in sorted(AGENTS.items(), key=lambda kv: (kv[1]["tier"], kv[0])):
            print(f"tier {spec['tier']}  {name:16s} {spec['label']:22s} -> {spec['target_hint']}")
        return 0
    filename, content = render(args.agent, args.api_key, args.transport, args.remote)
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{args.agent}-{filename}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content + "\n")
    spec = AGENTS[args.agent]
    print(f"wrote {path}")
    print(f"target: {spec['target_hint']}")
    print("identity: SWITCHBOARD_AGENT_KEY (server-side); never share this key publicly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
