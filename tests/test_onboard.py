import json

from switchboard.onboard import AGENTS, render


def test_all_agents_render_with_key_and_no_secret_leak_beyond_placeholder():
    for name in AGENTS:
        filename, content = render(name, "sb_test_key", "stdio")
        assert filename
        assert "sb_test_key" in content or "8766" in content
        assert "switchboard" in content.lower()


def test_json_configs_parse():
    for name in ("muse", "claude-code", "opencode", "cursor", "claude-desktop", "openclaw"):
        _, content = render(name, "sb_x", "stdio")
        json.loads(content)


def test_http_variants_use_mcp_url():
    for name in AGENTS:
        _, content = render(name, "sb_x", "http")
        assert "127.0.0.1:8766/mcp" in content


def test_muse_uses_settings_mcp_servers_block():
    _, content = render("muse", "sb_x", "stdio")
    data = json.loads(content)
    assert data["schema_version"] == 1
    server = data["mcpServers"]["switchboard"]
    assert server["command"] == "uv"
    assert server["env"]["SWITCHBOARD_AGENT_KEY"] == "sb_x"
    _, http_content = render("muse", "sb_x", "http")
    assert json.loads(http_content)["mcpServers"]["switchboard"]["url"].endswith(":8766/mcp")


def test_opencode_stdio_pins_db_and_cache():
    _, content = render("opencode", "sb_x", "stdio")
    data = json.loads(content)
    env = data["mcp"]["switchboard"]["environment"]
    assert env["SWITCHBOARD_DB"].endswith("switchboard.db")
    assert env["UV_CACHE_DIR"].endswith(".uv-cache")


def test_codex_toml_shape():
    _, content = render("codex", "sb_x", "stdio")
    assert "[mcp_servers.switchboard]" in content
    assert "SWITCHBOARD_AGENT_KEY" in content


def test_all_harnesses_can_reference_a_private_key_file(tmp_path, monkeypatch):
    import tomllib
    project = tmp_path / "project with spaces, and punctuation"
    monkeypatch.setenv("SWITCHBOARD_HOME", str(project))
    key_file = tmp_path / "private agent.key"
    key_file.write_text("sb_private_contents_must_not_be_read")
    for name in AGENTS:
        _, content = render(name, api_key_file=str(key_file), remote="https://hub.example")
        assert "sb_private_contents" not in content
        parsed = tomllib.loads(content) if name == "codex" else json.loads(content)
        if name in ("codex", "hermes"):
            env = parsed["mcp_servers"]["switchboard"]["env"]
        elif name == "opencode":
            env = parsed["mcp"]["switchboard"]["environment"]
        elif name == "openclaw":
            env = parsed["mcp"]["servers"]["switchboard"]["env"]
        else:
            env = parsed["mcpServers"]["switchboard"]["env"]
        assert env["SWITCHBOARD_AGENT_KEY_FILE"] == str(key_file)
        assert "SWITCHBOARD_AGENT_KEY" not in env


def test_hosted_http_configs_use_the_requested_hub():
    for name in AGENTS:
        _, content = render(name, transport="http", remote="https://hub.example/")
        assert "https://hub.example/mcp" in content
        assert "127.0.0.1" not in content
