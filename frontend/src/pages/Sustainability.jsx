import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Slider from "../components/Slider.jsx";
import { api } from "../lib/api.js";
import ReportPicker from "../components/ReportPicker.jsx";
import { LAST_DESIGN_KEY } from "./Planner.jsx";

function lastDesign() {
  try {
    const v = JSON.parse(sessionStorage.getItem(LAST_DESIGN_KEY) || "null");
    return v?.design?.status === "ok" ? v : null;
  } catch {
    return null;
  }
}

export default function Sustainability() {
  const saved = useMemo(lastDesign, []);
  const [household, setHousehold] = useState(saved?.design.inputs.household || 4);
  const [sample, setSample] = useState(null);
  const [error, setError] = useState(null);

  // Your own design when you have one; a sample bundle otherwise.
  useEffect(() => {
    if (saved) return;
    api.sustainability(household).then(setSample).catch((e) => setError(e.message));
  }, [household, saved]);

  const w = saved ? saved.design.metrics.water : sample?.water;
  const ws = saved ? saved.design.watersense : sample?.watersense;
  const rupees = w ? Math.round(w.saved_gal * 3.78 * 0.05) : 0;
  const max = w ? Math.max(w.legacy_annual_gal, 1) : 1;

  return (
    <div>
      <header className="page-head">
        <div><span className="eyebrow">EPA WaterSense</span><h1>Water impact</h1></div>
      </header>
      {error && <div className="banner error">{error}</div>}
      {saved ? (
        <p className="muted">
          Your {saved.design.inputs.theme} design · {saved.design.inputs.length_ft}×{saved.design.inputs.width_ft} ft ·
          household of {saved.design.inputs.household}.
        </p>
      ) : (
        <p className="muted">Sample bundle. <Link to="/planner">Generate a design</Link> to see — and download — your own numbers.</p>
      )}
      <section className="panel">
        {!saved && (
          <div className="slider-wrap">
            <Slider name="household" label="Household size" value={household} min={1} max={12}
              format={(v) => `${v} ${v === 1 ? "person" : "people"}`} onChange={setHousehold} />
          </div>
        )}
        {w && (
          <>
            <div className="metrics">
              <div className="metric"><span>Saved per year</span><strong>{w.saved_gal.toLocaleString()} gal</strong><em>{w.saved_pct}% less</em></div>
              <div className="metric"><span>Approx. bill saving</span><strong>₹{rupees.toLocaleString("en-IN")}</strong></div>
              <div className="metric"><span>WaterSense</span><strong>{ws.certified_count}/{ws.total}</strong><em>fixtures certified</em></div>
            </div>
            {["toilet", "shower", "faucet"].map((k) => (
              <div key={k} className="bar-row">
                <span className="cat">{k}</span>
                <div className="bars">
                  <div className="bar legacy" style={{ width: `${(100 * w.legacy_breakdown[k]) / max}%` }}>{w.legacy_breakdown[k].toLocaleString()} gal legacy</div>
                  <div className="bar ours" style={{ width: `${(100 * w.breakdown[k]) / max}%` }}>{w.breakdown[k].toLocaleString()} gal Plumbline</div>
                </div>
              </div>
            ))}
          </>
        )}
      </section>
      {saved && (
        <section className="panel report-panel">
          <h3 className="panel-title">Download report</h3>
          <ReportPicker onDownload={(type) => api.downloadReport(saved.design, saved.selected_option, saved.edits, type)} />
        </section>
      )}
    </div>
  );
}
