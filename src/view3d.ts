// 3D half of the Box view: the assembled box (boxscene.ts) with Explode and Open sliders, each with a ▶ that sweeps
// it back and forth, and "Show assembly", which loops like a gallery tile (assemble, open and close, explode).
// Dimension lines give the finished outside and the inside (calipers on the closed box); compartments get their
// clear size on the floor. After every rebuild the camera keeps its angle and glides so the box fits in every pose
// the sliders can reach. The overlap check runs on the pose shown once nothing moves - not while a parameter slider
// is held or an animation plays - and overlapping parts turn red. Parts an assembler doesn't place yet lie in front.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";
import * as py from "./py";
import { BAD, BAD_EDGE, CHAR, GeometryCache, WOOD, buildBoxScene, lights, type BoxScene, type Pt3 } from "./boxscene";
import type { Build } from "./types";

const PLY = new THREE.MeshStandardMaterial({ color: 0x8a7a5e, roughness: 1, transparent: true, opacity: 0.35 });
const VIEW = new THREE.Vector3(0.9, -1.5, 1.1).normalize();   // the default 3/4 view
const GLIDE_MS = 150;
const FILL = 0.92;            // share of the view the motion envelope fills
const LOOP_MS = 4000;         // a slider's ▶: 0 → 100 → 0
const SEQ = { rest: 0.6, assemble: 900, play: 3600, hold: 400, explode: 900, pause: 700 };   // "Show assembly"
type SeqPhase = "assemble" | "play" | "hold" | "explode" | "pause";

const ease = (x: number) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);
const mm = (v: number) => v.toFixed(1);

function remembered(key: string, fallback: boolean) {
  try {
    const v = localStorage.getItem(key);
    return v == null ? fallback : v === "1";
  } catch {
    return fallback;
  }
}
function remember(key: string, v: boolean) {
  try {
    localStorage.setItem(key, v ? "1" : "0");
  } catch {
    /* private window: not remembered */
  }
}

export function createView3D(el: HTMLElement, controlsEl: HTMLElement, getRequest: () => object) {
  el.replaceChildren();
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  const labels = new CSS2DRenderer();
  labels.domElement.className = "dim-layer";
  el.append(renderer.domElement, labels.domElement);
  const note = document.createElement("div");
  note.className = "placeholder";
  note.hidden = true;
  note.style.pointerEvents = "none";
  note.style.alignItems = "start";
  note.style.paddingTop = "14px";
  el.append(note);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 1, 20000);
  camera.up.set(0, 0, 1);
  camera.position.copy(VIEW).multiplyScalar(300);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  // drawn only when something changed: an idle 3D drawing every frame took CPU from the Python worker, and
  // builds while dragging took 180 ms instead of 30
  let dirty = true;
  const redraw = () => (dirty = true);
  controls.addEventListener("change", redraw);
  lights(scene);
  const grid = new THREE.GridHelper(1000, 100, 0x3a4048, 0x262b31);
  grid.rotation.x = Math.PI / 2;
  scene.add(grid);
  const extras = new THREE.Group();     // sheets under flat parts
  scene.add(extras);
  const clashDots = new THREE.Group();
  scene.add(clashDots);
  const cache = new GeometryCache();

  let box: BoxScene | null = null;
  let partCount = 0;
  let lastKey = "";
  let draft = false;                    // the shown build is a slider-drag build: no overlap check yet
  const pose = { explode: 0, open: 0 };

  // ---- dimensions: lines on the closed box's outside, labels as HTML on top
  const DIM = new THREE.LineBasicMaterial({ color: 0xf2b33d, transparent: true, depthTest: false, depthWrite: false });
  const dims = new THREE.Group();
  scene.add(dims);
  const dimLines = new THREE.LineSegments(new THREE.BufferGeometry(), DIM);
  dimLines.renderOrder = 10;
  dims.add(dimLines);
  const label = (cls: string) => {
    const div = document.createElement("div");
    div.className = cls;
    const o = new CSS2DObject(div);
    dims.add(o);
    return o;
  };
  const dimLabel = { x: label("dim"), y: label("dim"), z: label("dim") };
  const cells = new THREE.Group();
  dims.add(cells);
  let showDims = remembered("superboxes.dims", true);
  let dimSide = "";

  // ---- controls
  controlsEl.replaceChildren();
  const playButton = (label: string, on: () => void) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "play";
    b.textContent = "▶";
    b.title = label;
    b.setAttribute("aria-label", label);
    b.setAttribute("aria-pressed", "false");
    b.onclick = on;
    return b;
  };
  const mk = (key: "explode" | "open", label: string) => {
    const input = document.createElement("input");
    input.type = "range";
    input.min = "0";
    input.max = "100";
    input.step = "1";
    input.value = "0";
    input.onpointerdown = () => stopAll();
    input.oninput = () => {
      stopAll();
      pose[key] = Number(input.value) / 100;
      applyPose();
    };
    input.onchange = () => scheduleClash(0);
    const text = document.createElement("span");
    text.textContent = label;
    const play = playButton(`Play ${label.toLowerCase()} back and forth`, () => (loops[key] ? stopLoop(key) : startLoop(key)));
    const lab = document.createElement("label");
    lab.append(text, input);
    const wrap = document.createElement("span");
    wrap.className = "pose-ctl";
    wrap.append(lab, play);
    return { wrap, input, text, play };
  };
  const seqBtn = document.createElement("button");
  seqBtn.type = "button";
  seqBtn.className = "play-seq";
  seqBtn.setAttribute("aria-pressed", "false");
  seqBtn.title = "Assemble, open and close, explode - in a loop";
  seqBtn.onclick = () => (seq ? stopSeq() : startSeq());
  const explode = mk("explode", "Explode");
  const open = mk("open", "Open lid");
  const dimToggle = document.createElement("label");
  dimToggle.className = "dim-toggle";
  const dimBox = document.createElement("input");
  dimBox.type = "checkbox";
  dimBox.checked = showDims;
  dimBox.onchange = () => {
    showDims = dimBox.checked;
    remember("superboxes.dims", showDims);
    dimSide = "";
    redraw();
    fit(true);
  };
  dimToggle.append(dimBox, document.createTextNode("Dimensions"));
  const status = document.createElement("span");
  const reset = document.createElement("button");
  reset.textContent = "Fit view";
  reset.title = "Fit the box and turn back to the 3/4 view";
  reset.onclick = () => fit(true, true);
  controlsEl.append(seqBtn, explode.wrap, open.wrap, dimToggle, reset, status);

  // ---- size and camera
  let size = "";
  function resize() {
    const w = el.clientWidth;
    const h = el.clientHeight;
    if (!w || !h) return false;
    if (size === `${w}x${h}`) return true;
    size = `${w}x${h}`;
    renderer.setSize(w, h, false);
    labels.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    redraw();
    return true;
  }
  new ResizeObserver(() => {
    if (resize()) fit(false);
  }).observe(el);

  /** Everything the camera must hold: the box in every pose the sliders reach, loose parts, the dimensions. */
  function envelope(): THREE.Box3 {
    const env = new THREE.Box3();
    if (!box) return env;
    if (box.asm.kind !== "assembled") {
      return env.setFromObject(box.root).union(new THREE.Box3().setFromObject(extras));
    }
    const poses = box.hasMotion ? [[0, 0], [1, 0], [0, 1], [1, 1]] : [[0, 0], [1, 0]];
    for (const [e, o] of poses) {
      box.setPose(e, o);
      box.root.updateMatrixWorld(true);
      for (const it of box.items) env.expandByObject(it.mesh);
    }
    box.setPose(pose.explode, pose.open);
    box.root.updateMatrixWorld(true);
    const o = box.asm.outside;
    if (o && showDims) {
      const m = dimOffset() * 1.8;   // dimension lines plus their labels
      env.union(new THREE.Box3(new THREE.Vector3(o.lo[0] - m, o.lo[1] - m, o.lo[2]), new THREE.Vector3(o.hi[0] + m, o.hi[1] + m, o.hi[2])));
    }
    return env;
  }

  let glide: { t0: number; from: THREE.Vector3; to: THREE.Vector3; d0: number; d1: number;
               dir0: THREE.Vector3; dir1: THREE.Vector3 | null } | null = null;

  /** Fit the envelope: keep the viewing angle (or turn back to the 3/4 view), move target and distance. */
  function fit(smooth: boolean, resetAngle = false) {
    if (!box || !el.clientWidth) return;
    const env = envelope();
    if (env.isEmpty()) return;
    const cur = camera.position.clone().sub(controls.target);
    const dir = resetAngle || cur.lengthSq() < 1e-9 ? VIEW.clone() : cur.clone().normalize();
    const fwd = dir.clone().negate();
    const right = new THREE.Vector3().crossVectors(fwd, camera.up);
    if (right.lengthSq() < 1e-9) right.set(1, 0, 0);
    right.normalize();
    const up = new THREE.Vector3().crossVectors(right, fwd).normalize();
    const c = env.getCenter(new THREE.Vector3());
    const pts: THREE.Vector3[] = [];
    for (const x of [env.min.x, env.max.x]) for (const y of [env.min.y, env.max.y]) for (const z of [env.min.z, env.max.z]) {
      const v = new THREE.Vector3(x, y, z).sub(c);
      pts.push(new THREE.Vector3(v.dot(right), v.dot(up), v.dot(dir)));
    }
    // centre what the camera sees, not just the box's middle
    const xm = (Math.min(...pts.map((p) => p.x)) + Math.max(...pts.map((p) => p.x))) / 2;
    const ym = (Math.min(...pts.map((p) => p.y)) + Math.max(...pts.map((p) => p.y))) / 2;
    const target = c.clone().addScaledVector(right, xm).addScaledVector(up, ym);
    const tanV = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * FILL;
    const tanH = tanV * camera.aspect;
    let d = 0;
    for (const p of pts) d = Math.max(d, p.z + Math.abs(p.x - xm) / tanH, p.z + Math.abs(p.y - ym) / tanV);
    const closed = box.asm.outside;
    grid.position.set(c.x, c.y, (closed ? closed.lo[2] : env.min.z) - 0.05);
    if (smooth) {
      glide = { t0: performance.now(), from: controls.target.clone(), to: target, d0: cur.length() || d, d1: d,
                dir0: cur.lengthSq() ? cur.clone().normalize() : dir, dir1: resetAngle ? dir : null };
    } else {
      glide = null;
      place(target, dir, d);
    }
  }

  function place(target: THREE.Vector3, dir: THREE.Vector3, d: number) {
    controls.target.copy(target);
    camera.position.copy(target).addScaledVector(dir, d);
    camera.near = d / 100;
    camera.far = d * 20;
    camera.updateProjectionMatrix();
    redraw();
  }

  function stepGlide(now: number) {
    if (!glide) return;
    const g = glide;
    const k = ease((now - g.t0) / GLIDE_MS);
    const dir = g.dir1 ? g.dir0.clone().lerp(g.dir1, k).normalize() : camera.position.clone().sub(controls.target).normalize();
    place(g.from.clone().lerp(g.to, k), dir, g.d0 + (g.d1 - g.d0) * k);
    if (k >= 1) glide = null;
  }

  // ---- dimensions
  function dimOffset() {
    const o = box?.asm.outside;
    if (!o) return 0;
    return Math.max(o.hi[0] - o.lo[0], o.hi[1] - o.lo[1], o.hi[2] - o.lo[2]) * 0.09 + 4;
  }

  function setLabel(o: CSS2DObject, outside: number, inside: string | null) {
    const b = document.createElement("b");
    b.textContent = mm(outside);
    o.element.replaceChildren(b);
    if (inside) {
      const s = document.createElement("span");
      s.textContent = inside;
      o.element.append(" ", s);
    }
  }

  /** Lines on the three edges facing the camera (they move to the other side as you orbit round). */
  function layoutDims() {
    const o = box?.asm.outside;
    if (!o) return;
    const sx = camera.position.x >= (o.lo[0] + o.hi[0]) / 2 ? 1 : -1;
    const sy = camera.position.y >= (o.lo[1] + o.hi[1]) / 2 ? 1 : -1;
    const key = `${sx}${sy}`;
    if (key === dimSide) return;
    dimSide = key;
    const [x0, y0, z0] = o.lo;
    const [x1, y1, z1] = o.hi;
    const off = dimOffset();
    const over = off * 0.3;
    const a = Math.min(off * 0.45, Math.max(x1 - x0, y1 - y0, z1 - z0) * 0.05);
    const seg: number[] = [];
    const line = (p: Pt3, q: Pt3) => seg.push(...p, ...q);
    const dimension = (p: Pt3, q: Pt3, side: Pt3) => {
      line(p, q);
      const len = Math.hypot(q[0] - p[0], q[1] - p[1], q[2] - p[2]) || 1;
      const d = [(q[0] - p[0]) / len, (q[1] - p[1]) / len, (q[2] - p[2]) / len];
      for (const [tip, s] of [[p, 1], [q, -1]] as [Pt3, number][]) {
        for (const w of [0.35, -0.35]) {
          line(tip, [tip[0] + s * d[0] * a + side[0] * a * w, tip[1] + s * d[1] * a + side[1] * a * w,
                     tip[2] + s * d[2] * a + side[2] * a * w]);
        }
      }
    };
    const yN = sy > 0 ? y1 : y0, xN = sx > 0 ? x1 : x0, xF = sx > 0 ? x0 : x1;
    // X along the bottom edge facing the camera
    const yd = yN + sy * off;
    line([x0, yN, z0], [x0, yd + sy * over, z0]);
    line([x1, yN, z0], [x1, yd + sy * over, z0]);
    dimension([x0, yd, z0], [x1, yd, z0], [0, 1, 0]);
    dimLabel.x.position.set((x0 + x1) / 2, yd, z0);
    // Y along the other bottom edge facing the camera
    const xd = xN + sx * off;
    line([xN, y0, z0], [xd + sx * over, y0, z0]);
    line([xN, y1, z0], [xd + sx * over, y1, z0]);
    dimension([xd, y0, z0], [xd, y1, z0], [1, 0, 0]);
    dimLabel.y.position.set(xd, (y0 + y1) / 2, z0);
    // Z up the far front corner, out to the side
    const xz = xF - sx * off;
    line([xF, yN, z0], [xz - sx * over, yN, z0]);
    line([xF, yN, z1], [xz - sx * over, yN, z1]);
    dimension([xz, yN, z0], [xz, yN, z1], [1, 0, 0]);
    dimLabel.z.position.set(xz, yN, (z0 + z1) / 2);
    dimLines.geometry.dispose();
    dimLines.geometry = new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(seg, 3));
  }

  function fillDims() {
    dimSide = "";
    for (const c of [...cells.children]) {
      cells.remove(c);
      (c as CSS2DObject).element.remove();
    }
    const o = box?.asm.outside;
    const ins = box?.asm.inside;
    if (!o) return;
    const inSize = ins ? [0, 1, 2].map((k) => ins.hi[k] - ins.lo[k]) : null;
    const inText = (k: number) => (inSize ? `in ${mm(inSize[k])}` : null);
    setLabel(dimLabel.x, o.hi[0] - o.lo[0], inText(0));
    setLabel(dimLabel.y, o.hi[1] - o.lo[1], inText(1));
    setLabel(dimLabel.z, o.hi[2] - o.lo[2],
      ins?.front != null ? `in ${mm(ins.front)} front · ${mm(ins.back!)} back` : inText(2));
    for (const c of ins?.cells ?? []) {
      const div = document.createElement("div");
      div.className = "dim-cell";
      div.textContent = `${mm(c.size[0])} × ${mm(c.size[1])}`;
      const obj = new CSS2DObject(div);
      obj.position.set((c.lo[0] + c.hi[0]) / 2, (c.lo[1] + c.hi[1]) / 2, (c.lo[2] + c.hi[2]) / 2 + 0.3);
      const corners: THREE.Vector3[] = [];
      for (const x of [c.lo[0], c.hi[0]]) for (const y of [c.lo[1], c.hi[1]]) for (const z of [c.lo[2], c.hi[2]]) {
        corners.push(new THREE.Vector3(x, y, z));
      }
      obj.userData = { corners, px: div.textContent.length * 6.6 + 12 };
      cells.add(obj);
    }
  }

  const _a = new THREE.Vector3();
  /** Fade the dimensions out as soon as the box opens or comes apart; hide compartment labels that don't fit
   *  inside their compartment as seen from here. */
  function showDimsNow() {
    const fade = Math.max(0, Math.min(1, 1 - Math.max(pose.explode, pose.open) * 5));
    dims.visible = showDims && fade > 0 && !!box?.asm.outside;
    if (!dims.visible) return;
    layoutDims();
    DIM.opacity = 0.9 * fade;
    for (const o of [dimLabel.x, dimLabel.y, dimLabel.z]) o.element.style.opacity = String(fade);
    const w = el.clientWidth / 2, h = el.clientHeight / 2;
    for (const c of cells.children as CSS2DObject[]) {
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      for (const p of c.userData.corners as THREE.Vector3[]) {
        _a.copy(p).project(camera);
        x0 = Math.min(x0, _a.x);
        x1 = Math.max(x1, _a.x);
        y0 = Math.min(y0, _a.y);
        y1 = Math.max(y1, _a.y);
      }
      c.visible = (x1 - x0) * w > c.userData.px && (y1 - y0) * h > 18;
      c.element.style.opacity = String(fade);
    }
  }

  // ---- pose and animation
  const loops: Record<"explode" | "open", { t0: number; phase: number } | null> = { explode: null, open: null };
  let seq: { t0: number; phase: SeqPhase; from: number; fromOpen: number } | null = null;
  const playing = () => !!(seq || loops.explode || loops.open);

  function syncButtons() {
    for (const [k, c] of [["explode", explode], ["open", open]] as const) {
      c.play.textContent = loops[k] ? "⏸" : "▶";
      c.play.setAttribute("aria-pressed", String(!!loops[k]));
    }
    seqBtn.textContent = seq ? "⏸ Show assembly" : "▶ Show assembly";
    seqBtn.setAttribute("aria-pressed", String(!!seq));
  }

  function animationStarted() {
    clearTimeout(clashTimer);
    clashDots.clear();
    redraw();
    for (const it of box?.items ?? []) it.mesh.material = [WOOD, CHAR];
    status.textContent = "playing - the overlap check runs when it stops";
    status.className = "";
    syncButtons();
  }

  function animationStopped() {
    syncButtons();
    if (!playing()) scheduleClash(0);
  }

  function startLoop(k: "explode" | "open") {
    seq = null;
    // start where the slider is, moving up: value = (1 - cos(phase)) / 2
    loops[k] = { t0: performance.now(), phase: Math.acos(1 - 2 * pose[k]) };
    animationStarted();
  }

  function stopLoop(k: "explode" | "open") {
    loops[k] = null;
    animationStopped();
  }

  function startSeq() {
    loops.explode = loops.open = null;
    seq = { t0: performance.now(), phase: "assemble", from: pose.explode || SEQ.rest, fromOpen: pose.open };
    if (!pose.explode) {                 // assembled already: come apart first
      seq.phase = "explode";
      seq.from = 0;
    }
    animationStarted();
  }

  function stopSeq() {
    seq = null;
    animationStopped();
  }

  /** A hand on a slider stops every animation where it is. */
  function stopAll() {
    if (!playing()) return;
    seq = null;
    loops.explode = loops.open = null;
    animationStopped();
  }

  function stepAnimations(now: number) {
    if (!box || !playing()) return;
    for (const k of ["explode", "open"] as const) {
      const l = loops[k];
      if (l) pose[k] = (1 - Math.cos(l.phase + (2 * Math.PI * (now - l.t0)) / LOOP_MS)) / 2;
    }
    const s = seq;
    if (s) {
      const k = (now - s.t0) / SEQ[s.phase];
      const next = (phase: SeqPhase) => {
        s.phase = phase;
        s.t0 = now;
      };
      if (s.phase === "assemble") {
        pose.explode = s.from * (1 - ease(k));
        pose.open = s.fromOpen * (1 - ease(k));
        if (k >= 1) next(box.hasMotion ? "play" : "hold");
      } else if (s.phase === "play") {
        pose.explode = 0;
        pose.open = k >= 1 ? 0 : (1 - Math.cos(2 * Math.PI * k)) / 2;
        if (k >= 1) next("hold");
      } else if (s.phase === "hold") {
        if (k >= 1) next("explode");
      } else if (s.phase === "explode") {
        pose.explode = SEQ.rest * ease(k);
        pose.open = 0;
        if (k >= 1) next("pause");
      } else if (k >= 1) {
        s.from = SEQ.rest;
        s.fromOpen = 0;
        next("assemble");
      }
    }
    if (!box.hasMotion) pose.open = 0;
    explode.input.value = String(Math.round(pose.explode * 100));
    open.input.value = String(Math.round(pose.open * 100));
    box.setPose(pose.explode, pose.open);
    redraw();
  }

  function applyPose() {
    if (!box) return;
    box.setPose(pose.explode, pose.open);
    clashDots.clear();
    redraw();
    scheduleClash(400);
  }

  // ---- overlap check
  let clashTimer = 0;
  function scheduleClash(ms: number) {
    clearTimeout(clashTimer);
    if (box?.asm.kind !== "assembled" || playing() || draft) {
      if (!playing()) status.textContent = "";
      return;
    }
    status.textContent = "checking…";
    status.className = "";
    clashTimer = window.setTimeout(checkClash, ms);
  }

  async function checkClash() {
    if (!box) return;
    // one matrix per part index (child pieces aren't separate parts); loose parts aren't checked
    const matrices: (number[] | null)[] = new Array(partCount).fill(null);
    const owner = new Map<number, BoxScene["items"][number]>();
    for (const it of box.items) {
      if (it.place.group === "loose" || owner.has(it.part.index)) continue;
      owner.set(it.part.index, it);
      const e = it.group.matrix.elements;   // column-major 4x4 -> row-major 3x4
      matrices[it.part.index] = [e[0], e[4], e[8], e[12], e[1], e[5], e[9], e[13], e[2], e[6], e[10], e[14]];
    }
    const r = await py.latest<{ ok: boolean; clashes: { a: number; b: number; count: number; points: Pt3[] }[]; error?: string }>(
      "clash", "clash", { ...getRequest(), matrices });
    if (!r || !box || playing() || draft) return;
    clashDots.clear();
    redraw();
    if (!r.ok) {
      status.textContent = r.error ?? "check failed";
      status.className = "clash";
      return;
    }
    const bad = new Set<number>();
    for (const c of r.clashes) {
      bad.add(c.a);
      bad.add(c.b);
      const g = new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(c.points.flat(), 3));
      clashDots.add(new THREE.Points(g, new THREE.PointsMaterial({ color: 0xff2040, size: 6, sizeAttenuation: false })));
    }
    for (const it of box.items) it.mesh.material = bad.has(it.part.index) ? [BAD, BAD_EDGE] : [WOOD, CHAR];
    if (r.clashes.length) {
      const names = r.clashes.slice(0, 3).map((c) => `${owner.get(c.a)?.part.name} × ${owner.get(c.b)?.part.name}`).join(", ");
      status.textContent = `⚠ ${r.clashes.length} overlap${r.clashes.length > 1 ? "s" : ""}: ${names}`;
      status.className = "clash";
    } else {
      status.textContent = "✓ no parts overlap in this position";
      status.className = "noclash";
    }
  }

  // ---- building
  function build(b: Build, gen: string, thickness: number) {
    if (box) {
      scene.remove(box.root);
      box.dispose();
    }
    extras.clear();
    clashDots.clear();
    redraw();
    partCount = b.parts.length;
    box = buildBoxScene(b, thickness, { cache });
    cache.sweep();
    if (!box) return;
    scene.add(box.root);
    if (box.asm.kind === "flat") {
      // the sheets themselves under the parts, as in the 2D view
      const sh = (getRequest() as { sheet?: { w: number; h: number } }).sheet ?? { w: 297, h: 420 };
      const n = Math.max(1, ...b.placements.map((q) => q.sheet + 1));
      for (let k = 0; k < n; k++) {
        const plane = new THREE.Mesh(new THREE.PlaneGeometry(sh.w, sh.h), PLY);
        plane.position.set(k * (sh.w + 30) + sh.w / 2, sh.h / 2, -0.2);
        extras.add(plane);
      }
    }
    if (!box.hasMotion) {
      loops.open = null;
      pose.open = 0;
      open.input.value = "0";
    }
    open.wrap.hidden = !box.hasMotion;
    open.text.textContent = box.motionLabel || "Open";
    open.play.title = `Play ${open.text.textContent.toLowerCase()} back and forth`;
    explode.wrap.hidden = seqBtn.hidden = box.asm.kind !== "assembled";
    if (box.asm.kind !== "assembled") {
      seq = null;
      loops.explode = null;
    }
    syncButtons();
    const loose = box.asm.parts.filter((p) => p.group === "loose").length;
    note.hidden = box.asm.kind === "assembled" && loose === 0;
    note.textContent = box.asm.kind === "assembled"
      ? `${loose} small part${loose > 1 ? "s lie" : " lies"} in front of the box - ` +
        (gen === "Console2" ? "the panel springs, latches and clamps aren't placed in 3D yet." : "placing them in 3D comes later.")
      : `3D assembly for ${gen} isn't built yet - its parts lie flat, as on the sheets.`;
    fillDims();
    box.setPose(pose.explode, pose.open);
    scheduleClash(0);
  }

  let raf = 0;
  let shown = false;
  const loop = (now: number) => {
    raf = requestAnimationFrame(loop);
    if (!el.offsetParent) {          // hidden (Calibration tab, or the sheets fill the view)
      shown = false;
      return;
    }
    if (!shown) {
      shown = true;
      redraw();
    }
    stepAnimations(now);
    stepGlide(now);
    if (controls.update()) redraw();
    if (!dirty) return;
    dirty = false;
    showDimsNow();
    renderer.render(scene, camera);
    labels.render(scene, camera);
  };
  raf = requestAnimationFrame(loop);
  syncButtons();

  return {
    /** A new build. draft: a parameter slider is still held - no overlap check until the final build. */
    update(b: Build, gen: string, m: { thickness: number }, isDraft = false) {
      draft = isDraft;
      const key = `${gen}|${b.parts.length}`;
      build(b, gen, m.thickness);
      if (!size) resize();             // later size changes come from the ResizeObserver
      if (key !== lastKey) {
        lastKey = key;
        fit(false, true);
      } else {
        fit(true);
      }
    },
    resize() {
      if (resize()) fit(false);
    },
    dispose() {
      cancelAnimationFrame(raf);
      renderer.dispose();
    },
  };
}
