// Files on disk. With a folder picked (File System Access API: Chrome, Edge, or Brave with
// brave://flags/#file-system-access-api on) everything is written straight into it:
//   <folder>/<box name>/NN_name.lbrn2 (+ .svg)     the sheets
//   <folder>/<box name>/<box name>.box.json         the box
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
