import type { SteeringSession } from "../types";

function proposalLines(text: string, sample: boolean): string[] {
  const lines = text.split(/\r?\n/).filter((line) =>
    !sample || !/^\s*Revised after your (?:steer|request)\b/i.test(line));
  while (lines.length > 0 && !lines[0].trim()) lines.shift();
  while (lines.length > 0 && !lines[lines.length - 1].trim()) lines.pop();
  return lines;
}

/** Keep paragraphs and option lists readable while marking changed lines. */
export default function ProposalBody({ session }: { session: SteeringSession }) {
  const revisions = session.revisions;
  const sample = session.agent?.kind === "simulation" || session.agent?.name === "switchboard_demo";
  const current = proposalLines(session.proposal_text, sample);
  const previous = revisions.length > 1
    ? proposalLines(revisions[revisions.length - 2].proposal_text, sample)
    : [];

  return (
    <div className="proposal-body">
      {current.map((raw, index) => {
        const line = raw.trim();
        if (!line) return <div className="proposal-gap" key={index} aria-hidden="true" />;
        const match = line.match(/^([·•*-]|\d+[.)])\s+(.*)$/);
        const marker = match?.[1] ?? null;
        const content = match?.[2] ?? line;
        const before = (previous[index] ?? "").trim().replace(/^([·•*-]|\d+[.)])\s+/, "");
        const changed = previous.length > 0 && content.toLowerCase() !== before.toLowerCase();
        const text = changed ? <mark className="rev-new">{content}</mark> : content;

        if (marker) {
          const number = marker.match(/^\d/) ? marker : "•";
          return <div className="proposal-item" key={index}><span className="proposal-marker">{number}</span><span>{text}</span></div>;
        }
        if (/^For the .+ project:$/i.test(line)) return <p className="proposal-context" key={index}>{text}</p>;
        return <p className="proposal-paragraph" key={index}>{text}</p>;
      })}
    </div>
  );
}
