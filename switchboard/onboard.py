"""Generate MCP client configs so a real agent can call Switchboard.

Usage:
  uv run python -m switchboard.onboard --list
  uv run python -m switchboard.onboard --agent codex --api-key-file C:/private/codex.key --out integrations/generated
  uv run python -m switchboard.onboard --agent claude-code --transport http --remote https://your-hub.example
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


AGENTS = {'muse': {'label': 'Muse (Meta)',
          'filename': 'settings.json',
          'tier': 1,
          'target_hint': '~/.config/muse/settings.json (merge the mcpServers block)'},
 'claude-code': {'label': 'Claude Code',
                 'filename': '.mcp.json',
                 'tier': 1,
                 'target_hint': 'workspace root or ~/.claude.json'},
 'codex': {'label': 'Codex CLI',
           'filename': 'config.toml',
           'tier': 1,
           'target_hint': '~/.codex/config.toml (append)'},
 'opencode': {'label': 'OpenCode',
              'filename': 'opencode.json',
              'tier': 1,
              'target_hint': 'project root or ~/.config/opencode/'},
 'cursor': {'label': 'Cursor',
            'filename': 'mcp.json',
            'tier': 2,
            'target_hint': '.cursor/mcp.json (project) or ~/.muse/mcp.json'},
 'claude-desktop': {'label': 'Claude Desktop',
                    'filename': 'claude_desktop_config.json',
                    'tier': 2,
                    'target_hint': '%APPDATA%/Claude — Store builds: '
                                   '%LOCALAPPDATA%/Packages/Claude_*/LocalCache/Roaming/Claude (merge '
                                   'mcpServers, keep existing keys)'},
 'hermes': {'label': 'Hermes Agent',
            'filename': 'hermes-config.yaml',
            'tier': 2,
            'target_hint': '~/.hermes/config.yaml; native Windows: %LOCALAPPDATA%/hermes/config.yaml '
                           '(merge mcp_servers)'},
 'openclaw': {'label': 'OpenClaw',
              'filename': 'openclaw.json',
              'tier': 2,
              'target_hint': '~/.openclaw/openclaw.json (merge mcp.servers)'}}


def render(agent: str, api_key: str = "sb_REPLACE_ME", transport: str = "stdio",
           remote: str | None = None, api_key_file: str | None = None) -> tuple[str, str]:
    spec = AGENTS[agent]
    # One canonical entry, adapted to each client's container shape. A private
    # key-file reference keeps credentials out of config and process arguments.
    if transport == "http":
        endpoint = (remote.rstrip("/") + "/mcp") if remote else _http()["url"]
        server = {"url": endpoint}
    else:
        server = _stdio(api_key, remote)
        if api_key_file:
            server["env"].pop("SWITCHBOARD_AGENT_KEY")
            server["env"]["SWITCHBOARD_AGENT_KEY_FILE"] = os.path.abspath(api_key_file)

    if agent == "codex":
        content = "[mcp_servers.switchboard]\n"
        content += "".join(f"{key} = {json.dumps(value)}\n" for key, value in server.items() if key != "env")
        if "env" in server:
            content += "\n[mcp_servers.switchboard.env]\n"
            content += "".join(f"{key} = {json.dumps(value)}\n" for key, value in server["env"].items())
    elif agent == "hermes":
        # JSON is valid YAML and safely quotes Windows paths and punctuation.
        content = json.dumps({"mcp_servers": {"switchboard": server}}, indent=2)
    elif agent == "opencode":
        native = ({"type": "remote", **server} if transport == "http" else
                  {"type": "local", "command": [server["command"], *server["args"]],
                   "environment": server["env"]})
        content = json.dumps({"$schema": "https://opencode.ai/config.json",
                              "mcp": {"switchboard": native}}, indent=2)
    elif agent == "openclaw":
        content = json.dumps({"mcp": {"servers": {"switchboard": server}}}, indent=2)
    else:
        data = {"mcpServers": {"switchboard": server}}
        if agent == "muse":
            data = {"schema_version": 1, **data}
        content = json.dumps(data, indent=2)
    return spec["filename"], content


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate a Switchboard MCP config for a real agent.")
    ap.add_argument("--agent", choices=sorted(AGENTS))
    ap.add_argument("--api-key", default=os.environ.get("SWITCHBOARD_AGENT_KEY", "sb_REPLACE_ME"))
    ap.add_argument("--api-key-file", default=os.environ.get("SWITCHBOARD_AGENT_KEY_FILE"),
                    help="private credential file; generated configs contain its path, never its contents")
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
    filename, content = render(args.agent, args.api_key, args.transport, args.remote, args.api_key_file)
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{args.agent}-{filename}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content + "\n")
    spec = AGENTS[args.agent]
    print(f"wrote {path}")
    print(f"target: {spec['target_hint']}")
    print("identity: private credential file" if args.api_key_file else
          "identity: SWITCHBOARD_AGENT_KEY (server-side); never share this key publicly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
