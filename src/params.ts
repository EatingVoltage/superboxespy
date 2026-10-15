// The parameter panel: one widget per boxes.py argument. Sliders always come with a number field, and the
// number field accepts values beyond the slider's range (the slider then stretches).

import type { Group, Param } from "./types";

type OnChange = (name: string, value: any, final: boolean) => void;

const h = <K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, any> = {}, ...kids: (Node | string)[]) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) (el as any)[k] = v;
    else if (v !== undefined && v !== null && v !== false) el.setAttribute(k, String(v));
  }
  kids.forEach((c) => el.append(c));
  return el;
};

const PRETTY: Record<string, string> = {
  x: "Width (x)", y: "Depth (y)", h: "Height (h)", hi: "Inner height", sx: "Columns (sx)", sy: "Rows (sy)",
  outside: "Outside dimensions", bottom_edge: "Bottom edge", top_edge: "Top edge", lidheight: "Lid height",
  splitlid: "Split lid at", front_height: "Front height", angle: "Panel angle", n: "Lid sides",
  play: "Play", inner_corners: "Inner corners", tabs: "Holding tabs",
};

function label(p: Param): string {
  if (PRETTY[p.name]) return PRETTY[p.name];
  const short = p.name.includes("_") && /^[A-Z]/.test(p.name) ? p.name.split("_").slice(1).join(" ") : p.name;
  return short.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function unit(p: Param): string {
  if (/angle/i.test(p.name) || /degree|°/i.test(p.help)) return "°";
  if (/multiples? of (the )?(wall |material )?thickness/i.test(p.help)) return "× t";
  if (/\bmm\b/.test(p.help) || ["x", "y", "h", "hi"].includes(p.name)) return "mm";
  if (/percent|%/.test(p.help)) return "%";
  return "";
}

function fmt(v: number, step = 0.01) {
  const d = step >= 1 ? 0 : Math.min(3, Math.max(0, -Math.floor(Math.log10(step))));
  return Number(v).toFixed(d).replace(/\.?0+$/, "") || "0";
}

function numberRow(p: Param, value: number, onChange: OnChange) {
  const step = p.step ?? (p.kind === "int" ? 1 : 0.01);
  let min = p.min ?? 0;
  let max = Math.max(p.max ?? 100, value);
  const range = h("input", { type: "range", min, max, step, value, "aria-label": label(p) }) as HTMLInputElement;
  const num = h("input", { type: "number", step, value: fmt(value, step), class: "num", "aria-label": label(p) }) as HTMLInputElement;
  const set = (v: number, final: boolean) => {
    if (!Number.isFinite(v)) return;
    if (p.kind === "int") v = Math.round(v);
    if (v > max) {
      max = v;
      range.max = String(max);
    }
    if (v < min) {
      min = v;
      range.min = String(min);
    }
    range.value = String(v);
    num.value = fmt(v, step);
    onChange(p.name, v, final);
  };
  range.oninput = () => set(Number(range.value), false);
  range.onchange = () => set(Number(range.value), true);
  num.onchange = () => set(Number(num.value), true);
  num.onkeydown = (e: KeyboardEvent) => {
    if (e.key === "Enter") set(Number(num.value), true);
  };
  const u = unit(p);
  return h("div", { class: "row num-row", title: p.help },
    h("div", { class: "row-head" }, h("label", {}, label(p)), h("span", { class: "num-wrap" }, num, u ? h("span", { class: "unit" }, u) : "")),
    range);
}

function boolRow(p: Param, value: boolean, onChange: OnChange) {
  const box = h("input", { type: "checkbox", checked: value, role: "switch" }) as HTMLInputElement;
  box.onchange = () => onChange(p.name, box.checked, true);
  return h("label", { class: "row bool-row", title: p.help }, h("span", {}, label(p)), h("span", { class: "switch" }, box, h("i")));
}

function selectRow(p: Param, value: string, onChange: OnChange) {
  const sel = h("select", { "aria-label": label(p) }) as HTMLSelectElement;
  for (const c of p.choices ?? []) {
    const text = p.labels?.[c] ? `${c} — ${p.labels[c]}` : c;
    sel.append(h("option", { value: c, selected: c === value }, text));
  }
  sel.onchange = () => onChange(p.name, sel.value, true);
  return h("div", { class: "row sel-row", title: p.help }, h("label", {}, label(p)), sel);
}

// "50*3:30" <-> [50, 50, 50, 30]
export function parseSections(s: string): number[] {
  const out: number[] = [];
  for (const part of String(s).split(/[\s:]+/).filter(Boolean)) {
    let m = part.match(/^(\d+(?:\.\d+)?)\*(\d+)$/);
    if (m) {
      for (let i = 0; i < Number(m[2]); i++) out.push(Number(m[1]));
      continue;
    }
    m = part.match(/^(\d+(?:\.\d+)?)\/(\d+)$/);
    if (m) {
      for (let i = 0; i < Number(m[2]); i++) out.push(Number(m[1]) / Number(m[2]));
      continue;
    }
    const v = Number(part);
    if (Number.isFinite(v)) out.push(v);
  }
  return out;
}

export function formatSections(v: number[]): string {
  const runs: string[] = [];
  for (let i = 0; i < v.length; ) {
    let j = i;
    while (j < v.length && v[j] === v[i]) j++;
    runs.push(j - i > 1 ? `${fmt(v[i])}*${j - i}` : fmt(v[i]));
    i = j;
  }
  return runs.join(":");
}

function sectionsRow(p: Param, value: string, onChange: OnChange) {
  const wrap = h("div", { class: "row sections-row", title: p.help });
  const text = h("input", { type: "text", value, class: "sections-text", spellcheck: "false", "aria-label": label(p) }) as HTMLInputElement;
  const chips = h("div", { class: "chips" });
  const total = h("span", { class: "hint" });
  const draw = (vals: number[]) => {
    chips.replaceChildren();
    vals.forEach((v, i) => {
      const n = h("input", { type: "number", value: fmt(v), step: 0.5, min: 1, class: "chip", "aria-label": `${label(p)} ${i + 1}` }) as HTMLInputElement;
      n.onchange = () => {
        vals[i] = Math.max(1, Number(n.value) || v);
        commit(vals);
      };
      const del = h("button", { class: "chip-x", title: "remove", "aria-label": "remove" }, "×");
      del.onclick = () => {
        if (vals.length > 1) {
          vals.splice(i, 1);
          commit(vals);
        }
      };
      chips.append(h("span", { class: "chip-wrap" }, n, del));
    });
    const add = h("button", { class: "chip-add", title: "add a section" }, "+");
    add.onclick = () => {
      vals.push(vals[vals.length - 1] ?? 50);
      commit(vals);
    };
    chips.append(add);
    total.textContent = `${vals.length} × · ${fmt(vals.reduce((a, b) => a + b, 0))} mm`;
  };
  const commit = (vals: number[]) => {
    const s = formatSections(vals);
    text.value = s;
    draw(vals);
    onChange(p.name, s, true);
  };
  text.onchange = () => {
    const vals = parseSections(text.value);
    if (vals.length) commit(vals);
  };
  draw(parseSections(value));
  wrap.append(h("div", { class: "row-head" }, h("label", {}, label(p)), total), chips, text);
  return wrap;
}

function textRow(p: Param, value: string, onChange: OnChange) {
  const multi = p.name === "layout";
  const el = (multi ? h("textarea", { rows: 10, spellcheck: "false", class: "mono" }) : h("input", { type: "text" })) as
    HTMLInputElement | HTMLTextAreaElement;
  el.value = value ?? "";
  el.onchange = () => onChange(p.name, el.value, true);
  return h("div", { class: "row text-row", title: p.help }, h("label", {}, label(p)), el);
}

export function widget(p: Param, value: any, onChange: OnChange): HTMLElement {
  switch (p.kind) {
    case "float":
    case "int":
      return numberRow(p, Number(value), onChange);
    case "bool":
      return boolRow(p, Boolean(value), onChange);
    case "choice":
    case "edge":
      return selectRow(p, String(value), onChange);
    case "sections":
    case "ints":
      return sectionsRow(p, String(value), onChange);
    default:
      return textRow(p, value, onChange);
  }
}

export function renderParams(el: HTMLElement, groups: Group[], values: Record<string, any>, onChange: OnChange,
                             openAdvanced: Set<string>) {
  el.replaceChildren();
  const main = groups.filter((g) => !g.advanced);
  const adv = groups.filter((g) => g.advanced);
  for (const g of main) {
    const sec = h("section", { class: "group" }, h("h3", {}, g.title === "Default Settings" ? "Cutting" : g.title));
    g.params.forEach((p) => sec.append(widget(p, values[p.name] ?? p.default, onChange)));
    el.append(sec);
  }
  if (adv.length) {
    const sec = h("section", { class: "group advanced" }, h("h3", {}, "Advanced"));
    for (const g of adv) {
      const d = h("details", { open: openAdvanced.has(g.title) }, h("summary", {}, g.title)) as HTMLDetailsElement;
      d.ontoggle = () => (d.open ? openAdvanced.add(g.title) : openAdvanced.delete(g.title));
      g.params.forEach((p) => d.append(widget(p, values[p.name] ?? p.default, onChange)));
      sec.append(d);
    }
    el.append(sec);
  }
}

export { h };
