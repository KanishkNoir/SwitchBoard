"""Claude Code PreToolUse gate for Switchboard.

This command reads one Claude hook JSON object from stdin and writes one hook
decision to stdout. It never prints agent credentials or tool argument bodies.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_HUB = "https://kanishksingh-1106--switchboard-web.us-east.modal.run"
READ_ONLY_TOOLS = {
    "Read", "Glob", "Grep", "WebFetch", "WebSearch", "NotebookRead", "LS",
}
SWITCHBOARD_TOOLS = {
    "ask", "get_rules", "get_action_request_status", "record_use", "report_outcome",
}


def project_root() -> Path:
    configured = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[2]


def credentials() -> tuple[str, str]:
    key = os.environ.get("SWITCHBOARD_AGENT_KEY", "")
    url = os.environ.get("SWITCHBOARD_REMOTE_URL", "")
    if not key:
        try:
            config = json.loads((project_root() / ".mcp.json").read_text(encoding="utf-8"))
            servers = config.get("mcpServers", {})
            if not servers:
                servers = config.get("mcp", {})
            for name, server in servers.items():
                if "switchboard" not in name.lower():
                    continue
                env = server.get("env") or server.get("environment") or {}
                key = env.get("SWITCHBOARD_AGENT_KEY", key)
                url = env.get("SWITCHBOARD_REMOTE_URL", url)
                if key:
                    break
        except Exception:
            pass
    url = (url or DEFAULT_HUB).rstrip("/")
    if not key:
        raise RuntimeError("Switchboard agent key unavailable")
    if not url.startswith("https://") and not url.startswith("http://127.0.0.1") and not url.startswith("http://localhost"):
        raise RuntimeError("Switchboard hub must use HTTPS")
    return url, key


def call_api(url: str, key: str, path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url + path,
        data=data,
        method="GET" if body is None else "POST",
        headers={"x-agent-key": key, "Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("Switchboard is unavailable") from exc


def human_answer(url: str, key: str, question_id: str,
                 status_route: str = "/api/action-requests/{question_id}") -> dict:
    wait_seconds = min(max(int(os.environ.get("SWITCHBOARD_GUARD_WAIT_SECONDS", "300")), 1), 900)
    deadline = time.monotonic() + wait_seconds
    endpoint = status_route.format(question_id=urllib.parse.quote(question_id, safe=""))
    while time.monotonic() < deadline:
        status = call_api(url, key, endpoint)
        if status.get("status") == "answered":
            return status
        if status.get("status") != "pending":
            raise RuntimeError("Switchboard could not verify the answer")
        time.sleep(2)
    raise RuntimeError("Switchboard request is still pending")


def answer_for(url: str, key: str, response: dict,
               status_route: str = "/api/action-requests/{question_id}") -> dict:
    if response.get("decision") == "answer":
        answer = response.get("answer") or {}
        receipt_id = response.get("receipt_id")
        decision_id = response.get("decision_id")
    elif response.get("question_id"):
        status = human_answer(url, key, response["question_id"], status_route)
        answer = status.get("answer") or {}
        receipt_id = status.get("receipt_id")
        decision_id = status.get("decision_id")
    else:
        raise RuntimeError("Switchboard deferred this request")
    if not receipt_id or not decision_id:
        raise RuntimeError("Switchboard did not return a valid receipt")
    return {"answer": answer, "receipt_id": receipt_id, "decision_id": decision_id}


def record_use(url: str, key: str, approval: dict, dependent_id: str) -> None:
    call_api(url, key, "/api/record_use", {
        "receipt_id": approval["receipt_id"],
        "dependent_type": "claude_code_tool_call",
        "dependent_id": dependent_id,
        "relationship": "authorized_action",
        "status": "pending",
    })


def emit(decision: str, reason: str, updated_input: dict | None = None) -> None:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    if updated_input is not None:
        output["hookSpecificOutput"]["updatedInput"] = updated_input
    print(json.dumps(output, separators=(",", ":")))


def safe_summary(tool_name: str, tool_input: dict) -> dict:
    fields = sorted(tool_input.keys()) if isinstance(tool_input, dict) else []
    summary: dict = {"tool": tool_name, "argument_fields": fields}
    path = tool_input.get("file_path") or tool_input.get("path") if isinstance(tool_input, dict) else None
    if isinstance(path, str):
        summary["target"] = Path(path).name
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, str):
        tokens = command.strip().split()
        summary["command_prefix"] = " ".join(tokens[:2])[:100]
    return summary


def allow_is_explicit(answer: dict) -> bool:
    if answer.get("allow") is True or answer.get("option_id") == "allow":
        return True
    return str(answer.get("value", "")).strip().lower() == "allow"


def choose_option(answer: dict, options: list[dict]) -> str | None:
    selected = answer.get("option_id") or answer.get("value")
    if selected is None:
        return None
    selected = str(selected).strip()
    for option in options:
        if selected in (option["id"], option["label"]):
            return option["label"]
    return None


def ask_switchboard(url: str, key: str, *, request_id: str, question: str,
                    category: str, intent_type: str, reversibility: str,
                    context: dict, action: dict, options: list[dict],
                    status_route: str = "/api/action-requests/{question_id}") -> dict:
    result = call_api(url, key, "/api/ask", {
        "request_id": request_id,
        "question": question[:4000],
        "category": category,
        "intent_type": intent_type,
        "reversibility": reversibility,
        "context": context,
        "action": action,
        "options": options,
    })
    return answer_for(url, key, result, status_route)


def answer_user_question(event: dict, url: str, key: str) -> None:
    tool_input = event.get("tool_input") or {}
    questions = tool_input.get("questions") or []
    if not questions:
        raise RuntimeError("Claude supplied no question for Switchboard")
    answers = {}
    for index, item in enumerate(questions):
        if item.get("multiSelect"):
            raise RuntimeError("Switchboard currently supports one choice per question")
        text = str(item.get("question") or "").strip()
        raw_options = item.get("options") or []
        options = [
            {"id": f"option_{i + 1}", "label": str(option.get("label") or "").strip()}
            for i, option in enumerate(raw_options) if str(option.get("label") or "").strip()
        ]
        if not text or not options:
            raise RuntimeError("Claude question is missing text or answer options")
        approval = ask_switchboard(
            url, key,
            request_id=f"claude-code-{event.get('session_id', 'session')}-{event.get('tool_use_id', 'call')}-{index}",
            question=text,
            category=os.environ.get("SWITCHBOARD_QUESTION_CATEGORY", "preferences"),
            intent_type="preference",
            reversibility="reversible",
            context={"harness": "claude_code", "question_index": index},
            action={"type": "user_question", "options": [o["label"] for o in options]},
            options=options,
            status_route="/api/questions/{question_id}/answer",
        )
        selected = choose_option(approval["answer"], options)
        if selected is None:
            raise RuntimeError("Switchboard did not choose one of Claude's options")
        dependent = f"{event.get('session_id', 'session')}:{event.get('tool_use_id', 'call')}:{index}"
        record_use(url, key, approval, dependent)
        answers[text] = selected
        save_approval(event, approval, f"question:{index}")
    updated = dict(tool_input)
    updated["answers"] = answers
    emit("allow", "Switchboard supplied the answer", updated)


def state_directory() -> Path:
    path = project_root() / ".tmp" / "claude-switchboard-gate"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path(event: dict, suffix: str = "") -> Path:
    tool_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(event.get("tool_use_id") or "unknown"))
    return state_directory() / f"{tool_id}{suffix}.json"


def save_approval(event: dict, approval: dict, suffix: str = "") -> None:
    state_path(event, suffix).write_text(json.dumps({
        "decision_id": approval["decision_id"],
        "created_at": time.time(),
    }), encoding="utf-8")


def post_outcome(event: dict, outcome: str) -> None:
    try:
        url, key = credentials()
        paths = list(state_directory().glob(state_path(event).stem + "*.json"))
        for path in paths:
            state = json.loads(path.read_text(encoding="utf-8"))
            path.unlink(missing_ok=True)
            call_api(url, key, "/api/report_outcome", {
                "decision_id": state["decision_id"],
                "outcome": outcome,
                "detail": f"Claude Code {event.get('tool_name', 'tool')} completed; agent-reported evidence.",
            })
    except Exception:
        pass


def handle_pre_tool(event: dict) -> None:
    tool_name = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") or {}
    if tool_name in READ_ONLY_TOOLS:
        emit("allow", "Read-only tool")
        return
    mcp_server = event.get("mcp_server") or {}
    server_name = str(mcp_server.get("name") or "").lower()
    if server_name == "switchboard" or tool_name.startswith("mcp__switchboard__"):
        emit("allow", "Switchboard control-plane tool")
        return

    url, key = credentials()
    if tool_name == "AskUserQuestion":
        answer_user_question(event, url, key)
        return

    summary = safe_summary(tool_name, tool_input)
    reversible = tool_name in {"Edit", "Write"}
    approval = ask_switchboard(
        url, key,
        request_id=f"claude-code-{event.get('session_id', 'session')}-{event.get('tool_use_id', 'call')}",
        question=f"Allow this one Claude Code action? {json.dumps(summary, ensure_ascii=False)}",
        category=os.environ.get("SWITCHBOARD_ACTION_CATEGORY", "agent_action"),
        intent_type="action_review",
        reversibility="reversible" if reversible else "unknown",
        context={"harness": "claude_code", "tool": tool_name},
        action={"type": tool_name, **summary},
        options=[
            {"id": "allow", "label": "Allow this action once"},
            {"id": "deny", "label": "Do not run this action"},
        ],
    )
    if not allow_is_explicit(approval["answer"]):
        raise RuntimeError("Switchboard did not explicitly allow this action")
    record_use(url, key, approval, f"{event.get('session_id', 'session')}:{event.get('tool_use_id', 'call')}")
    save_approval(event, approval)
    emit("allow", "Switchboard allowed this one action")


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
        event_name = event.get("hook_event_name")
        if event_name == "PostToolUse":
            post_outcome(event, "success")
            return 0
        if event_name == "PostToolUseFailure":
            post_outcome(event, "failure")
            return 0
        handle_pre_tool(event)
    except Exception as exc:
        reason = str(exc)
        if len(reason) > 250:
            reason = reason[:250]
        emit("deny", f"Switchboard blocked this tool call: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
