// Box type gallery: one tile per type, rendered in the current material by the same scene builder as the 3D tab.
// At rest a tile shows the box exploded. On hover / keyboard focus the parts assemble quickly, then the box turns
// slowly and plays its motion (lid, drawer, cover); on leaving it explodes again. One shared WebGL renderer draws
// every tile into its own 2D canvas, and only tiles that are moving get redrawn.

import * as THREE from "three";
import { buildBoxScene, lights, type BoxScene } from "./boxscene";
import type { Build } from "./types";

export interface GalleryCtx {
  catalog: { name: string; short: string }[];
  current(): string;
  thickness(): number;
  build(name: string): Promise<Build | null>;
  pick(name: string): void;
}

const REST = 0.6;          // explode amount at rest
const ASSEMBLE_MS = 380;   // parts coming together / flying apart
const TURN = 0.55;         // rad/s while playing
const CYCLE_MS = 3600;     // one open-close cycle
const W = 236, H = 172;    // tile canvas, CSS px

type Phase = "idle" | "assemble" | "play" | "explode";
interface Tile {
  name: string;
  el: HTMLButtonElement;
  canvas: HTMLCanvasElement;
  box: BoxScene | null;
  centre: THREE.Vector3;
  r0: number;              // framing radius while playing (assembled, lid / drawer open)
  r1: number;              // framing radius at rest (exploded)
  phase: Phase;
  t0: number;              // phase start
  explode: number;
  from: number;            // explode at phase start
  angle: number;
  open: number;
  playStart: number;
}

const ease = (x: number) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);

export function createGallery(button: HTMLButtonElement, ctx: GalleryCtx) {
  const pop = document.createElement("div");
  pop.className = "gallery";
  pop.hidden = true;
  pop.setAttribute("role", "dialog");
  pop.setAttribute("aria-label", "Box types");
  const grid = document.createElement("div");
  grid.className = "gallery-grid";
  const hint = document.createElement("p");
  hint.className = "gallery-hint";
  hint.textContent = "Hover a box to see it assemble · Enter picks · Esc closes";
  pop.append(grid, hint);
  document.body.append(pop);

  const dpr = Math.min(devicePixelRatio || 1, 2);
  let renderer: THREE.WebGLRenderer | null = null;
  const scene = new THREE.Scene();
  lights(scene);
  const camera = new THREE.PerspectiveCamera(30, W / H, 1, 20000);
  camera.up.set(0, 0, 1);
  const VIEW = new THREE.Vector3(0.9, -1.5, 1.05).normalize();
  let shown: THREE.Object3D | null = null;
  let builtFor = NaN;      // thickness the tiles were built with
  let raf = 0;

  const tiles: Tile[] = ctx.catalog.map((g) => {
    const el = document.createElement("button");
    el.className = "tile";
    el.type = "button";
    el.title = g.short;
    const canvas = document.createElement("canvas");
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = `${W}px`;
    canvas.style.height = `${H}px`;
    const name = document.createElement("b");
    name.textContent = g.name;
    const short = document.createElement("span");
    short.textContent = g.short.split("\n")[0];
    el.append(canvas, name, short);
    grid.append(el);
    const tile: Tile = {
      name: g.name, el, canvas, box: null, centre: new THREE.Vector3(), r0: 1, r1: 1, phase: "idle", t0: 0,
      explode: REST, from: REST, angle: 0, open: 0, playStart: 0,
    };
    el.onclick = () => {
      close();
      ctx.pick(g.name);
    };
    el.onpointerenter = el.onfocus = () => start(tile);
    el.onpointerleave = el.onblur = () => stop(tile);
    return tile;
  });

  function draw(tile: Tile) {
    if (!tile.box || !renderer) return;
    if (shown !== tile.box.root) {
      if (shown) scene.remove(shown);
      scene.add(tile.box.root);
      shown = tile.box.root;
    }
    tile.box.setPose(tile.explode, tile.open);
    const c = tile.centre;
    const root = tile.box.root;
    root.matrixAutoUpdate = false;
    root.matrix.makeTranslation(c.x, c.y, c.z)
      .multiply(new THREE.Matrix4().makeRotationZ(tile.angle))
      .multiply(new THREE.Matrix4().makeTranslation(-c.x, -c.y, -c.z));
    root.matrixWorldNeedsUpdate = true;
    const r = tile.r0 + (tile.r1 - tile.r0) * (tile.explode / REST);
    const d = r / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.02;
    camera.position.copy(c).addScaledVector(VIEW, d);
    camera.near = d / 50;
    camera.far = d * 10;
    camera.updateProjectionMatrix();
    camera.lookAt(c);
    renderer.render(scene, camera);
    const g = tile.canvas.getContext("2d")!;
    g.clearRect(0, 0, tile.canvas.width, tile.canvas.height);
    g.drawImage(renderer.domElement, 0, 0, tile.canvas.width, tile.canvas.height);
  }

  let prev = 0;
  function frame(now: number) {
    raf = 0;
    const dt = prev ? Math.min(0.05, (now - prev) / 1000) : 0.016;
    prev = now;
    let moving = false;
    for (const tile of tiles) {
      if (tile.phase === "idle" || !tile.box) continue;
      moving = true;
      const k = (now - tile.t0) / ASSEMBLE_MS;
      if (tile.phase === "assemble") {
        tile.explode = tile.from * (1 - ease(k));
        tile.open = 0;
        if (k >= 1) {
          tile.phase = "play";
          tile.t0 = tile.playStart = now;
        }
      } else if (tile.phase === "play") {
        tile.explode = 0;
        tile.angle += TURN * dt;
        tile.open = tile.box.hasMotion ? (1 - Math.cos((2 * Math.PI * (now - tile.playStart)) / CYCLE_MS)) / 2 : 0;
      } else if (tile.phase === "explode") {
        tile.explode = tile.from + (REST - tile.from) * ease(k);
        tile.open *= 0.85;
        tile.angle += TURN * dt * (1 - ease(k));
        if (k >= 1) {
          tile.phase = "idle";
          tile.explode = REST;
          tile.open = 0;
        }
      }
      draw(tile);
    }
    if (moving) raf = requestAnimationFrame(frame);
    else prev = 0;
  }

  function kick() {
    if (!raf) raf = requestAnimationFrame(frame);
  }

  function start(tile: Tile) {
    if (!tile.box || tile.phase === "play" || tile.phase === "assemble") return;
    tile.phase = "assemble";
    tile.from = tile.explode;
    tile.t0 = performance.now();
    kick();
  }

  function stop(tile: Tile) {
    if (tile.phase === "idle" || tile.phase === "explode") return;
    tile.phase = "explode";
    tile.from = tile.explode;
    tile.t0 = performance.now();
    kick();
  }

  async function fill() {
    const t = ctx.thickness();
    if (t === builtFor) return;
    builtFor = t;
    if (!renderer) {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
      renderer.setPixelRatio(1);
      renderer.setSize(W * dpr, H * dpr, false);
    }
    for (const tile of tiles) {
      tile.el.classList.add("loading");
      if (tile.box) {
        if (shown === tile.box.root) {
          scene.remove(shown);
          shown = null;
        }
        tile.box.dispose();
        tile.box = null;
      }
    }
    for (const tile of tiles) {
      const b = await ctx.build(tile.name);
      if (builtFor !== t) return;      // material changed meanwhile: a newer fill runs
      tile.el.classList.remove("loading");
      if (!b?.ok) {
        tile.el.classList.add("failed");
        continue;
      }
      const box = buildBoxScene(b, t, { hideLoose: true });
      if (!box) continue;
      tile.box = box;
      // the box turns about its assembled centre: frame a sphere round it that holds the assembled box with
      // its lid / drawer fully open (playing) and the exploded parts (at rest)
      const assembled = box.assembledBounds();
      const c = assembled.getCenter(new THREE.Vector3());
      const reach = (explode: number, open: number) => {
        box.setPose(explode, open);
        box.root.updateMatrixWorld(true);
        const bb = new THREE.Box3().setFromObject(box.root).union(assembled);
        let r = 0;
        for (const x of [bb.min.x, bb.max.x]) for (const y of [bb.min.y, bb.max.y]) for (const z of [bb.min.z, bb.max.z]) {
          r = Math.max(r, Math.hypot(x - c.x, y - c.y), Math.abs(z - c.z));
        }
        return r;
      };
      tile.centre = c;
      tile.r0 = reach(0, box.hasMotion ? 1 : 0);
      tile.r1 = reach(REST, 0);
      tile.explode = REST;
      tile.angle = 0;
      draw(tile);
      if (tile.el.matches(":hover") || document.activeElement === tile.el) start(tile);
    }
  }

  function place() {
    const r = button.getBoundingClientRect();
    pop.style.left = `${Math.max(8, Math.min(r.left, innerWidth - pop.offsetWidth - 8))}px`;
    pop.style.top = `${r.bottom + 6}px`;
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") {
      close();
      button.focus();
      return;
    }
    const i = tiles.findIndex((t) => t.el === document.activeElement);
    if (i < 0) return;
    const cols = Math.max(1, Math.round(grid.clientWidth / (tiles[0].el.offsetWidth + 10)));
    const step = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols }[e.key];
    if (step) {
      e.preventDefault();
      tiles[Math.min(tiles.length - 1, Math.max(0, i + step))].el.focus();
    }
  }

  function onOutside(e: PointerEvent) {
    if (!pop.contains(e.target as Node) && e.target !== button && !button.contains(e.target as Node)) close();
  }

  function open() {
    tiles.forEach((t) => t.el.classList.toggle("current", t.name === ctx.current()));
    pop.hidden = false;
    place();
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onOutside);
    (tiles.find((t) => t.name === ctx.current()) ?? tiles[0]).el.focus({ preventScroll: true });
    fill();
  }

  function close() {
    pop.hidden = true;
    document.removeEventListener("keydown", onKey);
    document.removeEventListener("pointerdown", onOutside);
    tiles.forEach((t) => {
      if (t.phase !== "idle") {
        t.phase = "idle";
        t.explode = REST;
        t.open = 0;
        draw(t);
      }
    });
  }

  button.onclick = () => (pop.hidden ? open() : close());
  addEventListener("resize", () => !pop.hidden && place());
  return { open, close, invalidate: () => (builtFor = NaN) };
}
