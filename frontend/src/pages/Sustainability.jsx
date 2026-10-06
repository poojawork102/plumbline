import { useEffect, useState } from "react";
import { api } from "../lib/api.js";

export default function Sustainability() {
  const [household, setHousehold] = useState(4);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.sustainability(household).then(setData).catch((e) => setError(e.message));
  }, [household]);

  const w = data?.water;
  const max = w ? Math.max(w.legacy_annual_gal, 1) : 1;
  return (
    <div>
      <header className="page-head"><div><span className="eyebrow">EPA WaterSense</span><h1>Water impact</h1></div></header>
      {error && <div className="banner error">{error}</div>}
      <section className="panel">
        <label className="inline">Household size
          <input type="range" min="1" max="12" value={household} onChange={(e) => setHousehold(Number(e.target.value))} />
          <strong>{household}</strong>
        </label>
        {w && (
          <>
            <div className="metrics">
              <div className="metric"><span>Saved per year</span><strong>{w.saved_gal.toLocaleString()} gal</strong><em>{w.saved_pct}% less</em></div>
              <div className="metric"><span>Approx. bill saving</span><strong>₹{data.rupees_saved.toLocaleString("en-IN")}</strong></div>
              <div className="metric"><span>WaterSense</span><strong>{data.watersense.certified_count}/{data.watersense.total}</strong><em>fixtures certified</em></div>
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
    </div>
  );
}
