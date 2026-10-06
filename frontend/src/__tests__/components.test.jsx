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
  it("shows each step, the model's words, and rejected attempts with critique", () => {
    render(<ReasoningPanel steps={steps} />);
    expect(screen.getByText("Understand the brief")).toBeInTheDocument();
    expect(screen.getByText("“A calm spa bathroom”")).toBeInTheDocument();
    // rejected attempt is expanded by default, showing the verifier's reason
    expect(screen.getByText("✗ toilet overlaps shower")).toBeInTheDocument();
    expect(screen.getByText("Critique sent back to the model")).toBeInTheDocument();
    // accepted attempt collapsed until clicked
    expect(screen.queryByText("“separate walls”")).toBeNull();
    fireEvent.click(screen.getByText(/Attempt 2/));
    expect(screen.getByText("“separate walls”")).toBeInTheDocument();
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
