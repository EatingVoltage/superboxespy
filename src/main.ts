import * as py from "./py";
import * as files from "./files";
import * as cfg from "./config";
import * as mats from "./materials";
import { renderParams, h } from "./params";
import { SheetView, problems } from "./sheetview";
import { renderCalibration } from "./calibration";
import { createGallery } from "./gallery";
import { A3 } from "./types";
import type { BoxConfig, Build, Fit, Group, Options, OutFile, Placement, Sheet } from "./types";

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
  sheet: A3 as Sheet,
  options: { labels_engrave: false, mark: { enabled: true, text: null, part: null } } as Options,
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

function menu(anchor: HTMLElement, items: { label: string; run: () => void }[], empty = "Nothing here yet") {
  const m = $("menu");
  m.replaceChildren();
  if (!items.length) m.append(h("div", { class: "empty" }, empty));
  for (const it of items) {
    const b = h("button", {}, it.label);
    b.onclick = () => {
      m.hidden = true;
      it.run();
    };
    m.append(b);
  }
  const r = anchor.getBoundingClientRect();
  m.style.left = `${Math.min(r.left, innerWidth - 260)}px`;
  m.style.top = `${r.bottom + 4}px`;
  m.hidden = false;
  setTimeout(() => document.addEventListener("click", () => (m.hidden = true), { once: true }), 0);
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
  return {
    key: p.key, thickness: t, burn, fit: S.fit, status: c.status, fit_note: note,
    ...(axis ? { burn_x: bx, burn_y: by } : {}),
  };
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
    S.compOverride = S.thicknessOverride = null;
    changed(true);
    renderMaterial();
  };
  el.append(h("div", { class: "row" }, sel));
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
      "Burn ", h("b", {}, burnText), " ", chip)));
  if (S.compOverride || S.thicknessOverride != null) {
    const use = h("button", {}, "Use the material profile instead");
    use.onclick = () => {
      S.compOverride = S.thicknessOverride = null;
      changed(true);
      renderMaterial();
    };
    el.append(h("div", { class: "notice" }, "This box was saved with other material values than your current profile. ", use));
  } else if (m.status === "default") {
    const go = h("button", {}, "Open calibration");
    go.onclick = () => tab("calib");
    el.append(h("div", { class: "notice" }, "Burn 0.10 is boxes.py's default, never measured on your Falcon2. Cut the calibration sheets before cutting boxes you care about. ", go));
  }
}

// ------------------------------------------------------------------ output options
function renderOutput() {
  const el = $("output");
  el.replaceChildren(h("h3", {}, "Engraving & notes"));
  const sw = (label: string, checked: boolean, on: (v: boolean) => void, title = "") => {
    const box = h("input", { type: "checkbox", checked, role: "switch" }) as HTMLInputElement;
    box.onchange = () => on(box.checked);
    return h("label", { class: "row bool-row", title }, h("span", {}, label), h("span", { class: "switch" }, box, h("i")));
  };
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
  const notes = h("textarea", { rows: 3, placeholder: "Notes for next time (fit, glue, what you'd change)" }) as HTMLTextAreaElement;
  notes.value = S.notes;
  notes.oninput = () => {
    S.notes = notes.value;
    S.dirty = true;
  };
  el.append(h("div", { class: "row text-row" }, h("label", {}, "Notes"), notes));
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
    layout, options: S.options, name: S.name,
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
  sheetView.show(b, S.sheet, S.placements);
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

// ------------------------------------------------------------------ sheets view
const sheetView = new SheetView($("sheets"), {
  change(placements, moved) {
    S.placements = placements;
    moved.forEach((i) => S.manual.add(i));
    S.dirty = true;
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
    h("span", { class: "hint" }, "drag · R rotate · arrows nudge (Shift ×10) · PgUp/PgDn sheet"),
  );
}

// ------------------------------------------------------------------ config
function config(): BoxConfig {
  const m = material();
  return {
    app: "superboxespy", version: 1, name: S.name, generator: S.generator, boxes_version: S.boxesVersion,
    params: { ...S.params },
    material: { key: m.key, thickness: m.thickness, fit: S.fit, burn: m.burn,
                ...(m.burn_x != null ? { burn_x: m.burn_x, burn_y: m.burn_y } : {}) },
    sheet: S.sheet,
    layout: S.manual.size ? S.placements : null,
    options: S.options, notes: S.notes, saved: new Date().toISOString(),
  };
}

async function load(c: BoxConfig, useProfile = false) {
  const groups = await schema(c.generator);
  S.generator = c.generator;
  S.name = c.name || c.generator.toLowerCase();
  S.params = { ...defaults(groups), ...c.params };
  S.materialKey = mats.get(c.material?.key ?? "poplar3.6").key;
  S.fit = c.material?.fit ?? "press";
  // a saved box keeps the burns it was made with; the side panel offers to switch to the current profile
  const prof = mats.compensation(mats.get(S.materialKey), S.fit);
  const cm = c.material;
  const fx = cm ? cm.burn_x ?? cm.burn : prof.bx;
  const fy = cm ? cm.burn_y ?? cm.burn : prof.by;
  S.compOverride = !useProfile && cm && (Math.abs(fx - prof.bx) > 1e-6 || Math.abs(fy - prof.by) > 1e-6)
    ? { burn: cm.burn, bx: fx, by: fy } : null;
  S.thicknessOverride = !useProfile && cm && Math.abs(cm.thickness - mats.get(S.materialKey).thickness) > 1e-6
    ? cm.thickness : null;
  S.sheet = c.sheet ?? A3;
  const o = c.options as Partial<Options> | undefined;   // older files may lack fields
  S.options = { labels_engrave: o?.labels_engrave ?? false, mark: { enabled: true, text: null, part: null, ...(o?.mark ?? {}) } };
  S.notes = c.notes ?? "";
  S.placements = c.layout ?? [];
  S.manual = new Set((c.layout ?? []).map((p) => p.part));
  S.fileVersion = c.boxes_version ?? null;
  S.dirty = false;
  setGenLabel();
  ($("name") as HTMLInputElement).value = S.name;
  renderMaterial();
  renderParamPanel();
  renderOutput();
  await rebuild();
}

async function newBox(gen: string, name?: string, params: Record<string, any> = {}) {
  const groups = await schema(gen);
  await load({
    app: "superboxespy", version: 1, name: name ?? gen.toLowerCase(), generator: gen, boxes_version: S.boxesVersion,
    params: { ...defaults(groups), ...params },
    material: { key: S.materialKey, thickness: profile().thickness, fit: S.fit, burn: material().burn },
    sheet: S.sheet, layout: null, options: { labels_engrave: false, mark: { enabled: true, text: null, part: null } },
    notes: "", saved: "",
  }, true);
}

async function saveBox() {
  const c = config();
  const name = files.safeName(S.name);
  const where = await files.save(name, `${name}.box.json`, [{ name: `${name}.box.json`, content: cfg.toJSON(c) }]);
  cfg.remember(c);
  S.dirty = false;
  toast(`${where}.`);
}

async function openBox() {
  const f = await files.openFile(".json,application/json");
  if (!f) return;
  try {
    await load(cfg.parse(f.text));
    cfg.remember(config());
    toast(`Opened ${f.name}`);
  } catch (e) {
    toast(`Couldn't open ${f.name}: ${(e as Error).message}`, true);
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
async function exportFiles(kind: "lbrn2" | "svg") {
  if (!S.build) return;
  const bad = problems(S.build.parts, S.placements, S.sheet);
  if (bad.size) {
    toast("Some parts break the sheet rules (shown red). Move them or Re-pack first.", true);
    return;
  }
  S.busy++;
  setStatus("Writing files…");
  const name = files.safeName(S.name);
  // carry over layer settings the user changed in LightBurn (eVlaser rule: a rebuild never wipes them)
  const previous: Record<number, string> = {};
  if (kind === "lbrn2" && files.folderName()) {
    const n = Math.max(0, ...S.placements.map((q) => q.sheet + 1));
    for (let k = 0; k < n; k++) {
      const nn = String(k + 1).padStart(2, "0");
      const text = await files.lightburnSaved(name, [`${nn}_${name}.lbrn2`, `${nn}_${name}_backup.lbrn2`]);
      if (text) previous[k] = text;
    }
  }
  const r = await py.call<{ ok: boolean; error?: string; files: OutFile[] }>("export", { ...request(S.placements), previous });
  S.busy--;
  setStatus("Ready");
  if (!r.ok) {
    toast(r.error ?? "Export failed", true, 8000);
    return;
  }
  const out = r.files.filter((f) => f.kind === kind).map((f) => ({ ...f, name: f.name.replace(/^(\d\d)_[^.]*/, `$1_${name}`) }));
  const withBox = files.folderName() ? [...out, { name: `${name}.box.json`, content: cfg.toJSON(config()) }] : out;
  const where = await files.save(name, `${name}_${kind}.zip`, withBox);
  if (withBox.length > out.length) cfg.remember(config());
  const times = out.filter((f) => f.minutes).map((f, i) =>
    `sheet ${i + 1}: ~${Object.values(f.minutes!).reduce((a, b) => a + b, 0).toFixed(1)} min`).join(", ");
  toast(`${where}.` +
    (times ? `\nEstimated ${times}.` : "") +
    (Object.keys(previous).length
      ? `\nKept your LightBurn layer settings on sheet ${Object.keys(previous).map((k) => Number(k) + 1).join(", ")}.` : "") +
    (kind === "lbrn2" ? "\nIf LightBurn has them open: reopen, or you'll cut the old geometry." : ""), false, 9000);
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

function tab(name: string) {
  document.querySelectorAll<HTMLButtonElement>("[role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  document.querySelectorAll<HTMLElement>(".pane").forEach((p) => (p.hidden = p.dataset.pane !== name));
  document.querySelectorAll<HTMLElement>(".tab-tools").forEach((t) => (t.hidden = t.dataset.for !== name));
  if (name === "box") {
    sheetView.fit();
    show3D();
  }
  if (name === "calib") renderCalib();
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
  const params = name === FIRST_BOX.generator ? { ...defaults(groups), ...FIRST_BOX.params } : defaults(groups);
  const r = await py.call<Build>("build", {
    generator: name, params, material: material(), sheet: S.sheet, layout: null,
    options: { labels_engrave: false, mark: { enabled: true, text: null, part: null } },
  });
  return r.ok ? r : null;
}

// ------------------------------------------------------------------ wiring
async function setFolderButton() {
  const b = $("btn-folder");
  const n = files.folderName();
  b.textContent = n ?? (files.canPickFolder() ? "Pick folder" : "Downloads");
  b.classList.toggle("set", !!n);
  b.title = n ? `Files go to ${n}/<box name>/ - click to change` :
    files.canPickFolder() ? "Pick the folder boxes and LightBurn files are written to (e.g. C:\\Projects\\Laser lightburn)"
      : "This browser can't write to a folder: files are downloaded. In Brave, enable brave://flags/#file-system-access-api";
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
  $("btn-new").onclick = () => newBox(S.generator, S.generator === FIRST_BOX.generator ? FIRST_BOX.name : undefined,
    S.generator === FIRST_BOX.generator ? FIRST_BOX.params : {});
  $("btn-open").onclick = openBox;
  $("btn-save").onclick = saveBox;
  $("btn-share").onclick = share;
  $("btn-recent").onclick = (e) => {
    e.stopPropagation();
    menu($("btn-recent"), cfg.recent().map((r) => ({
      label: `${r.name} · ${r.generator} · ${r.saved ? new Date(r.saved).toLocaleDateString() : ""}`,
      run: () => load(r.config),
    })), "No saved boxes yet");
  };
  $("btn-folder").onclick = async () => {
    if (!files.canPickFolder()) {
      toast("This browser can't write into a folder, so files are downloaded.\nIn Brave: enable brave://flags/#file-system-access-api (or use Chrome/Edge).", false, 9000);
      return;
    }
    if (await files.pickFolder()) {
      await loadMaterialsFromFolder();
      renderMaterial();
      toast(`Files now go to ${files.folderName()}/<box name>/`);
    }
    setFolderButton();
  };
  $("btn-lbrn").onclick = () => exportFiles("lbrn2");
  $("btn-svg").onclick = () => exportFiles("svg");
  $("btn-repack").onclick = () => {
    S.manual.clear();
    S.placements = [];
    changed(true);
  };
  $("btn-zoom-in").onclick = () => sheetView.setZoom(Number(getComputedStyle(document.documentElement).getPropertyValue("--sheet-zoom") || 1) * 1.2);
  $("btn-zoom-out").onclick = () => sheetView.setZoom(Number(getComputedStyle(document.documentElement).getPropertyValue("--sheet-zoom") || 1) / 1.2);
  document.querySelectorAll<HTMLButtonElement>("[role=tab]").forEach((b) => (b.onclick = () => tab(b.dataset.tab!)));
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") {
      e.preventDefault();
      saveBox();
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
  setFolderButton();
  if (files.folderName()) loadMaterialsFromFolder().then(renderMaterial).catch(() => {});
  tab("box");
  if (!(await openFromHash())) await newBox(FIRST_BOX.generator, FIRST_BOX.name, FIRST_BOX.params);
}

main();
