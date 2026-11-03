import { randomUUID } from "node:crypto"
import { readFile } from "node:fs/promises"
import { join } from "node:path"

const READ_ONLY_BUILTINS = new Set([
  "read", "glob", "grep", "list", "webfetch", "websearch", "lsp",
  "lsp_diagnostics", "lsp_symbols", "git_diff", "git_status",
])

const OWN_SWITCHBOARD_TOOLS = new Set([
  "ask", "get_rules", "get_action_request_status", "record_use", "report_outcome",
])

async function loadCredentials(directory) {
  let configured = {}
  for (const filename of ["opencode.json", "opencode.jsonc"]) {
    try {
      const parsed = JSON.parse(await readFile(join(directory, filename), "utf8"))
      const servers = parsed.mcp ?? {}
      const entry = Object.entries(servers).find(([name]) => name.toLowerCase().includes("switchboard"))
      if (entry) configured = entry[1].environment ?? {}
      break
    } catch {
      // An absent or non-JSONC project config is fine; environment variables can supply credentials.
    }
  }
  let key = process.env.SWITCHBOARD_AGENT_KEY || configured.SWITCHBOARD_AGENT_KEY || ""
  if (!key || key.startsWith("${")) {
    const keyFile = process.env.SWITCHBOARD_AGENT_KEY_FILE || configured.SWITCHBOARD_AGENT_KEY_FILE
    key = keyFile ? (await readFile(keyFile, "utf8")).trim() : ""
  }
  const baseUrl = (process.env.SWITCHBOARD_REMOTE_URL || configured.SWITCHBOARD_REMOTE_URL || "").replace(/\/+$/, "")
  if (baseUrl) {
    const parsed = new URL(baseUrl)
    if (parsed.protocol !== "https:" && !["localhost", "127.0.0.1"].includes(parsed.hostname)) {
      throw new Error("Switchboard guard requires HTTPS for a remote hub")
    }
  }
  return { key, baseUrl }
}

function isSwitchboardTool(name) {
  const normalized = String(name || "").toLowerCase()
  return normalized.startsWith("switchboard_") || normalized.startsWith("switchboard.") ||
    OWN_SWITCHBOARD_TOOLS.has(normalized)
}

function isExplicitlyReadOnly(name) {
  const normalized = String(name || "").toLowerCase()
  return READ_ONLY_BUILTINS.has(normalized) || normalized.startsWith("lsp_")
}

function actionSummary(tool, args) {
  const fields = args && typeof args === "object" && !Array.isArray(args)
    ? Object.keys(args).sort()
    : []
  const summary = { tool, argument_fields: fields }
  const target = args?.filePath ?? args?.path
  if (typeof target === "string") summary.target = target.split(/[\\/]/).filter(Boolean).at(-1) ?? ""
  const command = args?.command ?? args?.cmd
  if (typeof command === "string") {
    summary.command_prefix = command.trim().split(/\s+/).slice(0, 2).join(" ").slice(0, 100)
  }
  return summary
}

function isAllow(answer) {
  if (!answer || typeof answer !== "object") return false
  if (answer.allow === true || answer.option_id === "allow") return true
  return typeof answer.value === "string" && answer.value.trim().toLowerCase() === "allow"
}

function isDeny(answer) {
  if (!answer || typeof answer !== "object") return false
  if (answer.allow === false || answer.option_id === "deny") return true
  return typeof answer.value === "string" && answer.value.trim().toLowerCase() === "deny"
}

async function requestJson(credentials, path, method, body) {
  if (!credentials.key || !credentials.baseUrl) {
    throw new Error("Switchboard guard is not configured; the action was blocked")
  }
  let response
  try {
    response = await fetch(`${credentials.baseUrl}${path}`, {
      method,
      headers: {
        "content-type": "application/json",
        "x-agent-key": credentials.key,
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: AbortSignal.timeout(15000),
    })
  } catch {
    throw new Error("Switchboard is unreachable; the action was blocked")
  }
  if (!response.ok) throw new Error(`Switchboard returned HTTP ${response.status}; the action was blocked`)
  return response.json()
}

async function waitForHumanAnswer(credentials, questionId) {
  const maxWaitMs = Math.min(
    Math.max(Number(process.env.SWITCHBOARD_GUARD_WAIT_MS) || 300000, 1000),
    900000,
  )
  const stopAt = Date.now() + maxWaitMs
  while (Date.now() < stopAt) {
    const status = await requestJson(credentials, `/api/action-requests/${encodeURIComponent(questionId)}`, "GET")
    if (status.status === "answered") return status
    if (status.status !== "pending") throw new Error("Switchboard could not verify the answer; the action was blocked")
    await new Promise((resolve) => setTimeout(resolve, 2000))
  }
  throw new Error(`Switchboard left this action pending (${questionId}); no action was run`)
}

export const SwitchboardGate = async ({ directory }) => {
  // Keep the hook registered even when configuration is broken. Throwing
  // during plugin initialization can leave OpenCode without a gate at all.
  let credentials
  try {
    credentials = await loadCredentials(directory)
  } catch {
    credentials = { key: "", baseUrl: "" }
  }
  const approvedCalls = new Map()

  return {
    "tool.execute.before": async (input, output) => {
      const tool = String(input.tool || "")
      if (isSwitchboardTool(tool) || isExplicitlyReadOnly(tool)) return

      const reversible = ["write", "edit", "apply_patch"].includes(tool.toLowerCase())
      const summary = actionSummary(tool, output.args)
      const requestId = `opencode-${input.sessionID || "session"}-${input.callID || randomUUID()}`
      const decision = await requestJson(credentials, "/api/ask", "POST", {
        request_id: requestId,
        question: `Allow this one OpenCode action? ${JSON.stringify(summary)}`,
        category: process.env.SWITCHBOARD_ACTION_CATEGORY || "agent_action",
        intent_type: "action_review",
        reversibility: reversible ? "reversible" : "unknown",
        context: { harness: "opencode", tool, session_id: input.sessionID || "" },
        action: { type: tool, ...summary },
        options: [
          { id: "allow", label: "Allow this action once" },
          { id: "deny", label: "Do not run this action" },
        ],
      })

      let approval = decision
      if (decision.decision !== "answer" && decision.question_id) {
        approval = await waitForHumanAnswer(credentials, decision.question_id)
      }
      const answer = approval.answer
      if (isDeny(answer)) throw new Error("Switchboard denied this action; it was not run")
      if (!isAllow(answer) || !approval.receipt_id || !approval.decision_id) {
        throw new Error(`Switchboard deferred this action (${decision.reason_code || "no explicit allow"}); it was not run`)
      }

      await requestJson(credentials, "/api/record_use", "POST", {
        receipt_id: approval.receipt_id,
        dependent_type: "opencode_tool_call",
        dependent_id: `${input.sessionID || "session"}:${input.callID || requestId}`,
        relationship: "authorized_action",
        status: "pending",
      })
      approvedCalls.set(input.callID, { decision_id: approval.decision_id, tool })
    },

    "tool.execute.after": async (input, output) => {
      const approved = approvedCalls.get(input.callID)
      if (!approved) return
      approvedCalls.delete(input.callID)
      try {
        await requestJson(credentials, "/api/report_outcome", "POST", {
          decision_id: approved.decision_id,
          outcome: "success",
          detail: `OpenCode tool ${approved.tool} returned; this is agent-reported evidence.`,
        })
      } catch {
        // The action already ran. Do not turn an audit-reporting failure into a false tool failure.
      }
    },
  }
}
