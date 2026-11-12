// The symbol library (.grill/symbol-library.md): Lucide and Tabler's line icons, read from public/symbols.json
// (scripts/build-symbols.mjs) the first time the face editor's library opens; the search over them and the logos;
// and Recent, the last 16 placed from the library (logos and symbols), kept in this browser.
//
// A symbol's drawing is SVG path data on a 24-unit grid with a 2-unit stroke: "d" stroked, "f" filled. A placed
// symbol keeps its drawing in the box (faces.py draws it from there), so Recent keeps it too and needs no index.

import { svgEl } from "./sheetview";

export interface SymbolEntry { id: string; t: string; d: string; f?: string }
export interface SymbolIndex {
  sets: Record<string, { name: string; version: string; license: string; url: string; file: string }>;
  symbols: SymbolEntry[];
}

let index: Promise<SymbolIndex | null> | null = null;
/** The index, fetched once (null when it can't be: the app built without `npm run setup`). */
export function loadSymbols(): Promise<SymbolIndex | null> {
  index ??= fetch(new URL("symbols.json", document.baseURI).href)
    .then((r) => (r.ok ? (r.json() as Promise<SymbolIndex>) : null))
    .catch(() => null);
  return index;
}

/** "midi-port" of "lucide:midi-port". */
export const symbolName = (id: string) => id.slice(id.indexOf(":") + 1);

/** The set's name and license of a symbol id, "Lucide (ISC)". */
export function setOf(id: string, ix: SymbolIndex | null): string {
  const key = id.slice(0, id.indexOf(":"));
  const s = ix?.sets[key];
  return s ? `${s.name} (${s.license})` : key;
}

const words = (s: string) => s.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);

/** The typed words (lower case). */
export const queryWords = (q: string) => words(q);

/** Does every typed word start a word of `names` (name: true), or of `names` and `tags` (name: false)? null: no. */
export function matches(q: string[], names: string[], tags: string[] = []): { name: boolean } | null {
  if (q.every((w) => names.some((n) => n.startsWith(w)))) return { name: true };
  if (q.every((w) => names.some((n) => n.startsWith(w)) || tags.some((t) => t.startsWith(w)))) return { name: false };
  return null;
}

const wordsOf = new WeakMap<SymbolEntry, [string[], string[]]>();
function symbolWords(s: SymbolEntry): [string[], string[]] {
  let w = wordsOf.get(s);
  if (!w) wordsOf.set(s, (w = [words(symbolName(s.id)), s.t ? s.t.split(" ") : []]));
  return w;
}

/** The symbols the typed words find: name matches first (the name itself first), then tag matches; shorter names
 *  first within each. */
export function searchSymbols(ix: SymbolIndex, q: string[]): SymbolEntry[] {
  if (!q.length) return [];
  const exact = q.join("-");
  const hits: [number, SymbolEntry][] = [];
  for (const s of ix.symbols) {
    const [names, tags] = symbolWords(s);
    const m = matches(q, names, tags);
    if (m) hits.push([symbolName(s.id) === exact ? 0 : m.name ? 1 : 2, s]);
  }
  hits.sort((a, b) => a[0] - b[0] || symbolName(a[1].id).length - symbolName(b[1].id).length ||
    (symbolName(a[1].id) < symbolName(b[1].id) ? -1 : symbolName(a[1].id) > symbolName(b[1].id) ? 1 : 0));
  return hits.map((h) => h[1]);
}

/** A symbol's tags, from the index (none before it's read). */
export function tagsOf(ix: SymbolIndex | null, id: string): string[] {
  const s = ix?.symbols.find((x) => x.id === id);
  return s ? symbolWords(s)[1] : [];
}

/** A symbol drawn as designed (its strokes 2 of the 24 grid), for a tile or what follows the pointer. */
export function symbolPreview(d: string, f?: string): SVGSVGElement {
  const s = svgEl("svg", { class: "lib-art", viewBox: "-1 -1 26 26", "aria-hidden": "true" }) as SVGSVGElement;
  if (f) s.append(svgEl("path", { d: f, class: "lib-fill" }));
  if (d) s.append(svgEl("path", { d, class: "lib-stroke" }));
  return s;
}

// ------------------------------------------------------------------ Recent
export type Recent = { kind: "logo"; logo: string } | { kind: "symbol"; symbol: string; path: string; path_fill?: string };
const RECENT = "superboxespy.libraryRecent.v1";
const KEEP = 16;
const keyOf = (r: Recent) => (r.kind === "logo" ? "logo:" + r.logo : r.symbol);

/** The last ones placed from the library, newest first. */
export function recent(): Recent[] {
  try {
    const list = JSON.parse(localStorage.getItem(RECENT) ?? "[]");
    return Array.isArray(list) ? list.filter((r) => r && (r.kind === "logo" ? r.logo : r.symbol && typeof r.path === "string")) : [];
  } catch {
    return [];
  }
}

/** One placed (dropped, clicked, or put in place of another): first in Recent. */
export function used(r: Recent) {
  const list = [r, ...recent().filter((x) => keyOf(x) !== keyOf(r))].slice(0, KEEP);
  try {
    localStorage.setItem(RECENT, JSON.stringify(list));
  } catch {
    /* storage off (a private window): Recent just isn't kept */
  }
}
