// Files on disk. With a folder picked (File System Access API: Chrome, Edge, or Brave with
// brave://flags/#file-system-access-api on) everything is written straight into it:
//   <folder>/<box name>/<box name>.lbrn2           the LightBurn project, one page per sheet
//   <folder>/<box name>/NN_<box name>.svg          the sheets as SVG
//   <folder>/<box name>/<box name>.sbox             the box (JSON; boxes saved before 2026-11-07 are .box.json)
//   <folder>/materials.json                         thickness, kerf and fits per material
// Without one, files are downloaded (several at once as a zip).

import JSZip from "jszip";

type DirHandle = any; // FileSystemDirectoryHandle - typed loosely, the API isn't in every TS lib yet

const DB = "superboxespy";
const STORE = "handles";

function idb<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest): Promise<T | undefined> {
  return new Promise((resolve) => {
    let open: IDBOpenDBRequest;
    try {
      open = indexedDB.open(DB, 1);
    } catch {
      resolve(undefined);
      return;
    }
    open.onupgradeneeded = () => open.result.createObjectStore(STORE);
    open.onerror = () => resolve(undefined);
    open.onsuccess = () => {
      try {
        const req = fn(open.result.transaction(STORE, mode).objectStore(STORE));
        req.onsuccess = () => resolve(req.result as T);
        req.onerror = () => resolve(undefined);
      } catch {
        resolve(undefined);
      }
    };
  });
}

let folder: DirHandle | null = null;

export const canPickFolder = () => typeof (window as any).showDirectoryPicker === "function";

export async function restoreFolder(): Promise<DirHandle | null> {
  if (!canPickFolder()) return null;
  folder = (await idb<DirHandle>("readonly", (s) => s.get("folder"))) ?? null;
  return folder;
}

export function folderName(): string | null {
  return folder?.name ?? null;
}

export async function pickFolder(): Promise<DirHandle | null> {
  if (!canPickFolder()) return null;
  try {
    folder = await (window as any).showDirectoryPicker({ id: "superboxespy", mode: "readwrite" });
    await idb("readwrite", (s) => s.put(folder, "folder"));
    return folder;
  } catch {
    return null; // cancelled
  }
}

async function writable(): Promise<DirHandle | null> {
  if (!folder) return null;
  const opts = { mode: "readwrite" };
  if ((await folder.queryPermission(opts)) === "granted") return folder;
  if ((await folder.requestPermission(opts)) === "granted") return folder;
  return null;
}

export function safeName(s: string): string {
  return s.replace(/[\\/:*?"<>|]+/g, "-").trim() || "box";
}

/** Write files into <folder>/<sub>/. Returns the path written to, or null when there's no usable folder. */
export async function writeToFolder(sub: string | null, files: { name: string; content: string }[]): Promise<string | null> {
  const root = await writable();
  if (!root) return null;
  const dir = sub ? await root.getDirectoryHandle(safeName(sub), { create: true }) : root;
  for (const f of files) {
    const fh = await dir.getFileHandle(f.name, { create: true });
    const w = await fh.createWritable();
    await w.write(f.content);
    await w.close();
  }
  return sub ? `${root.name}/${safeName(sub)}` : root.name;
}

/** Newest of `names` in <folder>/<sub>/ that LightBurn itself saved (its header has AskForSendName). */
export async function lightburnSaved(sub: string, names: string[]): Promise<string | null> {
  const root = await writable();
  if (!root) return null;
  let dir: DirHandle;
  try {
    dir = await root.getDirectoryHandle(safeName(sub));
  } catch {
    return null;
  }
  let best: { text: string; t: number } | null = null;
  for (const n of names) {
    try {
      const f = await (await dir.getFileHandle(n)).getFile();
      const text = await f.text();
      if (text.slice(0, 600).includes("AskForSendName") && (!best || f.lastModified > best.t)) best = { text, t: f.lastModified };
    } catch {
      /* not there */
    }
  }
  return best?.text ?? null;
}

/** Names of the files in <folder>/<sub>/ ([] when there's no folder or no such subfolder). */
export async function listFolder(sub: string): Promise<string[]> {
  const root = await writable();
  if (!root) return [];
  try {
    const dir = await root.getDirectoryHandle(safeName(sub));
    const names: string[] = [];
    for await (const [n, h] of dir.entries()) if (h.kind === "file") names.push(n);
    return names;
  } catch {
    return [];
  }
}

// ------------------------------------------------------------------ Open in LightBurn
// The browser can't start programs, and it never learns the picked folder's full path, only its name. serve.py
// finds the folder by that name (checking the file there by its SHA-256, so it's the one just written) and starts
// LightBurn on it. The full path it found is remembered per folder name; if it can't find the folder, the user is
// asked for the path once.
const ROOT_KEY = "superboxes.folderPath.";

function remembered(name: string): string | null {
  try {
    return localStorage.getItem(ROOT_KEY + name);
  } catch {
    return null;
  }
}

function remember(name: string, path: string) {
  try {
    localStorage.setItem(ROOT_KEY + name, path);
  } catch {
    /* private window: ask again next time */
  }
}

async function sha256(text: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export type OpenResult = { ok: true; path: string } | { ok: false; error: string; cancelled?: boolean };

/** Open <folder>/<sub>/<file> (written a moment ago with `content`) in LightBurn. */
export async function openInLightBurn(sub: string, file: string, content: string): Promise<OpenResult> {
  const name = folder?.name;
  if (!name) return { ok: false, error: "No folder picked." };
  const req = { folder: name, path: [safeName(sub), file], sha256: await sha256(content) };
  const ask = async (root: string | null) => {
    try {
      const r = await fetch("/api/open-lightburn", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...req, root }),
      });
      if (!r.ok) throw new Error(String(r.status));
      return (await r.json()) as { ok: boolean; path?: string; root?: string; error?: string; need_root?: boolean };
    } catch {
      return { ok: false, error: "Open in LightBurn needs the app started with start.bat or the Start menu entry (serve.py)." };
    }
  };
  let r = await ask(remembered(name));
  if (!r.ok && r.need_root) {
    const typed = prompt(`Where is the folder "${name}" on this computer? Paste its full path ` +
      `(in Explorer: click the address bar and copy).`, remembered(name) ?? "");
    if (!typed?.trim()) return { ok: false, error: "Not opened.", cancelled: true };
    r = await ask(typed.trim().replace(/^"(.*)"$/, "$1"));
  }
  if (!r.ok) return { ok: false, error: r.error ?? "LightBurn didn't start." };
  if (r.root) remember(name, r.root);
  return { ok: true, path: r.path ?? file };
}

export async function readFromFolder(name: string): Promise<string | null> {
  const root = await writable();
  if (!root) return null;
  try {
    const fh = await root.getFileHandle(name);
    return await (await fh.getFile()).text();
  } catch {
    return null;
  }
}

function downloadBlob(name: string, blob: Blob) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

export async function download(zipName: string, files: { name: string; content: string }[]) {
  if (files.length === 1) {
    downloadBlob(files[0].name, new Blob([files[0].content], { type: "application/octet-stream" }));
    return;
  }
  const zip = new JSZip();
  files.forEach((f) => zip.file(f.name, f.content));
  downloadBlob(zipName, await zip.generateAsync({ type: "blob" }));
}

/** Folder if there is one, else download. Returns a short description of where the files went. */
export async function save(sub: string | null, zipName: string, files: { name: string; content: string }[]): Promise<string> {
  const names = files.map((f) => f.name).join(", ");
  const where = await writeToFolder(sub, files);
  if (where) return `Saved ${names} to ${where}`;
  await download(zipName, files);
  return files.length === 1 ? `Downloaded ${names}` : `Downloaded ${zipName} (${names})`;
}

export function openFile(accept: string): Promise<{ name: string; text: string } | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = accept;
    input.onchange = async () => {
      const f = input.files?.[0];
      resolve(f ? { name: f.name, text: await f.text() } : null);
    };
    input.oncancel = () => resolve(null);
    input.click();
  });
}

// ------------------------------------------------------------------ a box beside its own file
// A box opened or saved through serve.py (Open..., Save as..., a .sbox handed to serve.py) keeps its full path,
// its home: Save and the exports write beside it (.grill/stamp-case-merge.md). Only serve.py knows full paths, so it
// reads and writes there and shows Windows' own Open / Save As dialogs. Without serve.py (npm run dev) boxes go to the
// picked folder as before.
type BoxReply = {
  ok: boolean; error?: string; cancelled?: boolean; path?: string; text?: string | null; mtime?: number; dir?: string;
  names?: string[];
};

async function boxCall(req: object): Promise<BoxReply> {
  try {
    const r = await fetch("/api/box", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
    });
    if (!r.ok) return { ok: false, error: `serve.py answered ${r.status}` };
    return await r.json();
  } catch {
    return { ok: false, error: NEEDS_SERVE };
  }
}

const NEEDS_SERVE = "This needs the app started with start.bat or the Start menu entry (serve.py).";

let served: Promise<boolean> | null = null;

/** Is serve.py there to read and write boxes by their full path? */
export function canUseHome(): Promise<boolean> {
  served ??= boxCall({ op: "hello" }).then((r) => r.ok);
  return served;
}

export const dirOf = (path: string) => path.replace(/[\\/][^\\/]*$/, "");
export const fileOf = (path: string) => path.replace(/^.*[\\/]/, "");
export const boxNameOf = (path: string) => fileOf(path).replace(/\.(sbox|box\.json)$/i, "");
/** Where the box goes when it's saved as `name` beside `home`. */
export const homeFor = (home: string, name: string) => `${dirOf(home)}\\${safeName(name)}${BOX_EXT}`;
/** A box file: its own extension, so a double-click can open it (Windows goes by the last extension only). Boxes
 *  saved before 2026-11-07 are .box.json: they still open, and save as .sbox. */
export const BOX_EXT = ".sbox";

/** The picked folder's full path, if Open in LightBurn ever found it. */
export function folderPath(): string | null {
  return folder ? remembered(folder.name) : null;
}

export type HomeRead = { ok: true; path: string; text: string } | { ok: false; error?: string; cancelled?: boolean };

const asRead = (r: BoxReply): HomeRead =>
  r.ok && r.path && typeof r.text === "string"
    ? { ok: true, path: r.path, text: r.text }
    : { ok: false, error: r.error, cancelled: r.cancelled };

export async function readHome(path: string): Promise<HomeRead> {
  return asRead(await boxCall({ op: "read", path }));
}

/** Windows' Open dialog, starting in `start`: the box picked, read. */
export async function askOpen(start: string | null): Promise<HomeRead> {
  return asRead(await boxCall({ op: "ask_open", start }));
}

/** Windows' Save As dialog, starting in `start` with `name` filled in: the .sbox path picked. */
export async function askSaveAs(name: string, start: string | null):
    Promise<{ ok: true; path: string } | { ok: false; error?: string; cancelled?: boolean }> {
  const r = await boxCall({ op: "ask_save", name, start });
  return r.ok && r.path ? { ok: true, path: r.path } : { ok: false, error: r.error, cancelled: r.cancelled };
}

/** Write files beside the box at `home`: the folder written to, or the error. */
export async function writeBeside(home: string, files: { name: string; content: string }[]):
    Promise<{ ok: true; dir: string } | { ok: false; error: string }> {
  const r = await boxCall({ op: "write", home, files });
  return r.ok && r.dir ? { ok: true, dir: r.dir } : { ok: false, error: r.error ?? "not written" };
}

// ------------------------------------------------------------------ where a box's files go
/** Where an export reads and writes: beside the box's own file, or <picked folder>/<box name>/. */
export interface Place {
  /** Names of the files there. */
  list(): Promise<string[]>;
  /** The newest of `names` that LightBurn itself saved (its layers carry over), or null. */
  saved(names: string[]): Promise<string | null>;
  /** Write the files: where they went, or null when it couldn't. */
  write(files: { name: string; content: string }[]): Promise<string | null>;
  /** Open the project just written there in LightBurn. */
  open(file: string, content: string): Promise<OpenResult>;
}

export function besideHome(home: string): Place {
  return {
    list: async () => (await boxCall({ op: "list", home })).names ?? [],
    async saved(names) {
      let best: { text: string; t: number } | null = null;
      for (const name of names) {
        const r = await boxCall({ op: "read_beside", home, name });
        const text = r.text ?? "";
        const byLightBurn = text.slice(0, 600).includes("AskForSendName");
        if (byLightBurn && (!best || (r.mtime ?? 0) > best.t)) {
          best = { text, t: r.mtime ?? 0 };
        }
      }
      return best?.text ?? null;
    },
    async write(files) {
      const r = await writeBeside(home, files);
      return r.ok ? r.dir : null;
    },
    async open(file, content) {
      try {
        const r = await fetch("/api/open-lightburn", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file: `${dirOf(home)}\\${file}`, sha256: await sha256(content) }),
        });
        const o = await r.json();
        return o.ok ? { ok: true, path: o.path } : { ok: false, error: o.error ?? "LightBurn didn't start." };
      } catch {
        return { ok: false, error: NEEDS_SERVE };
      }
    },
  };
}

export function inFolder(sub: string): Place {
  return {
    list: () => listFolder(sub),
    saved: (names) => lightburnSaved(sub, names),
    write: (files) => writeToFolder(sub, files),
    open: (file, content) => openInLightBurn(sub, file, content),
  };
}
