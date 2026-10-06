import { useState } from "react";
import { useAuth } from "../lib/auth.jsx";
import { canUseKohlerReport, defaultReportType, REPORT_TYPES } from "../lib/personas.js";

/**
 * Choose who the PDF is for, then download. `onDownload(type)` must return a
 * promise resolving to the saved filename.
 * compact: a single row (select + button) for lists.
 */
export default function ReportPicker({ onDownload, compact = false }) {
  const { user } = useAuth();
  const role = user?.role || "homeowner";
  const [type, setType] = useState(() => defaultReportType(role));
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const allowed = (t) => t !== "kohler" || canUseKohlerReport(role);

  async function go() {
    setBusy(true);
    setMsg("Preparing PDF…");
    try {
      setMsg(`Downloaded ${await onDownload(type)}`);
    } catch (e) {
      setMsg(`Report failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  if (compact) {
    return (
      <span className="report-compact">
        <select aria-label="Report type" value={type} onChange={(e) => setType(e.target.value)}>
          {REPORT_TYPES.map((t) => (
            <option key={t.id} value={t.id} disabled={!allowed(t.id)}>
              {t.label}{allowed(t.id) ? "" : " (Kohler sign-in)"}
            </option>
          ))}
        </select>
        <button type="button" className="btn small" onClick={go} disabled={busy}>PDF</button>
        {msg && msg.startsWith("Report failed") && <span className="small bad-text" role="status">{msg}</span>}
      </span>
    );
  }

  return (
    <div className="report-picker">
      <div className="report-types" role="radiogroup" aria-label="Report type">
        {REPORT_TYPES.map((t) => {
          const ok = allowed(t.id);
          return (
            <label key={t.id} className={`report-type ${type === t.id ? "on" : ""} ${ok ? "" : "locked"}`}
              title={ok ? undefined : "Needs a Kohler team sign-in"}>
              <input type="radio" name="report-type" value={t.id} checked={type === t.id} disabled={!ok}
                onChange={() => setType(t.id)} />
              <strong>{t.label}{ok ? "" : " 🔒"}</strong>
              <span className="muted small">{ok ? t.blurb : "Needs a Kohler team sign-in"}</span>
            </label>
          );
        })}
      </div>
      <button type="button" className="btn primary block" onClick={go} disabled={busy}>Download PDF report</button>
      {msg && <p className="small" role="status">{msg}</p>}
    </div>
  );
}
