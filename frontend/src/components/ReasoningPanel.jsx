import { useState } from "react";

const ACTOR_LABEL = {
  gemini: "Gemini",
  regex: "Offline parser",
  controls: "Manual",
  solver: "Solver",
  verifier: "Verifier",
  deterministic: "Solver",
  cache: "Cache",
  offline: "Offline",
  mixed: "AI + Solver",
};

function Attempt({ a }) {
  const [open, setOpen] = useState(!a.accepted);
  return (
    <li className={`attempt ${a.accepted ? "ok" : "bad"}`}>
      <button type="button" className="attempt-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="attempt-mark">{a.accepted ? "✓" : "✗"}</span>
        {a.stage === "alternatives" ? "Alternative" : "Attempt"} {a.attempt} · {a.source}
        {a.ms ? <span className="muted"> · {a.ms} ms</span> : null}
      </button>
      {open && (
        <div className="attempt-body">
          {a.reasoning && <p className="quote">“{a.reasoning}”</p>}
          {a.arrangement && (
            <p className="mono">
              {Object.entries(a.arrangement).map(([c, v]) => `${c}: ${v.wall} @ ${Math.round(v.offset)}in`).join(" · ")}
            </p>
          )}
          {a.problems.length > 0 ? (
            <ul className="problems">{a.problems.map((p) => <li key={p}>✗ {p}</li>)}</ul>
          ) : (
            <p className="pass">✓ Passed independent spatial verification</p>
          )}
          {a.critique && (
            <details>
              <summary>Critique sent back to the model</summary>
              <pre className="critique">{a.critique}</pre>
            </details>
          )}
        </div>
      )}
    </li>
  );
}

/** Step-by-step view of how the design was produced (AI + deterministic). */
export default function ReasoningPanel({ steps }) {
  if (!steps || steps.length === 0) return <p className="muted">Generate a design to see the reasoning.</p>;
  return (
    <ol className="reasoning" data-testid="reasoning">
      {steps.map((s, i) => (
        <li key={s.stage} className={`step step-${s.stage}`}>
          <div className="step-head">
            <span className="step-num">{String(i + 1).padStart(2, "0")}</span>
            <strong>{s.title}</strong>
            <span className={`actor actor-${s.actor}`}>{ACTOR_LABEL[s.actor] || s.actor}</span>
          </div>
          <p className="step-summary">{s.summary}</p>
          {s.said && <p className="quote">“{s.said}”</p>}
          {s.details?.length > 0 && (
            <ul className="step-details">{s.details.map((d) => <li key={d}>{d}</li>)}</ul>
          )}
          {s.attempts?.length > 0 && (
            <ul className="attempts">{s.attempts.map((a) => <Attempt key={`${a.stage}-${a.attempt}-${a.source}`} a={a} />)}</ul>
          )}
        </li>
      ))}
    </ol>
  );
}
