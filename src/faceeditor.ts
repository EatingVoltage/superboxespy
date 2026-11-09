// The face editor: text and logos on a box's outside faces (python/superboxes/faces.py, .grill/face-editor.md).
//
// The 2D half gets a tab per face of the closed box (Top, Front, Back, Left, Right, Bottom) beside Sheets. A face is
// drawn as seen from outside, up being the box's up (its back for the top). Python places every item and says whether
// it's clear of the edges; while an item is dragged it moves here, and on release it pins to the nearest of the 9
// anchor spots (corners, edge middles, centre) with its distance to it, so it keeps its place when the box changes
// size. Every edit goes to the host as the box's new items, which keeps undo and asks Python again.
//
// Add logo opens the logo library (.grill/logo-library.md): the logos folder's .svg and LightBurn .lbrn2 files, read
// again each time it opens. Drag one onto the face (it lands where it's dropped, at its true size), or click it. A
// selected text, logo or SVG has corner handles: drag one to size it, proportions kept, the opposite corner fixed.
//
// The toolbar over the face adds things (Text, Logo, SVG…, Hole ▾) and picks the side; its ? card holds the keys.
// The bar under the face shows only the selected item's settings (.grill/ui-toolbars-menus.md).

import { h } from "./params";
import { call } from "./py";
import { btn, fillToolbar, helpButton, helpCard, menuButton, seg, type MenuItem } from "./ui";
import type { Build, FaceInfo, FaceItem, LogoEntry } from "./types";

const NS = "http://www.w3.org/2000/svg";
const svg = (tag: string, attrs: Record<string, any> = {}) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
};

export type Faces = Record<string, FaceItem[]>;

export interface FaceHost {
  build(): Build | null;
  faces(): Faces;
  commit(faces: Faces): void;
  showSheets(on: boolean): void;
  boards(): Record<string, number>;
  setBoard(role: string, mm: number | null): void;
  refresh(): void;             // ask Python again, nothing changed here (a logo file may have)
}

const ORDER = ["top", "front", "back", "left", "right", "bottom"];
// Every face the closed box has: Python leaves out a face only a mirrored cut could decorate (assembly).
const READY = new Set(ORDER);
const TITLE: Record<string, string> = { top: "Top", front: "Front", back: "Back", left: "Left", right: "Right", bottom: "Bottom" };
const ANCHOR_NAME: Record<string, string> = {
  tl: "top left", t: "top", tr: "top right", l: "left", c: "centre", r: "right", bl: "bottom left", b: "bottom", br: "bottom right",
};
const SNAP = 3;          // mm: closer than this to the centre line snaps onto it
const LOGO_SIZE = 20;    // mm: a new logo's height
const FILL_MAX = 20;     // mm: a logo this high or less fills its filled shapes, a taller one is hatched (faces.FILL_MAX)
const SIZED = new Set(["text", "logo", "svg"]);   // what the corner handles size (a hole keeps its typed size)

let library: LogoEntry[] | null = null;           // the last listing of the logos folder
let reading: Promise<LogoEntry[]> | null = null;
/** The logo library, read again (the worker copies the folder anew first). */
function readLibrary(): Promise<LogoEntry[]> {
  reading ??= call<{ ok: boolean; logos?: LogoEntry[] }>("logo_library")
    .then((r) => (library = r.ok ? r.logos ?? [] : []))
    .catch(() => (library = []))
    .finally(() => (reading = null));
  return reading;
}

/** A logo's preview: its strokes and filled areas, y up, fitted into the element. */
function logoPreview(e: LogoEntry): SVGSVGElement {
  const [x0, y0, x1, y1] = e.box ?? [0, 0, 1, 1];
  const pad = 0.04 * Math.max(x1 - x0, y1 - y0);
  const s = svg("svg", { class: "lib-art", viewBox: `${x0 - pad} ${-y1 - pad} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`,
    "aria-hidden": "true" }) as SVGSVGElement;
  const g = svg("g", { transform: "scale(1 -1)" });
  if (e.fill) g.append(svg("path", { d: e.fill, class: "lib-fill", "fill-rule": "evenodd" }));
  if (e.lines) g.append(svg("path", { d: e.lines, class: "lib-line" }));
  s.append(g);
  return s;
}

/** The anchor's point on a rectangle [x0, y0, x1, y1] (python faces._spot). */
function spot(r: number[], anchor: string): [number, number] {
  const [x0, y0, x1, y1] = r;
  const col = "lr".includes(anchor.slice(-1)) ? anchor.slice(-1) : "c";
  const row = "tb".includes(anchor[0]) ? anchor[0] : "c";
  return [col === "l" ? x0 : col === "r" ? x1 : (x0 + x1) / 2, row === "b" ? y0 : row === "t" ? y1 : (y0 + y1) / 2];
}

/** The anchor an item gets where it's dropped: the third of the face its centre is in. */
export function anchorAt(face: { w: number; h: number }, bounds: number[]): string {
  const cx = (bounds[0] + bounds[2]) / 2, cy = (bounds[1] + bounds[3]) / 2;
  const col = cx < face.w / 3 ? "l" : cx > (2 * face.w) / 3 ? "r" : "c";
  const row = cy > (2 * face.h) / 3 ? "t" : cy < face.h / 3 ? "b" : "c";
  if (row === "c") return col;
  return col === "c" ? row : row + col;
}

/** The item's anchor and offset once its bounds are at `bounds`: pinned to the nearest spot, snapped onto the
 *  centre lines, on a 0.5 mm grid. */
export function pin(face: { w: number; h: number }, bounds: number[]): { anchor: string; dx: number; dy: number } {
  const anchor = anchorAt(face, bounds);
  const [fx, fy] = spot([0, 0, face.w, face.h], anchor);
  const [ix, iy] = spot(bounds, anchor);
  let dx = ix - fx, dy = iy - fy;
  const col = "lr".includes(anchor.slice(-1)) ? anchor.slice(-1) : "c";
  const row = "tb".includes(anchor[0]) ? anchor[0] : "c";
  if (col === "c" && Math.abs(dx) < SNAP) dx = 0;
  if (row === "c" && Math.abs(dy) < SNAP) dy = 0;
  const r = (v: number) => Math.round(v * 2) / 2 || 0;
  return { anchor, dx: r(dx), dy: r(dy) };
}

const ringsD = (rings: number[][][], dx = 0, dy = 0) =>
  rings.map((r) => "M" + r.map(([x, y]) => `${(x + dx).toFixed(2)} ${(y + dy).toFixed(2)}`).join("L") + "Z").join("");
const linesD = (lines: number[][][], dx = 0, dy = 0) =>
  lines.map((l) => "M" + l.map(([x, y]) => `${(x + dx).toFixed(2)} ${(y + dy).toFixed(2)}`).join("L")).join("");

/** A hole preset from the parts library (serve.py /api/parts): its confirmed panel hole or window. */
interface HolePreset {
  code: string; name: string; kind: "hole" | "window" | "edge"; shape: "round" | "rect"; d?: number; w?: number; h?: number;
  r?: number; lift?: number;
}

let presets: Promise<HolePreset[]> | null = null;
function holePresets(): Promise<HolePreset[]> {
  presets ??= fetch("/api/parts").then((r) => (r.ok ? r.json() : [])).catch(() => []);
  return presets;
}

const holeSize = (p: { shape?: string; d?: number; w?: number; h?: number; r?: number }) =>
  p.shape === "rect" ? `${p.w} × ${p.h}${p.r ? `, r ${p.r}` : ""}` : `Ø${p.d}`;

let nextId = 0;
const newId = () => `i${Date.now().toString(36)}${(nextId++).toString(36)}`;

export class FaceEditor {
  private tab = "sheets";              // a face role, or "sheets"
  private side: "out" | "in" = "out";  // the face seen from outside, or from inside the box (its other side)
  private selected: string | null = null;
  private active = false;
  private svgRoot: SVGSVGElement;
  private drag: { id: string; x0: number; y0: number; dx: number; dy: number; moved: boolean } | null = null;
  // a corner handle being dragged: the opposite corner (fx, fy) stays, the item scales by k
  private resize: { id: string; fx: number; fy: number; hx: number; hy: number; b: number[]; size: number; k: number } | null = null;
  private lib: HTMLElement;                    // the logo library's popover
  private libMode: "add" | "swap" = "add";     // add a logo, or put one in place of the selected logo
  private focusBoard = false;                  // an edge connector just went on a wall without a board height: ask

  constructor(private tabs: HTMLElement, private tools: HTMLElement, private root: HTMLElement, private bar: HTMLElement,
              private host: FaceHost) {
    this.svgRoot = svg("svg", { class: "board-svg face-svg", tabindex: 0 }) as SVGSVGElement;
    this.lib = h("div", { class: "face-lib", role: "dialog", "aria-label": "Logo library", tabindex: -1, hidden: true });
    this.lib.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        this.closeLibrary();
      }
    });
    root.append(this.svgRoot, this.lib);
    this.svgRoot.addEventListener("pointerdown", (e) => this.down(e));
    this.svgRoot.addEventListener("pointermove", (e) => this.move(e));
    this.svgRoot.addEventListener("pointerup", (e) => this.up(e));
    new ResizeObserver(() => this.draw()).observe(root);
  }

  /** Shown for every type but the stamp case (which has its own board editor). */
  setActive(on: boolean) {
    this.active = on;
    this.tabs.hidden = !on;
    if (on) {
      this.showFace(this.tab !== "sheets");
      return;
    }
    // switched off: hide what's ours and leave the 2D half to the stamp case's editor
    this.closeLibrary();
    this.root.hidden = this.bar.hidden = this.tools.hidden = true;
  }

  /** The face shown, or null on Sheets. */
  get face(): string | null {
    return this.active && this.tab !== "sheets" ? this.tab : null;
  }

  private info(): Record<string, FaceInfo> {
    return this.host.build()?.faces ?? {};
  }

  private items(role = this.faceKey): FaceItem[] {
    return this.host.faces()[role] ?? [];
  }

  update() {
    if (!this.active) return;
    const info = this.info();
    if (this.tab !== "sheets" && !(info[this.tab] && READY.has(this.tab))) this.setTab("sheets");
    if (this.selected && !this.items().some((i) => i.id === this.selected)) this.selected = null;
    this.renderTabs();
    this.renderTools();
    this.draw();
    this.renderBar();
  }

  private showFace(on: boolean) {
    this.root.hidden = this.tools.hidden = !on;
    this.bar.hidden = !on || !this.selected;
    this.host.showSheets(!on);
  }

  /** The faces' key of what's shown: "front", or "front.in" from inside. */
  private get faceKey(): string {
    return this.tab + (this.side === "in" ? ".in" : "");
  }

  private setSide(side: "out" | "in") {
    this.side = side;
    this.selected = null;
    this.closeLibrary();
    this.renderTools();
    this.draw();
    this.renderBar();
  }

  setTab(role: string) {
    this.tab = role;
    this.side = "out";
    this.selected = null;
    this.closeLibrary();
    this.renderTabs();
    this.showFace(role !== "sheets");
    this.renderTools();
    this.draw();
    this.renderBar();
  }

  private renderTabs() {
    const info = this.info();
    const faces = this.host.faces();
    this.tabs.replaceChildren();
    for (const role of ["sheets", ...ORDER.filter((r) => info[r] && READY.has(r))]) {
      const n = role === "sheets" ? 0 : (faces[role] ?? []).length + (faces[role + ".in"] ?? []).length;
      const b = h("button", { role: "tab", "aria-selected": this.tab === role,
        title: role === "sheets" ? "The parts on the sheets" : `What goes on the ${role}, outside and inside` },
        role === "sheets" ? "Sheets" : TITLE[role] + (n ? ` · ${n}` : ""));
      b.onclick = () => this.setTab(role);
      this.tabs.append(b);
    }
    this.tabs.hidden = !this.active || this.tabs.children.length < 2;   // no face to show: no tabs either
  }

  // ---------------------------------------------------------------- drawing
  private draw() {
    const f = this.info()[this.faceKey];
    if (!f || this.root.hidden) return;
    const pad = Math.max(10, 0.08 * Math.max(f.w, f.h));
    this.svgRoot.setAttribute("viewBox", `${-pad} ${-(f.h + pad)} ${f.w + 2 * pad} ${f.h + 2 * pad}`);
    const g = svg("g", { transform: "scale(1 -1)" });
    g.append(svg("path", { d: ringsD(f.outline), class: "board-wood", "fill-rule": "evenodd" }));
    if (f.covered.length) g.append(svg("path", { d: ringsD(f.covered), class: "face-covered", "fill-rule": "nonzero" }));
    g.append(svg("path", { d: ringsD(f.free), class: "face-free" }));
    if (f.fixed.length) g.append(svg("path", { d: linesD(f.fixed), class: "board-line face-fixed" }));
    if (f.board != null) g.append(svg("line", { x1: 0, y1: f.board, x2: f.w, y2: f.board, class: "face-board" }));
    const items = new Map(this.items().map((i) => [i.id, i]));
    const d = this.drag;
    for (const it of f.items) {
      if (!items.has(it.id)) continue;
      if (!it.bounds) {
        if (!it.error) continue;
        const [ax, ay] = spot([0, 0, f.w, f.h], items.get(it.id)!.anchor);
        g.append(svg("rect", { x: ax - 10, y: ay - 6, width: 20, height: 12, "data-id": it.id,
          class: `hit face-item bad${this.selected === it.id ? " sel" : ""}` }));
        continue;
      }
      const [ox, oy] = d && d.id === it.id ? [d.dx, d.dy] : [0, 0];
      const r = this.resize?.id === it.id ? this.resize : null;
      // while a corner is dragged, the item scales about the opposite corner
      const art = r ? svg("g", { transform: `translate(${r.fx} ${r.fy}) scale(${r.k}) translate(${-r.fx} ${-r.fy})` }) : g;
      if (it.fill?.length) art.append(svg("path", { d: ringsD(it.fill, ox, oy), class: "face-fill", "fill-rule": "evenodd" }));
      art.append(svg("path", { d: linesD(it.lines, ox, oy), class: it.hole ? "board-cut" : "board-line" }));
      if (r) g.append(art);
      const [x0, y0, x1, y1] = r ? this.scaled(r) : [it.bounds[0] + ox, it.bounds[1] + oy, it.bounds[2] + ox, it.bounds[3] + oy];
      const bad = (d && d.id === it.id && d.moved) || r ? !this.clear(f, [x0, y0, x1, y1]) : it.bad;
      g.append(svg("rect", { x: x0 - 1, y: y0 - 1, width: x1 - x0 + 2, height: y1 - y0 + 2, "data-id": it.id,
        class: `hit face-item${this.selected === it.id ? " sel" : ""}${bad ? " bad" : ""}` }));
      if (this.selected === it.id && !d?.moved && SIZED.has(items.get(it.id)!.kind)) this.handles(g, f, it.id, [x0, y0, x1, y1]);
    }
    if (this.resize) this.sizeLabel(g, f);
    // while dragging: where it will pin
    if (d?.moved) {
      const it = f.items.find((i) => i.id === d.id);
      if (it?.bounds) {
        const b = [it.bounds[0] + d.dx, it.bounds[1] + d.dy, it.bounds[2] + d.dx, it.bounds[3] + d.dy];
        const p = pin(f, b);
        const [fx, fy] = spot([0, 0, f.w, f.h], p.anchor);
        const [ix, iy] = spot(b, p.anchor);
        g.append(svg("line", { x1: fx, y1: fy, x2: ix, y2: iy, class: "face-pin" }));
        g.append(svg("circle", { cx: fx, cy: fy, r: 1.6, class: "face-spot" }));
      }
    }
    this.svgRoot.replaceChildren(g);
  }

  /** The four corner handles of the selected item, a fixed size on screen. */
  private handles(g: SVGElement, f: FaceInfo, id: string, b: number[]) {
    const s = this.mmPerPx(f) * 9;
    for (const [name, x, y] of [["bl", b[0], b[1]], ["br", b[2], b[1]], ["tl", b[0], b[3]], ["tr", b[2], b[3]]] as const) {
      g.append(svg("rect", { x: x - s / 2, y: y - s / 2, width: s, height: s, "data-id": id, "data-handle": name,
        class: `face-handle ${name === "bl" || name === "tr" ? "nesw" : "nwse"}` }));
    }
  }

  /** The item's height while a corner is dragged, beside that corner (upright: the drawing is flipped). */
  private sizeLabel(g: SVGElement, f: FaceInfo) {
    const r = this.resize!;
    const it = this.items().find((i) => i.id === r.id);
    if (!it) return;
    const mm = r.size * r.k;
    const what = it.kind === "text" ? "cap " : "";
    const entry = it.kind === "logo" ? library?.find((l) => l.logo === it.logo) : undefined;
    const fills = entry?.fills && it.style !== "outline" ? (mm <= FILL_MAX ? " · filled" : " · hatched") : "";
    const px = this.mmPerPx(f);
    const [hx, hy] = [r.fx + (r.hx - r.fx) * r.k, r.fy + (r.hy - r.fy) * r.k];
    const t = svg("text", { x: hx + 8 * px * Math.sign(hx - r.fx || 1), y: -(hy + 8 * px * Math.sign(hy - r.fy || 1)),
      transform: "scale(1 -1)", class: "face-size", "font-size": 13 * px,
      "text-anchor": hx >= r.fx ? "start" : "end" });
    t.textContent = `${what}${+mm.toFixed(1)} mm${fills}`;
    g.append(t);
  }

  /** mm of the face per screen pixel. */
  private mmPerPx(f: FaceInfo): number {
    const m = this.svgRoot.getScreenCTM();
    return m && m.a ? 1 / m.a : Math.max(f.w, f.h) / 600;
  }

  /** The bounds of an item being sized, scaled about the fixed corner. */
  private scaled(r: NonNullable<FaceEditor["resize"]>): number[] {
    const xs = [r.fx + (r.b[0] - r.fx) * r.k, r.fx + (r.b[2] - r.fx) * r.k];
    const ys = [r.fy + (r.b[1] - r.fy) * r.k, r.fy + (r.b[3] - r.fy) * r.k];
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }

  /** Bounds inside the free area (approximately: its four corners; Python has the last word). */
  private clear(f: FaceInfo, b: number[]): boolean {
    const inside = (x: number, y: number) => {
      let n = 0;
      for (const r of f.free) {
        for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
          const [xi, yi] = r[i], [xj, yj] = r[j];
          if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) n++;
        }
      }
      return n % 2 === 1;
    };
    return inside(b[0], b[1]) && inside(b[2], b[1]) && inside(b[2], b[3]) && inside(b[0], b[3]);
  }

  private toFace(e: PointerEvent): [number, number] {
    const m = this.svgRoot.getScreenCTM()!.inverse();
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m);
    return [p.x, -p.y];
  }

  private down(e: PointerEvent) {
    if (e.button !== 0) return;
    this.closeLibrary();
    this.svgRoot.focus({ preventScroll: true });
    const target = e.target as Element;
    const id = target.getAttribute?.("data-id");
    const handle = target.getAttribute?.("data-handle");
    this.selected = id;
    this.renderBar();
    if (!id) {
      this.draw();
      return;
    }
    const it = this.info()[this.faceKey]?.items.find((i) => i.id === id);
    const item = this.items().find((i) => i.id === id);
    if (handle && it?.bounds && item) {
      const [x0, y0, x1, y1] = it.bounds;
      const [hx, hy] = [handle.endsWith("l") ? x0 : x1, handle.startsWith("b") ? y0 : y1];
      this.resize = { id, fx: x0 + x1 - hx, fy: y0 + y1 - hy, hx, hy, b: it.bounds, size: item.size, k: 1 };
    } else {
      const [x, y] = this.toFace(e);
      this.drag = { id, x0: x, y0: y, dx: 0, dy: 0, moved: false };
    }
    try {
      this.svgRoot.setPointerCapture(e.pointerId);
    } catch {
      /* a pointer the browser doesn't track (a synthetic event): the drag still works inside the face */
    }
    this.draw();
  }

  private move(e: PointerEvent) {
    const r = this.resize;
    if (r) {
      const [x, y] = this.toFace(e);
      const w0 = Math.max(r.b[2] - r.b[0], 1e-6), h0 = Math.max(r.b[3] - r.b[1], 1e-6);
      const k = Math.max(Math.abs(x - r.fx) / w0, Math.abs(y - r.fy) / h0);
      const size = Math.max(1, Math.round(r.size * k * 2) / 2);        // 0.5 mm steps
      if (size / r.size !== r.k) {
        r.k = size / r.size;
        this.draw();
      }
      return;
    }
    const d = this.drag;
    if (!d) return;
    const [x, y] = this.toFace(e);
    d.dx = x - d.x0;
    const it = this.items().find((i) => i.id === d.id);
    d.dy = it?.board ? 0 : y - d.y0;                 // an edge connector stays at its board
    if (!d.moved && Math.hypot(d.dx, d.dy) < 0.8) return;
    d.moved = true;
    this.draw();
  }

  private up(e: PointerEvent) {
    const d = this.drag, r = this.resize;
    this.drag = this.resize = null;
    if (this.svgRoot.hasPointerCapture(e.pointerId)) this.svgRoot.releasePointerCapture(e.pointerId);
    if (r) {
      const f = this.info()[this.faceKey];
      if (f && r.k !== 1) this.change(r.id, { size: Math.round(r.size * r.k * 2) / 2, ...pin(f, this.scaled(r)) });
      else this.draw();
      return;
    }
    if (!d?.moved) {
      this.draw();
      return;
    }
    this.moveBy(d.id, d.dx, d.dy);
  }

  /** Move an item by (dx, dy) mm and pin it where it lands. */
  private moveBy(id: string, dx: number, dy: number) {
    const f = this.info()[this.faceKey];
    const it = f?.items.find((i) => i.id === id);
    if (!f || !it?.bounds) return;
    const b = [it.bounds[0] + dx, it.bounds[1] + dy, it.bounds[2] + dx, it.bounds[3] + dy];
    this.change(id, pin(f, b));
  }

  // ---------------------------------------------------------------- edits
  private change(id: string, patch: Partial<FaceItem>) {
    const faces = structuredClone(this.host.faces());
    const list = faces[this.faceKey] ?? [];
    const it = list.find((i) => i.id === id);
    if (!it) return;
    Object.assign(it, patch);
    faces[this.faceKey] = list;
    this.host.commit(faces);
  }

  /** Import SVG: a file picked here, its text kept in the box. Its own size if it says it in mm (height="40mm"). */
  importSvg() {
    const input = h("input", { type: "file", accept: ".svg,image/svg+xml" }) as HTMLInputElement;
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      const text = await file.text();
      const m = (new DOMParser().parseFromString(text, "image/svg+xml").documentElement.getAttribute("height") ?? "")
        .match(/^\s*([\d.]+)\s*(mm|cm|in)\s*$/);
      const mm = m ? Number(m[1]) * { mm: 1, cm: 10, in: 25.4 }[m[2] as "mm"] : 0;
      const f = this.info()[this.faceKey];
      const size = mm > 0 && f ? Math.min(mm, f.h * 0.8) : 30;
      const item: FaceItem = { id: newId(), kind: "svg", svg: text, name: file.name, size: Math.round(size * 2) / 2,
        style: "outline", rot: 0, anchor: "c", dx: 0, dy: 0 };
      const faces = structuredClone(this.host.faces());
      faces[this.faceKey] = [...(faces[this.faceKey] ?? []), item];
      this.selected = item.id;
      this.host.commit(faces);
    };
    input.click();
  }

  /** A hole at the face's centre: `p` a library preset, or a plain round / rectangle. */
  addHole(p: Omit<Partial<HolePreset>, "shape"> & { shape: "round" | "rect" | "notch" }) {
    if (p.shape === "notch") {                       // a thumb notch: on the top edge to start with
      this.addItem({ id: newId(), kind: "hole", shape: "notch", d: 30, rot: 0, anchor: "t", dx: 0, dy: 0, size: 0 });
      return;
    }
    const item: FaceItem = { id: newId(), kind: "hole", shape: p.shape, rot: 0, anchor: "c", dx: 0, dy: 0, size: 0,
      ...(p.shape === "rect" ? { w: p.w ?? 20, h: p.h ?? 10, r: p.r ?? 1 } : { d: p.d ?? 6 }),
      ...(p.name ? { part: p.name } : {}),
      ...(p.kind === "edge" ? { board: true, lift: p.lift ?? -0.5 } : {}) };
    // the first connector on a wall asks for the board's height: its bar opens with the field in focus
    if (p.kind === "edge" && this.host.boards()[this.tab] == null) this.focusBoard = true;
    this.addItem(item);
  }

  private addItem(item: FaceItem) {
    const faces = structuredClone(this.host.faces());
    faces[this.faceKey] = [...(faces[this.faceKey] ?? []), item];
    this.selected = item.id;
    this.host.commit(faces);
  }

  /** Hole ▾: the plain shapes, the parts library's panel holes, and on a wall the edge connectors. A hole lands in
   *  the face's centre (a notch on the top edge); drag it from there. */
  private async holeItems(): Promise<MenuItem[]> {
    const ps = await holePresets();
    const wall = this.info()[this.faceKey]?.floor != null;
    const panel = ps.filter((p) => p.kind !== "edge"), edge = ps.filter((p) => p.kind === "edge");
    const items: MenuItem[] = [
      { label: "Round", detail: "any size", run: () => this.addHole({ shape: "round" }) },
      { label: "Rectangle", detail: "any size", run: () => this.addHole({ shape: "rect" }) },
      { label: "Thumb notch", detail: "on an edge", title: "A half-round notch in a plain edge, to lift a lid",
        run: () => this.addHole({ shape: "notch" }) },
      { heading: "Parts library" },
      ...(panel.length
        ? panel.map((p): MenuItem => ({ label: p.name + (p.kind === "window" ? " (window)" : ""), detail: holeSize(p),
          title: `${p.code}: its confirmed front-plate ${p.kind}`, run: () => this.addHole(p) }))
        : [{ note: "None: start the app with serve.py (start.bat)" }]),
    ];
    if (wall && edge.length) {
      items.push({ heading: "Edge connectors, at the board" },
        ...edge.map((p): MenuItem => ({ label: p.name, detail: holeSize(p), title: "Its opening at the board's edge: it stays at the board",
          run: () => this.addHole(p) })));
    }
    return items;
  }

  add(kind: "text") {
    const f = this.info()[this.faceKey];
    if (!f) return;
    this.addItem({ id: newId(), kind, text: "TEXT", size: 10, bold: false, style: "outline", rot: 0, anchor: "c", dx: 0, dy: 0 });
  }

  // ---------------------------------------------------------------- the logo library
  /** Open the library over the face: to add a logo, or to put one in place of the selected logo. */
  openLibrary(mode: "add" | "swap") {
    this.libMode = mode;
    this.lib.hidden = false;
    this.renderLibrary();
    this.lib.focus({ preventScroll: true });
    readLibrary().then(() => {
      if (!this.lib.hidden) this.renderLibrary();
      this.renderBar();
      // a box links its logos by name: the folder was just copied again, so they're drawn from the files as they are
      if (Object.values(this.host.faces()).some((list) => list.some((i) => i.kind === "logo"))) this.host.refresh();
    });
  }

  private closeLibrary() {
    if (this.lib.hidden) return;
    this.lib.hidden = true;
    if (this.root.contains(document.activeElement)) this.svgRoot.focus({ preventScroll: true });
  }

  private renderLibrary() {
    const swap = this.libMode === "swap";
    const close = h("button", { class: "face-lib-close", title: "Close (Esc)", "aria-label": "Close" }, "×");
    close.onclick = () => this.closeLibrary();
    const head = h("div", { class: "face-lib-head" }, h("b", {}, swap ? "Change the logo" : "Logos"),
      h("span", { class: "hint" }, swap ? "Click one to put it in place of the selected logo."
        : "Drag one onto the face, or click it to put it at the top left."), close);
    const grid = h("div", { class: "face-lib-grid" });
    if (library === null) grid.append(h("p", { class: "hint" }, "Reading the logos folder…"));
    else if (!library.length) grid.append(h("p", { class: "hint" }, "No logos: start the app with serve.py (start.bat), " +
      "and put .svg or .lbrn2 files into the logos folder."));
    for (const e of library ?? []) {
      const size = e.w && e.h ? `${+e.w.toFixed(1)} × ${+e.h.toFixed(1)} mm as drawn` : "";
      const tile = h("button", { class: "face-lib-tile", disabled: !!e.error,
        title: e.error ? `${e.logo}: ${e.error}` : `${e.logo}\n${size}${e.fills ? "\nfilled shapes: filled up to " +
          FILL_MAX + " mm high, hatched above" : ""}` },
        e.error ? h("span", { class: "bad-text" }, "can't be read") : logoPreview(e), h("span", { class: "face-lib-name" }, e.label));
      tile.addEventListener("pointerdown", (ev) => this.libDown(ev, e));
      tile.onclick = (ev) => {
        if (ev.detail === 0) this.pick(e);          // Enter or Space; a pointer's click is handled by libDown
      };
      grid.append(tile);
    }
    const foot = h("p", { class: "hint face-lib-foot" }, "The logos folder (C:\\Projects\\eating voltage Fonts\\logos): " +
      "an .svg, or a LightBurn .lbrn2 (its first page as drawn: Scan layers filled, Cut and Line layers as outlines; " +
      "text needs no font). One file is one logo. A box links its logo by name: change the file and the box follows.");
    this.lib.replaceChildren(head, grid, foot);
  }

  /** Pointer down on a library tile: a click picks it; a drag carries it, at its true size, onto the face. */
  private libDown(ev: PointerEvent, e: LogoEntry) {
    if (ev.button !== 0 || e.error) return;
    ev.preventDefault();
    const [sx, sy] = [ev.clientX, ev.clientY];
    let ghost: HTMLElement | null = null;
    const move = (m: PointerEvent) => {
      if (!ghost) {
        if (this.libMode === "swap" || Math.hypot(m.clientX - sx, m.clientY - sy) < 5) return;
        ghost = this.ghost(e);
        document.body.append(ghost);
        this.lib.hidden = true;                     // the whole face is the drop target
      }
      ghost.style.left = `${m.clientX}px`;
      ghost.style.top = `${m.clientY}px`;
      ghost.classList.toggle("off", !this.overFace(m));
    };
    const end = (u: PointerEvent, drop: boolean) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);
      if (!ghost) {
        if (drop) this.pick(e);
        return;
      }
      ghost.remove();
      if (drop && this.overFace(u)) this.dropAt(e, this.toFace(u));
      this.closeLibrary();
    };
    const up = (u: PointerEvent) => end(u, true);
    const cancel = (u: PointerEvent) => end(u, false);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
  }

  /** What follows the pointer while a logo is dragged in: the logo as big as it will land on the face. */
  private ghost(e: LogoEntry): HTMLElement {
    const f = this.info()[this.faceKey];
    const px = f ? 1 / this.mmPerPx(f) : 3;
    const hgt = LOGO_SIZE * px, wid = e.w && e.h ? (hgt * e.w) / e.h : hgt * 2.5;
    const el = h("div", { class: "face-lib-ghost" });
    el.style.width = `${wid}px`;
    el.style.height = `${hgt}px`;
    el.append(logoPreview(e));
    return el;
  }

  private overFace(e: PointerEvent): boolean {
    const r = this.svgRoot.getBoundingClientRect();
    return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
  }

  /** A logo dropped on the face: its centre where it was dropped, pinned to the nearest spot. */
  private dropAt(e: LogoEntry, [x, y]: [number, number]) {
    const f = this.info()[this.faceKey];
    if (!f) return;
    const w = e.w && e.h ? (LOGO_SIZE * e.w) / e.h : LOGO_SIZE * 2.5;
    this.addItem({ id: newId(), kind: "logo", logo: e.logo, size: LOGO_SIZE, rot: 0,
      ...pin(f, [x - w / 2, y - LOGO_SIZE / 2, x + w / 2, y + LOGO_SIZE / 2]) });
  }

  /** A tile clicked: the selected logo becomes this one, or this one goes in at the top left. */
  private pick(e: LogoEntry) {
    const it = this.items().find((i) => i.id === this.selected);
    this.closeLibrary();
    if (this.libMode === "swap" && it?.kind === "logo") this.change(it.id, { logo: e.logo });
    else this.addItem({ id: newId(), kind: "logo", logo: e.logo, size: LOGO_SIZE, rot: 0, anchor: "tl", dx: 15, dy: -15 });
  }

  private remove() {
    if (!this.selected) return;
    const faces = structuredClone(this.host.faces());
    faces[this.faceKey] = (faces[this.faceKey] ?? []).filter((i) => i.id !== this.selected);
    if (!faces[this.faceKey].length) delete faces[this.faceKey];
    this.selected = null;
    this.host.commit(faces);
  }

  private duplicate() {
    const it = this.items().find((i) => i.id === this.selected);
    if (!it) return;
    // text below the original, a hole beside it (a row of pots)
    const copy = it.kind === "hole"
      ? { ...structuredClone(it), id: newId(), dx: it.dx + (it.shape === "rect" ? it.w ?? 10 : it.d ?? 6) + 4 }
      : { ...structuredClone(it), id: newId(), dy: it.dy - Math.max(4, it.size * 1.5) };
    const faces = structuredClone(this.host.faces());
    faces[this.faceKey] = [...(faces[this.faceKey] ?? []), copy];
    this.selected = copy.id;
    this.host.commit(faces);
  }

  /** Keys while the face is shown: arrows nudge (Shift 10 mm), R rotates, Ctrl+D duplicates, Del deletes. */
  key(e: KeyboardEvent): boolean {
    if (!this.face || !this.selected) return false;
    const it = this.items().find((i) => i.id === this.selected);
    if (!it) return false;
    const step = e.shiftKey ? 10 : 1;
    const k = e.key;
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "d") this.duplicate();
    else if (e.ctrlKey || e.metaKey || e.altKey) return false;
    else if (k === "Delete" || k === "Backspace") this.remove();
    else if (k === "r" || k === "R") this.change(it.id, { rot: (((it.rot ?? 0) + (e.shiftKey ? 270 : 90)) % 360) as FaceItem["rot"] });
    else if (k === "Escape") {
      this.selected = null;
      this.draw();
      this.renderBar();
    } else if (k.startsWith("Arrow")) {
      const [dx, dy] = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }[k as "ArrowUp"];
      this.moveBy(it.id, dx, dy);
    } else return false;
    return true;
  }

  // ---------------------------------------------------------------- the toolbar over the face
  private renderTools() {
    if (!this.active || this.tab === "sheets") return;
    const add: (Node | string)[] = [h("span", { class: "tb-label" }, "Add"),
      btn("Text", "Text in eV Sans, engraved", () => this.add("text")),
      btn("Logo", "The logo library: drag a logo onto the face, or click it", () => this.openLibrary("add")),
      btn("SVG…", "Line art from an SVG file, engraved: its paths and shapes (convert text to paths first). " +
        "The file is kept in the box.", () => this.importSvg())];
    if (this.side === "out") {
      add.push(menuButton("Hole", "A hole through the wood (CUT), at its finished size: the kerf is taken care of",
        () => this.holeItems()));
    }
    const sides = seg<"out" | "in">("Seen from", [["out", "Outside", "The face as seen from outside the box"],
      ["in", "Inside", "Its other side, as seen from inside the box: engraved on a page of its own before the sheet's, " +
        "the sheet turned over left to right"]], this.side, (v) => this.setSide(v));
    fillToolbar(this.tools, add, [sides, h("span", { class: "tb-gap" }), helpButton((b) => this.openHelp(b))]);
  }

  /** The ? card: the keys, then what the face's lines and colours mean. */
  private openHelp(anchor: HTMLElement) {
    const f = this.info()[this.faceKey];
    const inside = this.side === "in";
    const notes = ["The dashed line keeps the wood's thickness + 1.5 mm off the edges and the finger joints. An item " +
      "across it turns red and blocks the export."];
    if (f?.covered.length) notes.push(inside ? "Grey: where other parts meet this face inside the box."
      : "Grey: covered on the closed box (a lid's rim).");
    if (inside) notes.push("Inside: engraved on the part's other side. The export adds a page before the sheet's, for the " +
      "sheet turned over left to right. Holes go through anyway: add them outside.");
    if (f?.board != null) notes.push("Green dashes: the board's top. Edge connectors (Hole ▾) sit at it and only move " +
      "sideways; its height is in a connector's bar.");
    if (f?.fixed.length) notes.push("The maker's mark moves out of the items' way.");
    helpCard(anchor, `${TITLE[this.tab]}, seen from ${inside ? "inside" : "outside"}` +
      (f ? ` · ${f.w.toFixed(0)} × ${f.h.toFixed(0)} mm` : ""), [
      ["Drag", "move an item. It pins to the nearest corner, edge middle or the centre, and keeps that place when the box changes size"],
      ["Corner", "drag a selected item's corner to size it: proportions kept, 0.5 mm steps"],
      ["R / Shift+R", "rotate a quarter turn, either way"],
      ["Arrows", "nudge 1 mm (Shift: 10 mm)"],
      ["Ctrl+D", "duplicate"],
      ["Del", "delete"],
      ["Esc", "deselect"],
      ["Ctrl+Z / Ctrl+Y", "undo / redo"],
    ], notes);
  }

  // ---------------------------------------------------------------- the bar under the face: the selected item
  private renderBar() {
    const f = this.info()[this.faceKey];
    const it = this.items().find((i) => i.id === this.selected);
    this.bar.hidden = this.root.hidden || !f || !it;
    if (!f || !it) {
      this.bar.replaceChildren();
      return;
    }
    const kids: (Node | string)[] = [];
    const num = (value: number, label: string, set: (v: number) => void, step = 0.5, min = 1) => {
      const i = h("input", { type: "number", min, step, value: value, class: "num", "aria-label": label }) as HTMLInputElement;
      i.onchange = () => {
        const v = Number(i.value);
        if (v >= min) set(v);
      };
      return i;
    };
    const mm2 = (v: number) => +Math.abs(v).toFixed(2);
    const where = `${ANCHOR_NAME[it.anchor]}${it.dx || it.dy ? `, ${mm2(it.dx)} / ${mm2(it.dy)} mm` : ""}`;
    const got = f.items.find((i) => i.id === it.id);
    const state = got?.error ? h("span", { class: "bad-text" }, it.kind === "hole" ? got.error : `can't be read: ${got.error}`)
      : got?.bad ? h("span", { class: "bad-text" }, "runs into an edge, a finger joint or what covers it") : "";
    const styleSel = () => {
      const style = h("select", { "aria-label": "Engraving" }) as HTMLSelectElement;
      for (const [v, label] of [["outline", "Outline"], ["hatch", "Hatched"]]) {
        style.append(h("option", { value: v, selected: (it.style ?? "outline") === v }, label));
      }
      style.onchange = () => this.change(it.id, { style: style.value as FaceItem["style"] });
      return style;
    };
    if (it.kind === "text") {
      const text = h("textarea", { rows: 1, class: "face-text", spellcheck: "false", "aria-label": "Text" }) as HTMLTextAreaElement;
      text.value = it.text ?? "";
      text.rows = Math.min(4, Math.max(1, text.value.split("\n").length));
      text.onchange = () => this.change(it.id, { text: text.value });
      const bold = h("input", { type: "checkbox", checked: !!it.bold }) as HTMLInputElement;
      bold.onchange = () => this.change(it.id, { bold: bold.checked });
      kids.push(text, h("span", {}, "cap"), num(it.size, "Cap height, mm", (v) => this.change(it.id, { size: v })),
        h("span", { class: "unit" }, "mm"), h("label", { class: "check" }, bold, "Bold"), styleSel());
    } else if (it.kind === "hole") {
      kids.push(h("b", { title: it.shape === "notch" ? "A half-round notch in the edge, to lift a lid: drag it to the " +
        "top or bottom edge. Under a lid's rim (grey) make it deeper than the rim, so a finger reaches the rim's edge"
        : "Cut through, at its finished size" },
        it.part ?? (it.shape === "notch" ? "Thumb notch" : it.shape === "rect" ? "Rectangle hole" : "Round hole")));
      if (it.shape === "rect") {
        kids.push(num(it.w ?? 20, "Width, mm", (v) => this.change(it.id, { w: v }), 0.01, 0.5), h("span", {}, "×"),
          num(it.h ?? 10, "Height, mm", (v) => this.change(it.id, { h: v }), 0.01, 0.5), h("span", { class: "unit" }, "mm, r"),
          num(it.r ?? 0, "Corner radius, mm", (v) => this.change(it.id, { r: v }), 0.05, 0));
      } else {
        kids.push(h("span", {}, "Ø"), num(it.d ?? 6, "Diameter, mm", (v) => this.change(it.id, { d: v }), 0.01, 0.5));
      }
      kids.push(h("span", { class: "unit" }, "mm"));
      if (it.board) {                                 // an edge connector: the wall's board height lives here
        const role = this.tab;
        const v = this.host.boards()[role];
        const board = h("input", { type: "number", min: 0, step: 0.1, value: v ?? "", class: "num", placeholder: "—",
          "aria-label": "The board's top above the inside floor, mm" }) as HTMLInputElement;
        board.onchange = () => this.host.setBoard(role, board.value === "" ? null : Math.max(0, Number(board.value)));
        kids.push(h("label", { class: `check${v == null ? " bad-text" : ""}`, title: "The board's top surface above the " +
          "box's inside floor (standoff + board), the same for every connector on this wall" },
          "board at", board, "mm above the floor"));
        if (this.focusBoard) {
          this.focusBoard = false;
          requestAnimationFrame(() => {
            board.focus();
            board.select();
          });
        }
      }
    } else if (it.kind === "svg") {
      kids.push(h("b", { title: "An imported SVG, kept in the box" }, it.name ?? "SVG"), h("span", {}, "height"),
        num(it.size, "Height, mm", (v) => this.change(it.id, { size: v })), h("span", { class: "unit" }, "mm"),
        styleSel());
    } else {
      if (library === null) readLibrary().then(() => this.renderBar());     // to know whether it has filled shapes
      const entry = library?.find((l) => l.logo === it.logo);
      kids.push(h("b", { title: `${it.logo} in the logos folder, linked by name: change the file and this box follows` },
        (it.logo ?? "").replace(/\.(svg|lbrn2)$/i, "") || "Logo"),
        btn("Change…", "Put another logo from the library in its place", () => this.openLibrary("swap")),
        h("span", {}, "height"), num(it.size, "Logo height, mm", (v) => this.change(it.id, { size: v })),
        h("span", { class: "unit" }, "mm"));
      if (entry?.fills) {
        const style = h("select", { "aria-label": "Engraving", title: "As drawn: the file's Scan layers filled (FILL up to " +
          `${FILL_MAX} mm high, hatched on LINE above), its Cut and Line layers as outlines` }) as HTMLSelectElement;
        style.append(h("option", { value: "", selected: it.style !== "outline" }, "As drawn"),
          h("option", { value: "outline", selected: it.style === "outline" }, "Outline only"));
        style.onchange = () => this.change(it.id, { style: (style.value || undefined) as FaceItem["style"] });
        kids.push(style);
        if (it.style !== "outline") {
          kids.push(h("span", { class: "hint" }, it.size <= FILL_MAX ? `filled (FILL, ${FILL_MAX} mm high or less)`
            : `hatched (above ${FILL_MAX} mm)`));
        }
      }
    }
    if (!(it.kind === "hole" && (it.shape !== "rect" || it.board))) {   // round looks the same turned; at the board it stays
      kids.push(btn("Rotate", "R (Shift+R the other way)", () => this.change(it.id, { rot: (((it.rot ?? 0) + 90) % 360) as FaceItem["rot"] })));
    }
    kids.push(btn("Duplicate", "Ctrl+D", () => this.duplicate()), btn("Delete", "Del", () => this.remove()),
      h("span", { class: "hint" }, where), state);
    this.bar.replaceChildren(...kids);
  }
}
