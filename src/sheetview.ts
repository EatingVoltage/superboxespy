// 2D sheets: what LightBurn will get, drawn in the layer colours on a plywood-coloured A3. Parts can be dragged
// (also onto another sheet), rotated with R, nudged with the arrow keys. Anything that breaks the sheet rules
// (3 mm edge, 1.5 mm gap, 390 mm reach line) turns red and blocks the export. The part under the pointer is marked
// in the 3D; a double-click opens its page (a face of the box, a stamp case board).

import type { Build, PartJ, Placement, Sheet, Subpath } from "./types";
import { DRAG_PX } from "./ui";

const EDGE = 3;
const GAP = 1.5;
const NS = "http://www.w3.org/2000/svg";

const svgEl = (tag: string, attrs: Record<string, any> = {}) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
};

export function pathD(subs: Subpath[]): string {
  const out: string[] = [];
  for (const s of subs) {
    out.push(`M${s.start[0]} ${s.start[1]}`);
    for (const g of s.segs) out.push(g.length === 2 ? `L${g[0]} ${g[1]}` : `C${g.join(" ")}`);
    if (s.closed) out.push("Z");
  }
  return out.join("");
}

export const rotSize = (p: PartJ, rot: number): [number, number] => (rot % 180 ? [p.h, p.w] : [p.w, p.h]);

function partTransform(p: PartJ, pl: Placement): string {
  const r = ((pl.rot % 360) + 360) % 360;
  const [dx, dy] = ({ 0: [0, 0], 90: [p.h, 0], 180: [p.w, p.h], 270: [0, p.w] } as Record<number, number[]>)[r];
  return `translate(${pl.x + dx} ${pl.y + dy}) rotate(${r})`;
}

export function area(sheet: Sheet): [number, number, number, number] {
  return [EDGE, EDGE, sheet.w - EDGE, Math.min(sheet.usable, sheet.h - EDGE)];
}

/** Indices of parts whose placement breaks a rule (outside the area or closer than the gap to another). */
export function problems(parts: PartJ[], placements: Placement[], sheet: Sheet): Set<number> {
  const bad = new Set<number>();
  const [x0, y0, x1, y1] = area(sheet);
  const boxes = placements.map((pl) => {
    const [w, h] = rotSize(parts[pl.part], pl.rot);
    return { pl, x0: pl.x, y0: pl.y, x1: pl.x + w, y1: pl.y + h };
  });
  const t = 1e-3;
  for (const b of boxes) {
    if (b.x0 < x0 - t || b.y0 < y0 - t || b.x1 > x1 + t || b.y1 > y1 + t) bad.add(b.pl.part);
  }
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      if (a.pl.sheet !== b.pl.sheet) continue;
      if (a.x0 < b.x1 + GAP - t && b.x0 < a.x1 + GAP - t && a.y0 < b.y1 + GAP - t && b.y0 < a.y1 + GAP - t) {
        bad.add(a.pl.part);
        bad.add(b.pl.part);
      }
    }
  }
  return bad;
}

export function offcut(parts: PartJ[], placements: Placement[], sheet: Sheet, n: number): number {
  let top = 0;
  for (const pl of placements) if (pl.sheet === n) top = Math.max(top, pl.y + rotSize(parts[pl.part], pl.rot)[1]);
  return Math.max(0, sheet.h - top - GAP);
}

// The rest pieces: python/superboxes/sheets.py rest_pieces, which the export cuts. This copy draws them while
// parts are dragged, from the parts' boxes (the export takes the cut outlines: a fraction of a mm apart).
const FRAME_MIN_PIECE = 10;
const FRAME_STEP = 0.5;

export interface RestPiece { name: string; x0: number; y0: number; x1: number; y1: number }

export function restPieces(parts: PartJ[], placements: Placement[], sheet: Sheet, n: number): RestPiece[] {
  const boxes = placements.filter((pl) => pl.sheet === n).map((pl) => {
    const [w, h] = rotSize(parts[pl.part], pl.rot);
    return { x0: pl.x, y0: pl.y, x1: pl.x + w, y1: pl.y + h, name: parts[pl.part].name };
  });
  if (!boxes.length) return [];
  const usable = Math.min(sheet.usable, sheet.h);
  const top = Math.max(...boxes.map((b) => b.y1));
  const out: RestPiece[] = [];
  if (top <= usable - 0.5) out.push({ name: "top rest piece", x0: 0, y0: top, x1: sheet.w, y1: sheet.h });
  const tops: number[] = [];
  for (const t of boxes.map((b) => b.y1).sort((a, b) => a - b)) {
    if (tops.length && t - tops[tops.length - 1] < 1e-3) tops[tops.length - 1] = t;
    else tops.push(t);
  }
  type Band = { y0: number; y1: number; r: number; i: number };
  const bands: Band[] = [];
  let y0 = 0;
  for (const t of tops) {
    let best = -1;
    boxes.forEach((b, i) => {
      if (b.y0 < t - 1e-3 && b.y1 > y0 + 1e-3 &&
          (best < 0 || b.x1 > boxes[best].x1 || (b.x1 === boxes[best].x1 && b.y1 > boxes[best].y1))) best = i;
    });
    if (best < 0) continue;
    bands.push({ y0, y1: t, r: boxes[best].x1, i: best });
    y0 = t;
  }
  const join = (k: number) => {
    const a = bands[k], b = bands[k + 1];
    const r = b.r >= a.r - 1e-9 ? b : a;
    bands.splice(k, 2, { y0: a.y0, y1: b.y1, r: r.r, i: r.i });
  };
  const waste = (k: number) => {
    const a = bands[k], b = bands[k + 1];
    const low = a.r < b.r ? a : b;
    return Math.abs(a.r - b.r) * (low.y1 - low.y0);
  };
  for (let k = 0; k + 1 < bands.length;) {
    if (Math.abs(bands[k].r - bands[k + 1].r) < FRAME_STEP) join(k);
    else k++;
  }
  while (bands.length > 1) {
    const k = bands.findIndex((b) => b.y1 - b.y0 < FRAME_MIN_PIECE);
    if (k < 0) break;
    const near = [k - 1, k].filter((j) => j >= 0 && j < bands.length - 1);
    join(near.reduce((a, b) => (waste(b) < waste(a) ? b : a)));
  }
  bands.forEach((b, k) => {
    if (sheet.w - b.r >= FRAME_MIN_PIECE && b.y1 - b.y0 >= FRAME_MIN_PIECE && b.y1 <= usable - 0.5) {
      out.push({ name: k === 0 ? "right rest piece" : `rest piece beside the ${boxes[b.i].name.toLowerCase()}`,
        x0: b.r, y0: b.y0, x1: sheet.w, y1: b.y1 });
    }
  });
  return out;
}

const mm = (v: number) => v.toFixed(0);

export interface SheetViewEvents {
  change(placements: Placement[], moved: number[]): void;
  select(part: number | null): void;
  hover?(part: number | null): void;  // the part under the pointer (the 3D marks it), sent again on every crossing
  open?(part: number): void;          // a part double-clicked: its own page (a face, a board)
  fill?(): void;                      // empty space double-clicked: the sheets fill the view
}

/** The part (index) an event's target belongs to, or null. */
const partOf = (t: EventTarget | null) => {
  const pg = t instanceof Element ? t.closest<SVGGElement>(".part") : null;
  return pg ? Number(pg.dataset.i) : null;
};

export class SheetView {
  private build: Build | null = null;
  private sheet!: Sheet;
  private placements: Placement[] = [];
  private selected: number | null = null;
  private zoom = 1;
  private rest = true;
  private pressed: number | null = null;   // the part the last press was on (null: empty space)

  constructor(private root: HTMLElement, private ev: SheetViewEvents) {
    root.tabIndex = 0;
    root.addEventListener("keydown", (e) => this.key(e));
    root.addEventListener("pointerover", (e) => this.ev.hover?.(partOf(e.target)));
    root.addEventListener("pointerleave", () => this.ev.hover?.(null));
    // A double-click is the part its press was on, not the part under its target: a redraw between the clicks
    // can leave the event on the sheets themselves. Captured: a part's own press stops at the part.
    root.addEventListener("pointerdown", (e) => (this.pressed = partOf(e.target)), { capture: true });
    root.addEventListener("dblclick", () => (this.pressed == null ? this.ev.fill?.() : this.ev.open?.(this.pressed)));
    root.addEventListener("wheel", (e) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      this.setZoom(this.zoom * (e.deltaY < 0 ? 1.1 : 1 / 1.1));
    }, { passive: false });
  }

  setZoom(z: number) {
    this.zoom = Math.min(4, Math.max(0.4, z));
    this.root.style.setProperty("--sheet-zoom", String(this.zoom));
  }

  select(i: number | null) {
    this.selected = i;
    this.root.querySelectorAll<SVGGElement>(".part").forEach((g) =>
      g.classList.toggle("selected", Number(g.dataset.i) === i));
    this.ev.select(i);
  }

  show(build: Build, sheet: Sheet, placements: Placement[], rest = true) {
    this.build = build;
    this.sheet = sheet;
    this.rest = rest;
    this.placements = placements.map((p) => ({ ...p }));
    this.fit();
    this.draw();
  }

  /** Base card width so a whole sheet fits the pane's height at zoom 1. */
  fit() {
    if (!this.sheet || !this.root.clientHeight) return;
    const avail = this.root.clientHeight - 36 - 40;   // padding + caption
    const w = Math.max(240, avail * (this.sheet.w + 12) / (this.sheet.h + 12));
    this.root.style.setProperty("--sheet-base", `${Math.round(w)}px`);
  }

  private draw() {
    const b = this.build;
    if (!b) return;
    const sheet = this.sheet;
    const bad = problems(b.parts, this.placements, sheet);
    const n = Math.max(1, ...this.placements.map((p) => p.sheet + 1));
    this.root.replaceChildren();
    for (let k = 0; k < n; k++) {
      const card = document.createElement("figure");
      card.className = "sheet-card";
      card.dataset.sheet = String(k);
      const used = this.placements.filter((p) => p.sheet === k);
      const off = offcut(b.parts, this.placements, sheet, k);
      const pieces = this.rest ? restPieces(b.parts, this.placements, sheet, k) : [];
      const cap = document.createElement("figcaption");
      const left = pieces.length
        ? `rest ${pieces.map((r) => `${mm(r.x1 - r.x0)} × ${mm(r.y1 - r.y0)}`).join(", ")} mm`
        : `offcut ${sheet.w} × ${off.toFixed(0)} mm`;
      cap.innerHTML = `<b>Sheet ${k + 1}</b><span>${used.length} part${used.length === 1 ? "" : "s"}</span><span>${left}</span>`;
      const svg = svgEl("svg", { viewBox: `-6 -6 ${sheet.w + 12} ${sheet.h + 12}`, class: "sheet-svg" }) as SVGSVGElement;
      const g = svgEl("g", { transform: `translate(0 ${sheet.h}) scale(1 -1)` }) as SVGGElement;
      g.dataset.frame = "1";
      g.append(svgEl("rect", { x: 0, y: 0, width: sheet.w, height: sheet.h, class: "ply" }));
      if (sheet.usable < sheet.h) {
        g.append(svgEl("rect", { x: 0, y: sheet.usable, width: sheet.w, height: sheet.h - sheet.usable, class: "noreach" }));
        g.append(svgEl("line", { x1: 0, y1: sheet.usable, x2: sheet.w, y2: sheet.usable, class: "reach" }));
      }
      const [ax0, ay0, ax1, ay1] = area(sheet);
      g.append(svgEl("rect", { x: ax0, y: ay0, width: ax1 - ax0, height: ay1 - ay0, class: "margin" }));
      const top = sheet.h - off;
      if (!pieces.length && off > 5) g.append(svgEl("rect", { x: 0, y: top, width: sheet.w, height: off, class: "offcut" }));
      for (const r of pieces) {
        const piece = svgEl("rect", { x: r.x0, y: r.y0, width: r.x1 - r.x0, height: r.y1 - r.y0, class: "rest-piece" });
        const t = svgEl("title");
        t.textContent = `${r.name}: ${mm(r.x1 - r.x0)} × ${mm(r.y1 - r.y0)} mm, cut free last (CUT frame)`;
        piece.append(t);
        g.append(piece);
      }
      const labels = svgEl("g", { class: "rest-labels" });
      for (const r of pieces) {
        // the cuts that free it: its edges that aren't the sheet's
        if (r.y0 > 1e-6) g.append(svgEl("line", { x1: r.x0, y1: r.y0, x2: r.x1, y2: r.y0, class: "frame-cut" }));
        if (r.y1 < sheet.h - 1e-6) g.append(svgEl("line", { x1: r.x0, y1: r.y1, x2: r.x1, y2: r.y1, class: "frame-cut" }));
        if (r.x0 > 1e-6) g.append(svgEl("line", { x1: r.x0, y1: r.y0, x2: r.x0, y2: r.y1, class: "frame-cut" }));
        const w = r.x1 - r.x0, hh = Math.min(r.y1, sheet.usable) - r.y0;
        if (w >= 34 && hh >= 12) {
          const label = svgEl("text", { x: (r.x0 + r.x1) / 2, y: sheet.h - (r.y0 + hh / 2), class: "rest-label" });
          label.textContent = `${mm(w)} × ${mm(r.y1 - r.y0)}`;
          labels.append(label);
        }
      }
      for (const pl of used) {
        const p = b.parts[pl.part];
        const pg = svgEl("g", { class: "part", transform: partTransform(p, pl) }) as SVGGElement;
        pg.dataset.i = String(p.index);
        if (bad.has(p.index)) pg.classList.add("bad");
        if (p.index === this.selected) pg.classList.add("selected");
        const cut = (p.paths["2"] ?? []);
        pg.append(svgEl("path", { d: pathD(cut.filter((s) => s.closed)), class: "body", "fill-rule": "evenodd" }));
        if (p.paths["30"]) pg.append(svgEl("path", { d: pathD(p.paths["30"]), class: "ref" }));
        if (p.paths["1"]) pg.append(svgEl("path", { d: pathD(p.paths["1"]), class: "line" }));
        for (const d of p.deco) {
          const dd = d.lines.map((l) => "M" + l.map((q) => q.join(" ")).join("L") + (d.polys ? "Z" : "")).join("");
          // the inside faces' engraving is on the underside as cut: faint; a logo's fill (FILL) filled
          pg.append(svgEl("path", { d: dd, "fill-rule": "evenodd",
            class: d.side === "in" ? "underside" : d.polys ? "fill" : d.layer === 1 ? "line" : "ref" }));
        }
        pg.append(svgEl("path", { d: pathD(cut), class: "cut" }));
        const title = svgEl("title");
        title.textContent = `${p.name} — ${p.w.toFixed(1)} × ${p.h.toFixed(1)} mm`;
        pg.append(title);
        pg.addEventListener("pointerdown", (e) => this.drag(e as PointerEvent, pl, pg, g));
        g.append(pg);
      }
      svg.append(g, labels);
      svg.addEventListener("pointerdown", (e) => {
        if (!(e.target as Element).closest(".part")) this.select(null);
      });
      card.append(cap, svg);
      this.root.append(card);
    }
  }

  private toSheet(g: SVGGElement, e: PointerEvent): [number, number] {
    const m = g.getScreenCTM()!.inverse();
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m);
    return [p.x, p.y];
  }

  private drag(e: PointerEvent, pl: Placement, pg: SVGGElement, frame: SVGGElement) {
    e.preventDefault();
    e.stopPropagation();
    this.root.focus({ preventScroll: true });
    this.select(pl.part);
    const b = this.build!;
    const p = b.parts[pl.part];
    const start = this.toSheet(frame, e);
    const orig = { x: pl.x, y: pl.y };
    let moved = false;
    pg.setPointerCapture(e.pointerId);
    const snap = (v: number) => Math.round(v * 2) / 2;
    const move = (ev: PointerEvent) => {
      const [x, y] = this.toSheet(frame, ev);
      const nx = snap(orig.x + x - start[0]);
      const ny = snap(orig.y + y - start[1]);
      if (!moved && (Math.hypot(ev.clientX - e.clientX, ev.clientY - e.clientY) < DRAG_PX ||
                     Math.hypot(nx - orig.x, ny - orig.y) < 0.5)) return;
      moved = true;
      pl.x = nx;
      pl.y = ny;
      pg.setAttribute("transform", partTransform(p, pl));
      const bad = problems(b.parts, this.placements, this.sheet);
      pg.classList.toggle("bad", bad.has(pl.part));
    };
    const up = (ev: PointerEvent) => {
      pg.releasePointerCapture(e.pointerId);
      pg.removeEventListener("pointermove", move);
      pg.removeEventListener("pointerup", up);
      if (!moved) return;
      // dropped on another sheet? place it there, centred under the pointer
      const target = document.elementsFromPoint(ev.clientX, ev.clientY)
        .map((el) => el.closest?.(".sheet-card") as HTMLElement | null).find((c) => c);
      const tn = target ? Number(target.dataset.sheet) : pl.sheet;
      if (target && tn !== pl.sheet) {
        const tg = target.querySelector<SVGGElement>("g[data-frame]")!;
        const [x, y] = this.toSheet(tg, ev);
        const [w, h] = rotSize(p, pl.rot);
        pl.sheet = tn;
        pl.x = snap(x - w / 2);
        pl.y = snap(y - h / 2);
      }
      this.commit([pl.part]);
    };
    pg.addEventListener("pointermove", move);
    pg.addEventListener("pointerup", up);
  }

  private commit(moved: number[]) {
    // close gaps left by emptied sheets, so sheet numbers stay 1..n
    const used = [...new Set(this.placements.map((p) => p.sheet))].sort((a, b) => a - b);
    this.placements.forEach((p) => (p.sheet = used.indexOf(p.sheet)));
    this.draw();
    this.ev.change(this.placements.map((p) => ({ ...p })), moved);
  }

  private key(e: KeyboardEvent) {
    if (this.selected == null || !this.build) return;
    const pl = this.placements.find((p) => p.part === this.selected);
    if (!pl) return;
    const p = this.build.parts[pl.part];
    const step = e.shiftKey ? 10 : 1;
    let handled = true;
    if (e.key === "r" || e.key === "R") {
      const [w, h] = rotSize(p, pl.rot);
      const cx = pl.x + w / 2, cy = pl.y + h / 2;
      pl.rot = (pl.rot + 90) % 360;
      const [w2, h2] = rotSize(p, pl.rot);
      pl.x = Math.round((cx - w2 / 2) * 2) / 2;
      pl.y = Math.round((cy - h2 / 2) * 2) / 2;
    } else if (e.key === "ArrowLeft") pl.x -= step;
    else if (e.key === "ArrowRight") pl.x += step;
    else if (e.key === "ArrowUp") pl.y += step;
    else if (e.key === "ArrowDown") pl.y -= step;
    else if (e.key === "PageDown") pl.sheet += 1;
    else if (e.key === "PageUp") pl.sheet = Math.max(0, pl.sheet - 1);
    else if (e.key === "Escape") this.select(null);
    else handled = false;
    if (handled) {
      e.preventDefault();
      if (e.key !== "Escape") this.commit([pl.part]);
    }
  }
}
