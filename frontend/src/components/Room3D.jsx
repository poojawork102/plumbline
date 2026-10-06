import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { buildRoomGroup, disposeGroup, updateCutaway } from "../lib/scene.js";
import { currentTheme } from "../lib/theme.js";

const BACKGROUND = { light: 0xf8f6f0, dark: 0x16161a };

/** Interactive 3D view of the current layout (orbit, zoom, pan). */
export default function Room3D({ room, placements, bundle, invalid }) {
  const mountRef = useRef(null);
  const ctx = useRef(null);
  const [error, setError] = useState(null);

  // one-time renderer setup
  useEffect(() => {
    const mount = mountRef.current;
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      setError("3D view needs WebGL, which this browser has disabled.");
      return undefined;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(BACKGROUND[currentTheme()]);
    // follow the site's light/dark toggle
    const themeObserver = new MutationObserver(() => scene.background.setHex(BACKGROUND[currentTheme()]));
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    scene.add(new THREE.HemisphereLight(0xffffff, 0xd9d3c4, 1.1));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(6, 14, 10);
    sun.castShadow = true;
    scene.add(sun);

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 200);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.maxPolarAngle = Math.PI / 2.05;

    const resize = () => {
      const w = mount.clientWidth || 600;
      const h = mount.clientHeight || 420;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(mount);

    let frame;
    const loop = () => {
      controls.update();
      if (ctx.current?.group) updateCutaway(ctx.current.group, camera.position);
      renderer.render(scene, camera);
      frame = requestAnimationFrame(loop);
    };
    loop();

    ctx.current = { scene, camera, controls, group: null };
    return () => {
      cancelAnimationFrame(frame);
      themeObserver.disconnect();
      ro.disconnect();
      controls.dispose();
      if (ctx.current?.group) disposeGroup(ctx.current.group);
      renderer.dispose();
      mount.removeChild(renderer.domElement);
      ctx.current = null;
    };
  }, []);

  // rebuild the room whenever the layout changes
  useEffect(() => {
    const c = ctx.current;
    if (!c || !room || !placements) return;
    if (c.group) {
      c.scene.remove(c.group);
      disposeGroup(c.group);
    }
    c.group = buildRoomGroup(room, placements, bundle, invalid);
    c.scene.add(c.group);
  }, [room, placements, bundle, invalid]);

  // frame the camera when the room size changes, not on every drag
  useEffect(() => {
    const c = ctx.current;
    if (!c || !room) return;
    const span = Math.max(room.width, room.length) / 12;
    c.camera.position.set(span * 0.9, span * 1.1, span * 1.4);
    c.controls.target.set(0, 1.5, 0);
    c.controls.update();
  }, [room?.width, room?.length]);

  return (
    <div className="room3d" ref={mountRef} data-testid="room3d">
      {error && <p className="muted center">{error}</p>}
      <span className="room3d-hint">Drag to orbit · scroll to zoom · right-drag to pan</span>
    </div>
  );
}
