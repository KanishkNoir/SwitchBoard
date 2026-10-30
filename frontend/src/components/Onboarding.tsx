import { useState } from "react";
import { api } from "../api";
import type { OnboardingState } from "../types";

const RISKS = [
  { key: "careful", label: "Careful", desc: "Target: at most 1 in 100 auto-answers wrong." },
  { key: "balanced", label: "Balanced", desc: "Target: at most 2 in 100. A sensible start." },
  { key: "relaxed", label: "Relaxed", desc: "Target: at most 5 in 100. Fewer interruptions, more trust." },
] as const;

export function OnboardingWizard({ state, onDone }: { state: OnboardingState; onDone: () => void }) {
  const [step, setStep] = useState(0);
  const [modelCalls, setModelCalls] = useState(false);
  const [risk, setRisk] = useState<string>("balanced");
  const finish = async (skip = false) => {
    try {
      await api.completeOnboarding({ model_calls: modelCalls, risk_choice: skip ? "balanced" : risk });
    } catch {
      /* marker is best-effort; never trap the user in setup */
    }
    onDone();
  };
  return (
    <div className="panel wizard">
      <div className="wizard-dots">
        {[0, 1, 2, 3].map((i) => (
          <span key={i} className={i === step ? "dotstep on" : "dotstep"} />
        ))}
      </div>
      {step === 0 && (
        <>
          <h2 className="wizard-title">Your agents ask first.</h2>
          <p className="prose">
            Switchboard sits between you and your AI agents. When an agent is unsure,
            it asks Switchboard. If you've already answered something like it — inside
            the limits you set — the agent carries on. If not, the question lands here,
            once, in one place. Four short choices and you're set up.
          </p>
        </>
      )}
      {step === 1 && (
        <>
          <h2 className="wizard-title">May Switchboard think about your questions?</h2>
          <p className="prose">
            Switchboard can use a model to sort questions and notice which ones match
            your rules. It never needs this to keep you safe: without it, anything
            uncertain simply waits for you. Model calls are off unless you turn them on.
          </p>
          <div className="taprow">
            <button className={!modelCalls ? "primary" : ""} onClick={() => setModelCalls(false)}>
              Keep it simple — ask me
            </button>
            <button className={modelCalls ? "primary" : ""} onClick={() => setModelCalls(true)}>
              Yes, help sort my questions
            </button>
          </div>
          <p className="bb">Right now on this hub, reasoning is {state.t3_enabled ? "available" : "not configured"}.</p>
        </>
      )}
      {step === 2 && (
        <>
          <h2 className="wizard-title">Some things always wait for you.</h2>
          <p className="prose">
            These categories are locked. No rule, no agent, and no gesture can answer
            them — only you, every time. This isn't a setting; it's the deal.
          </p>
          <div className="taprow">
            {state.locked_categories.map((c) => (
              <span key={c} className="pill">{c.replace(/_/g, " ")}</span>
            ))}
          </div>
          <p className="prose">
            Everything else starts in <b>Shadow</b>: Switchboard watches and learns
            what it would have said, but asks you for real. Categories earn more
            independence only from answers you confirm.
          </p>
        </>
      )}
      {step === 3 && (
        <>
          <h2 className="wizard-title">How careful should Switchboard be?</h2>
          <p className="prose">
            Pick an error budget for answers Switchboard may one day give on its own.
            It's a target the risk gate measures against — never a guarantee — and you
            can change it anytime in Agents &amp; rules.
          </p>
          <div style={{ display: "grid", gap: 8 }}>
            {RISKS.map((r) => (
              <button
                key={r.key}
                className={risk === r.key ? "primary riskchoice" : "riskchoice"}
                onClick={() => setRisk(r.key)}
                style={{ textAlign: "left", minHeight: 56 }}
              >
                <b>{r.label}</b> — {r.desc}
              </button>
            ))}
          </div>
        </>
      )}
      <div className="taprow" style={{ marginTop: 18 }}>
        {step > 0 && <button onClick={() => setStep(step - 1)}>Back</button>}
        {step < 3 ? (
          <button className="primary" onClick={() => setStep(step + 1)}>Continue</button>
        ) : (
          <button className="primary" onClick={() => finish(false)}>Start using Switchboard</button>
        )}
        <button className="linkbtn" onClick={() => finish(true)}>Skip setup</button>
      </div>
    </div>
  );
}
