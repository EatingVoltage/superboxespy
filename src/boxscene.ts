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
/** Things in the box that aren't cut parts (the stamp case's magnets and stamps), in world coordinates of the
 *  assembled box; each moves with the part it belongs to (explode, lid). */
export type Extra =
  | { kind: "cylinder"; at: Pt3; r: number; h: number; part: number; color: "magnet" }
  | { kind: "box"; lo: Pt3; hi: Pt3; part: number; color: "stamp"; bad?: boolean; name?: string };
export interface Assembly {
  kind: "assembled" | "flat";
  parts: Placed3D[];
  size: Pt3 | null;
  outside: Extent | null;   // measured from the placed solids, lid closed: what calipers read
  inside: Inside | null;
  extras?: Extra[];
}

export const WOOD = new THREE.MeshStandardMaterial({ color: 0xf0dcb4, roughness: 0.8, metalness: 0 });
export const CHAR = new THREE.MeshStandardMaterial({ color: 0x5b3a1e, roughness: 0.95, metalness: 0 });
export const BAD = new THREE.MeshStandardMaterial({ color: 0xff5a73, roughness: 0.7, metalness: 0, emissive: 0x400010 });
export const BAD_EDGE = new THREE.MeshStandardMaterial({ color: 0x9b1030, roughness: 0.9 });
const ENGRAVE = new THREE.LineBasicMaterial({ color: 0x4a2c12 });
const MAGNET = new THREE.MeshStandardMaterial({ color: 0x9aa3ad, roughness: 0.35, metalness: 0.8 });
const STAMP = new THREE.MeshStandardMaterial({ color: 0x8c3b2f, roughness: 0.9, metalness: 0 });
export const EDGES = new THREE.LineBasicMaterial({ color: 0x3b250f, transparent: true, opacity: 0.55 });
// the magnets' and stamps' one solid each, scaled per instance; shared by every scene, never disposed
const UNIT_CYLINDER = new THREE.CylinderGeometry(1, 1, 1, 20);
const UNIT_BOX = new THREE.BoxGeometry(1, 1, 1);
const SHARED = new Set<THREE.BufferGeometry>([UNIT_CYLINDER, UNIT_BOX]);

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

export interface Item { group: THREE.Group; mesh: THREE.Mesh; edges: THREE.LineSegments; base: THREE.Matrix4; place: Placed3D;
                       part: PartJ }

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

/** Solids and FILL areas kept from one build to the next, keyed by what they're made from: while a slider drags or
 *  a face is edited, only the parts that changed are triangulated again (HobbyCase's back panel alone takes
 *  ~100 ms; a filled logo's earcut ~10x its key). Engraved lines aren't kept: building them costs less than their
 *  key would. The owner calls sweep() after a build. */
export class GeometryCache {
  private map = new Map<string, { geos: THREE.BufferGeometry[]; used: boolean }>();
  private mine = new Set<THREE.BufferGeometry>();
  private entry(key: string, make: () => THREE.BufferGeometry[]) {
    let e = this.map.get(key);
    if (!e) {
      e = { geos: make(), used: false };
      this.map.set(key, e);
      for (const g of e.geos) this.mine.add(g);
    }
    e.used = true;
    return e.geos;
  }
  get(polys: ShapePoly[], thickness: number) {
    const [geo, edges] = this.entry(`${thickness}|${JSON.stringify(polys)}`,
      () => [solid(polys, thickness), slabEdges(polys, thickness)]);
    return { geo, edges };
  }
  fill(polys: Pt[][][]) {
    return this.entry(`fill|${JSON.stringify(polys)}`, () => [fillGeometry(polys)])[0];
  }
  owns(geo: THREE.BufferGeometry) {
    return this.mine.has(geo);
  }
  /** Drop what the last build didn't use. */
  sweep() {
    for (const [k, e] of this.map) {
      if (!e.used) {
        for (const g of e.geos) {
          g.dispose();
          this.mine.delete(g);
        }
        this.map.delete(k);
      } else e.used = false;
    }
  }
}

const ENGRAVE_FILL = new THREE.MeshBasicMaterial({ color: 0x4a2c12, side: THREE.DoubleSide, polygonOffset: true,
  polygonOffsetFactor: -1, polygonOffsetUnits: -1 });

/** FILL's areas ([outer, holes...] each) as triangles. */
function fillGeometry(polys: Pt[][][]) {
  return new THREE.ShapeGeometry(polys.map(([outer, ...holes]) => {
    const s = new THREE.Shape(outer.map(([x, y]) => new THREE.Vector2(x, y)));
    s.holes = holes.map((r) => new THREE.Path(r.map(([x, y]) => new THREE.Vector2(x, y))));
    return s;
  }));
}

/** A logo's filled areas (FILL), as a burnt patch on the face they're engraved on. */
function engravedFill(part: PartJ, thickness: number, cache?: GeometryCache): THREE.Mesh[] {
  const out: THREE.Mesh[] = [];
  for (const d of part.deco) {
    if (!d.polys?.length) continue;
    const mesh = new THREE.Mesh(cache?.fill(d.polys) ?? fillGeometry(d.polys), ENGRAVE_FILL);
    mesh.position.z = d.side === "in" ? -0.02 : thickness + 0.02;
    out.push(mesh);
  }
  return out;
}

function engraving(part: PartJ, thickness: number): THREE.LineSegments | null {
  const segs: number[] = [];
  for (const d of part.deco) {
    if (d.layer !== 1 && !d.polys) continue;     // LINE, and FILL's outlines
    const z = d.side === "in" ? -0.03 : thickness + 0.03;   // inside: the part's other face
    for (const line of d.lines) for (let i = 1; i < line.length; i++) segs.push(line[i - 1][0], line[i - 1][1], z, line[i][0], line[i][1], z);
  }
  const z = thickness + 0.03;
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

// scratch for setPose, which runs every animation frame
const _m = new THREE.Matrix4();
const _v = new THREE.Vector3();

/** The pose of a part (or piece) into M: the lid's hinge or slide at `open`, then the explode offset. */
function poseInto(M: THREE.Matrix4, p: Placed3D, explode: number, open: number, assembled: boolean) {
  M.identity();
  const mo = p.motion;
  if (mo?.type === "hinge" && open > 0) {
    const [x, y, z] = mo.point;
    M.makeTranslation(x, y, z)
      .multiply(_m.makeRotationAxis(_v.set(...mo.axis).normalize(), THREE.MathUtils.degToRad(-mo.max * open)))
      .multiply(_m.makeTranslation(-x, -y, -z));
  } else if (mo?.type === "slide" && open > 0) {
    _v.set(...mo.dir).multiplyScalar(mo.max * open);
    M.makeTranslation(_v.x, _v.y, _v.z);
  }
  if (explode > 0 && assembled) {
    _v.set(...p.explode).multiplyScalar(explode);
    M.premultiply(_m.makeTranslation(_v.x, _v.y, _v.z));
  }
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
  // each part's (and piece's) pose, worked out once per setPose for all that move with it
  const poses = new Map<Placed3D, THREE.Matrix4>();
  const poseOf = (p: Placed3D) => {
    let M = poses.get(p);
    if (!M) poses.set(p, M = new THREE.Matrix4());
    return M;
  };
  const posed: { group: THREE.Group; pose: THREE.Matrix4; base: THREE.Matrix4 | null }[] = [];
  const add = (part: PartJ, place: Placed3D, polys: ShapePoly[] | null, withExtras: boolean) => {
    if (!polys) return;
    const { geo, edges } = opts.cache?.get(polys, thickness) ?? { geo: solid(polys, thickness), edges: slabEdges(polys, thickness) };
    const mesh = new THREE.Mesh(geo, [WOOD, CHAR]);
    const group = new THREE.Group();
    group.matrixAutoUpdate = false;
    const lines = new THREE.LineSegments(edges, EDGES);
    group.add(mesh, lines);
    if (withExtras) {
      const eng = engraving(part, thickness);
      if (eng) group.add(eng);
      for (const m of engravedFill(part, thickness, opts.cache)) group.add(m);
    }
    root.add(group);
    const base = matrix4(place.m);
    items.push({ group, mesh, edges: lines, base, place, part });
    posed.push({ group, pose: poseOf(place), base });
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
  // magnets and stamps: one group per part they belong to, posed like it, one instanced solid per material;
  // they're in world coordinates of the assembled box, so the group takes the pose without the part's base
  const owned = new Map<number, Map<THREE.Material, THREE.Matrix4[]>>();
  const q = new THREE.Quaternion(), up = new THREE.Quaternion().setFromEuler(new THREE.Euler(Math.PI / 2, 0, 0));
  const at = new THREE.Vector3(), size = new THREE.Vector3();
  for (const e of asm.extras ?? []) {
    if (!asm.parts[e.part]) continue;
    let mat: THREE.Material, m: THREE.Matrix4;
    if (e.kind === "cylinder") {
      mat = MAGNET;                                        // three's cylinders stand on Y; ours on Z
      m = new THREE.Matrix4().compose(at.set(e.at[0], e.at[1], e.at[2] + e.h / 2), up, size.set(e.r, e.h, e.r));
    } else {
      const [x0, y0, z0] = e.lo, [x1, y1, z1] = e.hi;
      mat = e.bad ? BAD : STAMP;
      m = new THREE.Matrix4().compose(at.set((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2), q,
        size.set(x1 - x0, y1 - y0, z1 - z0));
    }
    let byMat = owned.get(e.part);
    if (!byMat) owned.set(e.part, byMat = new Map());
    const list = byMat.get(mat);
    if (list) list.push(m);
    else byMat.set(mat, [m]);
  }
  for (const [part, byMat] of owned) {
    const group = new THREE.Group();
    group.matrixAutoUpdate = false;
    for (const [mat, ms] of byMat) {
      const mesh = new THREE.InstancedMesh(mat === MAGNET ? UNIT_CYLINDER : UNIT_BOX, mat, ms.length);
      ms.forEach((m, i) => mesh.setMatrixAt(i, m));
      group.add(mesh);
    }
    root.add(group);
    posed.push({ group, pose: poseOf(asm.parts[part]), base: null });
  }
  const assembled = asm.kind === "assembled";
  const scene: BoxScene = {
    root, items, asm,
    hasMotion: asm.parts.some((p) => p.motion),
    motionLabel: motionLabel(asm),
    setPose(explode, open) {
      for (const [p, M] of poses) poseInto(M, p, explode, open, assembled);
      for (const x of posed) {
        if (x.base) x.group.matrix.multiplyMatrices(x.pose, x.base);
        else x.group.matrix.copy(x.pose);
        x.group.matrixWorldNeedsUpdate = true;
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
        if (o instanceof THREE.InstancedMesh) o.dispose();     // its instance matrices
        const g = (o as THREE.Mesh).geometry;
        if (g && !SHARED.has(g) && !opts.cache?.owns(g)) g.dispose();
      });
    },
  };
  scene.setPose(0, 0);
  return scene;
}
