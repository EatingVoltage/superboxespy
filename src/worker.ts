// Web worker: hosts Pyodide + boxes.py so slider changes never freeze the page.
// Messages in: {id, fn, req}. Out: {id, result} (result is the JSON string from superboxes.api.call), or
// {type: "status", text} while starting up.
/// <reference lib="webworker" />

type PyodideAPI = {
  loadPackage(names: string[], opts?: { messageCallback?: (m: string) => void }): Promise<void>;
  unpackArchive(buf: ArrayBuffer, format: string, opts?: { extractDir?: string }): void;
  runPython(code: string): unknown;
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
  await py.loadPackage(["numpy", "shapely", "affine", "typing-extensions"], { messageCallback: () => {} });
  report("Loading boxes.py…");
  const zip = await (await fetch(new URL("py.zip", base).href, { cache: "no-cache" })).arrayBuffer();
  py.unpackArchive(zip, "zip", { extractDir: "/app" });
  py.runPython("import sys; sys.path.insert(0, '/app'); from superboxes import api");
  report("ready");
  return py;
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
    py.globals.set("_fn", fn);
    py.globals.set("_req", JSON.stringify(req ?? {}));
    const result = py.runPython("api.call(_fn, _req)") as string;
    self.postMessage({ id, result });
  } catch (e) {
    self.postMessage({ id, result: JSON.stringify({ ok: false, error: String((e as Error)?.message ?? e) }) });
  }
};
