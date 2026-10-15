// What one slider tick costs: a build in Pyodide (the browser's runtime, under Node) with a new value every time
// (nothing cached), parsing it, and turning it into three.js solids with the app's own scene builder (boxscene.ts,
// with its geometry cache, as the 3D view uses it). Drawing (WebGL, the 2D SVG) isn't counted.
//   npm run pack && node scripts/drag-bench.mjs           full builds (what every tick cost before draft builds)
//   npm run pack && node scripts/drag-bench.mjs draft     draft builds, as sent while a slider is held
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "rolldown";
import { loadPyodide } from "../public/pyodide/pyodide.mjs";

const draft = process.argv.includes("draft");
const here = (p) => fileURLToPath(new URL(p, import.meta.url));

// boxscene.ts as plain JS next to node_modules (so `three` resolves)
const out = await build({ input: here("../src/boxscene.ts"), platform: "node", write: false, external: ["three"],
                          output: { format: "esm" } });
mkdirSync(here("../node_modules/.cache/drag-bench/"), { recursive: true });
writeFileSync(here("../node_modules/.cache/drag-bench/boxscene.mjs"), out.output[0].code);
const { buildBoxScene, GeometryCache } = await import(pathToFileURL(here("../node_modules/.cache/drag-bench/boxscene.mjs")).href);

const py = await loadPyodide({ indexURL: here("../public/pyodide/") });
await py.loadPackage(["numpy", "shapely", "affine", "typing-extensions"], { messageCallback: () => {} });
const zip = readFileSync(here("../public/py.zip"));
py.unpackArchive(zip.buffer.slice(zip.byteOffset, zip.byteOffset + zip.byteLength), "zip", { extractDir: "/app" });
py.runPython("import sys; sys.path.insert(0, '/app'); from superboxes import api");
const call = (fn, req) => {
  py.globals.set("_fn", fn);
  py.globals.set("_req", JSON.stringify(req));
  return py.runPython("api.call(_fn, _req)");
};

const mat = { key: "poplar3.6", thickness: 3.6, burn: 0.1 };
const opts = { labels_engrave: false, mark: { enabled: true, text: null, part: null } };
// the slider each type is dragged on, and its range
const DRAG = { ABox: ["x", 50, 80], HingeBox: ["x", 80, 110], TypeTray: ["h", 40, 70], HobbyCase: ["unit_d", 120, 150],
               Console2: ["x", 90, 120], SlidingDrawer: ["x", 50, 80] };
for (const [gen, [key, a, b]] of Object.entries(DRAG)) {
  const schema = JSON.parse(call("schema", { generator: gen }));
  const params = {};
  for (const g of schema.groups) for (const p of g.params) params[p.name] = p.default;
  const req = (v, draft) => ({ generator: gen, params: { ...params, [key]: v }, material: mat,
                               sheet: { w: 297, h: 420, usable: 390 }, layout: null, options: opts, name: "bench", draft });
  call("build", req(a - 1, false));        // the full build before the drag: the mark's spot
  const cache = new GeometryCache();
  let scene = null;
  let py_ms = 0, json_ms = 0, three_ms = 0, n = 0, size = 0;
  for (let v = a; v < b; v += 3) {
    let t = performance.now();
    const text = call("build", req(v, draft));
    py_ms += performance.now() - t;
    t = performance.now();
    const r = JSON.parse(text);
    json_ms += performance.now() - t;
    if (!r.ok) throw new Error(gen + ": " + r.error);
    size = text.length;
    t = performance.now();
    scene?.dispose();
    scene = buildBoxScene(r, mat.thickness, { cache });
    cache.sweep();
    three_ms += performance.now() - t;
    n++;
  }
  const tick = (py_ms + json_ms + three_ms) / n;
  console.log(`${gen.padEnd(14)} python ${(py_ms / n).toFixed(0).padStart(4)} ms  parse ${(json_ms / n).toFixed(0).padStart(3)} ms  ` +
              `three ${(three_ms / n).toFixed(0).padStart(4)} ms  = ${tick.toFixed(0).padStart(4)} ms/tick  ${(1000 / tick).toFixed(1).padStart(5)}/s  ${(size / 1024).toFixed(0)} KB`);
}
