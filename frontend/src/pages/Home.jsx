import { Link } from "react-router-dom";

const STAGES = [
  ["Understand", "Gemini turns your words into a structured brief. A regex parser is the fallback."],
  ["Select", "Every catalogue bundle is scored; nothing over budget or over 40% floor use survives."],
  ["Arrange", "The model proposes a wall and offset per fixture — never raw coordinates."],
  ["Verify", "Code re-checks clearances, door swing and overlaps independently."],
  ["Repair", "Violations go back to the model as a critique. Two retries, then the solver steps in."],
  ["Compare", "You get three verified options, in 2D and 3D, and can drag fixtures — every drop is re-verified."],
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
      <section className="stages">
        {STAGES.map(([t, d], i) => (
          <div key={t} className="stage">
            <span className="step-num">{String(i + 1).padStart(2, "0")}</span>
            <h3>{t}</h3>
            <p>{d}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
