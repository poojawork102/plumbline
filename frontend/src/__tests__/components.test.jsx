import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import FloorPlan, { labelPosition } from "../components/FloorPlan.jsx";
import OptionPicker from "../components/OptionPicker.jsx";
import ReasoningPanel from "../components/ReasoningPanel.jsx";
import { buildPlacement } from "../lib/geometry.js";
import { invalidCategories } from "../pages/Planner.jsx";
import { RequireAuth } from "../App.jsx";
import { AuthProvider } from "../lib/auth.jsx";
import { FIXTURES, ROOM } from "./fixtures.js";

const steps = [
  { stage: "understand", title: "Understand the brief", actor: "gemini", summary: "Gemini read the brief.", said: "A calm spa bathroom", details: ["Room 10 x 8 ft"] },
  {
    stage: "arrange", title: "Arrange, verify & repair", actor: "gemini", summary: "1 rejected", details: [],
    attempts: [
      { attempt: 1, source: "gemini", stage: "primary", accepted: false, ms: 900, reasoning: "stack them", problems: ["toilet overlaps shower"], critique: "The reviewer REJECTED ...", arrangement: { toilet: { wall: "left", offset: 0 } } },
      { attempt: 2, source: "gemini", stage: "primary", accepted: true, ms: 700, reasoning: "separate walls", problems: [], arrangement: null },
    ],
  },
];

describe("ReasoningPanel", () => {
  it("shows one short line per step and expands details on demand", () => {
    const withShort = steps.map((s, i) => ({ ...s, short: i === 0 ? "10×8 ft · Zen · 4 people" : "AI layout passed after 1 fix(es)" }));
    render(<ReasoningPanel steps={withShort} />);
    expect(screen.getByText("10×8 ft · Zen · 4 people")).toBeInTheDocument();
    // details hidden until the step is opened
    expect(screen.queryByText("“A calm spa bathroom”")).toBeNull();
    expect(screen.queryByText(/toilet overlaps shower/)).toBeNull();
    fireEvent.click(screen.getByText("Understand the brief"));
    expect(screen.getByText("“A calm spa bathroom”")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Arrange, verify & repair"));
    expect(screen.queryByText("“A calm spa bathroom”")).toBeNull();   // one open at a time
    expect(screen.getByText(/toilet overlaps shower/)).toBeInTheDocument();
    expect(screen.getByText("Critique sent to the model")).toBeInTheDocument();
  });

  it("has an empty state", () => {
    render(<ReasoningPanel steps={[]} />);
    expect(screen.getByText(/Generate a design/)).toBeInTheDocument();
  });
});

const option = (id, extra = {}) => ({
  id, name: `Layout ${id}`, source: "deterministic", summary: "s", reasoning: null,
  features: { open_floor_pct: 70, wet_zone_grouped: true, toilet_screened: true }, ...extra,
});

describe("OptionPicker", () => {
  it("renders every option and reports selection", () => {
    const onSelect = vi.fn();
    render(<OptionPicker options={[option("Option A", { source: "gemini" }), option("Option B"), option("Option C", { features: { open_floor_pct: 60, wet_zone_grouped: false, toilet_screened: false } })]}
      selected={0} edited={{ "Option B": {} }} onSelect={onSelect} />);
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(3);
    expect(radios[0]).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("AI proposed")).toBeInTheDocument();
    expect(screen.getByText("WC faces door")).toBeInTheDocument();
    expect(screen.getByText("Edited")).toBeInTheDocument();
    fireEvent.click(radios[2]);
    expect(onSelect).toHaveBeenCalledWith(2);
  });
});

describe("FloorPlan drag-and-drop", () => {
  const placements = [
    { ...buildPlacement(FIXTURES[0], "top", 60, ROOM.width, ROOM.length), name: "Shower" },
    { ...buildPlacement(FIXTURES[1], "top", 6, ROOM.width, ROOM.length), name: "Toilet" },
    { ...buildPlacement(FIXTURES[2], "right", 60, ROOM.width, ROOM.length), name: "Vanity" },
  ];

  function setup(props = {}) {
    const onPreview = vi.fn();
    const onCommit = vi.fn();
    render(<FloorPlan room={ROOM} placements={placements} fixtures={FIXTURES} onPreview={onPreview} onCommit={onCommit} {...props} />);
    // jsdom has no SVG layout: make client coords == plan inches
    const svg = screen.getByTestId("floorplan");
    svg.getScreenCTM = () => ({ inverse: () => ({}) });
    svg.createSVGPoint = () => {
      const pt = { x: 0, y: 0 };
      pt.matrixTransform = () => ({ x: pt.x, y: pt.y });
      return pt;
    };
    return { onPreview, onCommit, svg };
  }

  it("drags a fixture to another wall and commits wall + offset", () => {
    const { onPreview, onCommit, svg } = setup();
    const vanity = screen.getByTestId("fixture-vanity");
    // grab vanity at its centre (85, 75), drop near the left wall
    fireEvent.pointerDown(vanity, { clientX: 85, clientY: 75, pointerId: 1 });
    fireEvent.pointerMove(svg, { clientX: 4, clientY: 50, pointerId: 1 });
    expect(onPreview).toHaveBeenCalled();
    const [cat, preview] = onPreview.mock.calls.at(-1);
    expect(cat).toBe("vanity");
    expect(preview.side).toBe("left");
    fireEvent.pointerUp(svg, { pointerId: 1 });
    expect(onCommit).toHaveBeenCalledWith({ category: "vanity", wall: "left", offset: 35 });
  });

  it("a click without movement commits nothing", () => {
    const { onCommit, svg } = setup();
    fireEvent.pointerDown(screen.getByTestId("fixture-toilet"), { clientX: 16, clientY: 14, pointerId: 1 });
    fireEvent.pointerUp(svg, { pointerId: 1 });
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("keyboard: arrows nudge along the wall, R changes wall", () => {
    const { onCommit } = setup();
    const toilet = screen.getByTestId("fixture-toilet");
    fireEvent.keyDown(toilet, { key: "ArrowRight" });
    expect(onCommit).toHaveBeenLastCalledWith({ category: "toilet", wall: "top", offset: 12 });
    fireEvent.keyDown(toilet, { key: "r" });
    expect(onCommit).toHaveBeenLastCalledWith({ category: "toilet", wall: "right", offset: 0 });
  });

  it("read-only plans cannot be dragged", () => {
    const { onCommit, svg } = setup({ editable: false });
    fireEvent.pointerDown(screen.getByTestId("fixture-vanity"), { clientX: 85, clientY: 75, pointerId: 1 });
    fireEvent.pointerMove(svg, { clientX: 4, clientY: 50, pointerId: 1 });
    fireEvent.pointerUp(svg, { pointerId: 1 });
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("highlights invalid fixtures", () => {
    setup({ invalid: new Set(["shower"]) });
    expect(screen.getByTestId("fixture-shower")).toHaveClass("invalid");
    expect(screen.getByTestId("fixture-toilet")).not.toHaveClass("invalid");
  });
});

it("invalidCategories parses verifier messages", () => {
  expect([...invalidCategories(["toilet overlaps shower", "vanity blocks door swing"])]).toEqual(["toilet", "vanity"]);
});

describe("RequireAuth", () => {
  it("redirects anonymous users to login", async () => {
    render(
      <MemoryRouter initialEntries={["/admin"]}>
        <AuthProvider>
          <RequireAuth admin><p>secret admin</p></RequireAuth>
        </AuthProvider>
      </MemoryRouter>,
    );
    expect(screen.queryByText("secret admin")).toBeNull();
  });
});

it("labels sit in front of the fixture, inside the room", () => {
  const vanity = { side: "right", x: 91, y: 40, w: 5, d: 40 };
  const pos = labelPosition(vanity, 4);
  expect(pos.x).toBeLessThan(vanity.x);              // pushed into the room, away from the wall
  expect(labelPosition({ side: "top", x: 0, y: 0, w: 20, d: 28 }, 4).y).toBeGreaterThan(28);
});

describe("FloorPlan drag feedback", () => {
  const placements = [
    { ...buildPlacement(FIXTURES[0], "top", 60, ROOM.width, ROOM.length) },
    { ...buildPlacement(FIXTURES[1], "top", 6, ROOM.width, ROOM.length) },
    { ...buildPlacement(FIXTURES[2], "right", 60, ROOM.width, ROOM.length) },
  ];
  function mount() {
    render(<FloorPlan room={ROOM} placements={placements} fixtures={FIXTURES} onPreview={() => {}} onCommit={() => {}} />);
    const svg = screen.getByTestId("floorplan");
    svg.getScreenCTM = () => ({ inverse: () => ({}) });
    svg.createSVGPoint = () => { const pt = { x: 0, y: 0 }; pt.matrixTransform = () => ({ x: pt.x, y: pt.y }); return pt; };
    return svg;
  }

  it("highlights the wall the fixture will snap to while dragging", () => {
    const svg = mount();
    expect(screen.queryByTestId("target-wall")).toBeNull();
    fireEvent.pointerDown(screen.getByTestId("fixture-vanity"), { clientX: 85, clientY: 75 });
    fireEvent.pointerMove(svg, { clientX: 4, clientY: 50 });
    const line = screen.getByTestId("target-wall");
    expect(line.getAttribute("x1")).toBe("0");
    expect(line.getAttribute("x2")).toBe("0");          // left wall
    fireEvent.pointerUp(svg);
    expect(screen.queryByTestId("target-wall")).toBeNull();
  });

  it("focuses the hovered fixture's clearance and dims the rest", () => {
    mount();
    fireEvent.pointerEnter(screen.getByTestId("fixture-toilet"));
    expect(screen.getByTestId("clearance-toilet")).toHaveClass("active");
    expect(screen.getByTestId("clearance-shower")).toHaveClass("dim");
  });

  it("gives thin fixtures a grab area of at least 18 inches", () => {
    const thin = [{ ...buildPlacement({ category: "vanity", width: 40, depth: 5, side_min: 0, front_min: 21 }, "left", 30, ROOM.width, ROOM.length) }];
    render(<FloorPlan room={ROOM} placements={thin} fixtures={[{ category: "vanity", width: 40, depth: 5, side_min: 0, front_min: 21 }]} />);
    const hit = screen.getByTestId("fixture-vanity").querySelector(".fp-hit");
    expect(Number(hit.getAttribute("width"))).toBeGreaterThanOrEqual(18);
  });
});
