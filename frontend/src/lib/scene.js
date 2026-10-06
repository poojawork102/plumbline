// Builds a Three.js scene graph for a verified layout. Kept free of any
// renderer so it can be unit-tested in Node (no WebGL needed).
//
// Units: 1 three.js unit = 1 foot. Room x -> three x, room y -> three z,
// height -> three y. The room is centred on the origin.
import * as THREE from "three";
import { DOOR_IN } from "./geometry.js";

const FT = 1 / 12;
const WALL_H = 8;
const WALL_T = 0.35;

const MATERIALS = {
  floor: () => new THREE.MeshStandardMaterial({ color: 0xe9e4d8, roughness: 0.9 }),
  wall: () => new THREE.MeshStandardMaterial({ color: 0xf8f6f0, roughness: 0.95 }),
  porcelain: () => new THREE.MeshStandardMaterial({ color: 0xfbfbf8, roughness: 0.25 }),
  wood: () => new THREE.MeshStandardMaterial({ color: 0x8b7355, roughness: 0.7 }),
  glass: () => new THREE.MeshPhysicalMaterial({ color: 0xbcd6de, transparent: true, opacity: 0.28, roughness: 0.05 }),
  tray: () => new THREE.MeshStandardMaterial({ color: 0x5a7d8c, roughness: 0.4 }),
  metal: () => new THREE.MeshStandardMaterial({ color: 0xb89758, metalness: 0.8, roughness: 0.3 }),
  clearance: () => new THREE.MeshBasicMaterial({ color: 0xb89758, transparent: true, opacity: 0.18, depthWrite: false }),
  error: () => new THREE.MeshStandardMaterial({ color: 0xd32f2f, transparent: true, opacity: 0.55 }),
};

function box(w, h, d, material, x, y, z, name) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  mesh.position.set(x, y, z);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  if (name) mesh.name = name;
  return mesh;
}

/** Direction a fixture faces (into the room) for each wall. */
function facing(side) {
  return { top: [0, 1], bottom: [0, -1], left: [1, 0], right: [-1, 0] }[side];
}

function fixtureMeshes(p, height, invalid) {
  const g = new THREE.Group();
  g.name = `fixture:${p.category}`;
  g.userData = { category: p.category, id: p.id, name: p.name };
  const w = p.w * FT;
  const d = p.d * FT;
  const cx = (p.x + p.w / 2) * FT;
  const cz = (p.y + p.d / 2) * FT;
  const h = Math.max(0.5, (height || 30) * FT);

  if (p.category === "shower") {
    g.add(box(w, 0.25, d, MATERIALS.tray(), cx, 0.125, cz, "tray"));
    g.add(box(w, 6.5, d, MATERIALS.glass(), cx, 0.25 + 3.25, cz, "enclosure"));
    const [fx, fz] = facing(p.side);
    // shower head on the back wall
    g.add(box(0.5, 0.08, 0.5, MATERIALS.metal(), cx - fx * (w / 2 - 0.4), 6.6, cz - fz * (d / 2 - 0.4), "head"));
  } else if (p.category === "toilet") {
    const [fx, fz] = facing(p.side);
    const tankDepth = (fx ? w : d) * 0.3;
    const bowlH = Math.min(h, 1.4);
    g.add(box(w * 0.85, bowlH, d * 0.85, MATERIALS.porcelain(), cx + fx * tankDepth * 0.3, bowlH / 2, cz + fz * tankDepth * 0.3, "bowl"));
    const tw = fx ? tankDepth : w;
    const td = fz ? tankDepth : d;
    g.add(box(tw, 2.4, td, MATERIALS.porcelain(), cx - fx * (w / 2 - tankDepth / 2), 1.2, cz - fz * (d / 2 - tankDepth / 2), "tank"));
  } else if (p.category === "vanity") {
    const vh = Math.min(h, 2.9);
    g.add(box(w, vh, d, MATERIALS.wood(), cx, vh / 2, cz, "cabinet"));
    g.add(box(w * 0.55, 0.12, d * 0.55, MATERIALS.porcelain(), cx, vh + 0.06, cz, "basin"));
    // mirror above the vanity, flush to its wall
    const [fx, fz] = facing(p.side);
    const mw = fx ? 0.05 : w * 0.8;
    const md = fz ? 0.05 : d * 0.8;
    g.add(box(mw, 2.2, md, MATERIALS.glass(), cx - fx * (w / 2), vh + 2.2, cz - fz * (d / 2), "mirror"));
  } else if (p.category === "faucet") {
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.1, 0.8, 16), MATERIALS.metal());
    mesh.position.set(cx, 2.9 + 0.4, cz);
    mesh.name = "spout";
    g.add(mesh);
  }

  if (invalid) {
    g.add(box(w + 0.05, 0.05, d + 0.05, MATERIALS.error(), cx, 0.03, cz, "error-outline"));
  }
  if (p.clearance && p.category !== "faucet") {
    const c = p.clearance;
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(c.w * FT, c.d * FT), MATERIALS.clearance());
    plane.rotation.x = -Math.PI / 2;
    plane.position.set((c.x + c.w / 2) * FT, 0.01, (c.y + c.d / 2) * FT);
    plane.name = "clearance";
    g.add(plane);
  }
  return g;
}

/**
 * @param {{width:number,length:number}} room  inches
 * @param {Array} placements  layout placements (inches, room coords)
 * @param {Array} bundle      catalogue products (for heights)
 * @param {Set<string>} invalid categories currently failing verification
 */
export function buildRoomGroup(room, placements, bundle = [], invalid = new Set()) {
  const W = room.width * FT;
  const L = room.length * FT;
  const root = new THREE.Group();
  root.name = "room";
  const content = new THREE.Group();
  content.position.set(-W / 2, 0, -L / 2);
  root.add(content);

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(W, L), MATERIALS.floor());
  floor.rotation.x = -Math.PI / 2;
  floor.position.set(W / 2, 0, L / 2);
  floor.receiveShadow = true;
  floor.name = "floor";
  content.add(floor);

  const wallMat = MATERIALS.wall();
  const door = DOOR_IN * FT;
  const walls = [
    box(W + 2 * WALL_T, WALL_H, WALL_T, wallMat, W / 2, WALL_H / 2, -WALL_T / 2, "wall:top"),
    box(WALL_T, WALL_H, L, wallMat, -WALL_T / 2, WALL_H / 2, L / 2, "wall:left"),
    box(WALL_T, WALL_H, L, wallMat, W + WALL_T / 2, WALL_H / 2, L / 2, "wall:right"),
    // bottom wall leaves a gap for the door in the bottom-left corner
    box(W - door, WALL_H, WALL_T, wallMat, door + (W - door) / 2, WALL_H / 2, L + WALL_T / 2, "wall:bottom"),
  ];
  const normals = { top: [0, -1], bottom: [0, 1], left: [-1, 0], right: [1, 0] };
  for (const wall of walls) {
    // outward normal in room-centred coordinates, used by updateCutaway()
    const [nx, nz] = normals[wall.name.slice(5)];
    wall.userData.outward = new THREE.Vector3(nx, 0, nz);
    wall.userData.cutaway = true;
    content.add(wall);
  }

  // door swing arc on the floor
  const arc = new THREE.Mesh(
    new THREE.RingGeometry(door - 0.04, door, 32, 1, 0, Math.PI / 2),
    new THREE.MeshBasicMaterial({ color: 0xb89758, side: THREE.DoubleSide }),
  );
  arc.rotation.x = -Math.PI / 2;
  arc.position.set(0, 0.02, L);
  arc.name = "door-swing";
  content.add(arc);

  const heights = Object.fromEntries(bundle.map((p) => [p.id, p.dimensions_in?.height]));
  for (const p of placements) {
    content.add(fixtureMeshes(p, heights[p.id], invalid.has(p.category)));
  }
  return root;
}

/**
 * Hide walls between the camera and the room (architectural cut-away), so
 * fixtures are always visible from any orbit angle. Returns the hidden walls.
 */
export function updateCutaway(group, cameraPosition) {
  const hidden = [];
  group.traverse((obj) => {
    if (!obj.userData?.cutaway) return;
    const wallPos = obj.getWorldPosition(new THREE.Vector3());
    const toCamera = cameraPosition.clone().sub(wallPos);
    toCamera.y = 0;
    obj.visible = toCamera.dot(obj.userData.outward) <= 0;
    if (!obj.visible) hidden.push(obj.name);
  });
  return hidden;
}

export function disposeGroup(group) {
  group.traverse((obj) => {
    if (obj.geometry) obj.geometry.dispose();
    if (obj.material) obj.material.dispose();
  });
}
