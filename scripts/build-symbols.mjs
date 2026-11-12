// The symbol library's index (.grill/symbol-library.md): Lucide (ISC) and Tabler's outline icons (MIT), pinned in
// package.json's devDependencies, turned into public/symbols.json for the face editor's library, with both sets'
// licenses beside it in public/symbols/. Run by `npm run setup` and before every `npm run build`; the output is
// generated, not committed.
//
// Both sets draw on a 24-unit grid with a 2-unit stroke, round caps and joins. Per symbol the index keeps its id
// ("lucide:midi-port"), its search words (name and tags, lower case) and its drawing as SVG path data: "d" what's
// stroked, "f" what's filled (a few dots and Tabler's percentage pies). Circles, ellipses, rects (rounded too), lines
// and polylines become path data, so Python and the page read one format. Left out: Lucide's aliases (old names of
// the same icon), Tabler's 24 x 24 bounding box path, and Tabler's Brand category (company logos: trademarks).
import { copyFileSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const LUCIDE = "node_modules/lucide-static";
const TABLER = "node_modules/@tabler/icons";
const OUT = "public/symbols.json";
const LICENSES = "public/symbols";

const version = (dir) => JSON.parse(readFileSync(join(dir, "package.json"), "utf8")).version;
const NUM = /[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g;
const TOKEN = /[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g;
const g = (v) => +(+v).toFixed(3);                       // short numbers in the generated path data

/** One element's attributes. */
function attrs(src) {
  const out = {};
  for (const m of src.matchAll(/([a-zA-Z-]+)="([^"]*)"/g)) out[m[1]] = m[2];
  return out;
}

/** Path data that starts with an absolute moveto, so drawings can be joined: a leading "m" is absolute (the SVG
 *  rule), the pairs after it relative linetos. */
function absStart(d) {
  const re = new RegExp(TOKEN.source, "g");
  const t = [];
  for (let m; t.length < 4 && (m = re.exec(d)); ) t.push({ s: m[0], end: re.lastIndex });
  if (t[0]?.s !== "m") return d.trim();
  const rest = d.slice(t[2].end).trim();
  return `M${t[1].s} ${t[2].s}` + (t[3] && !/[a-zA-Z]/.test(t[3].s) ? "l" : "") + rest;
}

const ARGS = { m: 2, l: 2, h: 1, v: 1, c: 6, s: 4, q: 4, t: 2, a: 7, z: 0 };

/** Path data with every number spelt out: an arc's two flags may be written run together ("a1 1 0 01-1 1", as
 *  Lucide does), which evlaser.svgpath (a plain number tokenizer) would read as one number. */
function spelt(d) {
  const out = [];
  let i = 0, cmd = null, k = 0;
  const num = /^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/;
  while (i < d.length) {
    const ch = d[i];
    if (/[\s,]/.test(ch)) {
      i++;
      continue;
    }
    if (/[a-zA-Z]/.test(ch)) {
      if (!(ch.toLowerCase() in ARGS)) throw new Error(`path command ${ch}`);
      cmd = ch;
      k = 0;
      out.push(ch);
      i++;
      continue;
    }
    if (!cmd) throw new Error("path data must start with a command");
    const n = ARGS[cmd.toLowerCase()];
    const flag = cmd.toLowerCase() === "a" && (k % 7 === 3 || k % 7 === 4);
    const m = flag ? d.slice(i).match(/^[01]/) : d.slice(i).match(num);
    if (!m) throw new Error(`bad number at ${d.slice(i, i + 10)}`);
    out.push(m[0]);
    i += m[0].length;
    k++;
    if (n && k % n === 0 && cmd.toLowerCase() === "m") cmd = cmd === "m" ? "l" : "L";   // pairs after a moveto are linetos
  }
  return out.join(" ").replace(/ ?([a-zA-Z]) ?/g, "$1");
}

/** An element as path data, or null for one that draws nothing. */
function pathData(tag, a) {
  const n = (k, d = 0) => (a[k] == null ? d : +a[k]);
  if (tag === "path") return a.d ? spelt(absStart(a.d)) : null;
  if (tag === "circle" || tag === "ellipse") {
    const cx = n("cx"), cy = n("cy");
    const rx = tag === "circle" ? n("r") : n("rx"), ry = tag === "circle" ? n("r") : n("ry");
    if (!(rx > 0 && ry > 0)) return null;
    return `M${g(cx - rx)} ${g(cy)}a${g(rx)} ${g(ry)} 0 1 0 ${g(2 * rx)} 0a${g(rx)} ${g(ry)} 0 1 0 ${g(-2 * rx)} 0z`;
  }
  if (tag === "rect") {
    const x = n("x"), y = n("y"), w = n("width"), h = n("height");
    if (!(w > 0 && h > 0)) return null;
    let rx = a.rx != null ? n("rx") : a.ry != null ? n("ry") : 0;
    let ry = a.ry != null ? n("ry") : rx;
    rx = Math.min(Math.max(rx, 0), w / 2);
    ry = Math.min(Math.max(ry, 0), h / 2);
    if (!rx || !ry) return `M${g(x)} ${g(y)}h${g(w)}v${g(h)}h${g(-w)}z`;
    const arc = (dx, dy) => `a${g(rx)} ${g(ry)} 0 0 1 ${g(dx)} ${g(dy)}`;
    return `M${g(x + rx)} ${g(y)}h${g(w - 2 * rx)}${arc(rx, ry)}v${g(h - 2 * ry)}${arc(-rx, ry)}` +
      `h${g(-(w - 2 * rx))}${arc(-rx, -ry)}v${g(-(h - 2 * ry))}${arc(rx, -ry)}z`;
  }
  if (tag === "line") return `M${g(n("x1"))} ${g(n("y1"))}L${g(n("x2"))} ${g(n("y2"))}`;
  if (tag === "polyline" || tag === "polygon") {
    const v = (a.points ?? "").match(NUM)?.map(Number) ?? [];
    if (v.length < 4) return null;
    const pts = [];
    for (let i = 0; i + 1 < v.length; i += 2) pts.push(`${g(v[i])} ${g(v[i + 1])}`);
    return "M" + pts.join("L") + (tag === "polygon" ? "z" : "");
  }
  throw new Error(`an element the index can't draw: <${tag}>`);
}

/** A set's SVG file as {d, f}: the stroked and the filled elements' path data. */
function drawing(file) {
  const svg = readFileSync(file, "utf8");
  const body = svg.replace(/^[\s\S]*?<svg[^>]*>/, "").replace(/<\/svg>[\s\S]*$/, "");
  const head = attrs(svg.match(/<svg([^>]*)>/)[1]);
  if (head.viewBox !== "0 0 24 24" || head["stroke-width"] !== "2") throw new Error(`${file}: not a 24 grid, 2 stroke`);
  const d = [], f = [];
  for (const m of body.matchAll(/<([a-zA-Z]+)([^>]*?)\/?>/g)) {
    const [tag, a] = [m[1], attrs(m[2])];
    if (a.transform) throw new Error(`${file}: a transform the index doesn't apply`);
    if (tag === "path" && a.d === "M0 0h24v24H0z" && a.stroke === "none") continue;      // Tabler's bounding box
    const p = pathData(tag, a);
    if (!p) continue;
    if (a.stroke !== "none") d.push(p);
    if (a.fill === "currentColor") f.push(p);
  }
  return { d: d.join(""), f: f.join("") };
}

const words = (s) => s.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);

const symbols = [];
// Lucide: the icons tags.json names (the other files are aliases, old names of the same icon)
const lucideTags = JSON.parse(readFileSync(join(LUCIDE, "tags.json"), "utf8"));
for (const name of Object.keys(lucideTags).sort()) {
  const { d, f } = drawing(join(LUCIDE, "icons", `${name}.svg`));
  if (!d && !f) continue;
  symbols.push({ id: `lucide:${name}`, t: [...new Set(lucideTags[name].flatMap(words))].join(" "), d, ...(f ? { f } : {}) });
}
// Tabler: its outline icons, but for the Brand category
const tabler = JSON.parse(readFileSync(join(TABLER, "icons.json"), "utf8"));
let brands = 0;
for (const name of Object.keys(tabler).sort()) {
  const e = tabler[name];
  if (!e.styles?.outline) continue;
  if (e.category === "Brand") {
    brands++;
    continue;
  }
  const { d, f } = drawing(join(TABLER, "icons", "outline", `${name}.svg`));
  if (!d && !f) continue;
  const tags = [...(e.tags ?? []).map(String), e.category ?? ""].flatMap(words);
  symbols.push({ id: `tabler:${name}`, t: [...new Set(tags)].join(" "), d, ...(f ? { f } : {}) });
}

const index = {
  sets: {
    lucide: { name: "Lucide", version: version(LUCIDE), license: "ISC", url: "https://lucide.dev", file: "symbols/lucide-LICENSE.txt" },
    tabler: { name: "Tabler Icons", version: version(TABLER), license: "MIT", url: "https://tabler.io/icons", file: "symbols/tabler-LICENSE.txt" },
  },
  grid: 24,
  stroke: 2,
  symbols,
};
mkdirSync(LICENSES, { recursive: true });
copyFileSync(join(LUCIDE, "LICENSE"), join(LICENSES, "lucide-LICENSE.txt"));
copyFileSync(join(TABLER, "LICENSE"), join(LICENSES, "tabler-LICENSE.txt"));
const text = JSON.stringify(index);
writeFileSync(OUT, text);
const by = (s) => symbols.filter((x) => x.id.startsWith(s)).length;
console.log(`${OUT}: ${symbols.length} symbols (Lucide ${by("lucide:")}, Tabler ${by("tabler:")}; ${brands} Tabler brands left out), ` +
  `${(text.length / 1e6).toFixed(2)} MB`);
