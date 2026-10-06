import { describe, expect, it } from "vitest";
import { arrangementOf, buildPlacement, feetLabel, quickProblems, snapToWall, toRoom } from "../lib/geometry.js";
import { FIXTURES, ROOM } from "./fixtures.js";

const [shower, toilet, vanity] = FIXTURES;
const W = ROOM.width;
const L = ROOM.length;

describe("toRoom (mirror of layout._to_room)", () => {
  it("maps each wall", () => {
    expect(toRoom("top", 10, 0, 20, 30, W, L)).toEqual([10, 0, 20, 30]);
    expect(toRoom("bottom", 10, 0, 20, 30, W, L)).toEqual([10, 90, 20, 30]);
    expect(toRoom("left", 10, 0, 20, 30, W, L)).toEqual([0, 10, 30, 20]);
    expect(toRoom("right", 10, 0, 20, 30, W, L)).toEqual([66, 10, 30, 20]);
  });
});

describe("buildPlacement", () => {
  it("matches the backend's geometry for a top-wall toilet", () => {
    const p = buildPlacement(toilet, "top", 30, W, L);
    expect(p).toMatchObject({ x: 30, y: 0, w: 20, d: 28, side: "top", u: 30 });
    // side_min 15 from centreline -> envelope 30 wide, depth + front
    expect(p.clearance).toEqual({ x: 25, y: 0, w: 30, d: 49 });
  });

  it("clamps any offset inside the wall run", () => {
    for (const off of [-500, 0, 99999]) {
      for (const wall of ["top", "right", "bottom", "left"]) {
        const p = buildPlacement(vanity, wall, off, W, L);
        expect(p.x).toBeGreaterThanOrEqual(0);
        expect(p.y).toBeGreaterThanOrEqual(0);
        expect(p.x + p.w).toBeLessThanOrEqual(W + 1e-6);
        expect(p.y + p.d).toBeLessThanOrEqual(L + 1e-6);
      }
    }
  });
});

describe("snapToWall", () => {
  it("snaps to the nearest wall and centres on the pointer", () => {
    expect(snapToWall(48, 5, shower, W, L)).toEqual({ wall: "top", offset: 30 });
    expect(snapToWall(92, 60, shower, W, L)).toEqual({ wall: "right", offset: 42 });
    expect(snapToWall(3, 60, vanity, W, L)).toEqual({ wall: "left", offset: 45 });
    expect(snapToWall(50, 118, vanity, W, L)).toEqual({ wall: "bottom", offset: 35 });
  });

  it("never returns an offset past the end of the wall", () => {
    expect(snapToWall(90, 2, shower, W, L)).toEqual({ wall: "top", offset: W - shower.width });
    expect(snapToWall(10, 2, shower, W, L)).toEqual({ wall: "top", offset: 0 });
  });

  it("clamps a pointer dragged outside the room onto the wall it crossed", () => {
    expect(snapToWall(50, -40, shower, W, L).wall).toBe("top");
    expect(snapToWall(500, 60, shower, W, L).wall).toBe("right");
    expect(snapToWall(-50, 60, shower, W, L).wall).toBe("left");
  });
});

describe("quickProblems", () => {
  it("passes a known-good layout", () => {
    const good = [
      buildPlacement(shower, "top", 60, W, L),
      buildPlacement(toilet, "top", 6, W, L),
      buildPlacement(vanity, "right", 60, W, L),
    ];
    expect(quickProblems(good, W, L)).toEqual([]);
  });

  it("enforces the toilet's side clearance against the wall", () => {
    expect(quickProblems([buildPlacement(toilet, "top", 0, W, L)], W, L)).toEqual(["toilet clearance zone outside room"]);
  });

  it("flags overlaps and the door swing", () => {
    const bad = [buildPlacement(shower, "left", 0, W, L), buildPlacement(toilet, "left", 0, W, L)];
    expect(quickProblems(bad, W, L)).toContain("shower overlaps toilet");
    const door = [buildPlacement(vanity, "bottom", 0, W, L)];
    expect(quickProblems(door, W, L)).toContain("vanity blocks door swing");
  });
});

it("arrangementOf ignores the faucet", () => {
  const ps = [buildPlacement(shower, "top", 6, W, L), { category: "faucet", side: "left", u: 3 }];
  expect(arrangementOf(ps)).toEqual({ shower: { wall: "top", offset: 6 } });
});

it("feetLabel", () => {
  expect(feetLabel(96)).toBe("8′");
  expect(feetLabel(102)).toBe("8′ 6″");
});
