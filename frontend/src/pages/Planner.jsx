import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import FloorPlan from "../components/FloorPlan.jsx";
import OptionPicker from "../components/OptionPicker.jsx";
import ReasoningPanel from "../components/ReasoningPanel.jsx";
import { BillOfMaterials, Checks, Metrics } from "../components/DesignSummary.jsx";
import Slider from "../components/Slider.jsx";
import ReportPicker from "../components/ReportPicker.jsx";
import { api } from "../lib/api.js";
import { useAuth } from "../lib/auth.jsx";
import { arrangementOf, quickProblems } from "../lib/geometry.js";
import { money } from "../lib/format.js";

export const LAST_DESIGN_KEY = "plumbline_last_design";

/** Remember the design on screen so Sustainability can report on it. */
function rememberDesign(value) {
  try {
    sessionStorage.setItem(LAST_DESIGN_KEY, JSON.stringify(value));
  } catch { /* storage full or blocked: Sustainability falls back to a sample */ }
}

export function compactMoney(v, currency) {
  if (currency !== "INR") return money(v, currency);
  if (v >= 1e7) return `₹${+(v / 1e7).toFixed(2)} Cr`;
  if (v >= 1e5) return `₹${+(v / 1e5).toFixed(1)} L`;
  return money(v, currency);
}

// three.js is ~600 KB: only load it when the 3D tab is opened.
const Room3D = lazy(() => import("../components/Room3D.jsx"));

const EXAMPLES = [
  "8x10 spa bathroom, family of 4, ₹6 lakh, touchless",
  "Compact 6x8 minimalist bath for a couple, 4 lakh budget",
  "12x10 classic luxury marble ensuite, ₹15L, smart toilet",
];

const DEFAULT_PARAMS = { length_ft: 10, width_ft: 8, budget: 600000, theme: "Japanese Zen", household: 4, prioritize_smart: false };

/** "toilet overlaps shower" -> "toilet" */
export function invalidCategories(problems) {
  return new Set((problems || []).map((p) => p.split(" ")[0]));
}

export default function Planner() {
  const { user } = useAuth();
  const [search, setSearch] = useSearchParams();
  const [config, setConfig] = useState(null);
  const [prompt, setPrompt] = useState(EXAMPLES[0]);
  const [params, setParams] = useState(DEFAULT_PARAMS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [design, setDesign] = useState(null);
  const [elapsed, setElapsed] = useState(null);
  const [selected, setSelected] = useState(0);
  const [edits, setEdits] = useState({});
  const [preview, setPreview] = useState(null);
  const [verifying, setVerifying] = useState(false);
  const [view, setView] = useState("2d");
  const [tab, setTab] = useState("reasoning");

  const [project, setProject] = useState(null);
  const [projectName, setProjectName] = useState("");
  const [saveMsg, setSaveMsg] = useState(null);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  // Re-open a saved cloud project: /planner?project=12
  const projectId = search.get("project");
  useEffect(() => {
    if (!projectId || !user) return;
    api.getProject(projectId)
      .then(({ project: p }) => {
        setProject(p);
        setProjectName(p.name);
        setDesign(p.data.design);
        const idx = Math.max(0, (p.data.design.options || []).findIndex((o) => o.id === p.data.selected_option));
        setSelected(idx);
        setEdits(p.data.edits || {});
        setPreview(null);
      })
      .catch((e) => setError(e.message));
  }, [projectId, user]);

  const option = design?.options?.[selected];
  const edit = option ? edits[option.id] : null;
  const basePlacements = edit?.placements || option?.placements || design?.alternative?.layout?.placements || [];
  const placements = preview || basePlacements;
  const problems = preview ? quickProblems(preview, design.layout.room_in.width, design.layout.room_in.length) : edit?.problems || [];
  const invalid = useMemo(() => invalidCategories(problems), [problems]);
  useEffect(() => {
    if (design?.status === "ok") rememberDesign({ design, selected_option: option?.id, edits });
  }, [design, option?.id, edits]);

  const room = design?.layout?.room_in
    || (design && { width: design.inputs.width_ft * 12, length: design.inputs.length_ft * 12 });

  async function generate(payload) {
    setLoading(true);
    setError(null);
    setSaveMsg(null);
    try {
      const r = await api.design(payload);
      setDesign(r.data);
      setElapsed(r.elapsed_ms);
      setSelected(0);
      setEdits({});
      setPreview(null);
      setProject(null);
      if (projectId) setSearch({});
      if (r.parsed) {
        setParams({
          length_ft: r.parsed.length_ft, width_ft: r.parsed.width_ft,
          budget: Math.min(5000000, Math.max(50000, Math.round(r.parsed.budget / 10000) * 10000)),
          theme: r.parsed.theme, household: r.parsed.household, prioritize_smart: r.parsed.prioritize_smart,
        });
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  function handlePreview(category, placement) {
    const base = basePlacements.filter((p) => p.category !== category && !(category === "vanity" && p.category === "faucet"));
    const prev = basePlacements.find((p) => p.category === category);
    setPreview([...base, { ...prev, ...placement }]);
  }

  async function handleCommit({ category, wall, offset }) {
    const arrangement = { ...arrangementOf(basePlacements), [category]: { wall, offset } };
    setVerifying(true);
    try {
      const r = await api.verifyLayout({
        room: { width_in: room.width, length_in: room.length },
        bundle_ids: design.bundle.map((p) => p.id),
        arrangement,
      });
      setEdits((e) => ({ ...e, [option.id]: { placements: r.placements, problems: r.problems, summary: r.summary } }));
      setSaveMsg(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setPreview(null);
      setVerifying(false);
    }
  }

  function resetEdits() {
    setEdits((e) => {
      const next = { ...e };
      delete next[option.id];
      return next;
    });
  }

  async function save() {
    if (!user) return;
    const data = { design, selected_option: option?.id, edits };
    const name = projectName.trim() || `${design.inputs.theme} ${design.inputs.length_ft}×${design.inputs.width_ft}`;
    try {
      const r = project && project.owner_id === user.id
        ? await api.updateProject(project.id, { name, data })
        : await api.createProject(name, data);
      setProject(r.project);
      setProjectName(r.project.name);
      setSaveMsg(`Saved to cloud · ${new Date(r.project.updated_at).toLocaleTimeString()}`);
    } catch (e) {
      setSaveMsg(`Save failed: ${e.message}`);
    }
  }

  const themes = config?.themes || ["Minimalist Modern", "Japanese Zen", "Classic Luxury"];
  const set = (k) => (v) => setParams({ ...params, [k]: v });
  const cur = config?.currency || "INR";

  return (
    <div className="planner">
      <header className="page-head">
        <div>
          <span className="eyebrow">Design studio</span>
          <h1>Planner</h1>
        </div>
        {elapsed !== null && <span className="badge">Solved in {elapsed} ms</span>}
      </header>

      <div className="planner-grid">
        <aside className="panel">
          <h3 className="panel-title">01 · Brief</h3>
          <form onSubmit={(ev) => { ev.preventDefault(); generate({ prompt }); }}>
            <textarea className="brief" value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={4}
              aria-label="Describe your bathroom" maxLength={2000} />
            <div className="chips">
              {EXAMPLES.map((ex) => (
                <button type="button" key={ex} className="chip" onClick={() => setPrompt(ex)}>{ex}</button>
              ))}
            </div>
            <button className="btn primary block" disabled={loading}>{loading ? "Designing…" : "Generate options"}</button>
          </form>

          <h3 className="panel-title">02 · Controls</h3>
          <form className="controls" onSubmit={(ev) => { ev.preventDefault(); generate({ params, prompt: "" }); }}>
            <Slider name="length" label="Length" value={params.length_ft} min={4} max={30} step={0.5}
              format={(v) => `${v} ft`} onChange={set("length_ft")} />
            <Slider name="width" label="Width" value={params.width_ft} min={4} max={30} step={0.5}
              format={(v) => `${v} ft`} onChange={set("width_ft")} />
            <Slider name="budget" label="Budget" value={params.budget} min={50000} max={5000000} step={10000}
              format={(v) => compactMoney(v, cur)} onChange={set("budget")} />
            <Slider name="household" label="Household" value={params.household} min={1} max={12}
              format={(v) => `${v} ${v === 1 ? "person" : "people"}`} onChange={set("household")} />
            <label className="wide field">Theme
              <select value={params.theme} onChange={(e) => set("theme")(e.target.value)}>{themes.map((t) => <option key={t}>{t}</option>)}</select>
            </label>
            <label className="check wide"><input type="checkbox" checked={params.prioritize_smart} onChange={(e) => set("prioritize_smart")(e.target.checked)} /> Prioritise smart fixtures</label>
            <button className="btn block" disabled={loading}>Apply controls</button>
          </form>
        </aside>

        <section className="panel canvas-panel">
          <div className="panel-title row">
            <span>03 · Layout {option ? `· ${option.id}` : ""}</span>
            <div className="seg" role="tablist" aria-label="View">
              <button type="button" role="tab" aria-selected={view === "2d"} className={view === "2d" ? "on" : ""} onClick={() => setView("2d")}>2D plan</button>
              <button type="button" role="tab" aria-selected={view === "3d"} className={view === "3d" ? "on" : ""} onClick={() => setView("3d")}>3D view</button>
            </div>
          </div>

          {error && <div className="banner error" role="alert">{error}</div>}
          {!design && !loading && <p className="muted center pad">Describe a bathroom and generate to see verified layout options.</p>}
          {loading && <p className="muted center pad">Reading the brief, selecting products, verifying layouts…</p>}

          {design && design.status !== "ok" && (
            <div className="banner warn" role="alert">
              <strong>No valid design.</strong> {design.message}
              {design.alternative && (
                <> Closest option costs {money(design.alternative.total_cost, design.currency)} (
                  {money(design.alternative.over_budget_by, design.currency)} over budget) — shown below.</>
              )}
            </div>
          )}

          {design?.options && (
            <OptionPicker options={design.options} selected={selected} edited={edits}
              onSelect={(i) => { setSelected(i); setPreview(null); }} />
          )}

          {design && room && placements.length > 0 && (
            <>
              {view === "2d" ? (
                <FloorPlan room={room} placements={placements} fixtures={design.layout?.fixtures}
                  invalid={invalid} editable={design.status === "ok" && !verifying}
                  onPreview={handlePreview} onCommit={handleCommit} />
              ) : (
                <Suspense fallback={<p className="muted center pad">Loading 3D…</p>}>
                  <Room3D room={room} placements={placements} bundle={design.bundle || design.alternative?.bundle} invalid={invalid} />
                </Suspense>
              )}
              {design.status === "ok" && (
                <div className="edit-bar">
                  <span className="muted">
                    {view === "2d" ? "Drag a fixture to any wall — every drop is re-verified by the server." : "Switch to 2D to edit."}
                  </span>
                  {verifying && <span className="badge">Verifying…</span>}
                  {edit && <button type="button" className="btn small" onClick={resetEdits}>Reset to {option.id}</button>}
                </div>
              )}
              {option && <p className="option-summary">{edit?.summary || option.summary}</p>}
            </>
          )}
        </section>

        <aside className="panel">
          <div className="seg full" role="tablist" aria-label="Details">
            <button type="button" role="tab" aria-selected={tab === "reasoning"} className={tab === "reasoning" ? "on" : ""} onClick={() => setTab("reasoning")}>AI reasoning</button>
            <button type="button" role="tab" aria-selected={tab === "checks"} className={tab === "checks" ? "on" : ""} onClick={() => setTab("checks")}>Checks</button>
          </div>
          {design?.status === "ok" && tab === "reasoning" && (
            <>
              {design.rationale?.headline && <h4 className="headline">{design.rationale.headline}</h4>}
              <ReasoningPanel steps={design.reasoning} />
            </>
          )}
          {design?.status === "ok" && tab === "checks" && (
            <>
              <Metrics design={design} />
              <Checks checks={design.checks} watersense={design.watersense} liveProblems={edit || preview ? problems : null} />
            </>
          )}
          {!design && <p className="muted">The model's reading of your brief, every proposal it made, what the verifier rejected and why will appear here.</p>}

          {design?.status === "ok" && (
            <div className="save-box">
              <h3 className="panel-title">04 · Save</h3>
              {user ? (
                <>
                  <input aria-label="Project name" placeholder="Project name" value={projectName} onChange={(e) => setProjectName(e.target.value)} />
                  <button type="button" className="btn primary block" onClick={save}>
                    {project && project.owner_id === user.id ? "Update cloud project" : "Save to cloud"}
                  </button>
                  {project && <p className="muted small">Status: <span className={`status ${project.status}`}>{project.status}</span> · <Link to="/projects">My projects</Link></p>}
                </>
              ) : (
                <p className="muted"><Link to="/login?next=/planner">Sign in</Link> to save designs to the cloud.</p>
              )}
              {saveMsg && <p className="small" role="status">{saveMsg}</p>}

              <h3 className="panel-title">05 · Report</h3>
              <ReportPicker onDownload={(type) => api.downloadReport(design, option?.id, edits, type)} />
            </div>
          )}
        </aside>
      </div>

      {design && (design.bundle?.length || design.alternative) && (
        <section className="panel">
          <h3 className="panel-title">06 · Bill of materials</h3>
          <BillOfMaterials bundle={design.bundle?.length ? design.bundle : design.alternative.bundle}
            total={design.metrics?.total_cost ?? design.alternative.total_cost} currency={design.currency} />
        </section>
      )}
    </div>
  );
}
