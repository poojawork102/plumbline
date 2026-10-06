import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { money } from "../lib/format.js";
import { ROLE_LABELS } from "../lib/personas.js";

const FILTERS = ["submitted", "approved", "rejected", "draft", ""];

export default function Admin() {
  const { user } = useAuth();
  const [stats, setStats] = useState(null);
  const [users, setUsers] = useState([]);
  const [projects, setProjects] = useState([]);
  const [filter, setFilter] = useState("submitted");
  const [notes, setNotes] = useState({});
  const [error, setError] = useState(null);

  const load = async () => {
    try {
      const [s, u, p] = await Promise.all([api.adminStats(), api.adminUsers(), api.adminProjects(filter)]);
      setStats(s.stats);
      setUsers(u.users);
      setProjects(p.projects);
    } catch (e) {
      setError(e.message);
    }
  };
  useEffect(() => { load(); }, [filter]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (fn) => {
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <div>
      <header className="page-head"><div><span className="eyebrow">Authority</span><h1>Admin console</h1></div></header>
      {error && <div className="banner error" role="alert">{error}</div>}

      {stats && (
        <div className="metrics">
          <div className="metric"><span>Users</span><strong>{stats.users}</strong></div>
          <div className="metric"><span>Projects</span><strong>{stats.projects}</strong></div>
          <div className="metric"><span>Awaiting review</span><strong>{stats.by_status.submitted}</strong></div>
          <div className="metric"><span>Approved</span><strong>{stats.by_status.approved}</strong></div>
        </div>
      )}

      <section className="panel">
        <div className="panel-title row">
          <span>Design review</span>
          <select aria-label="Status filter" value={filter} onChange={(e) => setFilter(e.target.value)}>
            {FILTERS.map((f) => <option key={f} value={f}>{f || "all"}</option>)}
          </select>
        </div>
        {projects.length === 0 && <p className="muted">Nothing here.</p>}
        <table className="bom">
          <tbody>
            {projects.map((p) => (
              <tr key={p.id}>
                <td><strong>{p.name}</strong><div className="muted small">{p.owner_email}</div></td>
                <td className="small">{p.summary.theme} · {p.summary.length_ft}×{p.summary.width_ft} ft · {money(p.summary.total_cost, p.summary.currency)}</td>
                <td><span className={`status ${p.status}`}>{p.status}</span></td>
                <td>
                  <div className="actions">
                  <Link className="btn small" to={`/planner?project=${p.id}`}>Inspect</Link>
                  <button type="button" className="btn small" onClick={() => act(() => api.downloadProjectReport(p.id))}>PDF</button>
                  {p.status === "submitted" && (
                    <>
                      <input aria-label={`Note for ${p.name}`} placeholder="Note (optional)" value={notes[p.id] || ""}
                        onChange={(e) => setNotes({ ...notes, [p.id]: e.target.value })} />
                      <button type="button" className="btn small primary" onClick={() => act(() => api.adminReview(p.id, "approved", notes[p.id]))}>Approve</button>
                      <button type="button" className="btn small danger" onClick={() => act(() => api.adminReview(p.id, "rejected", notes[p.id]))}>Reject</button>
                    </>
                  )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <div className="panel-title">Users & roles</div>
        <table className="bom">
          <thead><tr><th>Email</th><th>Name</th><th>Projects</th><th>Role</th></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.email}</td><td>{u.name}</td><td>{u.project_count}</td>
                <td>
                  <select aria-label={`Role for ${u.email}`} value={u.role} disabled={u.id === user.id}
                    onChange={(e) => act(() => api.adminSetRole(u.id, e.target.value))}>
                    {Object.entries(ROLE_LABELS).map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
