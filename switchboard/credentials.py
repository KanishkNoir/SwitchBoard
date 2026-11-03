"""Resolve private agent credentials without embedding them in project configs."""
import os
from pathlib import Path


def agent_key(environ=None):
    env = os.environ if environ is None else environ
    value = str(env.get("SWITCHBOARD_AGENT_KEY", "")).strip()
    if value and not value.startswith("${") and value not in ("sb_REPLACE_ME", "sb_YOUR_KEY"):
        return value
    filename = env.get("SWITCHBOARD_AGENT_KEY_FILE")
    if filename:
        try:
            return Path(filename).read_text(encoding="utf-8-sig").strip()
        except (OSError, ValueError):
            pass
    return ""
