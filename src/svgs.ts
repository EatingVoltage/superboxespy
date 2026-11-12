// Imported SVG files' texts, kept once each by their content. A box's face items hold a reference (svg_ref) instead
// of the text, so the face editor's edits, undo's snapshots and the requests to Python don't copy the file around.
// The store only grows: undo may bring back an item whose SVG was deleted since.
//
// The worker imports this module too and so keeps its own store: py.ts sends a text with the first request that needs
// it, and the worker puts the texts back into the items (svg) before Python reads them - Python sees what it always
// has. A box file holds the text inline (svg), as it always has: resolve() on save, intern() on open.

import type { FaceItem } from "./types";

type Faces = Record<string, FaceItem[]>;
const store = new Map<string, string>();

/** cyrb53: a 53-bit hash of the text, in base 36. */
function hash(s: string): string {
  let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 2654435761);
    h2 = Math.imul(h2 ^ c, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36);
}

/** Keep a text; its reference. */
export function keep(text: string): string {
  let ref = "svg" + hash(text);
  while (store.has(ref) && store.get(ref) !== text) ref += "_";      // another text, same hash
  store.set(ref, text);
  return ref;
}

/** Texts another store sent (the worker: what py.ts sends along). */
export function add(texts: Record<string, string>) {
  for (const [ref, text] of Object.entries(texts)) store.set(ref, text);
}

/** Every item with `from` turned into `to` by f, in the same place (Python and the box file see the same JSON). */
function swap(faces: Faces, from: "svg" | "svg_ref", to: "svg" | "svg_ref", f: (v: string) => string | undefined): Faces {
  const out: Faces = {};
  for (const [face, items] of Object.entries(faces)) {
    out[face] = items.map((it) => Object.fromEntries(Object.entries(it).map(([k, v]) => (k === from ? [to, f(v)] : [k, v]))) as FaceItem);
  }
  return out;
}

/** The items with their SVGs' texts in them: what a box file holds and Python reads. */
export function resolve(faces: Faces): Faces {
  return swap(faces, "svg_ref", "svg", (ref) => store.get(ref));
}

/** An opened box file's items, their SVGs kept here and referred to. */
export function intern(faces: Faces): Faces {
  return swap(faces, "svg", "svg_ref", keep);
}

/** The texts `faces` refers to that `known` doesn't hold yet (null: none); known holds them from now on. */
export function unsent(faces: Faces | undefined, known: Set<string>): Record<string, string> | null {
  let out: Record<string, string> | null = null;
  for (const items of Object.values(faces ?? {})) {
    for (const it of items) {
      if (!it.svg_ref || known.has(it.svg_ref) || !store.has(it.svg_ref)) continue;
      known.add(it.svg_ref);
      (out ??= {})[it.svg_ref] = store.get(it.svg_ref)!;
    }
  }
  return out;
}
