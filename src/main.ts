import * as py from "./py";
import * as files from "./files";
import * as cfg from "./config";
import * as mats from "./materials";
import { renderParams, h } from "./params";
import { SheetView, problems } from "./sheetview";
import { renderCalibration } from "./calibration";
import { createGallery } from "./gallery";
import * as sc from "./stampcase";
import { FaceEditor, type Faces } from "./faceeditor";
import { btn, fillToolbar, helpButton, helpCard, menu, type MenuItem } from "./ui";
import { A3 } from "./types";
import type { BoxConfig, Build, Case, ExportResult, Fit, Group, Options, Placement, Sheet } from "./types";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

// ------------------------------------------------------------------ state
const S = {
  catalog: [] as { name: string; short: string; description: string; group: string }[],
  boxesVersion: "",
  schemas: new Map<string, Group[]>(),
  generator: "ABox",
  name: "abox-50-tester",
  params: {} as Record<string, any>,
  materialKey: "poplar3.6",
  fit: "press" as Fit,
  compOverride: null as { burn: number; bx: number; by: number } | null,  // burns of an opened file that differ from the profile
  thicknessOverride: null as number | null,
  kerfOverride: null as { x: number; y: number } | null,                  // a stamp case file's kerf, if not the profile's
  sheet: A3 as Sheet,
  faces: {} as Faces,            // the face editor's items per face (not for the stamp case: its boards are its faces)
  boards: {} as Record<string, number>,   // per wall: the board's top above the inside floor, mm
  home: null as string | null,   // the box's own file on disk (serve.py): Save and the exports go beside it
  options: { labels_engrave: false, mark: { enabled: true, text: null, part: null }, rest_cuts: true } as Options,
  notes: "",
  build: null as Build | null,
  placements: [] as Placement[],
  manual: new Set<number>(),                 // parts placed by hand: kept where they are on rebuilds
  fileVersion: null as string | null,        // boxes.py version an opened file was made with
  dirty: false,
  openAdvanced: new Set<string>(),
  busy: 0,
};

const FIRST_BOX = { generator: "ABox", name: "abox-50-tester", params: { x: 50, y: 50, h: 50, outside: true } };
const isStamp = (gen = S.generator) => gen === sc.GENERATOR;

// ------------------------------------------------------------------ small UI helpers
let toastTimer = 0;
function toast(text: string, bad = false, ms = 4200) {
  const t = $("toast");
  t.textContent = text;
  t.classList.toggle("bad", bad);
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => (t.hidden = true), ms);
}

function setStatus(text: string) {
  const el = $("status");
  el.textContent = text;
  el.classList.toggle("busy", S.busy > 0 || text !== "Ready");
}

// ------------------------------------------------------------------ material and fit
function profile() {
  return mats.get(S.materialKey);
}

const f3 = (v: number) => v.toFixed(3).replace(/0$/, "");

/** What the box is cut with: the profile's compensation for the chosen fit, or the values a box file brought. */
function material() {
  const p = profile();
  const c = mats.compensation(p, S.fit);
  const o = S.compOverride;
  const bx = o ? o.bx : c.bx;
  const by = o ? o.by : c.by;
  const axis = Math.abs(bx - by) >= 0.0005;
  const burn = o ? o.burn : c.burn;
  const t = S.thicknessOverride ?? p.thickness;
  const what = axis ? `burn X ${f3(bx)} / Y ${f3(by)} mm (per axis)` : `burn ${f3(burn)} mm`;
  const note = o ? `${what} from the box file`
    : c.status === "measured" ? `${S.fit} fit ${c.delta >= 0 ? "+" : ""}${c.delta.toFixed(2)}, ${what} (measured)`
    : c.status === "kerf" ? `${what} = measured kerf / 2 (${S.fit} fit not tested yet)`
    : `${what} - UNCONFIRMED, cut the 00a/00b calibration sheets first`;
  const k = kerf();
  return {
    key: p.key, thickness: t, burn, fit: S.fit, status: c.status, fit_note: note,
    ...(axis ? { burn_x: bx, burn_y: by } : {}),
    ...(k ? { kerf_x: k.x, kerf_y: k.y } : {}),
  };
}

/** The kerf a stamp case is cut with (it takes kerf / 2 per axis and no fit): a file's own, else the profile's. */
function kerf(): { x: number; y: number } | null {
  if (S.kerfOverride) return S.kerfOverride;
  const p = profile();
  if (p.kerfX == null && p.kerfY == null) return null;
  return { x: p.kerfX ?? p.kerfY!, y: p.kerfY ?? p.kerfX! };
}

function renderMaterial() {
  const el = $("material");
  const p = profile();
  const m = material();
  el.replaceChildren(h("h3", {}, "Material & fit"));
  const sel = h("select", { "aria-label": "Material" }) as HTMLSelectElement;
  for (const q of mats.all()) sel.append(h("option", { value: q.key, selected: q.key === p.key }, q.label));
  sel.onchange = () => {
    S.materialKey = sel.value;
    S.compOverride = S.thicknessOverride = S.kerfOverride = null;
    changed(true);
    renderMaterial();
  };
  el.append(h("div", { class: "row" }, sel));
  if (isStamp()) {
    renderStampMaterial(el, m.thickness);
    return;
  }
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Fit" });
  for (const f of ["press", "glue"] as Fit[]) {
    const b = h("button", { "aria-pressed": S.fit === f }, f === "press" ? "Press fit" : "Glue fit");
    b.onclick = () => {
      S.fit = f;
      S.compOverride = null;
      changed(true);
      renderMaterial();
    };
    seg.append(b);
  }
  el.append(h("div", { class: "row" }, seg));
  const chip = h("span", { class: `chip-status ${S.compOverride ? "kerf" : m.status}` },
    S.compOverride ? "from file" : m.status === "measured" ? "measured" : m.status === "kerf" ? "from kerf" : "unconfirmed");
  const burnText = m.burn_x != null ? `X ${f3(m.burn_x)} · Y ${f3(m.burn_y!)} mm` : `${f3(m.burn)} mm`;
  el.append(h("div", { class: "readout" }, h("span", {}, "Thickness ", h("b", {}, `${m.thickness} mm`)),
    h("span", { title: m.burn_x != null ? "Per-axis kerf compensation: your spot cuts wider in one axis" : "" },
      "Burn ", h("b", {}, burnText), " ", chip)), calibrateRow());
  if (S.compOverride || S.thicknessOverride != null) {
    const use = h("button", {}, "Use the material profile instead");
    use.onclick = () => {
      S.compOverride = S.thicknessOverride = null;
      changed(true);
      renderMaterial();
    };
    el.append(h("div", { class: "notice" }, "This box was saved with other material values than your current profile. ", use));
  } else if (m.status === "default") {
    el.append(h("div", { class: "notice" }, "Burn 0.10 is boxes.py's default, never measured on your Falcon2. Cut the calibration sheets (Calibrate…) before cutting boxes you care about."));
  }
}

/** Calibration opens from here: it fills the work area until Back. */
function calibrateRow() {
  return h("div", { class: "row calib-row" },
    btn("Calibrate…", "Cut and measure the kerf test and the fit comb for this material", () => tab("calib")));
}

/** A stamp case has no press or glue fit (the 1 mm of air around each stamp is the fit): kerf / 2 per axis. */
function renderStampMaterial(el: HTMLElement, thickness: number) {
  const k = kerf();
  const kt = k ? `X ${f3(k.x)} · Y ${f3(k.y)} mm` : "not measured";
  el.append(h("div", { class: "readout" }, h("span", {}, "Thickness ", h("b", {}, `${thickness} mm`)),
    h("span", { title: "Outlines and pockets get half the kerf per axis; magnet holes are drawn as they are" }, "Kerf ", h("b", {}, kt), " ",
      h("span", { class: `chip-status ${S.kerfOverride ? "kerf" : k ? "measured" : "default"}` }, S.kerfOverride ? "from file" : k ? "measured" : "unconfirmed"))),
    calibrateRow());
  if (S.kerfOverride || S.thicknessOverride != null) {
    const use = h("button", {}, "Use the material profile instead");
    use.onclick = () => {
      S.kerfOverride = S.thicknessOverride = null;
      changed(true);
      renderMaterial();
    };
    el.append(h("div", { class: "notice" }, "This case was saved with other material values than your current profile. ", use));
  } else if (!k) {
    el.append(h("div", { class: "notice" }, "The kerf of this material hasn't been measured: cut the 00a kerf test first (Calibrate…). Until then the case uses 0.33 / 0.26."));
  }
}

// ------------------------------------------------------------------ output options
function renderOutput() {
  const el = $("output");
  el.replaceChildren(h("h3", {}, isStamp() ? "Sheets & notes" : "Engraving & notes"));
  const sw = (label: string, checked: boolean, on: (v: boolean) => void, title = "") => {
    const box = h("input", { type: "checkbox", checked, role: "switch" }) as HTMLInputElement;
    box.onchange = () => on(box.checked);
    return h("label", { class: "row bool-row", title }, h("span", {}, label), h("span", { class: "switch" }, box, h("i")));
  };
  const rest = sw("Cut the rest pieces free", S.options.rest_cuts, (v) => {
    S.options.rest_cuts = v;
    changed(true);
  }, "A last layer (C07, CUT's values) cuts the leftover wood into rectangles once the parts are done. " +
     "In LightBurn, switch that layer's Output off to keep a sheet whole.");
  if (isStamp()) {
    el.append(h("div", { class: "row hint" }, "The maker's mark goes on the top pocket board, next to the logo and the project name."));
    el.append(rest, notesRow());
    return;
  }
  el.append(sw("Maker's mark", S.options.mark.enabled, (v) => {
    S.options.mark.enabled = v;
    changed(true);
  }, "SG + month + year of the cut, on the bottom, LINE layer"));
  const mark = h("input", { type: "text", value: S.options.mark.text ?? "", placeholder: S.build?.mark ?? "SG1026", spellcheck: "false" }) as HTMLInputElement;
  mark.onchange = () => {
    S.options.mark.text = mark.value.trim() || null;
    changed(true);
  };
  const where = S.options.mark.part != null && S.build?.parts[S.options.mark.part]
    ? `on ${S.build.parts[S.options.mark.part].name}` : "on the bottom";
  el.append(h("div", { class: "row" }, h("div", { class: "row-head" }, h("label", {}, "Mark text"), h("span", { class: "hint" }, where)), mark));
  el.append(sw("Engrave part labels", S.options.labels_engrave, (v) => {
    S.options.labels_engrave = v;
    changed(true);
  }, "Off: labels only on the T1 tool layer (shown, never cut). On: engraved on LINE."));
  el.append(rest, notesRow());
}

function notesRow() {
  const notes = h("textarea", { rows: 3, placeholder: "Notes for next time (fit, glue, what you'd change)" }) as HTMLTextAreaElement;
  notes.value = S.notes;
  notes.oninput = () => {
    S.notes = notes.value;
    S.dirty = true;
  };
  return h("div", { class: "row text-row" }, h("label", {}, "Notes"), notes);
}

// ------------------------------------------------------------------ parameters
async function schema(gen: string): Promise<Group[]> {
  if (!S.schemas.has(gen)) {
    const r = await py.call("schema", { generator: gen });
    if (!r.ok) throw new Error(r.error);
    S.schemas.set(gen, r.groups);
  }
  return S.schemas.get(gen)!;
}

function defaults(groups: Group[]): Record<string, any> {
  const out: Record<string, any> = {};
  for (const g of groups) for (const p of g.params) out[p.name] = p.default;
  return out;
}

function renderParamPanel() {
  if (isStamp()) {
    sc.renderPanel($("params"), stampHost, editor);
    return;
  }
  const groups = S.schemas.get(S.generator);
  if (!groups) return;
  renderParams($("params"), groups, S.params, (name, value, final) => {
    S.params[name] = value;
    changed(final);
  }, S.openAdvanced);
}

// ------------------------------------------------------------------ build
let pendingTimer = 0;
let pendingFinal = false;
/** final = false while a slider is held: a draft build (the mark keeps its spot, no overlap check) - the
 *  slider's release sends final = true for the full build. Throttled, not debounced: a drag fires every ~16 ms,
 *  and a debounce kept restarting, so nothing updated until the mouse stopped. A build already on its way
 *  reads the newest values when it starts; py.latest drops builds a newer one has overtaken. */
function changed(final: boolean) {
  S.dirty = true;
  if (final) remember();
  pendingFinal ||= final;
  if (pendingTimer && !final) return;
  clearTimeout(pendingTimer);
  pendingTimer = window.setTimeout(() => {
    pendingTimer = 0;
    const f = pendingFinal;
    pendingFinal = false;
    rebuild(f);
  }, final ? 0 : 16);
}

function request(layout: Placement[] | null) {
  return {
    generator: S.generator, params: S.params, material: material(), sheet: S.sheet,
    layout, options: S.options, name: S.name, faces: S.faces, boards: S.boards,
  };
}

async function rebuild(final = true) {
  S.busy++;
  setStatus("Building…");
  const kept = S.placements.filter((p) => S.manual.has(p.part));
  const b = await py.latest<Build>("build", "build", { ...request(kept.length ? kept : null), draft: !final }, true);
  S.busy--;
  setStatus("Ready");
  if (!b) return; // superseded by a newer slider value
  if (!b.ok) {
    showMessages([`⚠ ${b.error}`], true);
    return;
  }
  S.build = b;
  S.placements = b.placements;
  if (b.info.layout != null && b.info.layout !== S.params.layout) {
    // TrayLayout: Python keeps the wall grid in step with the column/row sizes
    S.params.layout = b.info.layout;
    const ta = document.querySelector<HTMLTextAreaElement>("#params textarea");
    if (ta && document.activeElement !== ta) ta.value = b.info.layout;
  }
  // a hand-placed part stays hand-placed only if Python kept it exactly where it was
  const keptBy = new Map(kept.map((k) => [k.part, k]));
  S.manual = new Set(b.placements.filter((p) => {
    const k = keptBy.get(p.part);
    return k && k.x === p.x && k.y === p.y && k.rot === p.rot && k.sheet === p.sheet;
  }).map((p) => p.part));
  sheetView.show(b, S.sheet, S.placements, S.options.rest_cuts);
  if (!isStamp()) faceEditor.update();
  if (isStamp() && b.stampcase) {
    editor.update();
    if ($("params").contains(document.activeElement)) sc.renderCheck($("params"), stampHost, editor);
    else renderParamPanel();
  }
  updateMessages();
  renderOutputHint();
  view3dStale = true;
  buildIsDraft = !final;
  show3D();
}

function renderOutputHint() {
  const mark = document.querySelector<HTMLInputElement>("#output input[type=text]");
  if (mark && S.build) mark.placeholder = S.build.mark;
}

function showMessages(list: string[], bad = false) {
  const el = $("messages");
  el.replaceChildren(...list.map((t) => h("span", { class: bad || t.startsWith("⚠") ? "msg-bad" : "msg-warn" }, t)));
}

function updateMessages() {
  const b = S.build;
  if (!b) return;
  const out: string[] = [...b.warnings.map((w) => "⚠ " + w)];
  const bad = problems(b.parts, S.placements, S.sheet);
  if (bad.size) out.push(`⚠ ${bad.size} part${bad.size > 1 ? "s break" : " breaks"} the sheet rules (red) - move them or Re-pack`);
  if (S.fileVersion && S.fileVersion !== S.boxesVersion) {
    out.push(`This box was made with boxes.py ${S.fileVersion}, this app has ${S.boxesVersion}: check the parts before cutting`);
  }
  const n = Math.max(0, ...S.placements.map((p) => p.sheet + 1));
  if (!out.length) out.push(`${b.parts.length} parts on ${n} sheet${n === 1 ? "" : "s"} · ${b.title}`);
  showMessages(out);
}

// ------------------------------------------------------------------ undo / redo (every type, .grill/stamp-case-merge.md)
// A snapshot is the box's own state: parameters, hand-placed parts, options. remember() runs on every finished
// change (a slider's release, a sheet drag, an editor edit), so a whole slider drag is one step. Opening or
// starting a box clears it.
const H = { undo: [] as string[], redo: [] as string[], last: "" };

function snapshot() {
  return JSON.stringify({ params: S.params, layout: S.placements.filter((p) => S.manual.has(p.part)), options: S.options,
    faces: S.faces, boards: S.boards });
}

function remember() {
  const now = snapshot();
  if (now === H.last) return;
  if (H.last) H.undo.push(H.last);
  if (H.undo.length > 200) H.undo.shift();
  H.redo = [];
  H.last = now;
}

function resetHistory() {
  H.undo = [];
  H.redo = [];
  H.last = snapshot();
}

function restore(snap: string) {
  const o = JSON.parse(snap);
  S.params = o.params;
  S.placements = o.layout;
  S.manual = new Set(o.layout.map((p: Placement) => p.part));
  S.options = o.options;
  S.faces = o.faces ?? {};
  S.boards = o.boards ?? {};
  H.last = snap;
  S.dirty = true;
  renderParamPanel();
  renderOutput();
  if (!isStamp()) faceEditor.update();     // the tabs' counts at once; the faces' drawing follows the build
  rebuild(true);
}

function undo() {
  const prev = H.undo.pop();
  if (!prev) return toast("Nothing to undo.");
  H.redo.push(H.last);
  restore(prev);
}

function redo() {
  const next = H.redo.pop();
  if (!next) return toast("Nothing to redo.");
  H.undo.push(H.last);
  restore(next);
}

// ------------------------------------------------------------------ the stamp case (src/stampcase.ts)
const stampHost: sc.StampHost = {
  params: () => S.params as Case,
  build: () => S.build,
  commit(next, select) {
    S.params = next as unknown as Record<string, any>;
    if (select) editor.select(select);
    renderParamPanel();
    changed(true);
  },
  async op(op, extra = {}) {
    S.busy++;
    setStatus(op === "repack" ? "Packing the stamps…" : "Placing…");
    const r = await py.call("stampcase_op", { generator: sc.GENERATOR, params: S.params, material: material(), op, ...extra });
    S.busy--;
    setStatus("Ready");
    if (!r.ok) {
      toast(r.error ?? "That didn't work", true);
      return null;
    }
    stampHost.commit(r.params, r.select);
    return r.select as string[];
  },
  toast,
  showSheets(on) {
    $("sheets").hidden = $("sheet-tools").hidden = !on;
    if (!on) $("inspector").hidden = true;
    if (on) sheetView.fit();
  },
};

const editor = new sc.BoardEditor($("board-tabs"), $("board-tools"), $("board"), $("board-bar"), stampHost);

// ------------------------------------------------------------------ face editor (every type but the stamp case)
const faceEditor = new FaceEditor($("face-tabs"), $("face-tools"), $("face"), $("face-bar"), {
  build: () => S.build,
  faces: () => S.faces,
  boards: () => S.boards,
  setBoard(role, mm) {
    S.boards = { ...S.boards };
    if (mm == null) delete S.boards[role];
    else S.boards[role] = mm;
    changed(true);
  },
  commit(faces) {
    S.faces = faces;
    changed(true);
  },
  refresh: () => void rebuild(true),
  showSheets: (on) => stampHost.showSheets(on),
});

// ------------------------------------------------------------------ sheets view
const sheetView = new SheetView($("sheets"), {
  change(placements, moved) {
    S.placements = placements;
    moved.forEach((i) => S.manual.add(i));
    S.dirty = true;
    remember();
    updateMessages();
  },
  select(i) {
    renderInspector(i);
  },
});

function renderInspector(i: number | null) {
  const el = $("inspector");
  if (i == null || !S.build) {
    el.hidden = true;
    return;
  }
  const p = S.build.parts[i];
  const pl = S.placements.find((q) => q.part === i);
  el.hidden = false;
  const markHere = h("button", { title: "Put the maker's mark on this part" }, "Mark here");
  markHere.onclick = () => {
    S.options.mark.part = i;
    changed(true);
    renderOutput();
  };
  el.replaceChildren(
    h("b", {}, p.name),
    h("span", {}, `${p.w.toFixed(1)} × ${p.h.toFixed(1)} mm`),
    h("span", {}, pl ? `sheet ${pl.sheet + 1} · ${pl.rot}° · x ${pl.x.toFixed(1)} y ${pl.y.toFixed(1)}` : ""),
    markHere,
  );
}

// ------------------------------------------------------------------ config
function config(): BoxConfig {
  const m = material();
  return {
    app: "superboxespy", version: 1, name: S.name, generator: S.generator, boxes_version: S.boxesVersion,
    params: { ...S.params },
    material: isStamp() && m.kerf_x != null
      ? { key: m.key, thickness: m.thickness, fit: S.fit, burn: (m.kerf_x + m.kerf_y!) / 4, burn_x: m.kerf_x / 2,
          burn_y: m.kerf_y! / 2, kerf_x: m.kerf_x, kerf_y: m.kerf_y }
      : { key: m.key, thickness: m.thickness, fit: S.fit, burn: m.burn,
          ...(m.burn_x != null ? { burn_x: m.burn_x, burn_y: m.burn_y } : {}) },
    sheet: S.sheet,
    layout: S.manual.size ? S.placements : null,
    options: S.options, ...(Object.keys(S.faces).length ? { faces: S.faces } : {}),
    ...(Object.keys(S.boards).length ? { boards: S.boards } : {}), notes: S.notes,
    saved: new Date().toISOString(),
  };
}

async function load(c: BoxConfig, useProfile = false, home: string | null = null) {
  const groups = await schema(c.generator);
  S.home = home;
  S.generator = c.generator;
  S.name = c.name || c.generator.toLowerCase();
  S.params = isStamp() ? sc.normalise(c.params) as unknown as Record<string, any> : { ...defaults(groups), ...c.params };
  S.materialKey = mats.get(c.material?.key ?? "poplar3.6").key;
  S.fit = c.material?.fit ?? "press";
  // a saved box keeps the burns it was made with; the side panel offers to switch to the current profile
  const prof = mats.compensation(mats.get(S.materialKey), S.fit);
  const cm = c.material;
  const fx = cm ? cm.burn_x ?? cm.burn : prof.bx;
  const fy = cm ? cm.burn_y ?? cm.burn : prof.by;
  S.compOverride = !isStamp() && !useProfile && cm && (Math.abs(fx - prof.bx) > 1e-6 || Math.abs(fy - prof.by) > 1e-6)
    ? { burn: cm.burn, bx: fx, by: fy } : null;
  // a stamp case takes kerf / 2 and no fit: only its kerf counts
  const pk = mats.get(S.materialKey);
  S.kerfOverride = isStamp() && !useProfile && cm?.kerf_x != null && cm.kerf_y != null &&
    (Math.abs(cm.kerf_x - (pk.kerfX ?? NaN)) > 1e-6 || Math.abs(cm.kerf_y - (pk.kerfY ?? NaN)) > 1e-6)
    ? { x: cm.kerf_x, y: cm.kerf_y } : null;
  S.thicknessOverride = !useProfile && cm && Math.abs(cm.thickness - mats.get(S.materialKey).thickness) > 1e-6
    ? cm.thickness : null;
  S.sheet = c.sheet ?? A3;
  const o = c.options as Partial<Options> | undefined;   // older files may lack fields
  S.options = {
    labels_engrave: o?.labels_engrave ?? false, mark: { enabled: true, text: null, part: null, ...(o?.mark ?? {}) },
    rest_cuts: o?.rest_cuts ?? true,
  };
  S.notes = c.notes ?? "";
  S.faces = isStamp() ? {} : structuredClone(c.faces ?? {});
  S.boards = isStamp() ? {} : { ...(c.boards ?? {}) };
  S.placements = c.layout ?? [];
  S.manual = new Set((c.layout ?? []).map((p) => p.part));
  S.fileVersion = isStamp() ? null : c.boxes_version ?? null;   // boxes.py doesn't make stamp cases
  S.dirty = false;
  editor.selected.clear();
  faceEditor.setActive(!isStamp());     // the one switched off lets go of the 2D half; the one on decides what shows
  editor.setActive(isStamp());
  resetHistory();
  setGenLabel();
  ($("name") as HTMLInputElement).value = S.name;
  showHome();
  renderMaterial();
  renderParamPanel();
  renderOutput();
  await rebuild();
}

async function newBox(gen: string, name?: string, params: Record<string, any> = {}) {
  const groups = await schema(gen);
  if (isStamp(gen) && !Object.keys(params).length) params = structuredClone(sc.DEFAULT_CASE);
  await load({
    app: "superboxespy", version: 1, name: name ?? gen.toLowerCase(), generator: gen, boxes_version: S.boxesVersion,
    params: { ...defaults(groups), ...params },
    material: { key: S.materialKey, thickness: profile().thickness, fit: S.fit, burn: material().burn },
    sheet: S.sheet, layout: null, options: { labels_engrave: false, mark: { enabled: true, text: null, part: null }, rest_cuts: true },
    notes: "", saved: "",
  }, true);
}

async function saveBox() {
  const c = config();
  const name = files.safeName(S.name);
  if (S.home) {                    // beside its own file, wherever that is
    const r = await files.writeBeside(S.home, [{ name: name + files.BOX_EXT, content: cfg.toJSON(c) }]);
    if (!r.ok) {
      toast(`Couldn't save beside ${S.home}: ${r.error}`, true, 9000);
      return;
    }
    S.home = files.homeFor(S.home, name);
    showHome();
    cfg.remember(c, S.home);
    S.dirty = false;
    toast(`Saved ${S.home}.`);
    return;
  }
  const where = await files.save(name, name + files.BOX_EXT, [{ name: name + files.BOX_EXT, content: cfg.toJSON(c) }]);
  cfg.remember(c);
  S.dirty = false;
  toast(`${where}.`);
}

/** Save as...: Windows' Save As dialog (serve.py); the box then lives there, its exports beside it. */
async function saveAs() {
  if (!(await files.canUseHome())) {
    await saveBox();
    return;
  }
  const start = S.home ? files.dirOf(S.home) : files.folderPath();
  const r = await files.askSaveAs(files.safeName(S.name) + files.BOX_EXT, start);
  if (!r.ok) {
    if (!r.cancelled) toast(`Not saved: ${r.error}`, true, 9000);
    return;
  }
  S.home = r.path;
  S.name = files.boxNameOf(r.path);
  ($("name") as HTMLInputElement).value = S.name;
  await saveBox();
}

async function openBox() {
  if (await files.canUseHome()) {
    const r = await files.askOpen(S.home ? files.dirOf(S.home) : files.folderPath());
    if (r.ok) await openHome(r.path, r.text);
    else if (!r.cancelled) toast(`Couldn't open it: ${r.error}`, true, 9000);
    return;
  }
  const f = await files.openFile(".sbox,.json,application/json");
  if (!f) return;
  try {
    await load(cfg.parse(f.text));
    cfg.remember(config());
    toast(`Opened ${f.name}`);
  } catch (e) {
    toast(`Couldn't open ${f.name}: ${(e as Error).message}`, true);
  }
}

/** Open the box file at `path` (read through serve.py unless `text` is given): it keeps its files beside it. */
async function openHome(path: string, text?: string): Promise<boolean> {
  if (text == null) {
    const r = await files.readHome(path);
    if (!r.ok) {
      toast(`Couldn't open ${path}: ${r.error}`, true, 9000);
      return false;
    }
    text = r.text;
  }
  try {
    await load(cfg.parse(text), false, path);
  } catch (e) {
    toast(`Couldn't open ${path}: ${(e as Error).message}`, true, 9000);
    return false;
  }
  cfg.remember(config(), path);
  toast(`Opened ${path}.\nSave and the exports go beside it.`);
  return true;
}

/** The chip beside the box name: where Save and the exports go - the folder of the box's own file, else the
 *  picked folder (<folder>/<box name>/). Without either, files are downloaded and there's no chip. */
function showHome() {
  const el = $("home");
  const save = $("btn-save");
  const folder = files.folderName();
  el.hidden = !S.home && !folder;
  if (S.home) {
    const dir = files.dirOf(S.home);
    el.textContent = files.fileOf(dir) || dir;
    el.title = `${S.home}\nSave and the exports go into this folder.`;
    save.title = `Save to ${S.home} (Ctrl+S)`;
  } else if (folder) {
    el.textContent = folder;
    el.title = `Save and the exports go to ${folder}/<box name>/ (File ▾ changes the folder)`;
    save.title = `Save to ${folder}/<box name>/ (Ctrl+S)`;
  } else {
    save.title = "Save the box (Ctrl+S): downloaded, until a folder is picked under File ▾";
  }
}

async function share() {
  const link = await cfg.shareLink(config());
  try {
    await navigator.clipboard.writeText(link);
    toast("Link copied - it holds the whole box, layout included.");
  } catch {
    prompt("Copy this link:", link);
  }
}

// ------------------------------------------------------------------ export
/** Export: one .lbrn2 project with a page per sheet ("lbrn2") or one .svg per sheet. open: write the project into
 *  the folder (picking one first if needed) and open it in LightBurn. */
async function exportFiles(kind: "lbrn2" | "svg", open = false) {
  if (!S.build) return;
  const bad = problems(S.build.parts, S.placements, S.sheet);
  if (bad.size) {
    toast("Some parts break the sheet rules (shown red). Move them or Re-pack first.", true);
    return;
  }
  if (open && !S.home && !files.folderName()) {
    if (!files.canPickFolder()) {
      toast("Open in LightBurn writes the project into a folder, and this browser can't write into folders.\n" +
        "Use Chrome or Edge (in Brave: enable brave://flags/#file-system-access-api), or File ▾ › LightBurn file only.", true, 9000);
      return;
    }
    toast("Pick the folder the LightBurn files go to (e.g. C:\\Projects\\Laser lightburn).");
    if (!(await pickFolder())) return;
  }
  S.busy++;
  setStatus("Writing files…");
  const name = files.safeName(S.name);
  // beside the box's own file, else <picked folder>/<box name>/, else downloads
  const place = S.home ? files.besideHome(S.home) : files.folderName() ? files.inFolder(name) : null;
  // carry over layer settings the user changed in LightBurn (eVlaser rule: a rebuild never wipes them)
  let previous: string | null = null;
  let stale: string[] = [];
  if (kind === "lbrn2" && place) {
    const here = await place.list();
    previous = await place.saved([`${name}.lbrn2`, `${name}_backup.lbrn2`]);
    // before pages there was one NN_<name>.lbrn2 per sheet: their saved layers count until the project exists
    const literal = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`^\\d\\d_${literal}(_backup)?\\.lbrn2$`);
    const old = here.filter((n) => re.test(n));
    if (!previous && !here.includes(`${name}.lbrn2`)) previous = await place.saved(old);
    // stampcaser wrote one "<name> N <board>.lbrn2" per board
    const boards = new RegExp(`^${literal} \\d [^.]+\\.lbrn2$`);
    stale = [...old.filter((n) => !n.includes("_backup.")), ...here.filter((n) => boards.test(n))];
  }
  const r = await py.call<ExportResult>("export", { ...request(S.placements), previous });
  S.busy--;
  setStatus("Ready");
  if (!r.ok) {
    toast(r.error ?? "Export failed", true, 8000);
    return;
  }
  const out = r.files.filter((f) => f.kind === kind)
    .map((f) => ({ ...f, name: f.kind === "lbrn2" ? `${name}.lbrn2` : f.name.replace(/^(\d\d)_[^.]*/, `$1_${name}`) }));
  const withBox = place ? [...out, { name: name + files.BOX_EXT, content: cfg.toJSON(config()) }] : out;
  let where: string;
  if (place) {
    const dir = await place.write(withBox);
    if (!dir) {
      toast(S.home ? `Couldn't write beside ${S.home}.` :
        "Couldn't write into the folder: the browser has no permission. Pick it again under File ▾.", true, 9000);
      return;
    }
    where = `Saved ${withBox.map((f) => f.name).join(", ")} to ${dir}`;
    if (S.home) {
      S.home = files.homeFor(S.home, name);
      showHome();
    }
    cfg.remember(config(), S.home);
  } else {
    where = await files.save(name, `${name}_${kind}.zip`, withBox);
  }
  let opened = "";
  let failed = false;
  if (open) {
    setStatus("Opening LightBurn…");
    const o = await place!.open(out[0].name, out[0].content);
    setStatus("Ready");
    opened = o.ok ? `\nOpened ${o.path} in LightBurn.` : o.cancelled ? "\nNot opened in LightBurn." : `\nNot opened: ${o.error}`;
    failed = !o.ok && !o.cancelled;
  }
  const n = r.sheets.length;
  const times = r.sheets.map((s, i) =>
    `${n > 1 ? `sheet ${i + 1}` : "the sheet"}: ~${Object.values(s.minutes).reduce((a, b) => a + b, 0).toFixed(1)} min`).join(", ");
  toast(`${where}.` + opened +
    (kind === "lbrn2" && n > 1 ? `\n${n} sheets, one page each in LightBurn.` : "") +
    (times ? `\nEstimated ${times}.` : "") +
    (r.kept && kind === "lbrn2" ? "\nKept your LightBurn layer settings." : "") +
    (stale.length ? `\nThe old files ${stale.join(", ")} are still in the folder: delete them so they don't get cut.` : "") +
    (kind === "lbrn2" ? "\nIf LightBurn already had it open: reopen it, or you'll cut the old geometry." : ""), failed, 10000);
}

// ------------------------------------------------------------------ tabs, sheets | 3D split
type View3D = { update(b: Build, gen: string, m: ReturnType<typeof material>, draft?: boolean): void; resize(): void };
let view3d: View3D | null = null;
let view3dLoading: Promise<void> | null = null;
let view3dStale = true;          // a build the 3D hasn't shown yet (it was hidden)
let buildIsDraft = false;        // S.build came from a slider that's still held

function view3dShown() {
  return !$("split").closest<HTMLElement>(".pane")!.hidden && !$("split").classList.contains("max-sheets");
}

/** Hand the latest build to the 3D, if it can be seen; a hidden 3D catches up when it's shown again. */
async function show3D() {
  if (!S.build || !view3dShown()) return;
  if (!view3d) {
    view3dLoading ??= import("./view3d").then((mod) => {
      view3d = mod.createView3D($("view3d"), $("view3d-controls"), () => request(null));
    });
    await view3dLoading;
  }
  if (!view3dStale) return;
  view3dStale = false;
  view3d!.update(S.build!, S.generator, material(), buildIsDraft);
}

/** The work area: the box (2D | 3D), or the calibration, which opens from the Material section until Back. */
function tab(name: "box" | "calib") {
  document.querySelectorAll<HTMLElement>(".pane").forEach((p) => (p.hidden = p.dataset.pane !== name));
  if (name === "box") {
    sheetView.fit();
    show3D();
  } else {
    renderCalib();
    $("calib-back").focus({ preventScroll: true });
  }
}

/** The sheets' toolbar. */
function renderSheetTools() {
  const zoom = (k: number) =>
    sheetView.setZoom(Number(getComputedStyle(document.documentElement).getPropertyValue("--sheet-zoom") || 1) * k);
  fillToolbar($("sheet-tools"), [
    btn("Re-pack", "Forget hand-placed parts and pack again", () => {
      S.manual.clear();
      S.placements = [];
      changed(true);
    }),
    btn("−", "Zoom out (Ctrl+wheel)", () => zoom(1 / 1.2), "zoom-btn"),
    btn("+", "Zoom in (Ctrl+wheel)", () => zoom(1.2), "zoom-btn"),
  ], [helpButton((b) => helpCard(b, "Sheets", [
    ["Drag", "move a part, onto another sheet too"],
    ["R", "rotate the selected part"],
    ["Arrows", "nudge 1 mm (Shift: 10 mm)"],
    ["PgUp / PgDn", "to the sheet before / after"],
    ["Ctrl+wheel", "zoom"],
    ["Double-click", "empty space: the sheets fill the view (again: split)"],
    ["Esc", "deselect"],
    ["Ctrl+Z / Ctrl+Y", "undo / redo"],
  ], [
    "Red: closer than 1.5 mm to another part or 3 mm to the edge, or above the 390 mm reach line. It blocks the export.",
    "Magenta dashes: the cuts that free the rest pieces (Cut the rest pieces free, in the side panel).",
    "Re-pack forgets the parts you placed by hand. Mark here (a part's bar) moves the maker's mark onto that part.",
  ]))]);
}

const SPLIT_KEY = "superboxes.split";

/** The divider between sheets and 3D: drag or arrow keys; where it sits is remembered. Double-click on the
 *  sheets' empty space or on the 3D makes that half fill the view, again to split. */
function wireSplit() {
  const split = $("split");
  const divider = $("divider");
  const set = (f: number) => {
    f = Math.min(0.8, Math.max(0.2, f));
    split.style.setProperty("--split", `${(f * 100).toFixed(1)}%`);
    try {
      localStorage.setItem(SPLIT_KEY, String(f));
    } catch {
      /* not remembered */
    }
    return f;
  };
  let frac = 0.5;
  try {
    frac = Number(localStorage.getItem(SPLIT_KEY)) || 0.5;
  } catch {
    /* default */
  }
  frac = set(frac);
  const vertical = () => getComputedStyle(split).flexDirection === "column";
  divider.onpointerdown = (e) => {
    e.preventDefault();
    divider.setPointerCapture(e.pointerId);
    divider.classList.add("dragging");
    const r = split.getBoundingClientRect();
    divider.onpointermove = (m) => {
      frac = set(vertical() ? (m.clientY - r.top) / r.height : (m.clientX - r.left) / r.width);
    };
    divider.onpointerup = () => {
      divider.classList.remove("dragging");
      divider.onpointermove = divider.onpointerup = null;
    };
  };
  divider.onkeydown = (e) => {
    const step = { ArrowLeft: -0.05, ArrowUp: -0.05, ArrowRight: 0.05, ArrowDown: 0.05 }[e.key];
    if (step) {
      e.preventDefault();
      frac = set(frac + step);
    }
  };
  const toggle = (which: "max-sheets" | "max-3d") => {
    const on = !split.classList.contains("max-sheets") && !split.classList.contains("max-3d");
    split.classList.remove("max-sheets", "max-3d");
    if (on) split.classList.add(which);
    if (!split.classList.contains("max-sheets")) show3D();
  };
  $("sheets").addEventListener("dblclick", (e) => {
    if (!(e.target as Element).closest(".part")) toggle("max-sheets");
  });
  $("view3d").addEventListener("dblclick", () => toggle("max-3d"));
  new ResizeObserver(() => sheetView.fit()).observe($("sheets"));
}

function renderCalib() {
  renderCalibration($("calib"), {
    material: () => profile(),
    sheet: () => S.sheet,
    toast,
    saveFiles: (sub, zip, list) => files.save(sub, zip, list),
    afterUpdate: () => {
      S.compOverride = null;
      renderMaterial();
      changed(true);
      persistMaterials();
    },
  });
}

async function persistMaterials() {
  // a copy of all profiles next to the boxes, so measured fits survive a cleared browser
  if (files.folderName()) {
    await files.writeToFolder(null, [{ name: "materials.json", content: JSON.stringify(mats.all(), null, 2) + "\n" }]);
  }
}

// ------------------------------------------------------------------ box type gallery
function setGenLabel() {
  const b = $("gen");
  const g = S.catalog.find((c) => c.name === S.generator);
  b.replaceChildren(h("b", {}, S.generator), h("span", {}, g ? g.short.split("\n")[0] : ""),
    h("span", { "aria-hidden": "true" }, "▾"));
  b.title = "Pick a box type";
}

/** Each type with its defaults in the current material - what the gallery tiles show. */
async function thumbnailBuild(name: string): Promise<Build | null> {
  const groups = await schema(name);
  let params = name === FIRST_BOX.generator ? { ...defaults(groups), ...FIRST_BOX.params } : defaults(groups);
  if (isStamp(name)) {
    const packed = await py.call("stampcase_op", { generator: name, params: sc.demoCase(), material: material(), op: "repack" });
    if (!packed.ok) return null;
    params = packed.params;
  }
  const r = await py.call<Build>("build", {
    generator: name, params, material: material(), sheet: S.sheet, layout: null,
    options: { labels_engrave: false, mark: { enabled: true, text: null, part: null }, rest_cuts: true },
  });
  return r.ok ? r : null;
}

// ------------------------------------------------------------------ the File menu
let canHome = false;     // serve.py reads and writes beside a box's own file: Save as…, Windows' Open dialog

function newDefault() {
  const first = S.generator === FIRST_BOX.generator;
  return newBox(S.generator, first ? FIRST_BOX.name : undefined, first ? FIRST_BOX.params : {});
}

/** A box from the Recent list: one with a file of its own is read from there, as it may have changed since. */
async function openRecent(r: ReturnType<typeof cfg.recent>[number]) {
  if (r.home && canHome) {
    // boxes saved before 2026-11-07 were .box.json; renamed to .sbox since
    const sbox = r.home.replace(/\.box\.json$/i, files.BOX_EXT);
    if (sbox !== r.home && (await files.readHome(sbox)).ok && (await openHome(sbox))) return;
    if (await openHome(r.home)) return;
  }
  await load(r.config);
}

async function chooseFolder() {
  if (await pickFolder()) toast(`Files now go to ${files.folderName()}/<box name>/`);
}

function fileMenu(): MenuItem[] {
  const recent = cfg.recent();
  const folder = files.folderName();
  const saveAsItem: MenuItem[] = canHome
    ? [{ label: "Save as…", detail: "Ctrl+Shift+S", title: "Save the box somewhere else: it keeps its files beside it", run: saveAs }]
    : [];
  const recentItems: MenuItem[] = recent.length
    ? recent.map((r) => ({
      label: r.name, detail: `${r.generator}${r.saved ? " · " + new Date(r.saved).toLocaleDateString() : ""}`,
      title: r.home ?? "", run: () => void openRecent(r),
    }))
    : [{ note: "No saved boxes yet" }];
  const folderItem: MenuItem = files.canPickFolder()
    ? { label: folder ? `Folder: ${folder}` : "Pick folder…", detail: folder ? "change…" : "",
        title: "The folder boxes and LightBurn files are written to (e.g. C:\\Projects\\Laser lightburn): <folder>/<box name>/",
        run: () => void chooseFolder() }
    : { note: "Files are downloaded: this browser can't write into a folder (in Brave: brave://flags/#file-system-access-api)" };
  return [
    { label: "New", title: "Start over with this box type's defaults", run: () => void newDefault() },
    { label: "Open…", detail: "Ctrl+O", title: "Open a box (.sbox)", run: () => void openBox() },
    ...saveAsItem,
    { label: "Copy share link", title: "Copy a link with the whole box in it", run: () => void share() },
    { heading: "Export" },
    { label: "LightBurn file only", detail: ".lbrn2", title: "Write the LightBurn project (a page per sheet) without opening LightBurn",
      run: () => void exportFiles("lbrn2") },
    { label: "SVGs, one per sheet", detail: ".svg", title: "Write one .svg per sheet", run: () => void exportFiles("svg") },
    { heading: "Recent" },
    ...recentItems,
    { sep: true },
    folderItem,
  ];
}

// ------------------------------------------------------------------ wiring

/** Let the user pick the output folder; loads its materials.json. False when cancelled. */
async function pickFolder(): Promise<boolean> {
  const ok = !!(await files.pickFolder());
  if (ok) {
    await loadMaterialsFromFolder();
    renderMaterial();
  }
  showHome();
  return ok;
}

async function loadMaterialsFromFolder() {
  const text = await files.readFromFolder("materials.json");
  if (!text) return;
  try {
    for (const p of JSON.parse(text)) if (p?.key) mats.update(p.key, p);
  } catch {
    /* ignore a broken file */
  }
}

function wire() {
  createGallery($("gen") as HTMLButtonElement, {
    catalog: S.catalog,
    current: () => S.generator,
    thickness: () => material().thickness,
    build: thumbnailBuild,
    pick: async (name) => {
      if (name === S.generator) return;
      if (S.dirty && !confirm("Switch box type? Unsaved changes to this box are lost.")) return;
      await newBox(name);
    },
  });
  setGenLabel();
  const name = $("name") as HTMLInputElement;
  name.value = S.name;
  name.onchange = () => {
    S.name = name.value.trim() || S.generator.toLowerCase();
    S.dirty = true;
  };
  $("btn-file").onclick = () => menu($("btn-file"), fileMenu());
  $("btn-save").onclick = saveBox;
  files.canUseHome().then((ok) => (canHome = ok));
  $("btn-open-lbrn").onclick = () => exportFiles("lbrn2", true);
  renderSheetTools();
  $("calib-back").onclick = () => tab("box");
  document.addEventListener("keydown", (e) => {
    const ctrl = e.ctrlKey || e.metaKey;
    const k = e.key.toLowerCase();
    if (ctrl && k === "s") {
      e.preventDefault();
      (e.shiftKey ? saveAs : saveBox)();
      return;
    }
    if (ctrl && k === "o" && !e.shiftKey) {
      e.preventDefault();
      openBox();
      return;
    }
    const typing = (e.target as HTMLElement).closest("input, textarea, select");
    if (typing) return;                          // text fields keep their own keys, undo included
    if (!$("calib").closest<HTMLElement>(".pane")!.hidden) {
      if (e.key === "Escape") tab("box");          // the calibration's keys: Esc goes back to the box
      return;
    }
    if (e.key === "?" && !ctrl) {                  // the ? card of the 2D view shown
      const help = [...document.querySelectorAll<HTMLElement>(".half-sheets .toolbar .help-btn")].find((b) => b.offsetParent);
      if (help) {
        e.preventDefault();
        help.click();
        return;
      }
    }
    if (ctrl && (k === "z" || k === "y")) {
      e.preventDefault();
      (k === "y" || e.shiftKey ? redo : undo)();
      return;
    }
    if (isStamp() && !$("board").hidden && !(e.target as HTMLElement).closest(".sheets, .gallery, .menu")) {
      if (editor.key(k, e)) e.preventDefault();
    }
    if (faceEditor.face && !(e.target as HTMLElement).closest(".sheets, .gallery, .menu")) {
      if (faceEditor.key(e)) e.preventDefault();
    }
  });
  wireSplit();
  window.addEventListener("beforeunload", (e) => {
    if (S.dirty) e.preventDefault();
  });
  mats.onChange(() => renderMaterial());
  window.addEventListener("hashchange", openFromHash);
}

async function openFromHash(): Promise<boolean> {
  const m = location.hash.match(/^#open=(.+)$/);
  if (m) {                         // serve.py handed over a box file: a double-clicked .sbox
    history.replaceState(null, "", location.pathname + location.search);
    const path = decodeURIComponent(m[1]);
    if (S.dirty && !confirm(`Open ${path}? Unsaved changes to this box are lost.`)) return false;
    return openHome(path);
  }
  const c = await cfg.fromHash();
  if (!c) return false;
  if (S.dirty && !confirm(`Open "${c.name}" from the link? Unsaved changes to this box are lost.`)) return false;
  await load(c);
  toast(`Opened "${c.name}" from the link.`);
  history.replaceState(null, "", location.pathname + location.search);
  return true;
}

async function main() {
  py.onStatus((t) => setStatus(t === "ready" ? "Ready" : t));
  const cat = await py.call("catalog");
  if (!cat.ok) {
    setStatus("Python failed to start: " + cat.error);
    return;
  }
  S.catalog = cat.generators;
  S.boxesVersion = cat.boxes_version;
  await files.restoreFolder();
  wire();
  showHome();
  if (files.folderName()) loadMaterialsFromFolder().then(renderMaterial).catch(() => {});
  tab("box");
  if (!(await openFromHash())) await newBox(FIRST_BOX.generator, FIRST_BOX.name, FIRST_BOX.params);
}

main();
