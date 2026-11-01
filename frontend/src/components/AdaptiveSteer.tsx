import { useState } from "react";
import { api } from "../api";

type Suggestion = { text: string; why: string };

/** Shared optional language-model helper for the existing human steering flow. */
export default function AdaptiveSteer({
  sessionId,
  modelEnabled,
  disabled,
  onSend,
}: {
  sessionId: string;
  modelEnabled: boolean;
  disabled: boolean;
  onSend: (requestText: string) => Promise<boolean>;
}) {
  const [request, setRequest] = useState("");
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const suggest = async () => {
    if (!modelEnabled || disabled || busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.steeringSuggestions(sessionId);
      setSuggestions(result.suggestions);
    } catch {
      setError("Suggestions couldn't be generated. You can still write your request below.");
    } finally {
      setBusy(false);
    }
  };

  const send = async (text: string) => {
    if (disabled || busy || !text.trim()) return;
    setError("");
    if (await onSend(text.trim())) {
      setRequest("");
      setSuggestions([]);
    }
  };

  return (
    <div className="custom-steer">
      <div className="custom-steer-head">
        <div>
          <span className="steerpad-title">Need a different change?</span>
          <span className="steerpad-hint">Write what you want in your own words, or ask for a few ideas.</span>
        </div>
        <button className="suggest-steers" onClick={suggest}
          disabled={!modelEnabled || disabled || busy}
          title={modelEnabled ? "Uses this draft and its choices with your enabled reasoning model" : "Turn on reasoning in Switchboard setup to get model suggestions"}>
          {busy ? "Thinking…" : "Suggest ideas"}
        </button>
      </div>
      <textarea
        value={request}
        onChange={(event) => setRequest(event.target.value.slice(0, 500))}
        maxLength={500}
        rows={2}
        placeholder="For example: focus on what matters most, such as cost, comfort, or simplicity"
        aria-label="Describe the change you want"
        disabled={disabled || busy}
      />
      <div className="custom-steer-foot">
        <span>{modelEnabled
          ? "Suggest ideas shares this proposal and its offered changes with your enabled model."
          : "Model suggestions are off. You can still write and send your own request."}</span>
        <span>{request.length}/500</span>
      </div>
      {error && <div className="custom-steer-error" role="alert">{error}</div>}
      {suggestions.length > 0 && (
        <div className="model-steer-suggestions" aria-label="Model suggested changes">
          {suggestions.map((suggestion, index) => (
            <button key={`${index}-${suggestion.text}`} className="model-steer-suggestion"
              onClick={() => void send(suggestion.text)} disabled={disabled || busy}
              aria-label={`Send change request to agent: ${suggestion.text}`}>
              <span>{suggestion.text}</span>
              {suggestion.why && <small>{suggestion.why}</small>}
            </button>
          ))}
        </div>
      )}
      <div className="custom-steer-actions">
        <button className="primary" onClick={() => void send(request)}
          disabled={disabled || busy || !request.trim()}>
          Ask agent to revise
        </button>
        <span>This sends a change request only. It does not approve the plan.</span>
      </div>
    </div>
  );
}
