// .box.json configs, share links (the whole config in the URL hash) and the "recent boxes" list.

import type { BoxConfig } from "./types";

const RECENT = "superboxespy.recent.v1";

export function toJSON(c: BoxConfig): string {
  return JSON.stringify(c, null, 2) + "\n";
}

export function parse(text: string): BoxConfig {
  const c = JSON.parse(text);
  if (c?.app !== "superboxespy" || !c.generator || typeof c.params !== "object") {
    throw new Error("not a superboxespy box file");
  }
  return c as BoxConfig;
}

// URL hash: #box=<base64url(deflate(json))>; CompressionStream is in every current browser.
async function deflate(s: string): Promise<Uint8Array> {
  const cs = new Blob([s]).stream().pipeThrough(new CompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(cs).arrayBuffer());
}

async function inflate(b: Uint8Array): Promise<string> {
  const ds = new Blob([b as BlobPart]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return await new Response(ds).text();
}

const b64u = (b: Uint8Array) => btoa(String.fromCharCode(...b)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const unb64u = (s: string) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));

export async function shareLink(c: BoxConfig): Promise<string> {
  const url = new URL(location.href);
  url.hash = "box=" + b64u(await deflate(JSON.stringify(c)));
  return url.href;
}

export async function fromHash(): Promise<BoxConfig | null> {
  const m = location.hash.match(/box=([A-Za-z0-9_-]+)/);
  if (!m) return null;
  try {
    return parse(await inflate(unb64u(m[1])));
  } catch {
    return null;
  }
}

export interface RecentEntry { name: string; generator: string; saved: string; config: BoxConfig }

export function recent(): RecentEntry[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT) ?? "[]");
  } catch {
    return [];
  }
}

export function remember(c: BoxConfig) {
  try {
    const list = recent().filter((r) => r.name !== c.name);
    list.unshift({ name: c.name, generator: c.generator, saved: c.saved, config: c });
    localStorage.setItem(RECENT, JSON.stringify(list.slice(0, 12)));
  } catch {
    /* convenience only */
  }
}
