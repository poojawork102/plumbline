import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { buildRoomGroup, disposeGroup, updateCutaway } from "../lib/scene.js";
import { buildPlacement } from "../lib/geometry.js";
import { FIXTURES, ROOM } from "./fixtures.js";

const placements = [
  { ...buildPlacement(FIXTURES[0], "top", 60, ROOM.width, ROOM.length), id: "S" },
  { ...buildPlacement(FIXTURES[1], "top", 6, ROOM.width, ROOM.length), id: "T" },
  { ...buildPlacement(FIXTURES[2], "right", 60, ROOM.width, ROOM.length), id: "V" },
  { category: "faucet", side: "right", x: 86, y: 72, w: 6, d: 6, id: "F" },
];
const bundle = [{ id: "S", dimensions_in: { height: 80 } }, { id: "V", dimensions_in: { height: 34 } }];

describe("buildRoomGroup (Three.js)", () => {
  it("creates floor, walls, door swing and one group per fixture", () => {
    const g = buildRoomGroup(ROOM, placements, bundle);
    const names = [];
    g.traverse((o) => names.push(o.name));
    for (const n of ["floor", "wall:top", "wall:left", "wall:right", "wall:bottom", "door-swing"]) {
      expect(names).toContain(n);
    }
    for (const c of ["shower", "toilet", "vanity", "faucet"]) expect(names).toContain(`fixture:${c}`);
    expect(names.filter((n) => n === "clearance")).toHaveLength(3);
    disposeGroup(g);
  });

  it("places fixtures where the plan says (1 unit = 1 ft, room centred)", () => {
    const g = buildRoomGroup(ROOM, placements, bundle);
    const toilet = g.getObjectByName("fixture:toilet");
    const bowl = toilet.getObjectByName("bowl");
    const world = bowl.getWorldPosition(bowl.position.clone());
    // toilet footprint x 6..26in, room centred (half width = 4ft)
    expect(world.x).toBeGreaterThan(-4 + 6 / 12);
    expect(world.x).toBeLessThan(-4 + 26 / 12);
    // against the top wall: z near -L/2
    expect(world.z).toBeLessThan(-5 + 28 / 12);
  });

  it("marks invalid fixtures", () => {
    const g = buildRoomGroup(ROOM, placements, bundle, new Set(["toilet"]));
    expect(g.getObjectByName("fixture:toilet").getObjectByName("error-outline")).toBeTruthy();
    expect(g.getObjectByName("fixture:shower").getObjectByName("error-outline")).toBeFalsy();
  });
});

describe("updateCutaway", () => {
  it("hides exactly the walls facing the camera", () => {
    const g = buildRoomGroup(ROOM, placements, bundle);
    g.updateMatrixWorld(true);
    // camera in front of the bottom-right corner, above the room
    expect(updateCutaway(g, new THREE.Vector3(10, 12, 12)).sort()).toEqual(["wall:bottom", "wall:right"]);
    // orbit round to the top-left: the other two walls are cut away instead
    expect(updateCutaway(g, new THREE.Vector3(-10, 12, -12)).sort()).toEqual(["wall:left", "wall:top"]);
    expect(g.getObjectByName("wall:right").visible).toBe(true);
  });
});
