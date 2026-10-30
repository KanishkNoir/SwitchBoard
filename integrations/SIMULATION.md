# Multi-agent simulation — pitch run sheet

Three agents, three projects, overlapping categories. Labelled simulation,
real rails: every question and proposal goes through the same service paths a
live harness uses, onto the same ledger. Nothing is faked at the UI layer.

**Cast**

| Agent | Project | Asks about |
|---|---|---|
| sim-opencode | web-app | purchase ($12 domain), deploy to staging |
| sim-claude-code | api-refactor | purchase ($20 CI), deploy a migration |
| sim-hermes | work-trip | payments (locked), hotel proposal |

**Seed it:** Decide tab → Demo playground → “Run multi-agent simulation
(3 agents · 3 projects)”. Seeds 5 questions + 2 steerable proposals
(both in `purchase`, different projects).

**The four beats**

1. **Ask once, apply everywhere.** Answer one purchase question with
   Always… and a limit chip (“Only under $50”). Point at the second agent's
   purchase question: same category, different agent, different project —
   the standing rule already speaks for it.
2. **Steer one, taste transfers.** Steer a proposal “Cheaper”. The agent
   revises in place. Open the Passport (purchase): “How you steer” now
   carries that lean for every agent, not just the one you steered.
3. **Correct once, blast radius everywhere.** Correct the purchase rule in
   Agents & rules. The blast radius lists affected decisions from both
   projects; the category recalibrates for everyone at once.
4. **The locked line holds.** The payments question ignored all of it:
   locked pill, buttons only, no swipe, no rule, no steering. Only a
   deliberate tap answers it.

**Honesty lines for Q&A**

- The agents are simulated; the ledger, rules, steering, and receipts are
  the production code paths. Real harnesses (OpenCode, Muse, Hermes)
  call the identical APIs.
- Steering never accepts; acceptance is the separate version-stamped tap.
- The risk target is a goal the gate measures against, never a guarantee.
