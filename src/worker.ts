// Web worker: hosts Pyodide + boxes.py so slider changes never freeze the page.
// Messages in: {id, fn, req}. Out: {id, result} (result is the JSON string from superboxes.api.call), or
// {type: "status", text} while starting up.
/// <reference lib="webworker" />

type PyodideAPI = {
  loadPackage(names: string[], opts?: { messageCallback?: (m: string) => void }): Promise<void>;
  unpackArchive(buf: ArrayBuffer, format: string, opts?: { extractDir?: string }): void;
  runPython(code: string): unknown;
  FS: { mkdirTree(path: string): void; writeFile(path: string, data: Uint8Array): void; readdir(path: string): string[];
        unlink(path: string): void };
  globals: { set(name: string, value: unknown): void };
};

const report = (text: string) => self.postMessage({ type: "status", text });

// The page sends its own base URL first: public files (pyodide/, py.zip) sit next to index.html, wherever the
// worker script itself ends up (dev server or build).
let gotBase: (base: string) => void;
const baseURL = new Promise<string>((resolve) => (gotBase = resolve));

async function start(): Promise<PyodideAPI> {
  const base = new URL(await baseURL);
  const pyodideURL = new URL("pyodide/", base).href;
  report("Loading Python…");
  const mod = await import(/* @vite-ignore */ pyodideURL + "pyodide.mjs");
  const py: PyodideAPI = await mod.loadPyodide({ indexURL: pyodideURL });
  report("Loading geometry libraries…");
  await py.loadPackage(["numpy", "shapely", "affine", "typing-extensions", "fonttools"], { messageCallback: () => {} });
  report("Loading boxes.py…");
  const zip = await (await fetch(new URL("py.zip", base).href, { cache: "no-cache" })).arrayBuffer();
  py.unpackArchive(zip, "zip", { extractDir: "/app" });
  py.runPython("import sys; sys.path.insert(0, '/app'); from superboxes import api");
  await copyLogos(py, base);
  report("ready");
  return py;
}

/** The house logos, .svg and LightBurn .lbrn2, for the face editor's library and the stamp case: serve.py hands them
 *  over from Samuel's logos folder (they're private and never ship with the app). Under `npm run dev`, or without
 *  the folder, there are none and a case simply has no logo. Copied again each time the library opens
 *  (.grill/logo-library.md: a box links its logo by name, so a changed file shows without a restart). */
async function copyLogos(py: PyodideAPI, base: URL) {
  try {
    const res = await fetch(new URL("api/logos", base).href, { cache: "no-store" });
    if (!res.ok) return;
    const names: string[] = await res.json();
    py.FS.mkdirTree("/logos");
    for (const old of py.FS.readdir("/logos")) {
      if (old !== "." && old !== ".." && !names.includes(old)) py.FS.unlink("/logos/" + old);
    }
    await Promise.all(names.map(async (n) => {
      const r = await fetch(new URL("api/logos/" + encodeURIComponent(n), base).href, { cache: "no-store" });
      if (r.ok) py.FS.writeFile("/logos/" + n, new Uint8Array(await r.arrayBuffer()));
    }));
  } catch {
    /* no logos */
  }
}

const ready = start();

self.onmessage = async (ev: MessageEvent<{ id: number; fn: string; req: unknown; base?: string }>) => {
  if (ev.data.base) {
    gotBase(ev.data.base);
    return;
  }
  const { id, fn, req } = ev.data;
  try {
    const py = await ready;
    if (fn === "logo_library") await copyLogos(py, new URL(await baseURL));
    py.globals.set("_fn", fn);
    py.globals.set("_req", JSON.stringify(req ?? {}));
    const result = py.runPython("api.call(_fn, _req)") as string;
    self.postMessage({ id, result });
  } catch (e) {
    self.postMessage({ id, result: JSON.stringify({ ok: false, error: String((e as Error)?.message ?? e) }) });
  }
};
