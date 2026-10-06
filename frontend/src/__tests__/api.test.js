import { afterEach, describe, expect, it, vi } from "vitest";
import { api, API_URL, ApiError, setToken } from "../lib/api.js";

function mockFetch(status, body) {
  const fn = vi.fn().mockResolvedValue({ ok: status < 400, status, json: () => Promise.resolve(body) });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setToken(null);
});

describe("api client", () => {
  it("sends the bearer token on authenticated calls", async () => {
    setToken("abc");
    const f = mockFetch(200, { projects: [] });
    await api.listProjects();
    const [url, init] = f.mock.calls[0];
    expect(url).toBe(`${API_URL}/api/projects`);
    expect(init.headers.Authorization).toBe("Bearer abc");
  });

  it("does not send the token to public endpoints", async () => {
    setToken("abc");
    const f = mockFetch(200, { status: "success" });
    await api.design({ prompt: "x" });
    const [, init] = f.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(init.headers.Authorization).toBeUndefined();
    expect(JSON.parse(init.body)).toEqual({ prompt: "x" });
  });

  it("surfaces server error messages", async () => {
    mockFetch(403, { message: "Admin access required" });
    await expect(api.adminUsers()).rejects.toMatchObject({ message: "Admin access required", status: 403 });
  });

  it("explains network failures (cold backend)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = await api.health().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
  });
});
