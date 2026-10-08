// Thin client for the Flask API. In production VITE_API_URL (the Render URL)
// is baked in at build time on Vercel. Locally it is unset: requests go to the
// same origin -- Flask serves the built app (`python run.py`), or Vite proxies
// /api to Flask (`python run.py --dev`).
export const API_URL = (import.meta.env.VITE_API_URL || "").replace(/\/+$/, "");

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

/** Fetch a PDF and hand it to the browser as a download. */
export async function downloadFile(path, { method = "GET", body, fallbackName = "plumbline-report.pdf" } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let res;
  try {
    res = await fetch(`${API_URL}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError("Cannot reach the Plumbline API. It may be waking up — try again in a moment.", 0);
  }
  if (!res.ok) {
    let msg = `Download failed (${res.status})`;
    try { msg = (await res.json()).message || msg; } catch { /* not JSON */ }
    throw new ApiError(msg, res.status);
  }
  const blob = await res.blob();
  const match = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "");
  const name = match ? match[1] : fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return name;
}

export const api = {
  health: () => request("/api/health", { auth: false }),
  config: () => request("/api/config", { auth: false }),
  design: (payload) => request("/api/design", { method: "POST", body: payload, auth: false }),
  verifyLayout: (payload) => request("/api/layout/verify", { method: "POST", body: payload, auth: false }),
  sustainability: (household) => request(`/api/sustainability?household=${encodeURIComponent(household)}`, { auth: false }),

  register: (email, password, name, role) => request("/api/auth/register", { method: "POST", body: { email, password, name, role }, auth: false }),
  login: (email, password) => request("/api/auth/login", { method: "POST", body: { email, password }, auth: false }),
  me: () => request("/api/auth/me"),

  listProjects: () => request("/api/projects"),
  getProject: (id) => request(`/api/projects/${id}`),
  createProject: (name, data) => request("/api/projects", { method: "POST", body: { name, data } }),
  updateProject: (id, patch) => request(`/api/projects/${id}`, { method: "PUT", body: patch }),
  deleteProject: (id) => request(`/api/projects/${id}`, { method: "DELETE" }),
  submitProject: (id) => request(`/api/projects/${id}/submit`, { method: "POST", body: {} }),

  downloadReport: (design, selectedOption, edits) =>
    downloadFile("/api/report", { method: "POST", body: { design, selected_option: selectedOption, edits } }),
  downloadProjectReport: (id) => downloadFile(`/api/projects/${id}/report`),

  adminStats: () => request("/api/admin/stats"),
  adminUsers: () => request("/api/admin/users"),
  adminSetRole: (id, role) => request(`/api/admin/users/${id}`, { method: "PATCH", body: { role } }),
  adminProjects: (status) => request(`/api/admin/projects${status ? `?status=${status}` : ""}`),
  adminReview: (id, decision, note) => request(`/api/admin/projects/${id}/review`, { method: "POST", body: { decision, note } }),
};
