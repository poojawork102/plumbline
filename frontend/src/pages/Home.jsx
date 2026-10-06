import { Link } from "react-router-dom";

// who: "ai" = the language model, "code" = deterministic code
const STAGES = [
  ["Understand", "ai", "Your words become a structured brief. A regex parser is the fallback."],
  ["Select", "code", "Every catalogue bundle is scored; nothing over budget or over 40% floor use survives."],
  ["Arrange", "ai", "The model proposes a wall and offset per fixture — never raw coordinates."],
  ["Verify", "code", "Clearances, door swing and overlaps are re-checked independently."],
  ["Repair", "ai", "Violations go back to the model as a critique. Two retries, then the solver steps in."],
  ["Compare", "code", "Three verified options in 2D and 3D. Drag fixtures — every drop is re-verified."],
];

export default function Home() {
  return (
    <div className="home">
      <section className="hero">
        <span className="eyebrow">AI bathroom design · verified geometry</span>
        <h1>The language model proposes.<br />Deterministic geometry disposes.</h1>
        <p className="lead">
          Plumbline turns “8×10 spa bathroom, family of 4, ₹6 lakh, touchless” into costed,
          clearance-verified, EPA WaterSense-checked layout options — and shows its reasoning.
        </p>
        <div className="hero-actions">
          <Link to="/planner" className="btn primary">Open the planner</Link>
          <Link to="/sustainability" className="btn">Water impact</Link>
        </div>
      </section>

      <section className="pipeline" aria-labelledby="how-title">
        <div className="pipeline-head">
          <h2 id="how-title">How a design is made</h2>
          <p className="pipeline-legend">
            <span className="who who-ai">AI</span> proposes
            <span className="pipeline-arrow" aria-hidden="true">→</span>
            <span className="who who-code">Code</span> verifies
          </p>
        </div>
        <ol className="stage-grid">
          {STAGES.map(([title, who, text], i) => (
            <li key={title} className={`stage-card stage-${who}`}>
              <div className="stage-top">
                <span className="stage-num" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>
                <span className={`who who-${who}`}>{who === "ai" ? "AI" : "Code"}</span>
              </div>
              <h3>{title}</h3>
              <p>{text}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
