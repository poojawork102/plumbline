import { useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../lib/auth.jsx";
import { REPORT_DESCRIPTIONS, ROLE_LABELS, SELF_SERVICE_ROLES } from "../lib/personas.js";

export default function Login() {
  const { user, login, register } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("homeowner");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const next = params.get("next")?.startsWith("/") ? params.get("next") : "/projects";

  if (user) return <Navigate to={next} replace />;

  async function submit(ev) {
    ev.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, name, role);
      navigate(next, { replace: true });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-card panel">
      <div className="seg full" role="tablist">
        <button type="button" role="tab" aria-selected={mode === "login"} className={mode === "login" ? "on" : ""} onClick={() => setMode("login")}>Sign in</button>
        <button type="button" role="tab" aria-selected={mode === "register"} className={mode === "register" ? "on" : ""} onClick={() => setMode("register")}>Create account</button>
      </div>
      <form onSubmit={submit} className="stack">
        {mode === "register" && (
          <>
            <label>Name<input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></label>
            <fieldset className="role-pick">
              <legend>I am a…</legend>
              {SELF_SERVICE_ROLES.map((r) => (
                <label key={r} className={`role-option ${role === r ? "on" : ""}`}>
                  <input type="radio" name="role" value={r} checked={role === r} onChange={() => setRole(r)} />
                  <strong>{ROLE_LABELS[r]}</strong>
                  <span className="muted small">{REPORT_DESCRIPTIONS[r]}</span>
                </label>
              ))}
            </fieldset>
          </>
        )}
        <label>Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></label>
        <label>Password<input type="password" required minLength={mode === "register" ? 8 : undefined} value={password}
          onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} /></label>
        {error && <div className="banner error" role="alert">{error}</div>}
        <button className="btn primary block" disabled={busy}>{mode === "login" ? "Sign in" : "Create account"}</button>
      </form>
      <p className="muted small">Kohler team and admin access is granted by an admin after you sign up.</p>
    </div>
  );
}
