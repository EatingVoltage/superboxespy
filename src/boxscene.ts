// A box as a three.js scene graph: the real cut outlines extruded to the sheet thickness and put where Python's
// assembly says, posed by explode (0 = assembled) and open (0 = closed). Shared by the 3D tab and the gallery.

import * as THREE from "three";
import type { Build, PartJ, Pt, ShapePoly } from "./types";

export type Pt3 = [number, number, number];
export type Motion = null | { type: "hinge"; point: Pt3; axis: Pt3; max: number } | { type: "slide"; dir: Pt3; max: number };
export interface Placed3D {
  kind: "wall" | "flat";
  m: number[];
  explode: Pt3;
  group: string;
  motion: Motion;
  children?: Placed3D[];
}
export interface Extent { lo: Pt3; hi: Pt3 }
/** The clear inside of the closed box; cells = compartments (floor or opening as a flat box, clear size);
 *  front/back = inside height at the front and back of a sloped box. */
export interface Inside extends Extent { cells: (Extent & { size: [number, number] })[]; front?: number; back?: number }
export interface Assembly {
  kind: "assembled" | "flat";
  parts: Placed3D[];
  size: Pt3 | null;
  outside: Extent | null;   // measured from the placed solids, lid closed: what calipers read
  inside: Inside | null;
}

export const WOOD = new THREE.MeshStandardMaterial({ color: 0xf0dcb4, roughness: 0.8, metalness: 0 });
export const CHAR = new THREE.MeshStandardMaterial({ color: 0x5b3a1e, roughness: 0.95, metalness: 0 });
export const BAD = new THREE.MeshStandardMaterial({ color: 0xff5a73, roughness: 0.7, metalness: 0, emissive: 0x400010 });
export const BAD_EDGE = new THREE.MeshStandardMaterial({ color: 0x9b1030, roughness: 0.9 });
const ENGRAVE = new THREE.LineBasicMaterial({ color: 0x4a2c12 });
const EDGES = new THREE.LineBasicMaterial({ color: 0x3b250f, transparent: true, opacity: 0.55 });

export function lights(scene: THREE.Scene) {
  scene.add(new THREE.HemisphereLight(0xfff4e0, 0x3a3f48, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 2.2);
  sun.position.set(-1, -1.6, 2.4);
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0xbfd4ff, 0.9);
  fill.position.set(2, 1.5, 0.8);
  scene.add(fill);
}

function shapeOf(poly: ShapePoly): THREE.Shape {
  const s = new THREE.Shape(poly.outer.map(([x, y]) => new THREE.Vector2(x, y)));
  for (const hole of poly.holes) s.holes.push(new THREE.Path(hole.map(([x, y]) => new THREE.Vector2(x, y))));
  return s;
}

function matrix4(m: number[]): THREE.Matrix4 {
  const M = new THREE.Matrix4();
  M.set(m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9], m[10], m[11], 0, 0, 0, 1);
  return M;
}

export interface Item { group: THREE.Group; mesh: THREE.Mesh; base: THREE.Matrix4; place: Placed3D; part: PartJ }

export interface BoxScene {
  root: THREE.Group;
  items: Item[];            // parts and their child pieces
  asm: Assembly;
  hasMotion: boolean;
  motionLabel: string;
  setPose(explode: number, open: number): void;
  assembledBounds(): THREE.Box3;
  dispose(): void;
}

function solid(polys: ShapePoly[], thickness: number) {
  return new THREE.ExtrudeGeometry(polys.map(shapeOf), { depth: thickness, bevelEnabled: false, curveSegments: 6 });
}

/** The slab's visible edges straight from its outline: every ring on both faces, plus the side edges at corners
 *  sharper than 25°. Same lines as EdgesGeometry(solid, 25), without searching the triangles for them. */
function slabEdges(polys: ShapePoly[], thickness: number) {
  const out: number[] = [];
  const cos25 = Math.cos(THREE.MathUtils.degToRad(25));
  for (const poly of polys) {
    for (const ring of [poly.outer, ...poly.holes]) {
      const n = ring.length;
      for (let i = 0; i < n; i++) {
        const [ax, ay] = ring[i], [bx, by] = ring[(i + 1) % n], [px, py] = ring[(i + n - 1) % n];
        out.push(ax, ay, 0, bx, by, 0, ax, ay, thickness, bx, by, thickness);
        const ux = ax - px, uy = ay - py, vx = bx - ax, vy = by - ay;
        const lu = Math.hypot(ux, uy), lv = Math.hypot(vx, vy);
        if (lu && lv && (ux * vx + uy * vy) / (lu * lv) < cos25) out.push(ax, ay, 0, ax, ay, thickness);
      }
    }
  }
  return new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(out, 3));
}

/** Solids kept from one build to the next, keyed by outline: while a slider drags, only the parts that changed
 *  are triangulated again (HobbyCase's back panel alone takes ~100 ms). The owner calls sweep() after a build. */
export class GeometryCache {
  private map = new Map<string, { geo: THREE.BufferGeometry; edges: THREE.BufferGeometry; used: boolean }>();
  private mine = new Set<THREE.BufferGeometry>();
  get(polys: ShapePoly[], thickness: number) {
    const key = `${thickness}|${JSON.stringify(polys)}`;
    let e = this.map.get(key);
    if (!e) {
      e = { geo: solid(polys, thickness), edges: slabEdges(polys, thickness), used: false };
      this.map.set(key, e);
      this.mine.add(e.geo).add(e.edges);
    }
    e.used = true;
    return e;
  }
  owns(geo: THREE.BufferGeometry) {
    return this.mine.has(geo);
  }
  /** Drop what the last build didn't use. */
  sweep() {
    for (const [k, e] of this.map) {
      if (!e.used) {
        e.geo.dispose();
        e.edges.dispose();
        this.mine.delete(e.geo);
        this.mine.delete(e.edges);
        this.map.delete(k);
      } else e.used = false;
    }
  }
}

function engraving(part: PartJ, thickness: number): THREE.LineSegments | null {
  const segs: number[] = [];
  const z = thickness + 0.03;
  for (const d of part.deco) {
    if (d.layer !== 1) continue;
    for (const line of d.lines) for (let i = 1; i < line.length; i++) segs.push(line[i - 1][0], line[i - 1][1], z, line[i][0], line[i][1], z);
  }
  for (const s of part.paths["1"] ?? []) {
    let cur = s.start;
    for (const g of s.segs) {
      const end: Pt = g.length === 2 ? [g[0], g[1]] : [g[4], g[5]];
      segs.push(cur[0], cur[1], z, end[0], end[1], z);
      cur = end;
    }
  }
  if (!segs.length) return null;
  const geo = new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(segs, 3));
  return new THREE.LineSegments(geo, ENGRAVE);
}

export function motionLabel(asm: Assembly): string {
  const m = asm.parts.find((p) => p.motion)?.motion;
  if (!m) return "";
  if (m.type === "hinge") return "Open lid";
  const lidLike = asm.parts.some((p) => p.motion && p.group === "lid");
  return lidLike ? "Lift cover" : "Pull drawer";
}

export function buildBoxScene(b: Build, thickness: number,
                              opts: { hideLoose?: boolean; cache?: GeometryCache } = {}): BoxScene | null {
  const asm = (b as any).assembly as Assembly | undefined;
  if (!asm) return null;
  const root = new THREE.Group();
  const items: Item[] = [];
  const add = (part: PartJ, place: Placed3D, polys: ShapePoly[] | null, withExtras: boolean) => {
    if (!polys) return;
    const { geo, edges } = opts.cache?.get(polys, thickness) ?? { geo: solid(polys, thickness), edges: slabEdges(polys, thickness) };
    const mesh = new THREE.Mesh(geo, [WOOD, CHAR]);
    const group = new THREE.Group();
    group.matrixAutoUpdate = false;
    group.add(mesh);
    group.add(new THREE.LineSegments(edges, EDGES));
    if (withExtras) {
      const eng = engraving(part, thickness);
      if (eng) group.add(eng);
    }
    root.add(group);
    items.push({ group, mesh, base: matrix4(place.m), place, part });
  };
  for (const part of b.parts) {
    const place = asm.parts[part.index];
    if (!place || (opts.hideLoose && place.group === "loose")) continue;
    add(part, place, part.shape, true);
    (part.children ?? []).forEach((c, k) => {
      const cp = place.children?.[k] ?? place;
      add(part, cp, c, false);
    });
  }
  const tmp = new THREE.Matrix4();
  const poseMatrix = (p: Placed3D, explode: number, open: number) => {
    const M = new THREE.Matrix4();
    const mo = p.motion;
    if (mo?.type === "hinge" && open > 0) {
      const pt = new THREE.Vector3(...mo.point);
      M.makeTranslation(pt.x, pt.y, pt.z)
        .multiply(tmp.makeRotationAxis(new THREE.Vector3(...mo.axis).normalize(), THREE.MathUtils.degToRad(-mo.max * open)))
        .multiply(new THREE.Matrix4().makeTranslation(-pt.x, -pt.y, -pt.z));
    } else if (mo?.type === "slide" && open > 0) {
      const d = new THREE.Vector3(...mo.dir).multiplyScalar(mo.max * open);
      M.makeTranslation(d.x, d.y, d.z);
    }
    if (explode > 0 && asm.kind === "assembled") {
      const e = new THREE.Vector3(...p.explode).multiplyScalar(explode);
      M.premultiply(new THREE.Matrix4().makeTranslation(e.x, e.y, e.z));
    }
    return M;
  };
  const scene: BoxScene = {
    root, items, asm,
    hasMotion: asm.parts.some((p) => p.motion),
    motionLabel: motionLabel(asm),
    setPose(explode, open) {
      for (const it of items) {
        it.group.matrix.copy(poseMatrix(it.place, explode, open).multiply(it.base));
        it.group.matrixWorldNeedsUpdate = true;
      }
    },
    assembledBounds() {
      scene.setPose(0, 0);
      root.updateMatrixWorld(true);
      const box = new THREE.Box3();
      for (const it of items) if (it.place.group !== "loose") box.expandByObject(it.group);
      return box.isEmpty() ? new THREE.Box3().setFromObject(root) : box;
    },
    dispose() {
      root.traverse((o) => {
        const g = (o as THREE.Mesh).geometry;
        if (g && !opts.cache?.owns(g)) g.dispose();
      });
    },
  };
  scene.setPose(0, 0);
  return scene;
}
