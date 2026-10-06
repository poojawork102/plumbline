// Thin client for the Flask API on Render. All calls go over HTTPS in
// production: VITE_API_URL is baked in at build time on Vercel.
export const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:5000").replace(/\/+$/, "");

const TOKEN_KEY = "plumbline_token";

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: session-only login */
  }
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function request(path, { method = "GET", body, auth = true } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const token = auth ? getToken() : null;
  if (token) headers.Authorization = `Bearer ${token}`;

  let res;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("Cannot reach the Plumbline API. It may be waking up — try again in a moment.", 0);
  }
  let json = null;
  try {
    json = await res.json();
  } catch {
    /* non-JSON error page */
  }
  if (!res.ok) {
    throw new ApiError(json?.message || `Request failed (${res.status})`, res.status);
  }
  return json;
}

export const api = {
  health: () => request("/api/health", { auth: false }),
  config: () => request("/api/config", { auth: false }),
  design: (payload) => request("/api/design", { method: "POST", body: payload, auth: false }),
  verifyLayout: (payload) => request("/api/layout/verify", { method: "POST", body: payload, auth: false }),
  sustainability: (household) => request(`/api/sustainability?household=${encodeURIComponent(household)}`, { auth: false }),

  register: (email, password, name) => request("/api/auth/register", { method: "POST", body: { email, password, name }, auth: false }),
  login: (email, password) => request("/api/auth/login", { method: "POST", body: { email, password }, auth: false }),
  me: () => request("/api/auth/me"),

  listProjects: () => request("/api/projects"),
  getProject: (id) => request(`/api/projects/${id}`),
  createProject: (name, data) => request("/api/projects", { method: "POST", body: { name, data } }),
  updateProject: (id, patch) => request(`/api/projects/${id}`, { method: "PUT", body: patch }),
  deleteProject: (id) => request(`/api/projects/${id}`, { method: "DELETE" }),
  submitProject: (id) => request(`/api/projects/${id}/submit`, { method: "POST", body: {} }),

  adminStats: () => request("/api/admin/stats"),
  adminUsers: () => request("/api/admin/users"),
  adminSetRole: (id, role) => request(`/api/admin/users/${id}`, { method: "PATCH", body: { role } }),
  adminProjects: (status) => request(`/api/admin/projects${status ? `?status=${status}` : ""}`),
  adminReview: (id, decision, note) => request(`/api/admin/projects/${id}/review`, { method: "POST", body: { decision, note } }),
};
