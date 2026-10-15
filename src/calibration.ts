// Calibration tab: 00a kerf strips -> calipers -> 00b fit comb -> press-fit and glue-fit winners.
// Results go into the material profile; every box made afterwards uses them.
//
// Kerf is measured per axis. When X and Y differ (the Falcon2's spot isn't round), every cut is compensated per
// machine axis and the comb varies only the fit offset on top: burn X = kerf X / 2 + fit, burn Y = kerf Y / 2 + fit.
// Winners are stored as that fit offset either way.

import * as py from "./py";
import * as mats from "./materials";
import { h } from "./params";
import { SheetView } from "./sheetview";
import type { Build, MaterialProfile, OutFile, Sheet } from "./types";

export interface CalibCtx {
  material(): MaterialProfile;
  sheet(): Sheet;
  toast(text: string, bad?: boolean, ms?: number): void;
  saveFiles(sub: string | null, zip: string, files: { name: string; content: string }[]): Promise<string>;
  afterUpdate(): void;
}

const r4 = (v: number) => Math.round(v * 10000) / 10000;
const fmt = (v: number | null, d = 3) => (v == null ? "—" : v.toFixed(d));
const signed = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;

let shown: "kerf" | "comb" = "kerf";

/** The comb the current profile asks for: what Python needs, and the values engraved on the plates. */
function combPlan(p: MaterialProfile) {
  const base = mats.baseBurn(p);
  if (mats.perAxis(p)) {
    const deltas = [-2, -1, 0, 1, 2, 3].map((k) => r4(k * 0.02)).filter((d) => base.x + d > 0 && base.y + d > 0);
    return {
      axis: true, base,
      req: { kerf: { x: p.kerfX, y: p.kerfY }, material: { key: p.key, thickness: p.thickness } },
      options: deltas.map((d) => ({ delta: d, label: signed(d) })),
    };
  }
  const center = Math.round(base.x * 100) / 100;
  const burns = [-2, -1, 0, 1, 2, 3].map((k) => r4(center + k * 0.02)).filter((b) => b > 0);
  return {
    axis: false, base,
    req: { center, material: { key: p.key, thickness: p.thickness, burn: center } },
    options: burns.map((b) => ({ delta: r4(b - base.x), label: b.toFixed(2) })),
  };
}

export function renderCalibration(root: HTMLElement, ctx: CalibCtx) {
  const p = ctx.material();
  const plan = combPlan(p);

  root.replaceChildren();
  const left = h("div");
  const right = h("div", { class: "preview-sheet" });
  root.append(left, right);

  left.append(h("h2", {}, `Calibrate · ${p.label}`),
    h("p", { class: "hint" }, "Only measured values count. Cut 00a first, measure, then cut 00b - it's built on what you measured."));

  // --- step 1: kerf sheet
  const get00a = h("button", { class: "primary" }, "Get 00a kerf test");
  get00a.onclick = () => exportSheet(ctx, "kerf", {});
  const show00a = h("button", {}, "Show");
  show00a.onclick = () => {
    shown = "kerf";
    preview(right, ctx, plan.req);
  };
  left.append(h("div", { class: "step" },
    h("h4", {}, "1 · Cut the kerf strips (00a)"),
    h("p", {}, "Two strips of ten 10 mm bars, one along X and one along Y, raw geometry without burn correction. About a minute of cutting."),
    h("div", { class: "btn-group" }, get00a, show00a)));

  // --- step 2: measurements
  const lx = h("input", { type: "number", step: 0.01, placeholder: "e.g. 98.6", value: p.kerfX != null ? r4(100 - 10 * p.kerfX) : "" }) as HTMLInputElement;
  const ly = h("input", { type: "number", step: 0.01, placeholder: "e.g. 98.4", value: p.kerfY != null ? r4(100 - 10 * p.kerfY) : "" }) as HTMLInputElement;
  const th = h("input", { type: "number", step: 0.01, value: p.thickness }) as HTMLInputElement;
  const out = h("div", { class: "result" });
  const calc = () => {
    const kx = lx.value ? (100 - Number(lx.value)) / 10 : null;
    const ky = ly.value ? (100 - Number(ly.value)) / 10 : null;
    const lines = [`kerf X ${fmt(kx)} mm   kerf Y ${fmt(ky)} mm`];
    if (kx != null && ky != null) {
      const d = Math.abs(kx - ky);
      lines.push(d >= mats.AXIS_THRESHOLD
        ? `The spot isn't round: X and Y differ by ${d.toFixed(3)} mm.\nPer-axis compensation: burn X ${(kx / 2).toFixed(3)}, burn Y ${(ky / 2).toFixed(3)} mm (+ the fit from 00b).`
        : `X and Y are the same: one burn value, ${(((kx + ky) / 2) / 2).toFixed(3)} mm (+ the fit from 00b).`);
    }
    if ((kx != null && (kx <= 0 || kx > 0.6)) || (ky != null && (ky <= 0 || ky > 0.6))) {
      lines.push("That kerf looks wrong - re-measure: bars pushed tight together, end to end.");
    }
    out.textContent = lines.join("\n");
    return { kx, ky };
  };
  [lx, ly].forEach((i) => (i.oninput = calc));
  calc();
  const saveK = h("button", { class: "primary" }, "Save measurements");
  saveK.onclick = () => {
    const { kx, ky } = calc();
    const t = Number(th.value);
    if (kx == null && ky == null && !(t > 0)) return;
    mats.update(p.key, {
      kerfX: kx != null ? r4(kx) : p.kerfX, kerfY: ky != null ? r4(ky) : p.kerfY,
      thickness: t > 0 ? r4(t) : p.thickness, thicknessMeasured: t > 0 || p.thicknessMeasured,
      measuredOn: new Date().toISOString().slice(0, 10),
    });
    ctx.toast("Saved. Get 00b next - it's built on this kerf.");
    ctx.afterUpdate();
    renderCalibration(root, ctx);
  };
  left.append(h("div", { class: "step" },
    h("h4", {}, "2 · Measure with calipers"),
    h("p", {}, "Push the 10 bars of a strip tightly together, end to end as they were cut, and measure the total length along the strip. Thickness: average of three spots."),
    h("div", { class: "fields" },
      h("label", {}, "Strip X - 10 bars along X (mm)"), lx,
      h("label", {}, "Strip Y - 10 bars along Y (mm)"), ly,
      h("label", {}, "Sheet thickness (mm)"), th),
    out, saveK));

  // --- step 3: fit comb
  const get00b = h("button", { class: "primary" }, "Get 00b fit comb");
  get00b.onclick = () => exportSheet(ctx, "comb", plan.req);
  const show00b = h("button", {}, "Show");
  show00b.onclick = () => {
    shown = "comb";
    preview(right, ctx, plan.req);
  };
  const combText = plan.axis
    ? `Compensated per axis: burn X ${plan.base.x.toFixed(3)} / Y ${plan.base.y.toFixed(3)} mm plus the fit engraved on each plate (−0.04 … +0.06). ` +
      "A = fingers, B = corner counterpart, C = finger holes. The A90 B90 C90 row is turned 90° at +0.00: it should feel exactly like the +0.00 row - if not, tell Claude."
    : mats.kerf(p) == null
      ? "No kerf measured yet - this comb is centred on boxes.py's default 0.10. Better: do steps 1-2 first."
      : "Centred on your measured kerf / 2, six burn values, one step more on the tight side. A = fingers, B = corner counterpart, C = finger holes.";
  left.append(h("div", { class: "step" },
    h("h4", {}, plan.axis ? "3 · Cut the fit comb (00b), per axis" : `3 · Cut the fit comb (00b) around burn ${plan.options[2]?.label ?? ""}`),
    h("p", {}, combText),
    h("div", { class: "btn-group" }, get00b, show00b)));

  // --- step 4: winners, stored as the fit offset on top of kerf / 2
  const pick = (cur: number | null) => {
    const s = h("select") as HTMLSelectElement;
    s.append(h("option", { value: "" }, "not tested"));
    for (const o of plan.options) s.append(h("option", { value: o.delta, selected: cur != null && Math.abs(cur - o.delta) < 1e-6 }, o.label));
    if (cur != null && !plan.options.some((o) => Math.abs(cur - o.delta) < 1e-6)) {
      s.append(h("option", { value: cur, selected: true }, `${signed(cur)} (earlier comb)`));
    }
    return s;
  };
  const press = pick(p.fitPress);
  const glue = pick(p.fitGlue);
  const edgeWarn = h("p", { class: "hint" });
  const checkEdges = () => {
    const ends = [plan.options[0]?.delta, plan.options[plan.options.length - 1]?.delta];
    const hit = [press.value, glue.value].filter((v) => v !== "" && ends.some((e) => e != null && Math.abs(Number(v) - e) < 1e-6));
    edgeWarn.textContent = hit.length
      ? "A winner sits at the end of the comb - the real best may be beyond it. Cut another comb before trusting it."
      : "";
  };
  press.onchange = glue.onchange = checkEdges;
  checkEdges();
  const saveW = h("button", { class: "primary" }, "Save winners");
  saveW.onclick = () => {
    mats.update(p.key, {
      fitPress: press.value !== "" ? Number(press.value) : null,
      fitGlue: glue.value !== "" ? Number(glue.value) : null,
      measuredOn: new Date().toISOString().slice(0, 10),
    });
    ctx.toast("Fits saved. Boxes now use them (Press fit / Glue fit in the side panel).");
    ctx.afterUpdate();
    renderCalibration(root, ctx);
  };
  left.append(h("div", { class: "step" },
    h("h4", {}, "4 · Pick the winners"),
    h("p", {}, "Pick the value engraved on the plates. Press fit: goes together by hand pressure, holds without glue, nothing cracks. Glue fit: slides together with light pressure, a little play."),
    h("div", { class: "fields" }, h("label", {}, "Press fit (A in B and A in C)"), press, h("label", {}, "Glue fit"), glue),
    edgeWarn, saveW));

  // --- profile table
  const burns = (fit: "press" | "glue") => {
    const c = mats.compensation(p, fit);
    const won = fit === "press" ? p.fitPress : p.fitGlue;
    if (won == null) return "not tested";
    return c.perAxis ? `fit ${signed(won)} → burn X ${c.bx.toFixed(3)} / Y ${c.by.toFixed(3)} mm` : `fit ${signed(won)} → burn ${c.burn.toFixed(3)} mm`;
  };
  const rows: [string, string][] = [
    ["Thickness", `${p.thickness} mm${p.thicknessMeasured ? "" : " (nominal)"}`],
    ["Kerf X / Y", `${fmt(p.kerfX)} / ${fmt(p.kerfY)} mm${mats.perAxis(p) ? " - per-axis compensation" : ""}`],
    ["Press fit", burns("press")],
    ["Glue fit", burns("glue")],
    ["Last measured", p.measuredOn ?? "never"],
  ];
  left.append(h("div", { class: "step" }, h("h4", {}, "Current profile"),
    h("table", {}, ...rows.map(([k, v]) => h("tr", {}, h("th", {}, k), h("td", {}, v))))));

  preview(right, ctx, plan.req);
}

async function preview(el: HTMLElement, ctx: CalibCtx, req: object) {
  el.replaceChildren(h("p", { class: "hint" }, "Loading preview…"));
  const r = await py.call<Build & { values?: number[]; mode?: string }>(shown === "kerf" ? "kerf_sheet" : "comb_sheet", { ...req, sheet: ctx.sheet() });
  if (!r.ok) {
    el.replaceChildren(h("p", { class: "msg-bad" }, r.error ?? "preview failed"));
    return;
  }
  const holder = h("div", { class: "sheets" });
  const title = shown === "kerf" ? "00a kerf test"
    : r.mode === "axis" ? `00b fit comb, per axis · fit ${r.values?.map(signed).join(" / ")}`
    : `00b fit comb · burn ${r.values?.map((v) => v.toFixed(2)).join(" / ")}`;
  el.replaceChildren(h("h4", {}, title), holder);
  const view = new SheetView(holder, { change() {}, select() {} });
  view.show(r, ctx.sheet(), r.placements);
}

async function exportSheet(ctx: CalibCtx, which: "kerf" | "comb", req: object) {
  const r = await py.call<{ ok: boolean; error?: string; files: OutFile[] }>("calibration_export", { ...req, which, sheet: ctx.sheet() });
  if (!r.ok) {
    ctx.toast(r.error ?? "export failed", true);
    return;
  }
  const list = r.files.filter((f) => f.kind === "lbrn2");
  const where = await ctx.saveFiles("00_calibration", "00_calibration.zip", list);
  const min = list[0]?.minutes ? Object.values(list[0].minutes).reduce((a, b) => a + b, 0).toFixed(1) : "?";
  ctx.toast(`${where}. About ${min} min of cutting.`);
}
