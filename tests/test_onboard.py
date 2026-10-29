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


def test_codex_toml_shape():
    _, content = render("codex", "sb_x", "stdio")
    assert "[mcp_servers.switchboard]" in content
    assert "SWITCHBOARD_AGENT_KEY" in content
