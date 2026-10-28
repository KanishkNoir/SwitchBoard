# Switchboard

### Your agents learn when to ask.

Every AI agent you run asks you questions. The same questions. In different words. At the worst possible moments.

One asks which deploy target. Another asks again an hour later. A third applies yesterday's answer to today's completely different situation — confidently, and wrong.

**Switchboard is the layer that fixes this.** It sits between you and your agents, remembers what you actually decided, knows exactly where each decision applies (and where it doesn't), and only interrupts you when interrupting you is genuinely worth it.

> The scarce resource in a multi-agent workflow isn't compute. It isn't context. **It's your attention.**
> Switchboard treats your attention like it matters.

---

## Your morning, before and after

**Without Switchboard:**

```mermaid
flowchart LR
    A[🤖 Agent 1] -->|Which hotel budget?| Y[😩 You]
    B[🤖 Agent 2] -->|Hotel budget??| Y
    C[🤖 Agent 3] -->|Budget for the hotel?| Y
    Y -->|same answer, third time| A
    Y -->|same answer, third time| B
    Y -->|same answer, third time| C
```

**With Switchboard:**

```mermaid
flowchart LR
    A[🤖 Agent 1] --> S
    B[🤖 Agent 2] --> S
    C[🤖 Agent 3] --> S
    S[🎛️ Switchboard] -->|knows already — no bother| A
    S -->|knows already — no bother| B
    S -->|one real question| Y[🙂 You]
    Y -->|answer once| S
```

You answer the question **once**. Every agent hears it. That's the whole idea.

## What it actually does

**Ask less — not blindly less.**
Agents ask Switchboard first. If you've already answered this, in this scope, with a rule that's still current — the agent gets the answer instantly, with a receipt. You never see the question. If not, the question joins a priority queue where truly identical questions are merged into one card. You answer once; every waiting agent gets it.

**Corrections that understand blast radius.**
Change your mind about a preference, and Switchboard doesn't just update a note. It finds *every previous decision that relied on the old rule*, flags the pending ones for revalidation, and shows you the list. No more stale assumptions quietly compounding downstream.

Changed your mind? Here's who finds out:

```mermaid
flowchart LR
    OLD[💬 Old preference<br/>'aisle seat, always'] --> T1[✈️ Flight booked]
    OLD --> T2[🧳 Trip plan]
    OLD --> T3[📧 Email draft]
    YOU[✋ You: 'actually, window now'] --> NEW[💬 New preference]
    NEW -.->|replaces| OLD
    T1 -.->|not flown yet| FIX[🔄 Checked again]
    T2 -.->|already done| LOOK[👀 Shown to you]
    T3 -.->|not sure it was affected| Q[❓ Honestly flagged<br/>never hidden]
```

**Preferences that know their boundaries.**
"Use staging" was your answer *for staging*. When an agent tries to reuse it in production just because the words look similar, Switchboard blocks it. Scope is checked *before* similarity — a hard boundary, not a vibe.

**Evidence with a chain of custody.**
An agent claiming "it worked" is not the same as you confirming it, and Switchboard never pretends otherwise. Agent self-reports, model guesses, and synthetic test data are quarantined by design. Only human-confirmed evidence can teach the system anything.

**Autonomy you can read.**
Every category lives in one of three stages — `shadow` (watching), `suggest` (asking), `auto` (acting) — and its Autonomy Passport tells you exactly why, on what evidence, with what limits. When a correction lands, the flipped slice goes back on probation automatically. No silent promotions. No mystery confidence scores.

Think of it like a new assistant earning trust:

```mermaid
flowchart LR
    A[👀 Watching<br/>learns silently] --> B[🙋 Asking<br/>'shall I?']
    B --> C[✅ Trusted<br/>handles it alone]
    C -->|you correct it| D[🧑‍🏫 Probation<br/>proves it again]
    D -->|gets it right| C
    D -->|gets it wrong| A
```

---

## What happens when an agent asks

```mermaid
flowchart TD
    Q[🤖 'Can I book the cheap flight?'] --> SAFE{Is it risky?<br/>money, deleting, sending}
    SAFE -->|yes| YOU1[🙋 Asks you first<br/>always]
    SAFE -->|no| KNOW{Have you answered<br/>this before?}
    KNOW -->|not really| YOU2[🙋 Asks you<br/>nicely, once]
    KNOW -->|yes| FIT{Does that answer<br/>still fit here?}
    FIT -->|wrong place / changed| YOU2
    FIT -->|fits perfectly| GO[✅ Done<br/>with a receipt you can check]
```

Four questions, in order: *Is it risky? Have we covered this? Does the old answer still fit?* Only then does anything happen without you.

And when it can't answer safely? **It defers. Every time.** Locked actions — money, deletions, messages to new recipients, anything irreversible — *always* come to you in v1. No exceptions, no learned overrides, no Away-mode bypass.

---

## The visual side

Switchboard asks questions with pictures, not just text.

- **Visual Scout** takes an image, segments the objects in it with **SAM 3.1**, and asks one focused question about the actual thing you pointed at — click the lamp, and its real pixel mask lights up.
- **Muse Image** generates and edits concept previews as you steer: cheaper ← → more comfort, explore ↑, keep it simple ↓. Four edges, labels written for *this* question, driven by swipe, click, or arrow keys.
- Generated images are always labelled as concepts. Never dressed up as real listing photos. Prices and facts come from real inputs or are marked unknown.

Gestures steer. They never authorize. A swipe can reshape a proposal — it cannot buy, send, or delete anything.

---

## Quickstart

```powershell
uv sync
uv run python -m switchboard.app
```

Open **http://127.0.0.1:8765** in your browser.

Local-first, always: the ledger lives on your machine, model calls are opt-in, and every provider failure results in a deferral — never a guessed answer.

## Connect your agents (MCP)

Register an agent in the UI (**Agents & rules** tab), put its key in the agent's environment, and point it at Switchboard:

```powershell
$env:SWITCHBOARD_AGENT_KEY = "sb_..."
uv run python -m switchboard.mcp_server          # stdio
# or
$env:SWITCHBOARD_MCP_TRANSPORT = "streamable-http"  # http://127.0.0.1:8766/mcp
uv run python -m switchboard.mcp_server
```

MCP tools: `ask`, `get_rules`, `report_outcome`, `record_use`. Agent identity comes from credentials, never from payload JSON. A workspace `.mcp.json` is included for MCP-compatible clients, and a working demo harness lives in `harness/`.

For frontend development:

```powershell
cd frontend
npm install
npm run dev      # http://127.0.0.1:5173, proxies the API to :8765
npm run build    # FastAPI serves the build at /
```

---

## Does it work? Here's the evidence — including where it doesn't.

Our replay harness runs identical synthetic preference-flip traces against four strategies. After a user changes a preference:

| Approach | Questions handled alone | Wrong answers | Still using your old preference |
|---|---|---|---|
| Never learns (B0) | 91% | 8 | 8 |
| Learns instantly, no probation (B1) | 91% | 0 | 0 |
| **Switchboard (B2)** | **73%** | **0** | **0** |
| Switchboard + trust checks (B3) | **73%** | **0** | **0** |

B2 trades some coverage for safety: after a correction, the flipped slice serves a short probation — a handful of confirmations — while everything unrelated keeps flowing. Under a *noisy* first correction (the fix itself is wrong), that probation measurably wins: 2 wrong auto-answers vs B1's 3. Under a *misscoped* correction, both fail — a hold cannot fix a scope the system was never told, and we show that result instead of hiding it.

Adversarial agents flooding fake "it worked" reports? Measured: a naive system that counts agent labels gets contaminated; Switchboard's count stays at zero.

In plain terms — you change your mind, then we count how often each approach still gives the *old* answer:

```mermaid
xychart-beta
    title "Oops moments after you change your mind (fewer is better)"
    x-axis [Never learns, Learns instantly, Switchboard]
    y-axis "Wrong answers" 0 --> 9
    bar [8, 0, 0]
```

And not everyone's word counts the same. Here's the trust ladder:

```mermaid
flowchart TD
    A[🙋 You said it] -->|trusted| T[✅ Can teach Switchboard]
    B[✋ You corrected it] -->|trusted| T
    C[🔧 A tool proved it happened] -->|partly| P[📋 Proves actions, not wishes]
    D[🤖 An agent said 'trust me'] -->|not enough| Q[🚧 Kept aside]
    E[🎲 A model guessed it] -->|not enough| Q
```

These are synthetic traces, labelled as such, with uncertainty intervals — not a population error guarantee. Anyone who promises you a proven 2% error rate from eleven questions is selling something. We'd rather show the trade-off.

## Test

```powershell
uv run pytest -q
```

40 tests, including a real subprocess MCP-over-HTTP integration test.

---

## Optional model providers

All behind feature flags, all failing safe to a deferral:

| Provider | Role | Model |
|---|---|---|
| Modal | reasoning (T3) | Muse-Spark-Open-816B-A42B (self-hosted endpoint) |
| Baseten | reasoning (T3) | `meta-models/muse-spark-open-1026` |
| Meta Model API | reasoning + SAM 3.1 + Muse Image | `muse-spark-1.3`, `sam-3.1`, `muse-image-1.0` |

Deterministic logic — locks, scope, matching tiers, receipts, authorization — is never delegated to a generative model.

---

*Switchboard doesn't replace your agents. It teaches them the one skill they all lack: knowing when to ask.*
