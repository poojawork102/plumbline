import { useRef, useState } from "react";
import { buildPlacement, DOOR_IN, feetLabel, snapToWall, WALLS } from "../lib/geometry.js";
import { THEME_COLORS } from "../lib/format.js";

const NUDGE_IN = 6;

/** Wall-local -> room transform so fixture details face into the room. */
function localMatrix(p) {
  switch (p.side) {
    case "top": return [1, 0, 0, 1, p.x, p.y];
    case "bottom": return [1, 0, 0, -1, p.x, p.y + p.d];
    case "left": return [0, 1, 1, 0, p.x, p.y];
    default: return [0, 1, -1, 0, p.x + p.w, p.y];
  }
}

function Detail({ p }) {
  const u = p.u_len;
  const v = p.v_len;
  if (!u || !v) return null;
  if (p.category === "toilet") {
    const tank = v * 0.28;
    const bowl = v - tank;
    return (
      <>
        <rect className="fp-detail" x="0" y="0" width={u} height={tank} />
        <ellipse className="fp-detail" cx={u / 2} cy={tank + bowl / 2} rx={u * 0.4} ry={bowl * 0.45} />
      </>
    );
  }
  if (p.category === "shower") {
    return (
      <>
        <line className="fp-detail" x1="0" y1="0" x2={u} y2={v} />
        <line className="fp-detail" x1={u} y1="0" x2="0" y2={v} />
        <circle className="fp-detail" cx={u / 2} cy={v / 2} r={Math.min(u, v) * 0.07} />
      </>
    );
  }
  if (p.category === "vanity") {
    return <ellipse className="fp-detail" cx={u / 2} cy={v / 2} rx={u * 0.3} ry={v * 0.25} />;
  }
  return null;
}

/** Labels sit in the clear floor just in front of the fixture, so shallow
 * fixtures (a 5in-deep mirror vanity) never clip their own label. */
export function labelPosition(p, fs) {
  const [nx, ny] = { top: [0, 1], bottom: [0, -1], left: [1, 0], right: [-1, 0] }[p.side] || [0, 0];
  const reach = (nx ? p.w : p.d) / 2 + fs * 0.9;
  return { x: p.x + p.w / 2 + nx * reach, y: p.y + p.d / 2 + ny * reach + fs * 0.2 };
}

/**
 * 2D plan with drag-and-drop fixture editing.
 *
 * While dragging, the fixture snaps to the nearest wall and `onPreview` gets
 * the locally-derived placement (instant feedback). On release `onCommit`
 * gets {category, wall, offset}; the parent sends it to the backend verifier.
 * Keyboard: focus a fixture, arrows slide it along its wall, R moves it to
 * the next wall.
 */
export default function FloorPlan({ room, placements, fixtures, invalid = new Set(), editable = true, onPreview, onCommit }) {
  const svgRef = useRef(null);
  const [drag, setDrag] = useState(null);
  const [hover, setHover] = useState(null);
  const W = room.width;
  const L = room.length;
  const pad = 30;
  const fs = Math.max(3.4, Math.max(W, L) / 34);
  const specs = Object.fromEntries((fixtures || []).map((f) => [f.category, f]));

  const toSvg = (ev) => {
    const svg = svgRef.current;
    const ctm = svg?.getScreenCTM?.();
    if (!ctm) return null;
    const pt = svg.createSVGPoint();
    pt.x = ev.clientX;
    pt.y = ev.clientY;
    const r = pt.matrixTransform(ctm.inverse());
    return { x: r.x, y: r.y };
  };

  const startDrag = (ev, p) => {
    if (!editable || !specs[p.category]) return;
    ev.preventDefault();
    ev.currentTarget.setPointerCapture?.(ev.pointerId);
    const pt = toSvg(ev);
    if (!pt) return;
    // keep the grab point relative to the fixture centre
    setDrag({ category: p.category, dx: pt.x - (p.x + p.w / 2), dy: pt.y - (p.y + p.d / 2), last: null });
  };

  const moveDrag = (ev) => {
    if (!drag) return;
    const pt = toSvg(ev);
    if (!pt) return;
    const fx = specs[drag.category];
    const { wall, offset } = snapToWall(pt.x - drag.dx, pt.y - drag.dy, fx, W, L);
    if (drag.last && drag.last.wall === wall && drag.last.offset === offset) return;
    setDrag({ ...drag, last: { wall, offset } });
    onPreview?.(drag.category, buildPlacement(fx, wall, offset, W, L));
  };

  const endDrag = () => {
    if (!drag) return;
    if (drag.last) onCommit?.({ category: drag.category, ...drag.last });
    setDrag(null);
  };

  const onKey = (ev, p) => {
    if (!editable || !specs[p.category]) return;
    let wall = p.side;
    let offset = p.u;
    if (["ArrowLeft", "ArrowUp"].includes(ev.key)) offset -= NUDGE_IN;
    else if (["ArrowRight", "ArrowDown"].includes(ev.key)) offset += NUDGE_IN;
    else if (ev.key === "r" || ev.key === "R") {
      wall = WALLS[(WALLS.indexOf(p.side) + 1) % WALLS.length];
      offset = 0;
    } else return;
    ev.preventDefault();
    const placed = buildPlacement(specs[p.category], wall, offset, W, L);
    onPreview?.(p.category, placed);
    onCommit?.({ category: p.category, wall, offset: placed.u });
  };

  const floor = placements.filter((p) => p.category !== "faucet");
  const faucets = placements.filter((p) => p.category === "faucet" && !(drag && drag.category === "vanity"));

  const active = drag?.category || hover;
  const HIT_MIN = 18; // inches: thin fixtures (a 5in mirror vanity) still get a usable grab area
  const hitRect = (p) => {
    const w = Math.max(p.w, HIT_MIN);
    const d = Math.max(p.d, HIT_MIN);
    return { x: p.x + p.w / 2 - w / 2, y: p.y + p.d / 2 - d / 2, width: w, height: d };
  };
  const wallLine = (wall) => ({
    top: [0, 0, W, 0], bottom: [0, L, W, L], left: [0, 0, 0, L], right: [W, 0, W, L],
  })[wall];

  const grid = [];
  for (let x = 0; x <= W + 0.01; x += 12) grid.push(<line key={`gx${x}`} x1={x} y1="0" x2={x} y2={L} />);
  for (let y = 0; y <= L + 0.01; y += 12) grid.push(<line key={`gy${y}`} x1="0" y1={y} x2={W} y2={y} />);

  return (
    <>
    <svg
      ref={svgRef}
      className={`floorplan ${drag ? "dragging" : ""}`}
      viewBox={`${-pad} ${-pad} ${W + pad * 2} ${L + pad * 2}`}
      onPointerMove={moveDrag}
      onPointerUp={endDrag}
      onPointerLeave={endDrag}
      role="img"
      aria-label="Bathroom floor plan"
      data-testid="floorplan"
    >
      <g className="fp-grid">{grid}</g>

      {floor.map((p) => p.clearance && (
        <rect key={`c-${p.category}`}
          className={`fp-clearance ${invalid.has(p.category) ? "bad" : ""} ${active === p.category ? "active" : ""} ${active && active !== p.category ? "dim" : ""}`}
          x={p.clearance.x} y={p.clearance.y} width={p.clearance.w} height={p.clearance.d}
          data-testid={`clearance-${p.category}`} />
      ))}

      {drag?.last && (() => {
        const [x1, y1, x2, y2] = wallLine(drag.last.wall);
        return <line className="fp-target-wall" x1={x1} y1={y1} x2={x2} y2={y2} data-testid="target-wall" />;
      })()}

      <line className="fp-door-gap" x1="0" y1={L} x2={DOOR_IN} y2={L} />
      <path className="fp-door" d={`M 0 ${L} A ${DOOR_IN} ${DOOR_IN} 0 0 1 ${DOOR_IN} ${L - DOOR_IN}`} />
      <line className="fp-leaf" x1={DOOR_IN} y1={L} x2={DOOR_IN} y2={L - DOOR_IN} />

      {floor.map((p) => (
        <g
          key={p.category}
          className={`fp-fixture-group ${editable ? "editable" : ""} ${invalid.has(p.category) ? "invalid" : ""}`}
          onPointerDown={(ev) => startDrag(ev, p)}
          onPointerEnter={() => setHover(p.category)}
          onPointerLeave={() => setHover((h) => (h === p.category ? null : h))}
          onFocus={() => setHover(p.category)}
          onBlur={() => setHover(null)}
          onKeyDown={(ev) => onKey(ev, p)}
          tabIndex={editable ? 0 : -1}
          role={editable ? "button" : undefined}
          aria-label={`${p.category} on ${p.side} wall${editable ? " — drag, or use arrow keys and R to move" : ""}`}
          data-testid={`fixture-${p.category}`}
        >
          <title>{`${p.name || p.category} · ${p.u_len} × ${p.v_len} in`}</title>
          <rect className="fp-hit" {...hitRect(p)} />
          <rect className="fp-fixture" x={p.x} y={p.y} width={p.w} height={p.d}
            style={{ fill: THEME_COLORS[p.category] }} />
          <g transform={`matrix(${localMatrix(p).join(" ")})`}><Detail p={p} /></g>
          <text className="fp-label" fontSize={fs * 0.62} {...labelPosition(p, fs)} textAnchor="middle">
            {p.category.toUpperCase()}
          </text>
        </g>
      ))}

      {faucets.map((p) => (
        <rect key="faucet" className="fp-faucet" x={p.x} y={p.y} width={p.w} height={p.d} rx="1.2" />
      ))}

      <g className="fp-dims">
        <line className="fp-dim" x1="0" y1="-14" x2={W} y2="-14" />
        <text className="fp-text" fontSize={fs} x={W / 2} y="-19" textAnchor="middle">{feetLabel(W)}</text>
        <line className="fp-dim" x1="-14" y1="0" x2="-14" y2={L} />
        <text className="fp-text" fontSize={fs} x="-19" y={L / 2} textAnchor="middle" transform={`rotate(-90 -19 ${L / 2})`}>{feetLabel(L)}</text>
      </g>
      <rect className="fp-wall" x="0" y="0" width={W} height={L} />
    </svg>
    {editable && (
      <p className="fp-legend small muted">
        <span className="swatch clearance" /> Clear floor a fixture needs — zones may share space, never a fixture
        <span className="swatch target" /> Wall it will snap to
      </p>
    )}
    </>
  );
}
