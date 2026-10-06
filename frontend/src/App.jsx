import { lazy, Suspense } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./lib/auth.jsx";
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
        {user ? (
          <>
            <span className="muted small">{user.email}{isAdmin ? " · admin" : ""}</span>
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
