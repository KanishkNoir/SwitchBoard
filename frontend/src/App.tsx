import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import DecisionStage from "./components/DecisionStage";
import EvaluationPanel from "./components/Evaluation";
import { AgentsPanel, RulesPanel } from "./components/Manage";
import { InboxPanel, ObjectsPanel, PassportPanel } from "./components/Panels";
import type { DecisionPayload, GroundedObject, InboxItem, TradeOption } from "./types";

const LAPTOPS: TradeOption[] = [
  { id: "framework-13", price: 1599, comfort: 9, complexity: 3, novelty: 4 },
  { id: "eco-air-14", price: 899, comfort: 6, complexity: 1, novelty: 1 },
  { id: "titan-16", price: 2499, comfort: 8, complexity: 5, novelty: 7 },
];

export default function App() {
  const [health, setHealth] = useState<string>("connecting");
  const [t3, setT3] = useState(false);
  const [payload, setPayload] = useState<DecisionPayload | null>(null);
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [objects, setObjects] = useState<GroundedObject[]>([]);
  const [inbox, setInbox] = useState<InboxItem[]>([]);
  const [out, setOut] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [view, setView] = useState<"decision" | "manage" | "evaluation">("decision");
  const [notice, setNotice] = useState("");
  const [imageB64, setImageB64] = useState<string | null>(null);
  const [imageMime, setImageMime] = useState("image/webp");
  const [activeOverlay, setActiveOverlay] = useState<string | null>(null);
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);
  const [phrases, setPhrases] = useState("lamp, laptop, plant");

  const loadInbox = useCallback(async () => {
    try {
      setInbox(await api.inbox());
    } catch {
      /* queue panel keeps its last state */
    }
  }, []);

  useEffect(() => {
    api
      .health()
      .then((h) => {
        setHealth("local server ok");
        setT3(h.t3_enabled);
      })
      .catch(() => setHealth("server unreachable"));
    loadInbox();
    const es = new EventSource("/stream");
    es.onmessage = () => loadInbox();
    return () => es.close();
  }, [loadInbox]);

  const loadTradeoff = async () => {
    setImageSrc(null);
    setObjects([]);
    const p = await api.tradeoff(LAPTOPS);
    setPayload(p);
    setOut(
      "Options\n" +
        LAPTOPS.map((o) => `${o.id}  $${o.price}  comfort ${o.comfort}/10`).join("\n")
    );
  };

  const loadVisual = async () => {
    setImageSrc(null);
    setObjects([]);
    const p = await api.visual("make this workspace calmer", [{ id: "o1", label: "desk lamp" }]);
    setPayload(p);
    setOut("Use “Generate scene + segment” to ground this question in a real segmented image.");
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
      const s = await api.steer(payload, actionId);
      setOut(
        `Steered: ${s.action_id} (${s.edge})\nWeights ${JSON.stringify(s.weights)}\nNew ranking\n` +
          (s.ranked_option_ids ?? []).map((r, i) => `${i + 1}. ${r}`).join("\n")
      );
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
        <div className="logo">
          <i className="on" />
          <i />
          <i />
          <i className="on" />
        </div>
        <h1>
          Switch<em>board</em>
        </h1>
        <span className="tag">Your agents learn when to ask.</span>
        <div className="status">
          <span>
            <span className="dot" />
            {health}
          </span>
          <span>
            reasoning tier: {t3 ? "live (modal → baseten → meta)" : "off — questions will defer"}
          </span>
        </div>
      </header>

      <nav className="viewtabs">
        <button className={view === "decision" ? "tab active" : "tab"} onClick={() => setView("decision")}>
          Decide
        </button>
        <button className={view === "manage" ? "tab active" : "tab"} onClick={() => setView("manage")}>
          Agents &amp; rules
        </button>
        <button
          className={view === "evaluation" ? "tab active" : "tab"}
          onClick={() => setView("evaluation")}
        >
          Evaluation
        </button>
        {notice && <span className="notice">{notice}</span>}
      </nav>

      {view === "evaluation" ? (
        <main style={{ gridTemplateColumns: "1fr" }}>
          <section>
            <EvaluationPanel />
          </section>
        </main>
      ) : view === "manage" ? (
        <main className="manage-grid">
          <section>
            <RulesPanel />
          </section>
          <aside>
            <AgentsPanel />
            <PassportPanel />
          </aside>
        </main>
      ) : (
      <main>
        <section>
          <div className="panel">
            <div className="panel-head">
              <h2>Decision</h2>
              <span className="pill">
                {payload ? payload.agent_id.replace("_", " ") : "no question loaded"}
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
                <input
                  type="file"
                  accept="image/*"
                  hidden
                  onChange={(e) => onUpload(e.target.files?.[0])}
                />
              </label>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span className="mono-note">find:</span>
              <input
                value={phrases}
                onChange={(e) => setPhrases(e.target.value)}
                style={{ flex: 1 }}
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
          </div>
          <ObjectsPanel
            objects={objects}
            selected={selectedLabel}
            onSelect={(o) => {
              setSelectedLabel(o.label);
              setActiveOverlay(o.overlay_png_b64 ?? null);
              if (!o.overlay_png_b64) setOut(`No decoded mask for “${o.label}” — box only.`);
            }}
          />
        </section>

        <aside>
          <InboxPanel
            items={inbox}
            onRefresh={loadInbox}
            onAnswered={(m) => {
              setNotice(m);
              setTimeout(() => setNotice(""), 6000);
            }}
          />
          <PassportPanel />
          <div className="panel">
            <div className="panel-head">
              <h2>How to read this</h2>
            </div>
            <div className="prose">
              <p>
                Every card is one decision, with the evidence that produced it. Edge labels
                are written for <em>this</em> question — the directions are just where your
                hand already is.
              </p>
              <p>
                A category moves shadow → suggest → auto only on confirmed evidence, and
                drops back the moment a correction or a failed canary says it should.
              </p>
            </div>
          </div>
        </aside>
      </main>
      )}
      <footer>
        local-first · ledger on this machine · model calls are opt-in and fail closed · a risk
        target is a policy goal, not a guarantee
      </footer>
    </>
  );
}
