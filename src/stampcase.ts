// The stamp case (python/superboxes/stampcase): its side panel (project, stamps, problems) and the board editor in
// the 2D half (tabs Base / pocket boards / Lid / Sheets), as decided in .grill/stamp-case-merge.md (layout A).
//
// Every edit is made to the case JSON (= the box's params) here and handed to the host, which keeps undo and asks
// Python for the full layout. Only adding, duplicating, re-packing and placing a magnet need Python's placement
// (stampcase_op). While something is dragged, the editor checks the wood between pockets and around magnets itself,
// so red shows at once; the full layout follows on release.

import { h } from "./params";
import { pathD } from "./sheetview";
import { btn, fillToolbar, helpButton, helpCard } from "./ui";
import type { Block, BlockKey, Build, Case, Pocket, Pt, ShapePoly, Side, StampData } from "./types";

const NS = "http://www.w3.org/2000/svg";
const svg = (tag: string, attrs: Record<string, any> = {}) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
};

export const GENERATOR = "StampCase";

export const DEFAULT_CASE: Case = {
  project: "", pocket_boards: 2, air: 1, logo: "slogo_30mm_lite.svg", pockets: [], magnets: [], magnets_auto: true,
  top_block: { x: 0, y: 0, size: 8, rot: 90, placed: false },
  lid_title: { x: 0, y: 0, size: 24, rot: 0, placed: false },
  lid_logo: { x: 0, y: 0, size: 24, rot: 0, placed: false },
};

/** The gallery tile's case: a handful of stamps (Python packs them). */
export function demoCase(): Case {
  const sizes: [string, number, number][] = [["Fire", 40, 40], ["Water", 40, 40], ["Earth", 40, 40], ["Air", 40, 40],
    ["Logo", 60, 30], ["Date", 30, 20]];
  return { ...structuredClone(DEFAULT_CASE), project: "STAMPS",
    pockets: sizes.map(([name, w, hh], i) => newPocket(name, w, hh, `demo${i}`)) };
}

export function newPocket(name: string, w: number, hh: number, id = Math.random().toString(16).slice(2, 10)): Pocket {
  return { name, w, h: hh, x: 0, y: 0, notch_side: "right", notch_end: "low", label_pos: "notch", id, thickness: 0 };
}

/** A case as stored, with every field there (older files, new boxes). */
export function normalise(p: Record<string, any>): Case {
  const c = { ...structuredClone(DEFAULT_CASE), ...structuredClone(p) } as Case;
  c.pockets = (c.pockets ?? []).map((q) => ({ ...newPocket("", 40, 60, q.id), ...q }));
  return c;
}

// ------------------------------------------------------------------ the model's own edits (model.py)
const OPPOSITE: Record<Side, Side> = { left: "right", right: "left", bottom: "top", top: "bottom" };
const CCW: Record<Side, Side> = { right: "top", top: "left", left: "bottom", bottom: "right" };

function rotatePocket(p: Pocket, air: number) {
  const cx = p.x + (p.w + 2 * air) / 2, cy = p.y + (p.h + 2 * air) / 2;
  if (p.notch_side === "left" || p.notch_side === "right") p.notch_end = p.notch_end === "low" ? "high" : "low";
  p.notch_side = CCW[p.notch_side];
  [p.w, p.h] = [p.h, p.w];
  p.x = cx - (p.w + 2 * air) / 2;
  p.y = cy - (p.h + 2 * air) / 2;
}
const flipNotch = (p: Pocket) => (p.notch_side = OPPOSITE[p.notch_side]);
const swapEnd = (p: Pocket) => (p.notch_end = p.notch_end === "low" ? "high" : "low");
const cycleLabel = (p: Pocket) => (p.label_pos = p.label_pos === "notch" ? "side" : p.label_pos === "side" ? "end" : "notch");

/** The user takes over the magnets: from now on they're the list as it stands. */
function freezeMagnets(c: Case, d: StampData) {
  if (c.magnets_auto) {
    c.magnets = d.magnets.map(([x, y]) => [x, y]);
    c.magnets_auto = false;
  }
}

// ------------------------------------------------------------------ geometry for the live checks
type Ring = Pt[];
const rings = (polys: ShapePoly[] | null): Ring[] => (polys ?? []).flatMap((p) => [p.outer, ...p.holes]);

function segDist(px: number, py: number, ax: number, ay: number, bx: number, by: number) {
  const dx = bx - ax, dy = by - ay;
  const l = dx * dx + dy * dy;
  const t = l ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l)) : 0;
  return Math.hypot(px - ax - t * dx, py - ay - t * dy);
}

function inside(x: number, y: number, ring: Ring) {
  let ins = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) ins = !ins;
  }
  return ins;
}

/** Distance from a point to a polygon set's boundary (0 inside the first ring of a polygon). */
function pointDist(x: number, y: number, polys: ShapePoly[], dx = 0, dy = 0) {
  let d = Infinity;
  for (const p of polys) {
    if (inside(x - dx, y - dy, p.outer) && !p.holes.some((hh) => inside(x - dx, y - dy, hh))) return 0;
    for (const r of [p.outer, ...p.holes]) {
      for (let i = 1; i < r.length; i++) d = Math.min(d, segDist(x - dx, y - dy, r[i - 1][0], r[i - 1][1], r[i][0], r[i][1]));
    }
  }
  return d;
}

/** Least distance between two ring sets, b moved by (dx, dy): vertex-to-segment both ways. Rings here are dense
 *  (R3 corners and the notch in 16 segments a quarter), so this is within a few hundredths of a mm. */
function ringsDist(a: Ring[], b: Ring[], dx: number, dy: number) {
  let d = Infinity;
  for (const ra of a) for (const rb of b) {
    for (const [x, y] of ra) for (let i = 1; i < rb.length; i++) d = Math.min(d, segDist(x, y, rb[i - 1][0] + dx, rb[i - 1][1] + dy, rb[i][0] + dx, rb[i][1] + dy));
    for (const [x, y] of rb) for (let i = 1; i < ra.length; i++) d = Math.min(d, segDist(x + dx, y + dy, ra[i - 1][0], ra[i - 1][1], ra[i][0], ra[i][1]));
  }
  return d;
}

function bounds(polys: ShapePoly[] | null): [number, number, number, number] {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const r of rings(polys)) for (const [x, y] of r) {
    x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
  }
  return [x0, y0, x1, y1];
}

function polyD(polys: ShapePoly[] | null, dx = 0, dy = 0): string {
  return rings(polys).map((r) => "M" + r.map(([x, y]) => `${(x + dx).toFixed(3)} ${(y + dy).toFixed(3)}`).join("L") + "Z").join("");
}

// ------------------------------------------------------------------ host
export interface StampHost {
  params(): Case;
  build(): Build | null;
  /** The case changed: keep it, push undo, build. select: what to select afterwards. panel = false: the side panel
   *  control already shows the change, so the panel isn't redrawn (that would drop the field the user clicked next). */
  commit(next: Case, select?: string[], panel?: boolean): void;
  /** Python's placement for add / duplicate / repack / add_magnet; resolves with the selection it reports. */
  op(op: string, extra?: Record<string, unknown>): Promise<string[] | null>;
  toast(text: string, bad?: boolean): void;
  /** The Sheets tab: hand the 2D half to the sheet view (true) or back to the board editor (false). */
  showSheets(on: boolean): void;
}

const SNAP_FALLBACK = 0.5;

// ------------------------------------------------------------------ side panel
export function renderPanel(el: HTMLElement, host: StampHost, editor: BoardEditor) {
  const c = host.params();
  const d = host.build()?.stampcase ?? null;
  // a stamp half typed into the add row survives a redraw (a drag on the board, Pocket boards)
  const draft = afterAdd ? [] : [...el.querySelectorAll<HTMLInputElement>(".stamp-add input")].map((i) => i.value);
  el.replaceChildren();
  const commit = (fn: (c: Case) => void, select?: string[], panel = true) => {
    const n = structuredClone(host.params());
    fn(n);
    host.commit(n, select, panel);
  };

  // case
  const g1 = h("section", { class: "group" }, h("h3", {}, "Stamp case"));
  const project = h("input", { type: "text", value: c.project, placeholder: "the design these stamps are for", spellcheck: "false" }) as HTMLInputElement;
  project.onchange = () => commit((n) => (n.project = project.value), undefined, false);
  g1.append(h("label", { class: "row text-row" }, h("span", {}, "Project"), project));
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Pocket boards" });
  for (const k of [1, 2, 3, 4]) {
    const b = h("button", { "aria-pressed": c.pocket_boards === k, title: `${k} pocket board${k > 1 ? "s" : ""}: pockets ${(k * (host.build()?.info.thickness ?? 3.7)).toFixed(1)} mm deep` }, String(k));
    b.onclick = () => commit((n) => (n.pocket_boards = k));
    seg.append(b);
  }
  g1.append(h("div", { class: "row" }, h("div", { class: "row-head" }, h("label", {}, "Pocket boards"),
    h("span", { class: "hint" }, d ? `pockets ${d.depth.toFixed(1)} mm deep` : "")), seg));
  const logos = d?.logos ?? [];
  if (logos.length) {
    const sel = h("select", { "aria-label": "Logo" }) as HTMLSelectElement;
    for (const f of logos) sel.append(h("option", { value: f, selected: f === c.logo }, f.replace(/\.svg$/i, "")));
    sel.onchange = () => commit((n) => (n.logo = sel.value), undefined, false);
    g1.append(h("label", { class: "row sel-row" }, h("span", {}, "Logo"), sel));
  } else {
    g1.append(h("div", { class: "row hint" }, "No logo: the logos folder (C:\\Projects\\eating voltage Fonts\\logos) isn't reachable."));
  }
  el.append(g1);

  // stamps
  const g2 = h("section", { class: "group stamps" }, h("h3", {}, `Stamps (${c.pockets.length})`));
  const nName = h("input", { type: "text", placeholder: "name", spellcheck: "false", "aria-label": "Stamp name" }) as HTMLInputElement;
  const nW = h("input", { type: "number", min: 1, step: 0.5, placeholder: "W", class: "num", "aria-label": "Stamp width, mm" }) as HTMLInputElement;
  const nH = h("input", { type: "number", min: 1, step: 0.5, placeholder: "H", class: "num", "aria-label": "Stamp height, mm" }) as HTMLInputElement;
  if (draft.length) [nName.value, nW.value, nH.value] = draft;
  const add = h("button", { class: "primary-soft", title: "Add the stamp in free space (Enter)" }, "Add");
  const doAdd = async () => {
    const w = Number(nW.value), hh = Number(nH.value);
    if (!(w > 0 && hh > 0)) {
      host.toast("Type the stamp's width and height as measured, in mm.", true);
      (w > 0 ? nH : nW).focus();
      return;
    }
    afterAdd = true;
    if (!(await host.op("add", { pocket: { name: nName.value.trim(), w, h: hh } }))) afterAdd = false;
  };
  add.onclick = doAdd;
  // block body: an on… handler that returns false cancels the keystroke
  for (const i of [nName, nW, nH]) i.onkeydown = (e) => { if (e.key === "Enter") doAdd(); };
  g2.append(h("div", { class: "row stamp-add" }, nName, nW, h("span", { class: "unit" }, "×"), nH, add),
    h("div", { class: "hint row" }, "The stamp itself, as measured: 1 mm of air is added on every side."));
  const list = h("div", { class: "stamp-list" });
  for (const p of c.pockets) {
    const sel = editor.selected.has(p.id);
    const row = h("div", { class: `stamp-row${sel ? " sel" : ""}`, "data-id": p.id });
    const bad = d?.problems.some((q) => q.level === "error" && q.refs.includes(p.id));
    if (bad) row.classList.add("bad");
    const name = h("input", { type: "text", value: p.name, spellcheck: "false", "aria-label": "Name" }) as HTMLInputElement;
    const num = (v: number | undefined, label: string, ph = "") =>
      h("input", { type: "number", min: 0, step: 0.5, value: v ? String(v) : "", placeholder: ph, class: "num", "aria-label": label }) as HTMLInputElement;
    const w = num(p.w, "Width, mm"), hh = num(p.h, "Height, mm"), t = num(p.thickness, "Thickness, mm (optional)", "t");
    t.title = "The stamp's thickness, optional: the 3D shows it, and a stamp too thick for the pockets is an error";
    const set = (fn: (q: Pocket) => void) => commit((n) => {
      const q = n.pockets.find((x) => x.id === p.id);
      if (q) fn(q);
    }, [p.id], false);
    name.onchange = () => set((q) => (q.name = name.value));
    w.onchange = () => Number(w.value) > 0 && set((q) => (q.w = Number(w.value)));
    hh.onchange = () => Number(hh.value) > 0 && set((q) => (q.h = Number(hh.value)));
    t.onchange = () => set((q) => (q.thickness = Math.max(0, Number(t.value) || 0)));
    const del = h("button", { class: "chip-x", title: "Delete (Del)", "aria-label": `Delete ${p.name || "stamp"}` }, "×");
    del.onclick = () => commit((n) => (n.pockets = n.pockets.filter((x) => x.id !== p.id)), []);
    row.onclick = (e) => {
      if ((e.target as HTMLElement).tagName === "INPUT" || (e.target as HTMLElement).tagName === "BUTTON") return;
      editor.select([p.id], e.shiftKey);
    };
    name.onfocus = () => editor.select([p.id]);
    row.append(name, w, h("span", { class: "unit" }, "×"), hh, t, del);
    list.append(row);
  }
  g2.append(list);
  el.append(g2);

  // problems and sheets: refreshed on their own after every build (renderCheck), so typing isn't interrupted
  const g3 = h("section", { class: "group stamp-check" });
  el.append(g3);
  renderCheck(el, host, editor);
  if (afterAdd) {
    afterAdd = false;
    nName.focus();
  }
}

let afterAdd = false;       // this redraw follows an Add: a fresh add row, its name field focused for the next stamp

/** The Check section only: problems (click to show them) and how the boards use the sheets. */
export function renderCheck(el: HTMLElement, host: StampHost, editor: BoardEditor) {
  const g3 = el.querySelector<HTMLElement>(".stamp-check");
  const d = host.build()?.stampcase ?? null;
  if (!g3) return;
  g3.replaceChildren(h("h3", {}, "Check"));
  if (!d) return;
  if (!d.problems.length) g3.append(h("div", { class: "row ok" }, "✓ Ready to cut"));
  for (const p of d.problems) {
    const b = h("button", { class: `problem ${p.level}`, title: p.refs.length ? "Show it" : "" }, (p.level === "error" ? "✕ " : "⚠ ") + p.text);
    b.onclick = () => p.refs.length && editor.select(p.refs);
    g3.append(b);
  }
  const [bw, bh] = d.size;
  g3.append(h("div", { class: "row hint sheet-use" },
    `${d.boards.length} boards ${bw.toFixed(0)} × ${bh.toFixed(0)} mm` +
    (d.sheets ? ` · ${d.per_sheet} a sheet: ${d.sheets} sheet${d.sheets > 1 ? "s" : ""}` : ` · too big (most ${d.max_board[0]} × ${d.max_board[1]})`) +
    (d.hint ? ` · ${d.hint[0].toFixed(0)} mm ${d.hint[1]} would need ${d.hint[2]}` : "")));
  el.querySelectorAll<HTMLElement>(".stamp-row").forEach((r) => {
    const bad = d.problems.some((q) => q.level === "error" && q.refs.includes(r.dataset.id!));
    r.classList.toggle("bad", bad);
  });
}

// ------------------------------------------------------------------ board editor
type Hit = { kind: "pocket"; id: string } | { kind: "magnet"; i: number } | { kind: "block"; key: BlockKey };
const refOf = (t: Hit) => (t.kind === "pocket" ? t.id : t.kind === "magnet" ? `magnet:${t.i}` : t.key);

const BLOCKS_ON: Record<string, BlockKey[]> = { lid: ["lid_title", "lid_logo"] };
const BLOCK_NAME: Record<BlockKey, string> = { top_block: "logo, project name and mark", lid_title: "lid title", lid_logo: "lid logo" };

export class BoardEditor {
  selected = new Set<string>();
  private tab = "";                     // board key, or "sheets"
  private svgRoot: SVGSVGElement;
  private view: [number, number, number, number] | null = null;   // viewBox x, y, w, h (flipped: y is -ymax)
  private drag: { hits: Hit[]; x0: number; y0: number; dx: number; dy: number; moved: boolean } | null = null;
  private pan: { x: number; y: number; v: [number, number, number, number] } | null = null;

  constructor(private tabs: HTMLElement, private tools: HTMLElement, private root: HTMLElement, private bar: HTMLElement,
              private host: StampHost) {
    this.svgRoot = svg("svg", { class: "board-svg", tabindex: 0 }) as SVGSVGElement;
    root.append(this.svgRoot);
    this.svgRoot.addEventListener("wheel", (e) => this.wheel(e), { passive: false });
    this.svgRoot.addEventListener("pointerdown", (e) => this.down(e));
    this.svgRoot.addEventListener("pointermove", (e) => this.move(e));
    this.svgRoot.addEventListener("pointerup", (e) => this.up(e));
    this.svgRoot.addEventListener("dblclick", (e) => this.dbl(e));
    new ResizeObserver(() => this.draw()).observe(root);
  }

  /** Show the editor (stamp case) or hide it (any other type). */
  setActive(on: boolean) {
    this.tabs.hidden = !on;
    this.root.hidden = this.tools.hidden = !on || this.tab === "sheets";
    this.bar.hidden = !on || this.tab === "sheets" || !this.selected.size;
    if (on) this.host.showSheets(this.tab === "sheets");     // off: the face editor decides what shows
  }

  private data(): StampData | null {
    return this.host.build()?.stampcase ?? null;
  }

  /** The part (index) of the board shown, or null on Sheets. */
  get part(): number | null {
    return this.data()?.boards.find((b) => b.key === this.tab)?.part ?? null;
  }

  /** A part double-clicked on the sheets: open its board. False when it isn't one (a wall). */
  openPart(i: number): boolean {
    const board = this.data()?.boards.find((b) => b.part === i);
    if (!board) return false;
    this.setTab(board.key);
    return true;
  }

  update() {
    const d = this.data();
    if (!d) return;
    if (!this.tab || (this.tab !== "sheets" && !d.boards.some((b) => b.key === this.tab))) this.tab = d.top_key;
    // drop selections that no longer exist
    const ids = new Set([...d.pockets.map((p) => p.id), ...d.magnets.map((_, i) => `magnet:${i}`), "top_block", "lid_title", "lid_logo"]);
    for (const s of [...this.selected]) if (!ids.has(s)) this.selected.delete(s);
    this.renderTabs();
    this.renderTools();
    this.draw();
    this.renderBar();
  }

  select(refs: string[], add = false) {
    if (!add) this.selected.clear();
    for (const r of refs) {
      if (add && this.selected.has(r)) this.selected.delete(r);
      else this.selected.add(r);
    }
    // show it on a board that has it
    const d = this.data();
    if (d && this.tab !== "sheets") {
      if (refs.some((r) => r.startsWith("magnet:")) && this.tab !== d.top_key && this.tab !== "lid") this.setTab(d.top_key);
      else if (refs.includes("top_block")) this.setTab(d.top_key);
      else if (refs.includes("lid_title") || refs.includes("lid_logo")) this.setTab("lid");
    } else if (this.tab === "sheets" && d) this.setTab(d.top_key);
    this.draw();
    this.renderBar();
    document.querySelectorAll<HTMLElement>(".stamp-row").forEach((r) => r.classList.toggle("sel", this.selected.has(r.dataset.id!)));
  }

  private setTab(key: string) {
    this.tab = key;
    this.renderTabs();
    this.root.hidden = this.tools.hidden = key === "sheets";
    this.host.showSheets(key === "sheets");
    this.renderTools();
    this.draw();
    this.renderBar();
  }

  private renderTabs() {
    const d = this.data();
    if (!d) return;
    this.tabs.replaceChildren();
    for (const [key, title] of [["sheets", "Sheets"] as const, ...d.boards.map((b) => [b.key, b.title] as const)]) {
      const b = h("button", { role: "tab", "aria-selected": this.tab === key }, title);
      b.onclick = () => this.setTab(key);
      this.tabs.append(b);
    }
  }

  // ---------------------------------------------------------------- drawing
  private fitView(): [number, number, number, number] {
    const d = this.data()!;
    const [x0, y0, x1, y1] = d.rect;
    const pad = Math.max(8, 0.06 * Math.max(x1 - x0, y1 - y0));
    return [x0 - pad, -(y1 + pad), x1 - x0 + 2 * pad, y1 - y0 + 2 * pad];
  }

  fit() {
    this.view = null;
    this.draw();
  }

  private draw() {
    const d = this.data();
    const b = this.host.build();
    if (!d || !b || this.tab === "sheets" || this.root.hidden) return;
    const board = d.boards.find((q) => q.key === this.tab);
    if (!board) return;
    const part = b.parts[board.part];
    const v = this.view ?? this.fitView();
    this.svgRoot.setAttribute("viewBox", v.map((n) => n.toFixed(2)).join(" "));
    const [ox, oy] = d.origin;
    const g = svg("g", { transform: "scale(1 -1)" });
    // the board: wood, engraving, cuts - as LightBurn gets them, before kerf
    const wood = svg("path", { d: polyD(part.shape, ox, oy), class: "board-wood", "fill-rule": "evenodd" });
    g.append(wood);
    const art = svg("g", { transform: `translate(${ox} ${oy})` });
    if (part.paths["1"]) art.append(svg("path", { d: pathD(part.paths["1"]), class: "board-line" }));
    if (part.paths["2"]) art.append(svg("path", { d: pathD(part.paths["2"]), class: "board-cut" }));
    g.append(art);

    // what can be picked: pockets everywhere, magnets on the top board and lid, the blocks on their board
    const bad = new Set(d.problems.filter((p) => p.level === "error").flatMap((p) => p.refs));
    const dd = this.drag;
    const moving = (t: Hit) => !!dd && dd.hits.some((x) => refOf(x) === refOf(t));
    const off = (t: Hit) => (moving(t) && dd ? [dd.dx, dd.dy] : [0, 0]);
    const live = dd?.moved ? this.liveBad() : new Set<string>();
    const cls = (t: Hit, base: string) => {
      const r = refOf(t);
      return `${base}${this.selected.has(r) ? " sel" : ""}${(dd?.moved ? live.has(r) : bad.has(r)) ? " bad" : ""}`;
    };
    for (const p of d.pockets) {
      const t: Hit = { kind: "pocket", id: p.id };
      const [mx, my] = off(t);
      const el = svg("path", { d: polyD(p.hole, mx, my), class: cls(t, "hit pocket"), "data-ref": p.id });
      g.append(el);
      if (this.selected.has(p.id) && p.label_box && this.tab === d.top_key) {
        g.append(svg("path", { d: polyD(p.label_box, mx, my), class: "label-box" }));
      }
    }
    if (this.tab === d.top_key || this.tab === "lid") {
      d.magnets.forEach(([x, y], i) => {
        const t: Hit = { kind: "magnet", i };
        const [mx, my] = off(t);
        g.append(svg("circle", { cx: x + mx, cy: y + my, r: Math.max(d.magnet_r, 1.6), class: cls(t, "hit magnet"), "data-ref": `magnet:${i}` }));
      });
    }
    const blocks: BlockKey[] = this.tab === d.top_key ? ["top_block"] : BLOCKS_ON[this.tab] ?? [];
    for (const k of blocks) {
      const bl = d.blocks[k];
      if (!bl.region) continue;
      const t: Hit = { kind: "block", key: k };
      const [mx, my] = off(t);
      g.append(svg("path", { d: polyD(bl.region, mx, my), class: cls(t, "hit block"), "data-ref": k }));
    }
    this.svgRoot.replaceChildren(g);
  }

  // ---------------------------------------------------------------- the toolbar over the board
  private renderTools() {
    const d = this.data();
    if (!d || this.tab === "sheets") return;
    const c = this.host.params();
    const magnets = this.tab === d.top_key || this.tab === "lid";
    const magnet = btn("Magnet", magnets ? "A magnet in the free wood nearest the board's middle (or double-click free wood)"
      : "Magnets go on the top pocket board and the lid", () => {
      const [x0, y0, x1, y1] = d.rect;
      this.host.op("add_magnet", { x: (x0 + x1) / 2, y: (y0 + y1) / 2 });
    });
    magnet.disabled = !magnets;
    const auto = btn("Auto magnets", "Hand the magnets back to the app (Ctrl+M)", () => this.edit((n) => {
      n.magnets_auto = true;
      n.magnets = [];
    }));
    auto.disabled = c.magnets_auto;
    fillToolbar(this.tools, [h("span", { class: "tb-label" }, "Add"), magnet, h("span", { class: "tb-gap" }),
      btn("Re-pack stamps", "Lay every pocket out from scratch: fewest sheets, then the smallest board (Ctrl+P)",
        () => this.host.op("repack")), auto],
    [helpButton((b) => this.openHelp(b))]);
  }

  private openHelp(anchor: HTMLElement) {
    helpCard(anchor, "Stamp case boards", [
      ["Click", "select a pocket, a magnet or a text block (Shift+click: add to the selection)"],
      ["Drag", "move what's selected"],
      ["R", "rotate a pocket or a text block"],
      ["F", "flip the finger notch to the other side"],
      ["E", "the notch to the other end"],
      ["N", "where the stamp's name goes: beside the notch, opposite side, far end"],
      ["Arrows", "nudge (Shift: 10 steps)"],
      ["Ctrl+D", "duplicate a pocket"],
      ["Del", "delete"],
      ["Double-click", "free wood on the top pocket board or the lid: a magnet"],
      ["Wheel", "zoom; middle button pans, Ctrl+0 fits"],
      ["Ctrl+P / Ctrl+M", "re-pack the stamps / auto magnets"],
    ], ["Red: what the side panel's Check lists as an error (click one there to see it)."]);
  }

  // ---------------------------------------------------------------- the bar under the editor: the selection
  private renderBar() {
    const d = this.data();
    const c = this.host.params();
    this.bar.hidden = !d || this.tab === "sheets" || this.root.hidden || !this.selected.size;
    if (!d || this.tab === "sheets") return;
    const sel = [...this.selected];
    const pockets = c.pockets.filter((p) => this.selected.has(p.id));
    const blocks = sel.filter((s): s is BlockKey => s in d.blocks);
    const mags = sel.filter((s) => s.startsWith("magnet:"));
    const kids: (Node | string)[] = [];
    if (pockets.length === 1) {
      const p = pockets[0];
      kids.push(h("b", {}, p.name || "(no name)"), h("span", {}, `${p.w} × ${p.h} mm${p.thickness ? `, ${p.thickness} thick` : ""}`),
        h("span", { class: "hint" }, `notch ${p.notch_side}, name ${p.label_pos === "notch" ? "beside the notch" : p.label_pos === "side" ? "opposite side" : "far end"}`));
    } else if (pockets.length) kids.push(h("b", {}, `${pockets.length} stamps`));
    if (pockets.length) {
      kids.push(btn("Rotate", "R", () => this.key("r")), btn("Flip notch", "F", () => this.key("f")),
        btn("Notch end", "E", () => this.key("e")), btn("Name", "N: beside the notch, opposite side, far end", () => this.key("n")),
        btn("Duplicate", "Ctrl+D", () => this.duplicate()), btn("Delete", "Del", () => this.remove()));
    }
    if (blocks.length === 1) {
      const k = blocks[0];
      const geo = d.blocks[k];
      const size = h("input", { type: "number", min: 2, step: 0.5, value: geo.size.toFixed(1), class: "num", "aria-label": "Size, mm" }) as HTMLInputElement;
      size.onchange = () => this.edit((n) => {
        const v = Number(size.value);
        if (v > 0) Object.assign(n[k], { x: geo.x, y: geo.y, rot: geo.rot, size: v, placed: true } satisfies Block);
      });
      kids.push(h("b", {}, BLOCK_NAME[k]), h("span", {}, "size"), size, h("span", { class: "unit" }, "mm"),
        btn("Rotate", "R", () => this.key("r")),
        btn(geo.placed ? "Auto place" : "placed automatically", "Let the app place it again", () => this.edit((n) => (n[k].placed = false))));
    }
    if (mags.length) kids.push(h("b", {}, `${mags.length} magnet${mags.length > 1 ? "s" : ""}`), btn("Delete", "Del", () => this.remove()));
    this.bar.replaceChildren(...kids);
  }

  // ---------------------------------------------------------------- edits
  private edit(fn: (c: Case, d: StampData) => void, select?: string[]) {
    const d = this.data();
    if (!d) return;
    const n = structuredClone(this.host.params());
    fn(n, d);
    this.host.commit(n, select);
  }

  /** Keys while the editor is shown; true when handled. */
  key(k: string, e?: KeyboardEvent): boolean {
    const d = this.data();
    if (!d || this.tab === "sheets") return false;
    const ctrl = !!e && (e.ctrlKey || e.metaKey);
    const ids = [...this.selected];
    const pocketIds = ids.filter((s) => d.pockets.some((p) => p.id === s));
    const air = this.host.params().air;
    const each = (fn: (p: Pocket) => void) => pocketIds.length && this.edit((n) => n.pockets.filter((p) => pocketIds.includes(p.id)).forEach(fn), ids);
    if (ctrl) {
      if (k === "d") return this.duplicate(), true;
      if (k === "p") return this.host.op("repack"), true;
      if (k === "m") return this.edit((n) => { n.magnets_auto = true; n.magnets = []; }), true;
      if (k === "0") return this.fit(), true;
      return false;
    }
    switch (k) {
      case "r": {
        const blocks = ids.filter((s): s is BlockKey => s in d.blocks);
        if (!pocketIds.length && !blocks.length) return false;
        this.edit((n) => {
          n.pockets.filter((p) => pocketIds.includes(p.id)).forEach((p) => rotatePocket(p, air));
          for (const bk of blocks) {
            const geo = d.blocks[bk];
            n[bk] = { x: geo.x, y: geo.y, size: geo.size, rot: 90 - geo.rot, placed: true };
          }
        }, ids);
        return true;
      }
      case "f": return each(flipNotch), pocketIds.length > 0;
      case "e": return each(swapEnd), pocketIds.length > 0;
      case "n": return each(cycleLabel), pocketIds.length > 0;
      case "delete": case "backspace": return this.remove(), ids.length > 0;
      case "escape": return this.select([]), true;
      case "arrowleft": case "arrowright": case "arrowup": case "arrowdown": {
        if (!ids.length) return false;
        const s = (d.snap || SNAP_FALLBACK) * (e?.shiftKey ? 10 : 1);
        const [dx, dy] = { arrowleft: [-s, 0], arrowright: [s, 0], arrowup: [0, s], arrowdown: [0, -s] }[k]!;
        this.applyMove(this.hitsOf(ids), dx, dy);
        return true;
      }
    }
    return false;
  }

  private async duplicate() {
    const d = this.data();
    if (!d) return;
    const ids = [...this.selected].filter((s) => d.pockets.some((p) => p.id === s));
    if (ids.length) await this.host.op("duplicate", { ids });
  }

  private remove() {
    const ids = [...this.selected];
    const mags = ids.filter((s) => s.startsWith("magnet:")).map((s) => Number(s.split(":")[1])).sort((a, b) => b - a);
    const pockets = ids.filter((s) => !s.startsWith("magnet:") && !(s in (this.data()?.blocks ?? {})));
    if (!mags.length && !pockets.length) return;
    this.edit((n, d) => {
      n.pockets = n.pockets.filter((p) => !pockets.includes(p.id));
      if (mags.length) {
        freezeMagnets(n, d);
        for (const i of mags) if (i < n.magnets.length) n.magnets.splice(i, 1);
      }
    }, []);
  }

  private hitsOf(ids: string[]): Hit[] {
    const d = this.data()!;
    return ids.map((s): Hit | null => s.startsWith("magnet:") ? { kind: "magnet", i: Number(s.split(":")[1]) }
      : s in d.blocks ? { kind: "block", key: s as BlockKey } : d.pockets.some((p) => p.id === s) ? { kind: "pocket", id: s } : null)
      .filter((x): x is Hit => !!x);
  }

  private applyMove(hits: Hit[], dx: number, dy: number) {
    if (!hits.length || (!dx && !dy)) return;
    this.edit((n, d) => {
      const r = (v: number) => Math.round(v * 1000) / 1000;
      for (const t of hits) {
        if (t.kind === "pocket") {
          const p = n.pockets.find((q) => q.id === t.id);
          if (p) { p.x = r(p.x + dx); p.y = r(p.y + dy); }
        } else if (t.kind === "magnet") {
          freezeMagnets(n, d);
          const m = n.magnets[t.i];
          if (m) n.magnets[t.i] = [r(m[0] + dx), r(m[1] + dy)];
        } else {
          const geo = d.blocks[t.key];
          n[t.key] = { x: r(geo.x + dx), y: r(geo.y + dy), size: geo.size, rot: geo.rot, placed: true };
        }
      }
    }, hits.map(refOf));
  }

  // ---------------------------------------------------------------- live checks while dragging
  /** Refs that would break the wood rules where the drag has them now (Python has the last word on release). */
  private liveBad(): Set<string> {
    const out = new Set<string>();
    const d = this.data();
    const dd = this.drag;
    if (!d || !dd) return out;
    const moved = new Set(dd.hits.map(refOf));
    const holes = d.pockets.map((p) => ({ id: p.id, rings: rings(p.hole), b: bounds(p.hole), m: moved.has(p.id) }));
    const web = d.web - 0.01;
    for (let i = 0; i < holes.length; i++) for (let j = i + 1; j < holes.length; j++) {
      const a = holes[i], b = holes[j];
      if (a.m === b.m) continue;                         // moving together keeps their distance
      const [ax, ay] = a.m ? [dd.dx, dd.dy] : [0, 0];
      const [bx, by] = b.m ? [dd.dx, dd.dy] : [0, 0];
      if (a.b[0] + ax > b.b[2] + bx + web || b.b[0] + bx > a.b[2] + ax + web ||
          a.b[1] + ay > b.b[3] + by + web || b.b[1] + by > a.b[3] + ay + web) continue;
      if (ringsDist(a.rings, b.rings, bx - ax, by - ay) < web) {
        out.add(a.id);
        out.add(b.id);
      }
    }
    const r = d.magnet_r, wood = d.magnet_wood - 0.01;
    d.magnets.forEach(([x, y], i) => {
      const mm = moved.has(`magnet:${i}`);
      const mx = x + (mm ? dd.dx : 0), my = y + (mm ? dd.dy : 0);
      for (const p of d.pockets) {
        const pm = moved.has(p.id);
        if (mm === pm) continue;
        if (pointDist(mx, my, p.hole, pm ? dd.dx : 0, pm ? dd.dy : 0) < r + wood) {
          out.add(`magnet:${i}`);
          out.add(p.id);
        }
      }
    });
    return out;
  }

  // ---------------------------------------------------------------- pointer
  private toMM(e: { clientX: number; clientY: number }): [number, number] {
    const m = this.svgRoot.getScreenCTM();
    if (!m) return [0, 0];
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse());
    return [p.x, -p.y];                                  // the drawing is flipped: Y up
  }

  private down(e: PointerEvent) {
    this.svgRoot.focus();
    if (e.button === 1) {
      e.preventDefault();
      this.pan = { x: e.clientX, y: e.clientY, v: [...(this.view ?? this.fitView())] as [number, number, number, number] };
      this.svgRoot.setPointerCapture(e.pointerId);
      return;
    }
    if (e.button !== 0) return;
    const ref = (e.target as Element).closest("[data-ref]")?.getAttribute("data-ref");
    if (!ref) {
      if (!e.shiftKey) this.select([]);
      return;
    }
    if (e.shiftKey) {
      this.select([ref], true);
      return;
    }
    if (!this.selected.has(ref)) this.select([ref]);
    const [x, y] = this.toMM(e);
    this.drag = { hits: this.hitsOf([...this.selected]), x0: x, y0: y, dx: 0, dy: 0, moved: false };
    this.svgRoot.setPointerCapture(e.pointerId);
  }

  private move(e: PointerEvent) {
    if (this.pan) {
      const r = this.svgRoot.getBoundingClientRect();
      const v = this.pan.v;
      const k = v[2] / r.width;
      this.view = [v[0] - (e.clientX - this.pan.x) * k, v[1] - (e.clientY - this.pan.y) * k, v[2], v[3]];
      this.draw();
      return;
    }
    if (!this.drag) return;
    const [x, y] = this.toMM(e);
    const s = this.data()?.snap || SNAP_FALLBACK;
    const dx = Math.round((x - this.drag.x0) / s) * s, dy = Math.round((y - this.drag.y0) / s) * s;
    if (dx === this.drag.dx && dy === this.drag.dy) return;
    this.drag.dx = dx;
    this.drag.dy = dy;
    this.drag.moved = true;
    this.draw();
  }

  private up(e: PointerEvent) {
    if (this.pan) {
      this.pan = null;
      return;
    }
    const dd = this.drag;
    this.drag = null;
    this.svgRoot.releasePointerCapture?.(e.pointerId);
    if (dd?.moved) this.applyMove(dd.hits, dd.dx, dd.dy);
    else this.draw();
  }

  private dbl(e: MouseEvent) {
    const d = this.data();
    if (!d || (this.tab !== d.top_key && this.tab !== "lid")) return;
    if ((e.target as Element).closest("[data-ref]")) return;
    const [x, y] = this.toMM(e);
    this.host.op("add_magnet", { x, y });
  }

  private wheel(e: WheelEvent) {
    e.preventDefault();
    const v = this.view ?? this.fitView();
    const k = e.deltaY < 0 ? 1 / 1.15 : 1.15;
    const m = this.svgRoot.getScreenCTM();
    if (!m) return;
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse());
    this.view = [p.x - (p.x - v[0]) * k, p.y - (p.y - v[1]) * k, v[2] * k, v[3] * k];
    this.draw();
  }
}
