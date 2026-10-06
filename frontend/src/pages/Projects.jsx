import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api.js";
import ReportPicker from "../components/ReportPicker.jsx";
import { money } from "../lib/format.js";

export default function Projects() {
  const [projects, setProjects] = useState(null);
  const [error, setError] = useState(null);

  const load = () => api.listProjects().then((r) => setProjects(r.projects)).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function act(fn) {
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div>
      <header className="page-head">
        <div><span className="eyebrow">Cloud saved</span><h1>My projects</h1></div>
        <Link to="/planner" className="btn primary">New design</Link>
      </header>
      {error && <div className="banner error" role="alert">{error}</div>}
      {projects === null && !error && <p className="muted">Loading…</p>}
      {projects?.length === 0 && <p className="muted">No saved designs yet. Generate one in the planner and press “Save to cloud”.</p>}
      <div className="project-grid">
        {projects?.map((p) => (
          <article key={p.id} className="panel project-card">
            <div className="row"><strong>{p.name}</strong><span className={`status ${p.status}`}>{p.status}</span></div>
            <p className="muted small">
              {p.summary.theme} · {p.summary.length_ft}×{p.summary.width_ft} ft · {money(p.summary.total_cost, p.summary.currency)}
              {p.summary.option ? ` · ${p.summary.option}` : ""}
            </p>
            <p className="muted small">Updated {new Date(p.updated_at).toLocaleString()}</p>
            {p.review_note && <p className="note">Reviewer: “{p.review_note}”</p>}
            <div className="row gap">
              <Link className="btn small" to={`/planner?project=${p.id}`}>Open</Link>
              <ReportPicker compact onDownload={(type) => api.downloadProjectReport(p.id, type)} />
              {(p.status === "draft" || p.status === "rejected") && (
                <button type="button" className="btn small" onClick={() => act(() => api.submitProject(p.id))}>Submit for approval</button>
              )}
              <button type="button" className="btn small danger" onClick={() => window.confirm(`Delete “${p.name}”?`) && act(() => api.deleteProject(p.id))}>Delete</button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
