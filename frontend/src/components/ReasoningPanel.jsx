import { useState } from "react";

const ACTOR_LABEL = {
  gemini: "AI",
  regex: "Parser",
  controls: "Manual",
  solver: "Solver",
  verifier: "Check",
  deterministic: "Solver",
  cache: "Cache",
  offline: "Offline",
  mixed: "AI + Solver",
};

function Attempt({ a }) {
  return (
    <li className={`attempt ${a.accepted ? "ok" : "bad"}`}>
      <span className="attempt-mark">{a.accepted ? "✓" : "✗"}</span>
      {a.stage === "alternatives" ? "Alt" : "Try"} {a.attempt} · {a.source}
      {a.problems.length > 0 && <span className="problems"> — {a.problems.join("; ")}</span>}
      {a.reasoning && a.accepted && <span className="muted"> — “{a.reasoning}”</span>}
      {a.critique && (
        <details>
          <summary>Critique sent to the model</summary>
          <pre className="critique">{a.critique}</pre>
        </details>
      )}
    </li>
  );
}

/** One line per pipeline step; tap a step for the detail behind it. */
export default function ReasoningPanel({ steps }) {
  const [open, setOpen] = useState(null);
  if (!steps || steps.length === 0) return <p className="muted">Generate a design to see the reasoning.</p>;
  return (
    <ol className="reasoning" data-testid="reasoning">
      {steps.map((s) => {
        const isOpen = open === s.stage;
        const hasMore = s.summary || s.said || s.details?.length || s.attempts?.length;
        return (
          <li key={s.stage} className={`step ${isOpen ? "open" : ""}`}>
            <button type="button" className="step-line" aria-expanded={isOpen} disabled={!hasMore}
              onClick={() => setOpen(isOpen ? null : s.stage)}>
              <span className={`actor actor-${s.actor}`}>{ACTOR_LABEL[s.actor] || s.actor}</span>
              <span className="step-text"><strong>{s.title}</strong> <span>{s.short || s.summary}</span></span>
              {hasMore ? <span className="chev" aria-hidden="true">{isOpen ? "−" : "+"}</span> : null}
            </button>
            {isOpen && (
              <div className="step-body">
                {s.said && <p className="quote">“{s.said}”</p>}
                {s.summary && <p className="muted small">{s.summary}</p>}
                {s.details?.length > 0 && <ul className="step-details">{s.details.map((d) => <li key={d}>{d}</li>)}</ul>}
                {s.attempts?.length > 0 && (
                  <ul className="attempts">
                    {s.attempts.map((a) => <Attempt key={`${a.stage}-${a.attempt}-${a.source}`} a={a} />)}
                  </ul>
                )}
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
