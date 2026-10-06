import { lazy, Suspense } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./lib/auth.jsx";
import { ROLE_LABELS } from "./lib/personas.js";
import { useTheme } from "./lib/theme.js";
import Home from "./pages/Home.jsx";
import Login from "./pages/Login.jsx";
import Planner from "./pages/Planner.jsx";
import Projects from "./pages/Projects.jsx";
import Sustainability from "./pages/Sustainability.jsx";

const Admin = lazy(() => import("./pages/Admin.jsx"));

export function RequireAuth({ children, admin = false }) {
  const { user, ready } = useAuth();
  const loc = useLocation();
  if (!ready) return <p className="muted center pad">Loading…</p>;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname)}`} replace />;
  if (admin && user.role !== "admin") return <p className="banner error">Admin access required.</p>;
  return children;
}

function Nav() {
  const { user, isAdmin, logout } = useAuth();
  const { theme, toggle } = useTheme();
  return (
    <nav className="nav">
      <NavLink to="/" className="brand">PLUMBLINE</NavLink>
      <div className="nav-links">
        <NavLink to="/planner">Planner</NavLink>
        <NavLink to="/sustainability">Sustainability</NavLink>
        {user && <NavLink to="/projects">My projects</NavLink>}
        {isAdmin && <NavLink to="/admin">Admin</NavLink>}
      </div>
      <div className="nav-user">
        <button type="button" className="theme-toggle" onClick={toggle} data-testid="theme-toggle"
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`} title={`${theme === "dark" ? "Light" : "Dark"} mode`}>
          {theme === "dark" ? "☀" : "☾"}
        </button>
        {user ? (
          <>
            <span className="muted small">{user.email} · <span className="role-badge">{ROLE_LABELS[user.role] || user.role}</span></span>
            <button type="button" className="btn small" onClick={logout}>Sign out</button>
          </>
        ) : (
          <NavLink to="/login" className="btn small">Sign in</NavLink>
        )}
      </div>
    </nav>
  );
}

export default function App() {
  return (
    <>
      <Nav />
      <main className="main">
        <Suspense fallback={<p className="muted center pad">Loading…</p>}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/planner" element={<Planner />} />
            <Route path="/sustainability" element={<Sustainability />} />
            <Route path="/login" element={<Login />} />
            <Route path="/projects" element={<RequireAuth><Projects /></RequireAuth>} />
            <Route path="/admin" element={<RequireAuth admin><Admin /></RequireAuth>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </main>
    </>
  );
}
