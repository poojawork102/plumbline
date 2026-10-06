import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Slider from "../components/Slider.jsx";
import { Checks } from "../components/DesignSummary.jsx";
import { compactMoney } from "../pages/Planner.jsx";
import { useTheme } from "../lib/theme.js";
import { api, downloadFile, setToken } from "../lib/api.js";

afterEach(() => {
  vi.unstubAllGlobals();
  setToken(null);
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("Slider", () => {
  it("shows the formatted value and reports numbers", () => {
    const onChange = vi.fn();
    render(<Slider name="b" label="Budget" value={600000} min={50000} max={5000000} step={10000}
      format={(v) => compactMoney(v, "INR")} onChange={onChange} />);
    expect(screen.getByText("₹6 L")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Budget"), { target: { value: "1250000" } });
    expect(onChange).toHaveBeenCalledWith(1250000);
  });

  it("every budget the slider can produce is a valid input value (no step mismatch)", () => {
    render(<Slider name="b" label="Budget" value={600000} min={50000} max={5000000} step={10000} onChange={() => {}} />);
    const input = screen.getByLabelText("Budget");
    expect(input.validity.valid).toBe(true);
    expect((600000 - 50000) % 10000).toBe(0);
  });
});

it("compactMoney", () => {
  expect(compactMoney(600000, "INR")).toBe("₹6 L");
  expect(compactMoney(15000000, "INR")).toBe("₹1.5 Cr");
  expect(compactMoney(50000, "INR")).toBe("₹50,000");
});

it("Checks render as short bullets", () => {
  render(<Checks
    checks={[{ name: "Budget", passed: true, detail: "₹5,92,000 of ₹6,00,000 (99%)" },
             { name: "Door swing", passed: true, detail: "Door arc is unobstructed" }]}
    watersense={{ items: [{ category: "toilet", rated: 1, limit: 1.28, unit: "gpf", certified: true }] }}
    liveProblems={["toilet overlaps shower"]} />);
  expect(screen.getByText("₹5,92,000 / ₹6,00,000")).toBeInTheDocument();
  expect(screen.getByText("unobstructed")).toBeInTheDocument();
  expect(screen.getByText(/toilet overlaps shower/).closest("li")).toHaveClass("bad");
});

describe("useTheme", () => {
  it("toggles dark mode on <html> and remembers the choice", () => {
    const { result } = renderHook(() => useTheme());
    const start = result.current.theme;
    act(() => result.current.toggle());
    const next = start === "dark" ? "light" : "dark";
    expect(document.documentElement.dataset.theme).toBe(next);
    expect(localStorage.getItem("plumbline_theme")).toBe(next);
    const again = renderHook(() => useTheme());
    expect(again.result.current.theme).toBe(next);
  });
});

describe("report download", () => {
  it("posts the design with the token and saves the PDF under the server's filename", async () => {
    setToken("tok");
    const blob = new Blob(["%PDF"], { type: "application/pdf" });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, blob: () => Promise.resolve(blob),
      headers: { get: () => 'attachment; filename="plumbline-design-architect.pdf"' },
    });
    vi.stubGlobal("fetch", fetchMock);
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const name = await api.downloadReport({ status: "ok" }, "Option B", {});
    expect(name).toBe("plumbline-design-architect.pdf");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/report$/);
    expect(init.headers.Authorization).toBe("Bearer tok");
    expect(JSON.parse(init.body)).toMatchObject({ selected_option: "Option B" });
    expect(click).toHaveBeenCalled();
  });

  it("surfaces server errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 400, json: () => Promise.resolve({ message: "A valid design is needed for a report" }) }));
    await expect(downloadFile("/api/report", { method: "POST", body: {} })).rejects.toMatchObject({ message: "A valid design is needed for a report" });
  });
});

describe("ReportPicker", () => {
  async function renderPicker(role) {
    const { AuthProvider } = await import("../lib/auth.jsx");
    const ReportPicker = (await import("../components/ReportPicker.jsx")).default;
    const onDownload = vi.fn().mockResolvedValue("plumbline-design-x.pdf");
    if (role) {
      setToken("t");
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({ user: { id: 1, email: "a@b.c", role } }) }));
    }
    render(<AuthProvider><ReportPicker onDownload={onDownload} /></AuthProvider>);
    return onDownload;
  }

  it("anonymous users choose homeowner or architect; Kohler is locked", async () => {
    const onDownload = await renderPicker(null);
    const radios = screen.getAllByRole("radio");
    expect(radios.map((r) => r.value)).toEqual(["homeowner", "architect", "kohler"]);
    expect(radios[0]).toBeChecked();
    expect(radios[2]).toBeDisabled();
    fireEvent.click(radios[1]);
    fireEvent.click(screen.getByRole("button", { name: "Download PDF report" }));
    expect(onDownload).toHaveBeenCalledWith("architect");
    expect(await screen.findByText("Downloaded plumbline-design-x.pdf")).toBeInTheDocument();
  });
});
