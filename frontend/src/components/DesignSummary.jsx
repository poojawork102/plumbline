import { money } from "../lib/format.js";

export function Metrics({ design }) {
  const m = design.metrics;
  const w = m.water;
  return (
    <div className="metrics">
      <div className="metric"><span>Total cost</span><strong>{money(m.total_cost, design.currency)}</strong>
        <em className="ok">{m.budget_used_pct}% of budget</em></div>
      <div className="metric"><span>Water saved</span><strong>{w.saved_gal.toLocaleString()} gal/yr</strong>
        <em>{w.saved_pct}% less than legacy</em></div>
      <div className="metric"><span>Floor used</span><strong>{m.space_utilization_pct}%</strong>
        <em>limit 40%</em></div>
    </div>
  );
}

export function Checks({ checks, watersense, liveProblems }) {
  return (
    <div className="checks">
      {liveProblems && (
        <div className={`check-row ${liveProblems.length ? "bad" : "ok"}`}>
          {liveProblems.length ? "✗" : "✓"} Edited layout: {liveProblems.length ? liveProblems.join("; ") : "passes verification"}
        </div>
      )}
      {checks.map((c) => (
        <div key={c.name} className={`check-row ${c.passed ? "ok" : "bad"}`}>
          {c.passed ? "✓" : "✗"} {c.name} <span className="muted">{c.detail}</span>
        </div>
      ))}
      <h4 className="subhead">EPA WaterSense</h4>
      {watersense.items.map((w) => (
        <div key={w.category} className={`check-row ${w.certified ? "ok" : "bad"}`}>
          {w.certified ? "✓" : "✗"} {w.category}: {w.rated} {w.unit}
          <span className="muted"> (max {w.limit})</span>
        </div>
      ))}
    </div>
  );
}

export function BillOfMaterials({ bundle, total, currency }) {
  const price = (p) => (p.price_inr !== undefined ? p.price_inr : p.price_usd);
  return (
    <table className="bom">
      <thead><tr><th>Category</th><th>Product</th><th>SKU</th><th>Size</th><th className="num">Price</th></tr></thead>
      <tbody>
        {bundle.map((p) => (
          <tr key={p.id}>
            <td className="cat">{p.category}</td>
            <td><strong>{p.name}</strong>
              <div className="tags">{(p.smart_features || []).slice(0, 3).map((t) => <span key={t} className="tag">{t}</span>)}</div></td>
            <td className="mono">{p.sku}</td>
            <td>{p.dimensions_in.width} × {p.dimensions_in.depth} in</td>
            <td className="num">{money(price(p), currency)}</td>
          </tr>
        ))}
        <tr className="total"><td colSpan="4">Total</td><td className="num">{money(total, currency)}</td></tr>
      </tbody>
    </table>
  );
}
