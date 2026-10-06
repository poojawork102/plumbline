// Client-side mirror of backend/layout.py's wall-local geometry, used ONLY
// for instant drag previews. The backend (/api/layout/verify) stays the
// authority: every drop is re-verified there with the same verifier the AI
// layouts go through.

export const DOOR_IN = 30;
export const WALLS = ["top", "right", "bottom", "left"];

/** Map a wall-local rectangle (u along the wall, v into the room) to room coords. */
export function toRoom(wall, u0, v0, spanU, spanV, W, L) {
  if (wall === "top") return [u0, v0, spanU, spanV];
  if (wall === "bottom") return [u0, L - v0 - spanV, spanU, spanV];
  if (wall === "left") return [v0, u0, spanV, spanU];
  return [W - v0 - spanV, u0, spanV, spanU]; // right
}

export function wallRun(wall, W, L) {
  return wall === "top" || wall === "bottom" ? W : L;
}

/** Same as ai_engine.build_placement: geometry derived from (wall, offset). */
export function buildPlacement(fx, wall, offset, W, L) {
  const w = fx.width;
  const d = fx.depth;
  const half = Math.max(w / 2, fx.side_min);
  const u = Math.max(0, Math.min(offset, wallRun(wall, W, L) - w));
  const [x, y, fw, fd] = toRoom(wall, u, 0, w, d, W, L);
  const [ex, ey, ew, ed] = toRoom(wall, u + w / 2 - half, 0, 2 * half, d + fx.front_min, W, L);
  return {
    category: fx.category, side: wall, u, x, y, w: fw, d: fd, u_len: w, v_len: d,
    clearance: { x: ex, y: ey, w: ew, d: ed },
  };
}

/**
 * Where a fixture lands when dropped with its centre at (px, py):
 * snap to the nearest wall, offset so the fixture stays centred on the
 * pointer along that wall.
 */
export function snapToWall(px, py, fx, W, L) {
  // a pointer dragged outside the room still snaps to the wall it crossed
  px = Math.max(0, Math.min(px, W));
  py = Math.max(0, Math.min(py, L));
  const dist = { top: py, bottom: L - py, left: px, right: W - px };
  const wall = WALLS.reduce((best, w) => (dist[w] < dist[best] ? w : best), "top");
  const along = wall === "top" || wall === "bottom" ? px : py;
  const max = Math.max(0, wallRun(wall, W, L) - fx.width);
  const offset = Math.round(Math.max(0, Math.min(along - fx.width / 2, max)));
  return { wall, offset };
}

export function overlaps(a, b, eps = 1e-6) {
  return a.x < b.x + b.w - eps && b.x < a.x + a.w - eps && a.y < b.y + b.d - eps && b.y < a.y + a.d - eps;
}

/** Quick client-side check for live feedback while dragging. */
export function quickProblems(placements, W, L) {
  const floor = placements.filter((p) => p.category !== "faucet");
  const door = { x: 0, y: L - DOOR_IN, w: DOOR_IN, d: DOOR_IN };
  const out = [];
  for (const p of floor) {
    if (overlaps(p, door)) out.push(`${p.category} blocks door swing`);
    const c = p.clearance;
    if (c && (c.x < -1e-6 || c.y < -1e-6 || c.x + c.w > W + 1e-6 || c.y + c.d > L + 1e-6)) {
      out.push(`${p.category} clearance zone outside room`);
    }
    for (const q of floor) {
      if (q === p) continue;
      if (overlaps(p, q)) out.push(`${p.category} overlaps ${q.category}`);
      if (c && overlaps(c, q)) out.push(`${p.category} clearance blocked by ${q.category}`);
    }
  }
  return out;
}

export function arrangementOf(placements) {
  const out = {};
  for (const p of placements) {
    if (p.category !== "faucet") out[p.category] = { wall: p.side, offset: p.u };
  }
  return out;
}

export function feetLabel(inches) {
  const ft = Math.floor(inches / 12);
  const inch = Math.round(inches - ft * 12);
  return inch ? `${ft}′ ${inch}″` : `${ft}′`;
}
