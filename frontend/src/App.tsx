import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { subscribeStream } from "./stream";
import DecisionStage from "./components/DecisionStage";
import EvaluationPanel from "./components/Evaluation";
import FocusMode from "./components/FocusMode";
import BrandMark from "./components/BrandMark";
import PublicSandbox from "./components/PublicSandbox";
import { AgentsPanel, RulesPanel } from "./components/Manage";
import { AttentionAlerts, DebriefPanel, InboxPanel, ObjectsPanel, PassportPanel } from "./components/Panels";
import { OnboardingWizard } from "./components/Onboarding";
import SteeringPanel from "./components/Steering";
import type { OnboardingState } from "./types";
import type { DecisionPayload, GroundedObject, InboxItem, TradeOption } from "./types";

const LAPTOPS: TradeOption[] = [
  { id: "framework-13", price: 1599, comfort: 9, complexity: 3, novelty: 4 },
  { id: "eco-air-14", price: 899, comfort: 6, complexity: 1, novelty: 1 },
  { id: "titan-16", price: 2499, comfort: 8, complexity: 5, novelty: 7 },
];

export default function App() {
  const [health, setHealth] = useState<string>("connecting");
  const [publicSandbox, setPublicSandbox] = useState(false);
  const [sandboxRevision, setSandboxRevision] = useState(0);
  const [t3, setT3] = useState(false);
  const [steeringSuggestionsAvailable, setSteeringSuggestionsAvailable] = useState(false);
  const [steeringSummaryAvailable, setSteeringSummaryAvailable] = useState(false);
  const [payload, setPayload] = useState<DecisionPayload | null>(null);
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [objects, setObjects] = useState<GroundedObject[]>([]);
  const [inbox, setInbox] = useState<InboxItem[]>([]);
  const [out, setOut] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [view, setView] = useState<"decision" | "manage" | "evaluation" | "debrief">("decision");
  const [focusMode, setFocusMode] = useState(false);
  const [onboarding, setOnboarding] = useState<OnboardingState | null>(null);
  const [wizardDismissed, setWizardDismissed] = useState(false);
  const [showDemo, setShowDemo] = useState(false);
  const demoDialogRef = useRef<HTMLDialogElement>(null);
  const [steeringCount, setSteeringCount] = useState(0);
  const [simBeats, setSimBeats] = useState<{ run: string; beats: string[] } | null>(null);
  const [simError, setSimError] = useState("");
  // Capability handshake: "Ready" means compatible, not just reachable. A
  // stale server (healthy but missing routes) is reported as too old.
  const [missingCaps, setMissingCaps] = useState<string[] | null>(null);
  const [inboxError, setInboxError] = useState(false);
  const [onboardingFailed, setOnboardingFailed] = useState(false);
  const onboardingPending = Boolean(onboarding && !onboarding.completed && !wizardDismissed);

  useEffect(() => {
    if (showDemo) demoDialogRef.current?.showModal();
  }, [showDemo]);

  useEffect(() => {
    api.onboarding().then((s) => { setOnboarding(s); setOnboardingFailed(false); })
      .catch(() => { setOnboarding(null); setOnboardingFailed(true); });
  }, []);
  const segRef = useRef<HTMLDivElement>(null);
  const [segInk, setSegInk] = useState({ x: 2, w: 0 });

  // Liquid morph: one pill glides between segmented-control stops.
  useEffect(() => {
    const el = segRef.current?.querySelector<HTMLElement>(".tab.active");
    if (el) setSegInk({ x: el.offsetLeft, w: el.offsetWidth });
  }, [view]);
  const [notice, setNotice] = useState("");
  const [imageB64, setImageB64] = useState<string | null>(null);
  const [imageMime, setImageMime] = useState("image/webp");
  const [activeOverlay, setActiveOverlay] = useState<string | null>(null);
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);
  const [phrases, setPhrases] = useState("lamp, laptop, plant");

  const inboxHash = useRef("");
  const loadInbox = useCallback(async () => {
    try {
      const list = await api.inbox();
      setInboxError(false);
      const h = JSON.stringify(list.map((i) => [i.id, i.question_text]));
      if (h === inboxHash.current) return; // unchanged: no re-render
      inboxHash.current = h;
      setInbox(list);
    } catch {
      setInboxError(true); // failed load is an error, never an empty queue
    }
  }, []);

  // Every surface the UI renders from a backend route. If the server answers
  // /health but lacks any of these, it is too old — never "Ready".
  const REQUIRED_CAPS = [
    "inbox", "steering", "debrief", "onboarding", "simulation",
    "steering_written_requests", "simulation_semantic_steering",
    "rule_scope_contracts", "rule_correction_preview", "rule_hold_review",
  ];

  const runSimulation = async () => {
    setSimError("");
    if (missingCaps && missingCaps.includes("simulation")) {
      setSimError("The sample-agent service is older than this page. Restart the backend from the latest code, then try again.");
      return;
    }
    try {
      // One live simulation at a time: re-seeding while sample proposals are
      // still open would duplicate everything.
      const live = await api.steering();
      if (live.some((s) => (s.agent?.name ?? "").startsWith("sim-"))) {
        setSimError("Sample agents are already live below — steer or resolve those proposals before seeding again.");
        return;
      }
    } catch {
      /* fall through and let the seed attempt report its own error */
    }
    try {
      const result = await api.simulation();
      setSimBeats({ run: result.run, beats: result.beats });
      await loadInbox();
      setNotice(`Sample queue loaded: ${result.questions.length} questions and ${result.proposals.length} proposals.`);
      setTimeout(() => setNotice(""), 8000);
    } catch {
      setSimError("Sample preview failed — the hub connection dropped mid-seed. Check the hub and retry.");
    }
  };

  useEffect(() => {
    api
      .health()
      .then((h) => {
        const missing = REQUIRED_CAPS.filter((c) => !(h.capabilities ?? []).includes(c));
        setMissingCaps(missing);
        setPublicSandbox((h.capabilities ?? []).includes("public_sandbox"));
        setHealth(missing.length === 0 ? "Connected" : "Server too old");
        setT3(h.t3_enabled);
        setSteeringSuggestionsAvailable((h.capabilities ?? []).includes("steering_suggestions"));
        setSteeringSummaryAvailable((h.capabilities ?? []).includes("steering_summary"));
      })
      .catch(() => {
        setHealth("server unreachable");
        setMissingCaps(null);
        setSteeringSuggestionsAvailable(false);
        setSteeringSummaryAvailable(false);
      });
    loadInbox();
    return subscribeStream(loadInbox);
  }, [loadInbox]);

  const loadTradeoff = async () => {
    setImageSrc(null);
    setObjects([]);
    try {
      const p = await api.tradeoff(LAPTOPS);
      setPayload(p);
      setOut(
        "Options\n" +
          LAPTOPS.map((o) => `${o.id}  $${o.price}  comfort ${o.comfort}/10`).join("\n")
      );
    } catch {
      setOut("The demo didn't load — the hub may be unreachable. Nothing was started.");
    }
  };

  const loadVisual = async () => {
    setImageSrc(null);
    setObjects([]);
    try {
      const p = await api.visual("make this workspace calmer", [{ id: "o1", label: "desk lamp" }]);
      setPayload(p);
      setOut("Use “Generate scene + segment” to ground this question in a real segmented image.");
    } catch {
      setOut("The demo didn't load — the hub may be unreachable. Nothing was started.");
    }
  };

  const segmentCurrent = async (b64: string, mime: string) => {
    const list = phrases.split(",").map((p) => p.trim()).filter(Boolean);
    const s = await api.scout("make this workspace calmer", b64, list.length ? list : ["lamp"], mime);
    setPayload(s.payload);
    setObjects(s.evidence.objects);
    setActiveOverlay(null);
    setSelectedLabel(null);
    setOut(
      `Done — ${s.evidence.objects.length} objects grounded. Click an object below to see its mask. Pick an edge (or arrow key) to steer the preview.`
    );
    return s;
  };

  const loadScout = async () => {
    setBusy("Generating the scene with Muse Image…");
    setOut("");
    try {
      const g = await api.generate(
        "A tidy desk with a red table lamp on the left, a laptop in the center, and a potted plant on the right. Photorealistic, wide shot."
      );
      setImageSrc(`data:image/webp;base64,${g.b64_json}`);
      setImageB64(g.b64_json);
      setImageMime("image/webp");
      setPhrases("red table lamp, laptop, potted plant");
      setBusy("Segmenting with SAM 3.1…");
      await segmentCurrent(g.b64_json, "image/webp");
    } catch {
      setOut("Vision pipeline failed. The question was left unresolved — nothing was guessed.");
    }
    setBusy(null);
  };

  const onUpload = (file: File | undefined) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      const dataUrl = String(reader.result);
      const b64 = dataUrl.split(",")[1] ?? "";
      setImageSrc(dataUrl);
      setImageB64(b64);
      setImageMime(file.type || "image/jpeg");
      setBusy("Segmenting your photo with SAM 3.1…");
      try {
        await segmentCurrent(b64, file.type || "image/jpeg");
      } catch {
        setOut("Segmentation failed for this photo. Nothing was guessed.");
      }
      setBusy(null);
    };
    reader.readAsDataURL(file);
  };

  const steer = async (actionId: string) => {
    if (!payload) return;
    if (payload._options) {
      try {
        const s = await api.steer(payload, actionId);
        setOut(
          `Steered: ${s.action_id} (${s.edge})\nWeights ${JSON.stringify(s.weights)}\nNew ranking\n` +
            (s.ranked_option_ids ?? []).map((r, i) => `${i + 1}. ${r}`).join("\n")
        );
      } catch {
        setOut("That steer didn't go through — the hub may be unreachable. The ranking is unchanged.");
      }
    } else if (imageB64) {
      setBusy("Editing the preview with Muse Image…");
      try {
        const out2 = await api.steerEdit(imageB64, actionId, imageMime);
        setImageSrc(`data:image/webp;base64,${out2.b64_json}`);
        setImageB64(out2.b64_json);
        setImageMime("image/webp");
        setObjects([]);
        setActiveOverlay(null);
        setOut(
          `Preview updated (${actionId}). This is a generated concept, not a photo of a real place. Objects were cleared — re-segment to ground the new image.`
        );
      } catch {
        setOut("Image edit failed. The previous preview was kept; nothing was applied.");
      }
      setBusy(null);
    } else {
      setOut(
        `Steered: ${actionId}\nThe agent would now revise its proposal in that direction. No purchase, send or deletion is authorized by this gesture.`
      );
    }
  };

  return (
    <>
      <header>
        <BrandMark className="header-mark" />
        <h1>
          Switch<em>board</em>
        </h1>
        <span className="tag">Your agents learn when to ask.</span>
        <div className="status">
          <span>
            <span
              className="dot"
              style={{ background: health === "Connected" ? "var(--green)" : "var(--red, #d70015)" }}
            />
            {health === "Connected"
              ? "Ready"
              : health === "Server too old"
                ? "Server too old — restart it from the latest code"
                : "Can't reach your hub — answers will wait"}
          </span>
          <span className="tier">
            {publicSandbox ? "Sample workspace · model calls off" : t3 ? "Reasoning: on" : "Reasoning: off — questions will wait for you"}
          </span>
        </div>
      </header>

      {publicSandbox && <PublicSandbox compact={focusMode}
        onFocus={() => setFocusMode(true)}
        onManage={() => { setFocusMode(false); setView("manage"); }}
        onChange={() => { loadInbox(); setSandboxRevision((v) => v + 1); }} />}

      {!onboardingPending && !focusMode && <nav className="viewtabs">
        <div className="seg" role="tablist" aria-label="Views" ref={segRef}>
          <span
            className="seg-ink"
            style={{ transform: `translateX(${segInk.x - 2}px)`, width: segInk.w }}
          />
          <button className={view === "decision" ? "tab active" : "tab"} onClick={() => setView("decision")}>
            Decide{inbox.length + steeringCount > 0 ? ` · ${inbox.length + steeringCount}` : ""}
          </button>
          <button className={view === "debrief" ? "tab active" : "tab"} onClick={() => setView("debrief")}>
            Debrief
          </button>
          <button className={view === "manage" ? "tab active" : "tab"} onClick={() => setView("manage")}>
            Agents &amp; rules
          </button>
        </div>
        {!publicSandbox && <button className="how-link" onClick={() => setShowDemo(true)} aria-haspopup="dialog">
          How it works <span aria-hidden="true">↗</span>
        </button>}
        {notice && <span className="notice">{notice}</span>}
      </nav>}
      {!focusMode && view === "decision" && (
        <section className="desk-hero" aria-label="Switchboard decision desk">
          <div className="desk-copy">
            <span className="desk-kicker"><i /> CROSS-AGENT DECISION CONTROL</span>
            <h2 className="kinetic-title">Keep every agent <span className="kinetic-word">decision</span> in view.</h2>
            <p>Review requests, steer proposals, and set boundaries in one place.</p>
          </div>
          <svg className="desk-geometry" viewBox="0 0 320 150" fill="none" aria-hidden="true">
            <circle className="bauhaus-ring" cx="251" cy="78" r="55" />
            <path className="bauhaus-arc" d="M196 78a55 55 0 0 1 55-55v55h-55Z" />
            <rect className="bauhaus-square" x="70" y="36" width="30" height="30" rx="2" transform="rotate(-12 70 36)" />
            <path className="bauhaus-rule" d="M33 111h112M46 120h66" />
          </svg>
          <div className="desk-routing" aria-hidden="true">
            <svg className="desk-flow" viewBox="0 0 240 90" preserveAspectRatio="none">
              <path className="flow-line flow-blue" d="M0 18 C35 18 35 43 82 43 S133 18 174 25 S207 43 240 43" />
              <path className="flow-line flow-green" d="M0 43 C32 43 42 43 82 43 S133 68 174 61 S207 43 240 43" />
              <path className="flow-line flow-orange" d="M0 68 C35 68 35 43 82 43 S133 18 174 25 S207 43 240 43" />
              <circle className="flow-node node-blue" cx="82" cy="43" r="3" />
              <circle className="flow-node node-orange" cx="174" cy="25" r="3" />
              <circle className="flow-node node-green" cx="174" cy="61" r="3" />
            </svg>
            <div className="route-agents"><i /><i /><i /><span>AGENTS</span></div>
            <span className="route-wire" />
            <BrandMark className="route-hub-mark" />
            <span className="route-wire" />
            <div className="route-person"><b>YOU</b><i /></div>
          </div>
        </section>
      )}
      {missingCaps !== null && missingCaps.length > 0 && (
        <div className="compat-banner" role="alert">
          This page is ahead of the backend. Restart the Switchboard server from the latest code, then reload.
          Steering and some newer features may not work until then.
        </div>
      )}
      {onboardingFailed && (
        <div className="compat-banner compat-dim" role="alert">
          Setup state couldn't be loaded — showing defaults. Retry from Refresh below.
        </div>
      )}
      {!focusMode && !onboardingPending && view === "decision" && (inbox.length > 0 || steeringCount > 0) && (
        <div className="status-strip">
          {inbox.length > 0 && <span>{inbox.length} waiting on you</span>}
          {steeringCount > 0 && <span>{steeringCount} proposal{steeringCount > 1 ? "s" : ""} to steer</span>}
          {inbox.length === 0 && steeringCount > 0 && <span>nothing blocking — steer when ready</span>}
          <button className="focus-launch" onClick={() => setFocusMode(true)}>Start focus <span aria-hidden="true">→</span></button>
        </div>
      )}
      {onboarding && !onboarding.completed && !wizardDismissed ? (
        <main className="view-morph" style={{ gridTemplateColumns: "minmax(0, 640px)", justifyContent: "center" }}>
          <OnboardingWizard state={onboarding} onDone={() => setWizardDismissed(true)} />
        </main>
      ) : focusMode ? (
        <FocusMode
          items={inbox}
          onRefresh={loadInbox}
          modelEnabled={t3 && steeringSuggestionsAvailable}
          summaryEnabled={t3 && steeringSummaryAvailable}
          onExit={() => setFocusMode(false)}
          onAnswered={(m) => {
            setNotice(m);
            setTimeout(() => setNotice(""), 6000);
          }}
        />
      ) : view === "debrief" ? (
        <main className="view-morph" style={{ gridTemplateColumns: "1fr" }}>
          <div>
            <DebriefPanel onGoToDecide={() => setView("decision")} />
            <div className="taprow" style={{ marginTop: 12 }}>
              <button className="linkbtn" onClick={() => setView("evaluation")}>
                Proof — evaluation &amp; replay evidence →
              </button>
            </div>
          </div>
        </main>
      ) : view === "evaluation" ? (
        <main className="view-morph" style={{ gridTemplateColumns: "1fr" }}>
          <section>
            <EvaluationPanel />
          </section>
        </main>
      ) : view === "manage" ? (
        <main className="manage-grid view-morph">
          <section>
            <AttentionAlerts />
            <RulesPanel key={sandboxRevision} />
          </section>
          <aside>
            <AgentsPanel readOnly={publicSandbox} />
          </aside>
        </main>
      ) : (
      <>
      <main className={`view-morph decision-layout${inbox.length === 0 && steeringCount === 0 ? " is-clear" : ""}`}>
        <section>
          {/* Keep decisions first; steering is optional until a proposal exists. */}
          <InboxPanel
            items={inbox}
            onRefresh={loadInbox}
            loadError={inboxError}
            onPreviewSample={runSimulation}
            simulationError={simError}
            proposalCount={steeringCount}
            onAnswered={(m) => {
              setNotice(m);
              setTimeout(() => setNotice(""), 6000);
            }}
          />
          <SteeringPanel
            onCount={setSteeringCount}
            modelEnabled={t3 && steeringSuggestionsAvailable}
            summaryEnabled={t3 && steeringSummaryAvailable}
            onEvent={(m) => {
              setNotice(m);
              setTimeout(() => setNotice(""), 6000);
            }}
          />
        </section>

        <aside>
          <PassportPanel />
        </aside>
      </main>

      {showDemo && (
        <dialog
          ref={demoDialogRef}
          className="demo-dialog panel"
          aria-labelledby="demo-title"
          onCancel={(event) => { event.preventDefault(); setShowDemo(false); }}
          onClick={(event) => { if (event.target === event.currentTarget) setShowDemo(false); }}
        >
          <div className="demo-dialog-head">
            <div>
              <span className="demo-kicker">GUIDED SANDBOX</span>
              <h2 id="demo-title">See how Switchboard works</h2>
              <p>Steer a sample suggestion and explore visual grounding. This won’t change a real agent’s work.</p>
            </div>
            <button className="demo-close" autoFocus onClick={() => setShowDemo(false)}>Close</button>
          </div>
          {simBeats && (
            <div className="sim-beats">
              <div className="trajectory-title">Simulation live — your four beats</div>
              <ol>
                {simBeats.beats.map((beat, index) => <li key={index}>{beat}</li>)}
              </ol>
              <div className="taprow" style={{ marginTop: 10 }}>
                <button className="primary" onClick={() => { setShowDemo(false); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
                  Take me to them ↑
                </button>
              </div>
            </div>
          )}
          <div className="panel-head">
            <span className="pill">
              {payload ? `demo · ${payload.agent_id.replace("_", " ")}` : "demo · nothing loaded"}
            </span>
          </div>
          <DecisionStage
            payload={payload}
            imageSrc={imageSrc}
            objects={objects}
            busy={busy}
            onSteer={steer}
            activeOverlay={activeOverlay}
          />
          <div className="btnrow">
            <button onClick={loadTradeoff}>Trade-off demo</button>
            <button onClick={loadVisual}>Visual demo</button>
            <button className="primary" disabled={busy !== null} onClick={loadScout}>
              {busy ? "Working…" : "Generate scene + segment with SAM 3.1"}
            </button>
            <label className="upload-btn">
              Upload your photo
              <input type="file" accept="image/*" hidden onChange={(event) => onUpload(event.target.files?.[0])} />
            </label>
          </div>
          <div className="demo-phrases">
            <span className="mono-note">find:</span>
            <input
              value={phrases}
              onChange={(event) => setPhrases(event.target.value)}
              aria-label="Objects to find, comma separated"
            />
            {imageB64 && (
              <button
                disabled={busy !== null}
                onClick={async () => {
                  setBusy("Segmenting with SAM 3.1…");
                  try {
                    await segmentCurrent(imageB64, imageMime);
                  } catch {
                    setOut("Segmentation failed. Nothing was guessed.");
                  }
                  setBusy(null);
                }}
              >
                Re-segment
              </button>
            )}
          </div>
          {out && <pre className="out">{out}</pre>}
          <ObjectsPanel
            objects={objects}
            selected={selectedLabel}
            onSelect={(object) => {
              setSelectedLabel(object.label);
              setActiveOverlay(object.overlay_png_b64 ?? null);
              if (!object.overlay_png_b64) setOut(`No decoded mask for “${object.label}” — box only.`);
            }}
          />
        </dialog>
      )}
      </>
      )}
      <footer>
        Your agents ask first. You stay in control — every answer is recorded, and a
        risk target is a goal, never a guarantee.
      </footer>
    </>
  );
}
